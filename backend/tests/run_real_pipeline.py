"""Opt-in local integration benchmark. Requires media binaries, model, Ollama, and a test MP4."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path, help="Short owned/licensed Indonesian MP4")
    parser.add_argument("--long-video", type=Path, help="Optional 5-10 minute MP4")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPPER_DATA_DIR"] = str(args.output_dir / "appdata")
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from fastapi.testclient import TestClient

    from clipper.db import connect
    from clipper.main import app
    from clipper.media import _write_ass, executable

    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    ffprobe = executable("ffprobe", "FFPROBE_PATH")
    whisper = executable("whisper-cli", "WHISPER_CPP_PATH")
    model = Path(os.environ["WHISPER_MODEL_PATH"])
    if not model.is_file() or not args.video.is_file():
        raise SystemExit("Source video or multilingual Whisper model missing.")

    psutil.cpu_percent(None)
    results = {"source": str(args.video), "cloud_keys_available": False, "jobs": [], "renders": []}
    report_path = args.output_dir / "report.json"

    def save_report():
        report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    save_report()

    with TestClient(app) as client:
        # Probe failure must reject upload and leave source library unchanged.
        old_probe = os.environ["FFPROBE_PATH"]
        os.environ["FFPROBE_PATH"] = "klipnara-missing-ffprobe.exe"
        with args.video.open("rb") as video:
            failed_upload = client.post("/api/sources/upload", files={"file": (args.video.name, video, "video/mp4")})
        os.environ["FFPROBE_PATH"] = old_probe
        assert failed_upload.status_code == 400, failed_upload.text
        assert client.get("/api/sources").json() == []

        with args.video.open("rb") as video:
            uploaded = client.post("/api/sources/upload", files={"file": (args.video.name, video, "video/mp4")})
        assert uploaded.status_code == 200, uploaded.text
        source = uploaded.json()
        results["ingest"] = {key: source[key] for key in ("name", "duration", "width", "height", "video_codec", "audio_codec", "size_bytes")}
        save_report()

        options = {
            "count": 5, "duration": "15-30", "style": "Clean", "subtitle_enabled": True,
            "resolution": "720", "focus": "center", "provider": "local", "language": "indonesia",
        }

        # Missing FFmpeg must fail explicitly; it must not trigger a cloud provider.
        old_ffmpeg = os.environ["FFMPEG_PATH"]
        os.environ["FFMPEG_PATH"] = "klipnara-missing-ffmpeg.exe"
        missing_ffmpeg = client.post(f"/api/sources/{source['id']}/generate", json=options).json()["id"]
        failed = wait_job(client, missing_ffmpeg, args.timeout)
        assert failed["status"] == "failed" and "ffmpeg" in failed["message"].lower(), failed
        os.environ["FFMPEG_PATH"] = old_ffmpeg
        results["missing_ffmpeg"] = failed["message"]
        save_report()

        # Missing whisper.cpp must also fail locally; retry after restore should resume.
        old_whisper = os.environ["WHISPER_CPP_PATH"]
        os.environ["WHISPER_CPP_PATH"] = "klipnara-missing-whisper.exe"
        missing_whisper = client.post(f"/api/sources/{source['id']}/generate", json=options).json()["id"]
        failed = wait_job(client, missing_whisper, args.timeout)
        assert failed["status"] == "failed" and "whisper-cli" in failed["message"].lower(), failed
        os.environ["WHISPER_CPP_PATH"] = old_whisper
        results["missing_whisper"] = failed["message"]
        save_report()
        retry = client.post(f"/api/jobs/{missing_whisper}/retry", json={})
        assert retry.status_code == 200, retry.text
        first_job = wait_job(client, retry.json()["id"], args.timeout)
        assert first_job["status"] == "ready_for_review", first_job
        results["jobs"].append(first_job)
        results["ollama_runtime"] = ollama_process_list()
        save_report()

        source_data = client.get(f"/api/sources/{source['id']}").json()
        transcript = source_data["source"]["transcript"]
        assert len(transcript) >= 8 and source_data["source"]["transcript_language"] == "id"
        results["transcript"] = {"language": source_data["source"]["transcript_language"], "segments": len(transcript), "sample": transcript[:3]}
        transcript_before = json.dumps(transcript, ensure_ascii=False, sort_keys=True)
        clips = source_data["clips"]
        assert clips, "No Ollama candidates returned"
        assert all(0 <= clip["start"] < clip["end"] <= source["duration"] for clip in clips)
        results["candidates"] = [{key: clip[key] for key in ("rank", "start", "end", "title", "reason")} for clip in clips]
        save_report()

        clip = clips[0]
        clip_length = clip["end"] - clip["start"]
        style_runs = [
            ("Clean", "720", 50, 50),
            ("Bold", "720", 65, 42),
            ("Highlight", "720", 50, 50),
            ("Highlight", "1080", 65, 42),
        ]
        for index, (style, resolution, crop_x, crop_y) in enumerate(style_runs):
            edit = {
                "trim_start": 0.25,
                "trim_end": clip_length - 0.25,
                "subtitle_enabled": True,
                "style": style,
                "resolution": resolution,
                "crop_x": crop_x,
                "crop_y": crop_y,
                "subtitle_size": 48,
                "subtitle_position": 82,
                "subtitle_color": "#ffd700" if style == "Highlight" else "#ffffff",
            }
            saved = client.patch(f"/api/clips/{clip['id']}", json=edit)
            assert saved.status_code == 200, saved.text
            with connect() as conn:
                review_state = conn.execute("SELECT review_status FROM clips WHERE id=?", (clip["id"],)).fetchone()["review_status"]
            assert review_state == "needs_review", review_state
            job_id = client.post(f"/api/clips/{clip['id']}/render").json()["id"]
            job = wait_job(client, job_id, args.timeout)
            assert job["status"] == "completed", job

            with connect() as conn:
                row = conn.execute("SELECT rendered_path,edit_json,review_status FROM clips WHERE id=?", (clip["id"],)).fetchone()
            assert row["review_status"] == "needs_review", row["review_status"]
            approved = client.post(f"/api/clips/{clip['id']}/review", json={"status": "approved"})
            assert approved.status_code == 200 and approved.json()["review_status"] == "approved", approved.text
            original_output = Path(row["rendered_path"])
            label = f"{style.lower()}-{resolution}p-{index + 1}"
            output = args.output_dir / f"{label}.mp4"
            shutil.copy2(original_output, output)
            style_edit = json.loads(row["edit_json"])
            ass_path = args.output_dir / f"{label}.ass"
            _write_ass(ass_path, transcript, clip["start"] + edit["trim_start"], clip["start"] + edit["trim_end"], style_edit, int(resolution) * 1280 // 720)
            assert any(line.startswith("Dialogue:") for line in ass_path.read_text(encoding="utf-8-sig").splitlines())
            media = inspect_render(
                output, ffmpeg, ffprobe, args.output_dir / f"{label}-frame.jpg",
                expected_duration=edit["trim_end"] - edit["trim_start"],
            )
            results["renders"].append({"style": style, "resolution": resolution, "crop_x": crop_x, "crop_y": crop_y, "path": str(output), "seconds": job["_elapsed_seconds"], "review_status": approved.json()["review_status"], **media})
            save_report()
            assert json.dumps(client.get(f"/api/sources/{source['id']}").json()["source"]["transcript"], ensure_ascii=False, sort_keys=True) == transcript_before

        # Cancel a live render, then retry its saved edit without analysis.
        cancel_job, response = None, None
        active_cancel = False
        for _ in range(2):
            cancel_job = client.post(f"/api/clips/{clip['id']}/render").json()["id"]
            deadline = time.perf_counter() + 20
            while time.perf_counter() < deadline:
                current = client.get(f"/api/jobs/{cancel_job}").json()
                if current["status"] == "rendering":
                    response = client.post(f"/api/jobs/{cancel_job}/cancel")
                    if response.status_code == 200:
                        active_cancel = True
                        break
                if current["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            if response is not None and response.status_code == 200:
                break
        if active_cancel:
            cancelled = wait_job(client, cancel_job, args.timeout)
            assert cancelled["status"] == "cancelled", cancelled
            with connect() as conn:
                clip_state = conn.execute("SELECT status,rendered_path,review_status FROM clips WHERE id=?", (clip["id"],)).fetchone()
            assert clip_state["status"] == "needs_render" and clip_state["rendered_path"] and clip_state["review_status"] == "needs_review"
            prior_asset_preserved = Path(clip_state["rendered_path"]).is_file()
            assert prior_asset_preserved
            retried = client.post(f"/api/jobs/{cancel_job}/retry", json={})
            assert retried.status_code == 200, retried.text
            cancel_retry = wait_job(client, retried.json()["id"], args.timeout)
            assert cancel_retry["status"] == "completed", cancel_retry
            with connect() as conn:
                review_state = conn.execute("SELECT review_status FROM clips WHERE id=?", (clip["id"],)).fetchone()["review_status"]
            assert review_state == "needs_review", review_state
            results["cancel_retry"] = {"cancelled_job": cancelled, "retry_job": cancel_retry, "prior_asset_preserved_after_cancel": prior_asset_preserved}
        else:
            raise AssertionError("Could not cancel an active render before it completed.")
        save_report()

        # Local provider failure stays local; retry uses cached transcript.
        old_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
        os.environ["OLLAMA_MODEL"] = "klipnara-model-not-installed"
        failed_id = client.post(f"/api/sources/{source['id']}/generate", json=options).json()["id"]
        failed = wait_job(client, failed_id, args.timeout)
        assert failed["status"] == "failed", failed
        results["ollama_failure"] = failed["message"]
        save_report()
        os.environ["OLLAMA_MODEL"] = old_model
        retried = client.post(f"/api/jobs/{failed_id}/retry", json={})
        assert retried.status_code == 200, retried.text
        retry_job = wait_job(client, retried.json()["id"], args.timeout)
        assert retry_job["status"] == "ready_for_review", retry_job
        results["jobs"].append(retry_job)
        save_report()

        with connect() as conn:
            usage = [dict(row) for row in conn.execute("SELECT provider,model,input_tokens,output_tokens FROM provider_usage WHERE job_id IN (?,?)", (first_job["id"], retry_job["id"]))]
        assert usage and all(row["provider"] == "local" for row in usage)
        assert all(row["input_tokens"] is not None and row["output_tokens"] is not None for row in usage)
        results["local_provider_usage"] = usage
        assert json.dumps(client.get(f"/api/sources/{source['id']}").json()["source"]["transcript"], ensure_ascii=False, sort_keys=True) == transcript_before

        if args.long_video:
            with args.long_video.open("rb") as video:
                long_upload = client.post("/api/sources/upload", files={"file": (args.long_video.name, video, "video/mp4")})
            assert long_upload.status_code == 200, long_upload.text
            long_source = long_upload.json()
            long_id = client.post(f"/api/sources/{long_source['id']}/generate", json=options).json()["id"]
            long_job = wait_job(client, long_id, args.timeout)
            results["long_video"] = {"duration": long_source["duration"], "job": long_job}
            save_report()
            assert long_job["status"] == "ready_for_review", long_job

    save_report()
    print(json.dumps({"report": str(report_path), "candidate_count": len(results["candidates"]), "renders": len(results["renders"]), "durations": {item["style"] + item["resolution"]: item["seconds"] for item in results["renders"]}}, ensure_ascii=False, indent=2))


def wait_job(client, job_id, timeout):
    started, last_at, last_key = time.perf_counter(), time.perf_counter(), None
    stage_seconds, cpu_peak, rss_peak = {}, 0.0, 0
    sample_processes()
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        now = time.perf_counter()
        key = (job.get("status"), job.get("message"))
        if last_key is not None:
            stage_seconds[str(last_key)] = stage_seconds.get(str(last_key), 0) + now - last_at
        last_key, last_at = key, now
        cpu, rss = sample_processes()
        cpu_peak, rss_peak = max(cpu_peak, cpu), max(rss_peak, rss)
        if job["status"] in {"ready_for_review", "completed", "failed", "cancelled"}:
            break
        if now - started > timeout:
            raise TimeoutError(f"Job {job_id} timed out; latest state: {job}")
        time.sleep(0.5)
    job["_elapsed_seconds"] = round(time.perf_counter() - started, 2)
    job["_stage_seconds"] = {stage: round(seconds, 2) for stage, seconds in stage_seconds.items()}
    job["_peak_system_cpu_percent"] = round(cpu_peak, 1)
    job["_peak_process_rss_mib"] = round(rss_peak / 1024**2, 1)
    return job


def sample_processes():
    cpu = psutil.cpu_percent(None)
    names = ("python", "ffmpeg", "whisper", "ollama", "llama")
    rss = 0
    for process in psutil.process_iter(["name", "memory_info"]):
        try:
            if any(name in (process.info["name"] or "").lower() for name in names):
                rss += process.info["memory_info"].rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return cpu, rss


def ollama_process_list():
    binary = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    try:
        result = subprocess.run([binary, "ps"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "ollama ps unavailable"


def inspect_render(path, ffmpeg, ffprobe, frame_path, expected_duration=None):
    probe = subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    streams = {stream["codec_type"]: stream for stream in info["streams"]}
    video, audio = streams["video"], streams["audio"]
    duration = float(info["format"]["duration"])
    video_duration = float(video.get("duration", duration))
    audio_duration = float(audio.get("duration", duration))
    assert video["codec_name"] == "h264" and audio["codec_name"] == "aac"
    assert (video["width"], video["height"]) in {(720, 1280), (1080, 1920)}
    assert abs(float(video.get("start_time", 0)) - float(audio.get("start_time", 0))) < 0.1
    assert abs(video_duration - audio_duration) < 0.1
    if expected_duration is not None:
        assert abs(video_duration - expected_duration) < 0.15
    assert subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "NUL"], capture_output=True).returncode == 0
    black = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.05:pix_th=0.10:pic_th=0.99", "-an", "-f", "null", "NUL"], capture_output=True, text=True)
    assert black.returncode == 0 and "black_start" not in black.stderr
    frame = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{min(3, duration / 3):.2f}", "-i", str(path), "-frames:v", "1", "-y", str(frame_path)], capture_output=True)
    assert frame.returncode == 0 and frame_path.is_file()
    return {
        "duration": round(duration, 2), "video_duration": round(video_duration, 3),
        "audio_duration": round(audio_duration, 3),
        "av_duration_delta": round(abs(video_duration - audio_duration), 3),
        "bytes": path.stat().st_size,
        "video": f"{video['width']}x{video['height']} {video['codec_name']}",
        "audio": f"{audio['codec_name']} {audio.get('sample_rate')}Hz",
        "black_frames": 0, "decode": "ok", "frame": str(frame_path),
    }


if __name__ == "__main__":
    main()
