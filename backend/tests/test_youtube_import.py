import hashlib
import json
import os
import sys
import tempfile
import threading
from io import StringIO
from pathlib import Path
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-youtube-import-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import SOURCE_DIR
from clipper.db import connect
from clipper.jobs import runner
from clipper.main import app
from clipper.media import MediaError
from clipper.youtube_clip import parse_youtube_url
from clipper.youtube_import import build_command, capabilities, cleanup_temp, download_segment, validate_import, _run_downloader


def run():
    video_id = "Zz7os_kWwnM"
    short_url = f"https://youtu.be/{video_id}?si=sharing&t=12"
    reference = parse_youtube_url(short_url)
    assert reference["video_id"] == video_id
    assert reference["start_seconds"] == 12
    assert reference["canonical_url"] == f"https://www.youtube.com/watch?v={video_id}"
    validate_import(reference["canonical_url"], video_id, 12, 22, True)
    validate_import(reference["canonical_url"], video_id, 18_000, 18_010, True)
    try:
        validate_import("https://example.com/video.mp4", video_id, 12, 22, True)
    except MediaError:
        pass
    else:
        raise AssertionError("Accepted non-YouTube URL for segment import")
    try:
        validate_import(reference["canonical_url"], video_id, 12, 22, False)
    except MediaError:
        pass
    else:
        raise AssertionError("Accepted import without rights confirmation")

    command = build_command("yt-dlp", "ffmpeg", "segment.%(ext)s", reference["canonical_url"], 12.5, 22.25)
    assert command[command.index("--download-sections") + 1] == "*00:00:12.500-00:00:22.250"
    assert "--ignore-config" in command and "--no-playlist" in command
    assert "--force-keyframes-at-cuts" in command and "--" in command
    assert not any("cookie" in argument.lower() or "proxy" in argument.lower() for argument in command)

    with patch.dict(os.environ, {"YOUTUBE_IMPORT_ENABLED": "0"}):
        assert capabilities()["available"] is False
    with patch.dict(os.environ, {"YOUTUBE_IMPORT_ENABLED": "1"}), patch(
        "clipper.youtube_import.executable", side_effect=MediaError("yt-dlp executable missing"),
    ):
        unavailable = capabilities()
    assert unavailable["available"] is False and "missing" in unavailable["reason"]

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    progress_values = []

    def fake_download(argv, temp_dir, cancel, progress):
        assert argv[argv.index("--download-sections") + 1] == "*00:00:10.000-00:00:20.000"
        (temp_dir / "segment.mp4").write_bytes(b"mock partial segment")
        progress(0.5)

    with patch("clipper.youtube_import.capabilities", return_value={"available": True, "reason": None}), \
         patch("clipper.youtube_import.executable", side_effect=["yt-dlp", "ffmpeg"]), \
         patch("clipper.youtube_import._run_downloader", side_effect=fake_download), \
         patch("clipper.youtube_import.probe", return_value={
             "duration": 10.0, "width": 1280, "height": 720, "video_codec": "h264", "audio_codec": "aac",
         }):
        path, metadata, size, digest, temp_dir = download_segment(
            "partial-test", reference["canonical_url"], video_id, 10, 20, True, threading.Event(), progress_values.append,
        )
    assert path.read_bytes() == b"mock partial segment"
    assert metadata["duration"] == 10 and size == len(b"mock partial segment")
    assert digest == hashlib.sha256(b"mock partial segment").hexdigest() and 0.5 in progress_values
    cleanup_temp(temp_dir)
    assert not temp_dir.exists()

    def bad_file_download(_argv, temp_dir, _cancel, _progress):
        (temp_dir / "segment.webm").write_bytes(b"not an MP4 source")

    with patch("clipper.youtube_import.capabilities", return_value={"available": True, "reason": None}), \
         patch("clipper.youtube_import.executable", side_effect=["yt-dlp", "ffmpeg"]), \
         patch("clipper.youtube_import._run_downloader", side_effect=bad_file_download):
        try:
            download_segment("invalid-file-test", reference["canonical_url"], video_id, 10, 20, True, threading.Event(), lambda _value: None)
        except MediaError as exc:
            assert "MP4" in str(exc)
        else:
            raise AssertionError("Accepted non-MP4 partial import")
    assert not (SOURCE_DIR / ".youtube-import-invalid-file-test").exists()

    def oversized_download(_argv, temp_dir, _cancel, _progress):
        (temp_dir / "segment.mp4").write_bytes(b"larger than test cap")

    with patch("clipper.youtube_import.capabilities", return_value={"available": True, "reason": None}), \
         patch("clipper.youtube_import.executable", side_effect=["yt-dlp", "ffmpeg"]), \
         patch("clipper.youtube_import._run_downloader", side_effect=oversized_download), \
         patch("clipper.youtube_import.MAX_UPLOAD_BYTES", 10):
        try:
            download_segment("oversized-test", reference["canonical_url"], video_id, 10, 20, True, threading.Event(), lambda _value: None)
        except MediaError as exc:
            assert "batas impor" in str(exc).lower()
        else:
            raise AssertionError("Accepted segment above configured size limit")
    assert not (SOURCE_DIR / ".youtube-import-oversized-test").exists()

    def wrong_duration_download(_argv, temp_dir, _cancel, _progress):
        (temp_dir / "segment.mp4").write_bytes(b"duration mismatch")

    with patch("clipper.youtube_import.capabilities", return_value={"available": True, "reason": None}), \
         patch("clipper.youtube_import.executable", side_effect=["yt-dlp", "ffmpeg"]), \
         patch("clipper.youtube_import._run_downloader", side_effect=wrong_duration_download), \
         patch("clipper.youtube_import.probe", return_value={
             "duration": 30.0, "width": 1280, "height": 720, "video_codec": "h264", "audio_codec": "aac",
         }):
        try:
            download_segment("wrong-duration-test", reference["canonical_url"], video_id, 10, 20, True, threading.Event(), lambda _value: None)
        except MediaError as exc:
            assert "durasi segmen" in str(exc).lower()
        else:
            raise AssertionError("Accepted segment with mismatched duration")
    assert not (SOURCE_DIR / ".youtube-import-wrong-duration-test").exists()

    cancel_dir = SOURCE_DIR / ".youtube-import-cancel-test"
    cancel = threading.Event()

    def cancel_download(_argv, _temp_dir, event, _progress):
        event.set()
        raise MediaError("Impor dibatalkan pengguna.")

    with patch("clipper.youtube_import.capabilities", return_value={"available": True, "reason": None}), \
         patch("clipper.youtube_import.executable", side_effect=["yt-dlp", "ffmpeg"]), \
         patch("clipper.youtube_import._run_downloader", side_effect=cancel_download):
        try:
            download_segment("cancel-test", reference["canonical_url"], video_id, 10, 20, True, cancel, lambda _value: None)
        except MediaError as exc:
            assert "dibatalkan" in str(exc).lower()
        else:
            raise AssertionError("Cancellation did not stop partial import")
    assert not cancel_dir.exists()

    class FakeProcess:
        stdout = StringIO("")

        @staticmethod
        def poll():
            return None

    process_cancel = threading.Event()
    process_cancel.set()
    with patch("clipper.youtube_import.subprocess.Popen", return_value=FakeProcess()) as popen, \
         patch("clipper.youtube_import._terminate") as terminate:
        try:
            _run_downloader(command, SOURCE_DIR, process_cancel, lambda _value: None)
        except MediaError as exc:
            assert "dibatalkan" in str(exc).lower()
        else:
            raise AssertionError("Downloader did not stop when cancellation was requested")
    assert popen.call_args.kwargs["shell"] is False and terminate.called

    with patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            payload = {"url": reference["canonical_url"], "start": 12, "end": 22, "rights_confirmed": True}
            with patch.dict(os.environ, {"YOUTUBE_IMPORT_ENABLED": "0"}):
                disabled = client.post("/api/youtube-clips/imports", json=payload)
                assert disabled.status_code == 503

            with patch.dict(os.environ, {"YOUTUBE_IMPORT_ENABLED": "1"}), patch(
                "clipper.youtube_import.executable", return_value="available-binary",
            ):
                queued = client.post("/api/youtube-clips/imports", json=payload)
            assert queued.status_code == 200, queued.text
            job_id = queued.json()["id"]
            with connect() as conn:
                import_row = dict(conn.execute("SELECT * FROM youtube_import_jobs WHERE id=?", (job_id,)).fetchone())
            assert import_row["start_seconds"] == 12 and import_row["end_seconds"] == 22

            temp_dir = SOURCE_DIR / f".youtube-import-{job_id}"
            temp_dir.mkdir()
            segment = temp_dir / "segment.mp4"
            segment.write_bytes(b"mock integration segment")
            segment_metadata = {
                "duration": 10.0, "width": 1280, "height": 720, "video_codec": "h264", "audio_codec": "aac",
            }

            def fake_import(_job_id, canonical_url, parsed_id, start, end, rights, cancel_event, progress):
                assert canonical_url == reference["canonical_url"] and parsed_id == video_id
                assert (start, end, rights) == (12, 22, True)
                return segment, segment_metadata, segment.stat().st_size, hashlib.sha256(segment.read_bytes()).hexdigest(), temp_dir

            with patch("clipper.youtube_import.download_segment", side_effect=fake_import):
                runner._process_youtube_import(import_row, threading.Event())
            assert not temp_dir.exists()
            status = client.get(f"/api/youtube-clips/imports/{job_id}").json()
            source = status["source"]
            assert status["status"] == "ready" and source["id"] == job_id

            with patch("clipper.main.probe", return_value=segment_metadata):
                quick_clip = client.post(
                    f"/api/sources/{source['id']}/quick-clips",
                    json={
                        "title": "Imported segment", "start": 0, "end": 10,
                        "youtube_reference": {
                            "canonical_url": reference["canonical_url"], "video_id": video_id, "start": 12, "end": 22,
                        },
                    },
                )
            assert quick_clip.status_code == 200, quick_clip.text
            with connect() as conn:
                options = conn.execute(
                    "SELECT options_json FROM jobs WHERE id=?", (quick_clip.json()["id"],),
                ).fetchone()[0]
            provenance = json.loads(options)["youtube_reference"]
            assert provenance["source_association"] == "auto_imported"
            assert (provenance["start"], provenance["end"]) == (12, 22)

            with patch.dict(os.environ, {"YOUTUBE_IMPORT_ENABLED": "1"}), patch(
                "clipper.youtube_import.executable", return_value="available-binary",
            ):
                cancelled_job = client.post("/api/youtube-clips/imports", json=payload).json()["id"]
            cancelled = client.post(f"/api/youtube-clips/imports/{cancelled_job}/cancel")
            assert cancelled.status_code == 200
            assert client.get(f"/api/youtube-clips/imports/{cancelled_job}").json()["status"] == "cancelled"
            with patch.dict(os.environ, {"YOUTUBE_IMPORT_ENABLED": "1"}), patch(
                "clipper.youtube_import.executable", return_value="available-binary",
            ):
                retry = client.post(
                    f"/api/youtube-clips/imports/{cancelled_job}/retry", json={"rights_confirmed": True},
                )
            assert retry.status_code == 200 and retry.json()["id"] != cancelled_job

            source_path = SOURCE_DIR / f"{source['id']}.mp4"
            source_path.unlink(missing_ok=True)

    print("YouTube segment import URL, partial range, opt-in adapter, cancellation, cleanup, validation, and Quick Clip integration checks added")


if __name__ == "__main__":
    run()
