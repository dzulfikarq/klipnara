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
            assert initial_edit["subtitle_mode"] == "off" and initial_edit["subtitle_segments"] == []
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
            manual = client.patch(f"/api/clips/{queued['clip_id']}", json={
                "subtitle_mode": "manual", "subtitle_enabled": True,
                "subtitle_segments": [{"id": "manual-one", "start": 2.25, "end": 4.5, "text": "Teks tanpa transkrip."}],
            })
            assert manual.status_code == 200, manual.text
            restored = client.get(f"/api/clips/{queued['clip_id']}").json()["clip"]["edit"]
            assert restored["subtitle_segments"] == [{"id": "manual-one", "start": 2.25, "end": 4.5, "text": "Teks tanpa transkrip."}]
            with patch("clipper.jobs.render", side_effect=fake_render):
                manual_render = client.post(f"/api/clips/{queued['clip_id']}/render")
                assert manual_render.status_code == 200, manual_render.text
                with connect() as conn:
                    manual_job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (manual_render.json()["id"],)).fetchone())
                runner._process(manual_job, threading.Event())
            assert render_calls[-1] == (True, restored["subtitle_segments"], False)

            no_audio_stt = client.post(f"/api/clips/{queued['clip_id']}/subtitles/auto-generate", json={"provider": "local"})
            assert no_audio_stt.status_code == 409 and "no audio" in no_audio_stt.json()["detail"]
            client.patch(f"/api/clips/{queued['clip_id']}", json={"trim_start": 2, "trim_end": 10})
            with connect() as conn:
                conn.execute("UPDATE sources SET audio_codec='aac' WHERE id=?", (source_id,))
            with patch("clipper.main.extract_subtitle_audio") as blocked_audio_send:
                cloud_without_consent = client.post(
                    f"/api/clips/{queued['clip_id']}/subtitles/auto-generate",
                    json={"provider": "openai", "consent": False},
                )
            assert cloud_without_consent.status_code == 400 and "consent" in cloud_without_consent.json()["detail"]
            blocked_audio_send.assert_not_called()

            extraction_ranges = []
            def fake_extract(_source, start, end, provider):
                extraction_ranges.append((start, end, provider))
                return CLIP_DIR / "fake-subtitle-audio.wav"

            with patch("clipper.main.local_transcription_available", return_value=True), \
                 patch("clipper.main.extract_subtitle_audio", side_effect=fake_extract), \
                 patch("clipper.main.transcribe", return_value=([{"start": 0.5, "end": 1.5, "text": "Ucapan terpilih."}], "id", "fixture")):
                generated = client.post(
                    f"/api/clips/{queued['clip_id']}/subtitles/auto-generate",
                    json={"provider": "local", "language": "indonesia"},
                )
            assert generated.status_code == 200, generated.text
            assert extraction_ranges == [(842, 850, "local")]
            generated_edit = client.get(f"/api/clips/{queued['clip_id']}").json()["clip"]["edit"]
            assert generated_edit["subtitle_mode"] == "auto" and generated_edit["subtitle_enabled"] is True
            assert generated_edit["subtitle_segments"][0]["start"] == 2.5
            assert generated_edit["subtitle_segments"][0]["end"] == 3.5

            cloud_ranges = []
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only-key"}), \
                 patch("clipper.main.extract_subtitle_audio", side_effect=lambda _source, start, end, provider: cloud_ranges.append((start, end, provider)) or CLIP_DIR / "fake-cloud-audio.m4a"), \
                 patch("clipper.main.transcribe_openai", return_value=[{"start": 1, "end": 2, "text": "Cloud speech."}]) as cloud_stt:
                cloud_generated = client.post(
                    f"/api/clips/{queued['clip_id']}/subtitles/auto-generate",
                    json={"provider": "openai", "language": "english", "consent": True},
                )
            assert cloud_generated.status_code == 200, cloud_generated.text
            assert cloud_ranges == [(842, 850, "openai")] and cloud_stt.call_count == 1
            cloud_edit = client.get(f"/api/clips/{queued['clip_id']}").json()["clip"]["edit"]
            assert cloud_edit["subtitle_segments"][0]["start"] == 3
            assert cloud_edit["subtitle_segments"][0]["end"] == 4
            with patch("clipper.main.local_transcription_available", return_value=True), \
                 patch("clipper.main.extract_subtitle_audio", return_value=CLIP_DIR / "silent-subtitle-audio.wav"), \
                 patch("clipper.main.transcribe", return_value=([], "id", "fixture")):
                no_speech = client.post(
                    f"/api/clips/{queued['clip_id']}/subtitles/auto-generate",
                    json={"provider": "local", "language": "indonesia"},
                )
            assert no_speech.status_code == 422 and "No speech detected" in no_speech.json()["detail"]

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

            short_single = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "single", "trim_start": 0, "trim_end": 0.4,
                "scenes": [{"id": "short-single", "source_start": 1, "source_end": 1.4, "order": 0, "role": "body"}],
            })
            assert short_single.status_code == 200, short_single.text
            short_multi = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "multi",
                "scenes": [{"id": "short-multi", "source_start": 1, "source_end": 1.4, "order": 0, "role": "body"}],
            })
            assert short_multi.status_code == 422
            converted_multi = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "multi", "subtitle_timebase": "clip",
                "scenes": [{"id": "converted", "source_start": 1, "source_end": 4, "order": 0, "role": "body"}],
                "subtitle_segments": [{"id": "candidate-caption", "start": 0, "end": 2, "text": "Convert timebase"}],
            })
            assert converted_multi.status_code == 200, converted_multi.text
            assert converted_multi.json()["subtitle_timebase"] == "source"
            assert (converted_multi.json()["subtitle_segments"][0]["start"], converted_multi.json()["subtitle_segments"][0]["end"]) == (1, 3)

            multi_saved = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "multi",
                "scenes": [
                    {"id": "scene-a", "source_start": 1, "source_end": 4, "order": 0, "role": "hook"},
                    {"id": "scene-b", "source_start": 8, "source_end": 10, "order": 1, "role": "ending"},
                ],
                "subtitle_mode": "manual", "subtitle_enabled": True, "subtitle_timebase": "source",
                "subtitle_segments": [
                    {"id": "cut-boundary", "start": 3, "end": 5, "text": "Caption across trim"},
                    {"id": "later-caption", "start": 8.5, "end": 9.5, "text": "Later source time"},
                ],
            })
            assert multi_saved.status_code == 200, multi_saved.text
            restored_multi = client.get(f"/api/clips/{second['clip_id']}").json()["clip"]["edit"]
            assert restored_multi["scene_mode"] == "multi" and restored_multi["scenes"] == multi_saved.json()["scenes"]
            assert restored_multi["subtitle_timebase"] == "source" and restored_multi["subtitle_segments"][0]["start"] == 3
            invalid_long_multi = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "multi",
                "scenes": [
                    {"id": "long-a", "source_start": 1, "source_end": 101, "order": 0, "role": "hook"},
                    {"id": "long-b", "source_start": 102, "source_end": 183, "order": 1, "role": "ending"},
                ],
            })
            assert invalid_long_multi.status_code == 422
            invalid_many_scenes = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "multi",
                "scenes": [
                    {"id": f"scene-{index}", "source_start": index * 2, "source_end": index * 2 + 0.5, "order": index, "role": "body"}
                    for index in range(13)
                ],
            })
            assert invalid_many_scenes.status_code == 422
            assert client.get(f"/api/clips/{second['clip_id']}").json()["clip"]["edit"]["scenes"] == multi_saved.json()["scenes"]
            multi_job_response = client.post(f"/api/clips/{second['clip_id']}/render")
            assert multi_job_response.status_code == 200, multi_job_response.text
            with connect() as conn:
                multi_job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (multi_job_response.json()["id"],)).fetchone())
            with patch("clipper.jobs.render", side_effect=fake_render):
                runner._process(multi_job, threading.Event())
            assert render_calls[-1] == (True, [
                {"id": "scene-a-cut-boundary", "start": 2, "end": 3, "text": "Caption across trim"},
                {"id": "scene-b-later-caption", "start": 3.5, "end": 4.5, "text": "Later source time"},
            ], True)

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
                    Path(argv[-1]).write_bytes(b"fake MP4")
                    return FakeProcess()

                edit = {**initial_edit, "subtitle_enabled": False}
                with patch("clipper.media.executable", return_value="ffmpeg"), \
                     patch("clipper.media.subprocess.Popen", side_effect=fake_popen), \
                     patch("clipper.media.probe", return_value={"duration": 60, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}):
                    render("input.mp4", clip, edit, [], uuid.uuid4().hex, threading.Event(), lambda _progress: None, has_audio=has_audio)
                assert expected_map in command
                assert ("anullsrc=channel_layout=stereo:sample_rate=48000" in command) is (not has_audio)
                assert command[command.index("-c:a") + 1] == "aac"

            multi_command = []

            def fake_multi_popen(argv, **_kwargs):
                multi_command.extend(argv)
                Path(argv[-1]).write_bytes(b"fake multi MP4")
                return FakeProcess()

            multi_edit = {
                **initial_edit,
                "scene_mode": "multi",
                "scenes": [
                    {"id": "a", "source_start": 1, "source_end": 3, "order": 0, "role": "hook"},
                    {"id": "b", "source_start": 10, "source_end": 13, "order": 1, "role": "ending"},
                ],
                "subtitle_enabled": False,
                "fps": 30,
                "quality": "balanced",
                "audio": {"volume": 1, "muted": False, "fade_in": 0, "fade_out": 0, "normalize": False, "target_lufs": -18, "limiter": False},
                "title_overlay": {"enabled": True, "text": "Title only", "font": "Arial", "size": 48, "color": "#ffffff", "position": 18, "duration": 2, "fade_in": 0.2, "fade_out": 0.2},
            }
            ass_caption_inputs = []

            def capture_ass(_path, segments, *_args, **_kwargs):
                ass_caption_inputs.append(segments)

            with patch("clipper.media.executable", return_value="ffmpeg"), \
                 patch("clipper.media.subprocess.Popen", side_effect=fake_multi_popen), \
                 patch("clipper.media._write_ass", side_effect=capture_ass), \
                 patch("clipper.media.probe", return_value={"duration": 5, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}):
                render("input.mp4", clip, multi_edit, [{"id": "hidden", "start": 0, "end": 2, "text": "Must remain hidden"}], uuid.uuid4().hex, threading.Event(), lambda _progress: None, has_audio=True)
            graph = multi_command[multi_command.index("-filter_complex") + 1]
            assert "concat=n=2:v=1:a=1" in graph and "aresample=48000" in graph and "setpts=PTS-STARTPTS" in graph
            assert multi_command[multi_command.index("-t") + 1] == "5.000"
            assert ass_caption_inputs == [[]], "title-only overlay must not burn disabled subtitles"
            Path(multi_command[-1]).unlink(missing_ok=True)

            print("Quick Clip API, manual/auto subtitles, audio consent/range, AI isolation, render, review, cancel/retry checks passed")


if __name__ == "__main__":
    run()
