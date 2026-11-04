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
from clipper.main import ClipSceneTransition, app
from clipper.media import MediaError, SCENE_TRANSITION_TYPES, map_scene_subtitles, output_scenes, render, scene_output_duration
from clipper.subtitles import composition_signature


def run():
    one_scene_timeline = output_scenes({"id": "one-scene", "start": 0, "end": 24}, {
        "scene_mode": "multi",
        "scenes": [{"id": "solo", "source_start": 1, "source_end": 2.5, "order": 0, "role": "body"}],
    })
    assert len(one_scene_timeline) == 1 and one_scene_timeline[0]["timeline_end"] == 1.5

    transition_scenes = [
        {"id": "a", "source_start": 0, "source_end": 4, "order": 0, "role": "body"},
        {"id": "b", "source_start": 10, "source_end": 14, "order": 1, "role": "body"},
        {"id": "c", "source_start": 20, "source_end": 24, "order": 2, "role": "ending"},
    ]
    transition_edit = {
        "scene_mode": "multi", "scenes": transition_scenes,
        "transitions": {
            "a>b": {"type": "crossfade", "duration": 0.5, "smooth_audio": True},
            "b>c": {"type": "dip_to_black", "duration": 0.2, "smooth_audio": False},
        },
    }
    transition_timeline = output_scenes({"id": "transition", "start": 0, "end": 24}, transition_edit)
    assert [scene["timeline_start"] for scene in transition_timeline] == [0, 3.5, 7.3]
    assert scene_output_duration(transition_timeline) == 11.3
    subtitle_snapshot_scenes = [{key: scene[key] for key in ("id", "source_start", "source_end", "timeline_start", "transition_duration", "transition_timing_mode")} for scene in transition_timeline]
    assert composition_signature(subtitle_snapshot_scenes) == composition_signature(transition_timeline)
    mapped_transition_cues = map_scene_subtitles({"id": "transition", "start": 0, "end": 24}, {
        **transition_edit, "subtitle_timebase": "source", "subtitle_segments": [
            {"id": "before", "start": 3.6, "end": 4, "text": "Before"},
            {"id": "after", "start": 10, "end": 10.4, "text": "After"},
        ],
    }, [])
    assert [(round(item["start"], 3), round(item["end"], 3)) for item in mapped_transition_cues] == [(3.6, 3.75), (3.75, 3.9)]
    inserted_timeline = output_scenes({"id": "inserted", "start": 0, "end": 24}, {
        **transition_edit,
        "scenes": transition_scenes[:2],
        "transitions": {"a>b": {"type": "crossfade", "timing_mode": "insert_slot", "duration": 0.5, "smooth_audio": True}},
    })
    assert [scene["timeline_start"] for scene in inserted_timeline] == [0, 4.5]
    assert scene_output_duration(inserted_timeline) == 8.5
    inserted_snapshot_scenes = [{key: scene[key] for key in ("id", "source_start", "source_end", "timeline_start", "transition_duration", "transition_timing_mode")} for scene in inserted_timeline]
    assert composition_signature(inserted_snapshot_scenes) == composition_signature(inserted_timeline)
    frame_timeline = output_scenes({"id": "frame", "start": 0, "end": 24}, {
        "scene_mode": "multi", "fps": 30,
        "scenes": [
            {"id": "a", "source_start": 0, "source_end": 4.01, "order": 0, "role": "body"},
            {"id": "b", "source_start": 10, "source_end": 12, "order": 1, "role": "ending"},
        ],
        "transitions": {"a>b": {"type": "crossfade", "timing_mode": "insert_slot", "duration": 0.15}},
    })
    assert frame_timeline[0]["duration"] == 4 and frame_timeline[0]["transition_frames"] == 5
    assert frame_timeline[1]["timeline_start"] == 4 + 5 / 30
    assert map_scene_subtitles({"id": "frame", "start": 0, "end": 24}, {
        "scene_mode": "multi", "fps": 30, "scenes": frame_timeline,
        "transitions": {"a>b": {"type": "crossfade", "timing_mode": "insert_slot", "duration": 0.15}},
        "subtitle_timebase": "source", "subtitle_segments": [{"id": "tail", "start": 4.005, "end": 4.01, "text": "Not rendered"}],
    }, []) == []
    rounded_overlap_timeline = output_scenes({"id": "rounded", "start": 0, "end": 24}, {
        "scene_mode": "multi", "fps": 30,
        "scenes": [
            {"id": "a", "source_start": 0, "source_end": 4, "order": 0, "role": "body"},
            {"id": "b", "source_start": 10, "source_end": 10 + 61 / 30, "order": 1, "role": "body"},
            {"id": "c", "source_start": 20, "source_end": 24, "order": 2, "role": "ending"},
        ],
        "transitions": {
            "a>b": {"type": "crossfade", "duration": 61 / 60},
            "b>c": {"type": "crossfade", "duration": 61 / 60},
        },
    })
    assert [scene["transition_frames"] for scene in rounded_overlap_timeline] == [31, 30, 0]
    assert rounded_overlap_timeline[1]["transition_frames"] + rounded_overlap_timeline[0]["transition_frames"] == 61

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
            full_edit = client.get(f"/api/clips/{second['clip_id']}").json()["clip"]["edit"]
            full_edit["transitions"] = {"scene-a>scene-b": {"type": "crossfade", "duration": 0.25, "smooth_audio": True}}
            transition_saved = client.patch(f"/api/clips/{second['clip_id']}", json=full_edit)
            assert transition_saved.status_code == 200, transition_saved.text
            assert transition_saved.json()["transitions"]["scene-a>scene-b"] == {"type": "crossfade", "duration": 0.25, "timing_mode": "overlap", "smooth_audio": True}
            transition_defaults = client.patch(f"/api/clips/{second['clip_id']}", json={
                "transitions": {"scene-a>scene-b": {"type": "dip_to_black"}},
            })
            assert transition_defaults.status_code == 200, transition_defaults.text
            assert transition_defaults.json()["transitions"]["scene-a>scene-b"] == {"type": "dip_to_black", "duration": 0.25, "timing_mode": "overlap", "smooth_audio": False}
            inserted_transition = client.patch(f"/api/clips/{second['clip_id']}", json={
                "transitions": {"scene-a>scene-b": {"type": "crossfade", "timing_mode": "insert_slot", "smooth_audio": False}},
            })
            assert inserted_transition.status_code == 200, inserted_transition.text
            assert inserted_transition.json()["transitions"]["scene-a>scene-b"]["timing_mode"] == "insert_slot"
            assert inserted_transition.json()["transitions"]["scene-a>scene-b"]["duration"] == 0.5
            with patch("clipper.main.local_transcription_available", return_value=True):
                queued_subtitle = client.post(f"/api/clips/{second['clip_id']}/subtitles/transcribe", json={"provider": "local", "language": "indonesia"})
            assert queued_subtitle.status_code == 200, queued_subtitle.text
            with connect() as conn:
                subtitle_job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (queued_subtitle.json()["id"],)).fetchone())
            subtitle_options = json.loads(subtitle_job["options_json"])
            assert composition_signature(subtitle_options["scenes"]) == subtitle_options["composition_signature"]
            with patch("clipper.jobs.extract_composition_audio", return_value=5.5), \
                 patch("clipper.jobs.transcribe", return_value=([{"start": 0.5, "end": 1.5, "text": "Insert Slot cue."}], "id", f"whisper|{'m' * 160}|123|456|789|987")):
                runner._process(subtitle_job, threading.Event())
            generated_edit = client.get(f"/api/clips/{second['clip_id']}").json()
            generated_track = next(track for track in generated_edit["clip"]["edit"]["subtitle_tracks"] if track["id"] == subtitle_options["track_id"])
            assert len(generated_track["model"]) > 120
            assert generated_track["composition_signature"] == generated_edit["subtitle_status"]["composition_signature"]
            assert generated_track["id"] not in generated_edit["subtitle_status"]["stale_track_ids"]
            activate_generated = client.patch(f"/api/clips/{second['clip_id']}", json={
                "subtitle_tracks": generated_edit["clip"]["edit"]["subtitle_tracks"],
                "subtitle_active_track_id": generated_track["id"],
                "subtitle_segments": generated_track["segments"], "subtitle_timebase": "output",
                "subtitle_mode": "auto", "subtitle_enabled": True,
            })
            assert activate_generated.status_code == 200, activate_generated.text
            subtitle_export = client.get(f"/api/clips/{second['clip_id']}/subtitles/export", params={"track_id": generated_track["id"]})
            assert subtitle_export.status_code == 200 and "Insert Slot cue." in subtitle_export.text
            for invalid_duration in (0.05, 2.1):
                rejected_duration = client.patch(f"/api/clips/{second['clip_id']}", json={
                    "transitions": {"scene-a>scene-b": {"type": "crossfade", "timing_mode": "insert_slot", "duration": invalid_duration, "smooth_audio": False}},
                })
                assert rejected_duration.status_code == 422
            rejected_insert_zoom = client.patch(f"/api/clips/{second['clip_id']}", json={
                "transitions": {"scene-a>scene-b": {"type": "zoom_blur", "timing_mode": "insert_slot", "duration": 0.5, "smooth_audio": False}},
            })
            assert rejected_insert_zoom.status_code == 422
            rejected_transition = client.patch(f"/api/clips/{second['clip_id']}", json={
                "transitions": {"scene-a>scene-b": {"type": "crossfade", "duration": 2.1, "smooth_audio": False}},
            })
            assert rejected_transition.status_code == 422
            saved_transition = client.get(f"/api/clips/{second['clip_id']}").json()["clip"]["edit"]["transitions"]["scene-a>scene-b"]
            assert saved_transition["duration"] == 0.5 and saved_transition["timing_mode"] == "insert_slot"
            for transition_type in sorted(SCENE_TRANSITION_TYPES - {"none"}):
                assert ClipSceneTransition(type=transition_type).type == transition_type
                accepted_transition = client.patch(f"/api/clips/{second['clip_id']}", json={
                    "transitions": {"scene-a>scene-b": {"type": transition_type, "timing_mode": "overlap", "duration": 0.5}},
                })
                assert accepted_transition.status_code == 200, accepted_transition.text
            long_multi = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "multi",
                "scenes": [
                    {"id": "long-a", "source_start": 1, "source_end": 101, "order": 0, "role": "hook"},
                    {"id": "long-b", "source_start": 102, "source_end": 183, "order": 1, "role": "ending"},
                ],
            })
            assert long_multi.status_code == 200, long_multi.text
            blocked_long_render = client.post(f"/api/clips/{second['clip_id']}/render")
            assert blocked_long_render.status_code == 422 and "180 seconds" in blocked_long_render.json()["detail"]
            restored_multi = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "multi", "scenes": multi_saved.json()["scenes"],
            })
            assert restored_multi.status_code == 200, restored_multi.text
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
            assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vcat][acat]" in graph
            assert "aresample=48000" in graph and "setpts=PTS-STARTPTS" in graph
            assert multi_command[multi_command.index("-t") + 1] == "5.000"
            assert ass_caption_inputs == [[]], "title-only overlay must not burn disabled subtitles"
            Path(multi_command[-1]).unlink(missing_ok=True)

            transition_effects = {"crossfade": "fade", "dip_to_black": "fadeblack", "zoom_blur": "fade"}
            transition_effects.update({kind: kind for kind in SCENE_TRANSITION_TYPES if kind not in transition_effects and kind != "none"})
            for transition_type, effect in sorted(transition_effects.items()):
                smooth_audio = transition_type == "crossfade"
                transition_command = []

                def fake_transition_popen(argv, **_kwargs):
                    transition_command.extend(argv)
                    Path(argv[-1]).write_bytes(b"fake transition MP4")
                    return FakeProcess()

                transitioned_edit = {
                    **multi_edit,
                    "transitions": {"a>b": {"type": transition_type, "duration": 0.5, "smooth_audio": smooth_audio}},
                }
                with patch("clipper.media.executable", return_value="ffmpeg"), \
                     patch("clipper.media.subprocess.Popen", side_effect=fake_transition_popen), \
                 patch("clipper.media.probe", return_value={"duration": 4.5, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}):
                    render("input.mp4", clip, transitioned_edit, [], uuid.uuid4().hex, threading.Event(), lambda _progress: None, has_audio=True)
                transition_graph = transition_command[transition_command.index("-filter_complex") + 1]
                assert f"xfade=transition={effect}:duration=0.500000000:offset=1.500000000" in transition_graph
                assert transition_command[transition_command.index("-t") + 1] == "4.500000"
                if smooth_audio:
                    assert "acrossfade=d=0.500000000" in transition_graph
                else:
                    assert "atrim=start=0.250000000" in transition_graph
                Path(transition_command[-1]).unlink(missing_ok=True)

            inserted_command = []

            def fake_insert_popen(argv, **_kwargs):
                inserted_command.extend(argv)
                Path(argv[-1]).write_bytes(b"fake inserted-slot MP4")
                return FakeProcess()

            inserted_edit = {
                **multi_edit,
                "resolution": "1080",
                "fps": 60,
                "transitions": {"a>b": {"type": "crossfade", "timing_mode": "insert_slot", "duration": 0.5, "smooth_audio": True}},
            }
            with patch("clipper.media.executable", return_value="ffmpeg"), \
                 patch("clipper.media._video_encoder", return_value=["-c:v", "libx264"]), \
                 patch("clipper.media.subprocess.Popen", side_effect=fake_insert_popen), \
                 patch("clipper.media.probe", return_value={"duration": 5.5, "width": 1080, "height": 1920, "video_codec": "h264", "audio_codec": "aac"}):
                render("input.mp4", clip, inserted_edit, [], uuid.uuid4().hex, threading.Event(), lambda _progress: None, has_audio=True)
            inserted_graph = inserted_command[inserted_command.index("-filter_complex") + 1]
            assert inserted_command[inserted_command.index("-t") + 1] == "5.500000"
            assert "scale=1080:1920" in inserted_graph and "fps=60" in inserted_graph and "setpts=PTS-STARTPTS" in inserted_graph
            assert "[v0]split=2[vmain_src_0][vhold_src_0]" in inserted_graph
            assert "[v1]split=2[vto_hold_src_0][vto_main_src_0]" in inserted_graph
            assert "[vmain_src_0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:" in inserted_graph
            assert "[vto_main_src_0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:" in inserted_graph
            assert "[vmain_0][vslot_0][vto_main_0]concat=n=3:v=1:a=0" in inserted_graph
            assert "xfade=transition=fade:duration=0.500000000:offset=0" in inserted_graph and "trim=end_frame=30" in inserted_graph
            assert "concat=n=3:v=1:a=0" in inserted_graph and "anullsrc=r=48000:cl=stereo,atrim=duration=0.500000000" in inserted_graph
            assert "afade=t=out" in inserted_graph and "afade=t=in" in inserted_graph and "acrossfade" not in inserted_graph
            Path(inserted_command[-1]).unlink(missing_ok=True)

            wipe_insert_command = []

            def fake_wipe_insert_popen(argv, **_kwargs):
                wipe_insert_command.extend(argv)
                Path(argv[-1]).write_bytes(b"fake wipe insert MP4")
                return FakeProcess()

            wipe_insert_edit = {
                **multi_edit,
                "transitions": {"a>b": {"type": "wipeleft", "timing_mode": "insert_slot", "duration": 0.5, "smooth_audio": False}},
            }
            with patch("clipper.media.executable", return_value="ffmpeg"), \
                 patch("clipper.media.subprocess.Popen", side_effect=fake_wipe_insert_popen), \
                 patch("clipper.media.probe", return_value={"duration": 5.5, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}):
                render("input.mp4", clip, wipe_insert_edit, [], uuid.uuid4().hex, threading.Event(), lambda _progress: None, has_audio=True)
            wipe_insert_graph = wipe_insert_command[wipe_insert_command.index("-filter_complex") + 1]
            assert "xfade=transition=wipeleft:duration=0.500000000:offset=0" in wipe_insert_graph
            Path(wipe_insert_command[-1]).unlink(missing_ok=True)

            dip_command = []

            def fake_dip_popen(argv, **_kwargs):
                dip_command.extend(argv)
                Path(argv[-1]).write_bytes(b"fake dip-slot MP4")
                return FakeProcess()

            dip_edit = {
                **multi_edit,
                "transitions": {"a>b": {"type": "dip_to_black", "timing_mode": "insert_slot", "duration": 0.5, "smooth_audio": False}},
            }
            with patch("clipper.media.executable", return_value="ffmpeg"), \
                 patch("clipper.media.subprocess.Popen", side_effect=fake_dip_popen), \
                 patch("clipper.media.probe", return_value={"duration": 5.5, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}):
                render("input.mp4", clip, dip_edit, [], uuid.uuid4().hex, threading.Event(), lambda _progress: None, has_audio=False)
            dip_graph = dip_command[dip_command.index("-filter_complex") + 1]
            assert "fade=t=out" in dip_graph and "fade=t=in" in dip_graph and "concat=n=3:v=1:a=0" in dip_graph
            assert "anullsrc=r=48000:cl=stereo,atrim=duration=0.500000000" in dip_graph
            Path(dip_command[-1]).unlink(missing_ok=True)

            failure_id = uuid.uuid4().hex
            failure_target = CLIP_DIR / f"{clip['id']}-{failure_id}.mp4"

            class FailedProcess(FakeProcess):
                def __init__(self):
                    super().__init__()
                    self.returncode = 1

            def fake_failed_popen(argv, **kwargs):
                kwargs["stderr"].write(b"Invalid transition filtergraph")
                Path(argv[-1]).write_bytes(b"partial MP4")
                return FailedProcess()

            try:
                with patch("clipper.media.executable", return_value="ffmpeg"), \
                     patch("clipper.media.subprocess.Popen", side_effect=fake_failed_popen), \
                     patch("clipper.media.probe", return_value={"duration": 4.5, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}):
                    render("input.mp4", clip, {**multi_edit, "transitions": {"a>b": {"type": "crossfade", "duration": 0.5}}}, [], failure_id, threading.Event(), lambda _progress: None, has_audio=True)
            except MediaError as exc:
                assert "Invalid transition filtergraph" in str(exc)
            else:
                raise AssertionError("failed transition render must surface FFmpeg error")
            assert not failure_target.exists(), "failed render must remove partial MP4 output"

            fractional_trim = client.patch(f"/api/clips/{second['clip_id']}", json={
                "scene_mode": "single", "trim_start": 0.13, "trim_end": 8.87,
                "subtitle_mode": "off", "subtitle_enabled": False, "subtitle_timebase": "clip",
                "subtitle_segments": [], "subtitle_tracks": [],
                "subtitle_active_track_id": None, "subtitle_active_translation_id": None,
            })
            assert fractional_trim.status_code == 200, fractional_trim.text
            with patch("clipper.main.local_transcription_available", return_value=True):
                fractional_job_response = client.post(
                    f"/api/clips/{second['clip_id']}/subtitles/transcribe",
                    json={"provider": "local", "language": "indonesia"},
                )
            assert fractional_job_response.status_code == 200, fractional_job_response.text
            with connect() as conn:
                fractional_job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (fractional_job_response.json()["id"],)).fetchone())
            fractional_options = json.loads(fractional_job["options_json"])
            assert composition_signature(fractional_options["scenes"]) != fractional_options["composition_signature"]
            edit_during_transcription = client.patch(f"/api/clips/{second['clip_id']}", json={"subtitle_mode": "manual"})
            assert edit_during_transcription.status_code == 409
            with patch("clipper.jobs.extract_composition_audio", return_value=8.73), \
                 patch("clipper.jobs.transcribe", return_value=([{"start": 0.5, "end": 1.5, "text": "Fractional trim cue."}], "id", "fixture")):
                runner._process(fractional_job, threading.Event())
            fractional_result = client.get(f"/api/clips/{second['clip_id']}").json()
            fractional_track = next(track for track in fractional_result["clip"]["edit"]["subtitle_tracks"] if track["id"] == fractional_options["track_id"])
            assert fractional_track["composition_signature"] == fractional_result["subtitle_status"]["composition_signature"]
            assert fractional_track["id"] not in fractional_result["subtitle_status"]["stale_track_ids"]
            fractional_edit = fractional_result["clip"]["edit"]
            fractional_track["composition_signature"] = composition_signature(fractional_options["scenes"])
            assert fractional_track["composition_signature"] != fractional_result["subtitle_status"]["composition_signature"]
            stale_metadata_save = client.patch(f"/api/clips/{second['clip_id']}", json=fractional_edit)
            assert stale_metadata_save.status_code == 200, stale_metadata_save.text
            repaired_result = client.get(f"/api/clips/{second['clip_id']}").json()
            repaired_track = next(track for track in repaired_result["clip"]["edit"]["subtitle_tracks"] if track["id"] == fractional_options["track_id"])
            assert repaired_track["composition_signature"] == repaired_result["subtitle_status"]["composition_signature"]
            assert repaired_track["id"] not in repaired_result["subtitle_status"]["stale_track_ids"]
            repaired_edit = repaired_result["clip"]["edit"]
            repaired_track["composition_signature"] = composition_signature(fractional_options["scenes"])
            repaired_track["composition_fingerprint"] = "0" * 64
            repaired_edit.update({
                "subtitle_active_track_id": repaired_track["id"], "subtitle_active_translation_id": None,
                "subtitle_segments": repaired_track["segments"], "subtitle_timebase": "output",
                "subtitle_mode": "auto", "subtitle_enabled": True,
            })
            repaired_track["composition_signature"] = repaired_result["subtitle_status"]["composition_signature"]
            repaired_track["composition_fingerprint"] = repaired_result["subtitle_status"]["composition_fingerprint"]
            use_track_save = client.patch(f"/api/clips/{second['clip_id']}", json=repaired_edit)
            assert use_track_save.status_code == 200, use_track_save.text
            subtitle_export = client.get(f"/api/clips/{second['clip_id']}/subtitles/export", params={"format": "srt", "track_id": repaired_track["id"]})
            assert subtitle_export.status_code == 200 and "Fractional trim cue." in subtitle_export.text

            print("Quick Clip API, manual/auto subtitles, audio consent/range, AI isolation, render, review, cancel/retry checks passed")


if __name__ == "__main__":
    run()
