"""Opt-in real-media Quick Clip test; uses isolated DB/output roots and never copies or edits source."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import psutil


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for block in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path, help="Existing owned/licensed MP4/MOV source")
    parser.add_argument("--start", type=float, default=14 * 60, help="Start in source seconds (default 840)")
    parser.add_argument("--end", type=float, default=15 * 60, help="End in source seconds (default 900)")
    parser.add_argument("--resolution", choices=("720", "1080"), default="720")
    parser.add_argument("--output-dir", type=Path, help="Isolated app DB and render output directory")
    args = parser.parse_args()
    source_path = args.video.resolve()
    if not source_path.is_file():
        raise SystemExit("Source video does not exist.")
    output_dir = args.output_dir or Path(tempfile.gettempdir()) / f"klipnara-quick-clip-{uuid.uuid4().hex[:10]}"
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit("Output directory must be new or empty; refusing to overwrite data.")
    output_dir.mkdir(parents=True, exist_ok=True)

    os.environ["CLIPPER_DATA_DIR"] = str(output_dir / "appdata")
    os.environ["CLIPPER_SOURCE_DIR"] = str(source_path.parent)
    os.environ["CLIPPER_CLIP_DIR"] = str(output_dir / "clips")
    os.environ["WHISPER_CPP_PATH"] = "klipnara-disabled-whisper-for-quick-e2e.exe"
    os.environ["WHISPER_MODEL_PATH"] = ""
    os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from fastapi.testclient import TestClient

    from clipper.db import connect
    from clipper.jobs import now
    from clipper.main import app
    from clipper.media import probe
    from clipper import jobs

    def fail_if_ai_called(*_args, **_kwargs):
        raise AssertionError("Quick Clip invoked an AI/transcription function")

    jobs.transcribe = fail_if_ai_called
    jobs.analyze = fail_if_ai_called
    jobs.count_prompt_tokens = fail_if_ai_called

    render_durations = []
    actual_render = jobs.render

    def timed_render(*args, **kwargs):
        started = time.perf_counter()
        try:
            return actual_render(*args, **kwargs)
        finally:
            render_durations.append(time.perf_counter() - started)

    jobs.render = timed_render

    metadata = probe(source_path)
    if not (0 <= args.start < args.end <= metadata["duration"]):
        raise SystemExit(f"Timestamp range must fit source duration {metadata['duration']:.3f}s.")
    original_stat = source_path.stat()
    source_hash = _sha256(source_path)

    with TestClient(app) as client:
        source_id, seed_job = uuid.uuid4().hex, uuid.uuid4().hex
        with connect() as conn:
            conn.execute(
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (source_id, source_path.name, str(source_path), original_stat.st_size, metadata["duration"],
                 metadata["width"], metadata["height"], metadata["video_codec"], metadata["audio_codec"], source_hash, now()),
            )
            conn.execute(
                "INSERT INTO jobs(id,source_id,kind,status,phase,options_json,created_at,updated_at) "
                "VALUES(?,?,?,'completed','completed','{}',?,?)",
                (seed_job, source_id, "quick_e2e_seed", now(), now()),
            )

        queued = client.post(
            f"/api/sources/{source_id}/quick-clips",
            json={"title": "Quick Clip E2E", "start": args.start, "end": args.end, "resolution": args.resolution},
        )
        assert queued.status_code == 200, queued.text
        job_id = queued.json()["id"]

        process = psutil.Process()
        cpu_samples = []
        peak_tree_rss = process.memory_info().rss
        started = time.perf_counter()
        psutil.cpu_percent(None)
        deadline = started + 600
        while time.perf_counter() < deadline:
            cpu_samples.append(psutil.cpu_percent(interval=0.25))
            children = process.children(recursive=True)
            for item in [process, *children]:
                try:
                    peak_tree_rss = max(peak_tree_rss, item.memory_info().rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
        else:
            raise SystemExit("Quick Clip worker exceeded 600-second E2E timeout.")
        elapsed = time.perf_counter() - started
        if job["status"] != "completed":
            raise AssertionError(f"Quick Clip failed: {job}")

        with connect() as conn:
            clip = dict(conn.execute("SELECT * FROM clips WHERE id=?", (queued.json()["clip_id"],)).fetchone())
            transcript = conn.execute("SELECT transcript_json FROM sources WHERE id=?", (source_id,)).fetchone()["transcript_json"]
        assert transcript is None and clip["review_status"] == "needs_review"
        output_path = Path(clip["rendered_path"])
        result = probe(output_path)
        expected_duration = args.end - args.start
        assert result["video_codec"] == "h264" and result["audio_codec"] == "aac"
        expected_dimensions = (720, 1280) if args.resolution == "720" else (1080, 1920)
        assert (result["width"], result["height"]) == expected_dimensions
        assert abs(result["duration"] - expected_duration) <= 0.2, result
        approved = client.post(f"/api/clips/{clip['id']}/review", json={"status": "approved"})
        assert approved.status_code == 200, approved.text
        after_stat = source_path.stat()
        source_unchanged = source_hash == _sha256(source_path) and (original_stat.st_size, original_stat.st_mtime_ns) == (after_stat.st_size, after_stat.st_mtime_ns)
        assert source_unchanged

    print(json.dumps({
        "source": str(source_path),
        "source_duration_seconds": round(metadata["duration"], 3),
        "source_audio_codec": metadata["audio_codec"],
        "selected_start_seconds": args.start,
        "selected_end_seconds": args.end,
        "output_duration_seconds": round(result["duration"], 3),
        "output_dimensions": f"{result['width']}x{result['height']}",
        "output_video_codec": result["video_codec"],
        "output_audio_codec": result["audio_codec"],
        "output_size_bytes": output_path.stat().st_size,
        "render_elapsed_seconds": round(render_durations[0], 2),
        "worker_completion_elapsed_seconds": round(elapsed, 2),
        "peak_process_tree_rss_mib": round(peak_tree_rss / 1024**2, 1),
        "system_cpu_average_percent_sampled": round(sum(cpu_samples) / len(cpu_samples), 1) if cpu_samples else None,
        "review_after_render": approved.json()["review_status"],
        "ai_calls": 0,
        "source_unchanged": source_unchanged,
        "isolated_output_dir": str(output_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
