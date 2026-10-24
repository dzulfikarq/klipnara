import json
import os
import sys
import tempfile
import threading
import uuid
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-quick-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import CLIP_DIR
from clipper.db import connect
from clipper.jobs import runner
from clipper.main import app
from clipper.media import render


def run():
    with patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            silent_info = {"duration": 1500.0, "width": 1280, "height": 720, "video_codec": "h264", "audio_codec": None}
            with patch("clipper.main.probe", return_value=silent_info):
                uploaded = client.post("/api/sources/upload", files={"file": ("silent.mp4", BytesIO(b"fake silent MP4"), "video/mp4")})
            assert uploaded.status_code == 200 and uploaded.json()["audio_codec"] is None, uploaded.text
            source_id = uploaded.json()["id"]

            smart = client.post(f"/api/sources/{source_id}/generate", json={"provider": "local"})
            assert smart.status_code == 409 and "requires source audio" in smart.json()["detail"]
            with connect() as conn:
                assert conn.execute("SELECT count(*) FROM jobs WHERE source_id=?", (source_id,)).fetchone()[0] == 0

            invalid_equal = client.post(
                f"/api/sources/{source_id}/quick-clips",
                json={"title": "Invalid", "start": 12, "end": 12},
            )
            invalid_after_duration = client.post(
                f"/api/sources/{source_id}/quick-clips",
                json={"title": "Invalid", "start": 1490, "end": 1501},
            )
            assert invalid_equal.status_code == 422 and invalid_after_duration.status_code == 422

            created = client.post(
                f"/api/sources/{source_id}/quick-clips",
                json={"title": "Timestamp cut", "start": 14 * 60, "end": 15 * 60, "resolution": "720"},
            )
            assert created.status_code == 200, created.text
            queued = created.json()
            assert queued["status"] == "queued" and queued["clip_id"]
            with connect() as conn:
                job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (queued["id"],)).fetchone())
                clip = dict(conn.execute("SELECT * FROM clips WHERE id=?", (queued["clip_id"],)).fetchone())
                source = conn.execute("SELECT transcript_json,audio_codec FROM sources WHERE id=?", (source_id,)).fetchone()
            initial_edit = json.loads(clip["edit_json"])
            assert job["kind"] == "quick_clip" and clip["status"] == "ready"
            assert clip["review_status"] == "needs_review" and initial_edit["subtitle_enabled"] is False
            assert (clip["start"], clip["end"]) == (14 * 60, 15 * 60)
            assert source["transcript_json"] is None and source["audio_codec"] is None
            detail = client.get(f"/api/clips/{queued['clip_id']}").json()
            assert detail["clip"]["origin"] == "quick_clip" and detail["transcript"] == []
            source_detail = client.get(f"/api/sources/{source_id}").json()
            assert source_detail["clips"][0]["origin"] == "quick_clip"

            render_calls = []

            def fake_render(media_path, clip_row, edit, segments, job_id, cancel, progress, has_audio=True):
                render_calls.append((edit["subtitle_enabled"], segments, has_audio))
                target = CLIP_DIR / f"{clip_row['id']}-{job_id}.mp4"
                target.write_bytes(b"fake final MP4")
                progress(0.5)
                return target

            with patch("clipper.jobs.render", side_effect=fake_render), \
                 patch("clipper.jobs.transcribe", side_effect=AssertionError("Quick Clip called Whisper")), \
                 patch("clipper.jobs.analyze", side_effect=AssertionError("Quick Clip called AI")), \
                 patch("clipper.jobs.count_prompt_tokens", side_effect=AssertionError("Quick Clip called Ollama token preflight")):
                runner._process(job, threading.Event())
            assert render_calls == [(False, [], False)]
            with connect() as conn:
                final = conn.execute("SELECT status,review_status,rendered_path FROM clips WHERE id=?", (queued["clip_id"],)).fetchone()
            assert tuple(final[:2]) == ("completed", "needs_review") and Path(final["rendered_path"]).is_file()

            with patch("clipper.main.probe", return_value={"video_codec": "h264", "audio_codec": "aac"}):
                approved = client.post(f"/api/clips/{queued['clip_id']}/review", json={"status": "approved"})
            assert approved.status_code == 200
            with connect() as conn:
                fingerprint = conn.execute("SELECT reviewed_render_sha256 FROM clips WHERE id=?", (queued["clip_id"],)).fetchone()[0]
            assert fingerprint and len(fingerprint) == 64
            subtitles = client.patch(f"/api/clips/{queued['clip_id']}", json={"subtitle_enabled": True})
            assert subtitles.status_code == 409

            second = client.post(
                f"/api/sources/{source_id}/quick-clips",
                json={"title": "Retry cut", "start": 1, "end": 10},
            ).json()
            cancelled = client.post(f"/api/jobs/{second['id']}/cancel")
            assert cancelled.status_code == 200
            retried = client.post(f"/api/jobs/{second['id']}/retry", json={})
            assert retried.status_code == 200
            with connect() as conn:
                retry_job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (retried.json()["id"],)).fetchone())
            with patch("clipper.jobs.render", side_effect=fake_render), \
                 patch("clipper.jobs.transcribe", side_effect=AssertionError("Quick Clip retry called Whisper")), \
                 patch("clipper.jobs.analyze", side_effect=AssertionError("Quick Clip retry called AI")), \
                 patch("clipper.jobs.count_prompt_tokens", side_effect=AssertionError("Quick Clip retry called Ollama")):
                runner._process(retry_job, threading.Event())
            with connect() as conn:
                retry_state = conn.execute("SELECT status,review_status FROM clips WHERE id=?", (second["clip_id"],)).fetchone()
            assert tuple(retry_state) == ("completed", "needs_review")

            class FakeProcess:
                def __init__(self):
                    self.stdout = StringIO("")
                    self.returncode = 0

                def wait(self, *args, **kwargs):
                    return self.returncode

                def poll(self):
                    return self.returncode

            for has_audio, expected_map in ((False, "1:a:0"), (True, "0:a?")):
                command = []

                def fake_popen(argv, **_kwargs):
                    command.extend(argv)
                    return FakeProcess()

                edit = {**initial_edit, "subtitle_enabled": False}
                with patch("clipper.media.executable", return_value="ffmpeg"), patch("clipper.media.subprocess.Popen", side_effect=fake_popen):
                    render("input.mp4", clip, edit, [], uuid.uuid4().hex, threading.Event(), lambda _progress: None, has_audio=has_audio)
                assert expected_map in command
                assert ("anullsrc=channel_layout=stereo:sample_rate=48000" in command) is (not has_audio)
                assert command[command.index("-c:a") + 1] == "aac"

            print("Quick Clip API, no-audio import, AI isolation, render options, review approval, cancel/retry checks passed")


if __name__ == "__main__":
    run()
