import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="clipper-test-")
os.environ["OPENAI_API_KEY"] = "test-only-key"
os.environ["GEMINI_API_KEY"] = "test-only-key"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import CLIP_DIR
from clipper.db import connect
from clipper.jobs import now
from clipper.main import app
from clipper.subtitles import composition_fingerprint


def run():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/settings").json()["providers"]["gemini"]["model"] == "gemini-3.5-flash-lite"
        capabilities = client.get("/api/system/capabilities").json()
        assert capabilities["cpu"] and capabilities["ram_bytes"] and capabilities["gpus"]
        assert client.post("/api/sources/url", json={"url": "http://127.0.0.1/video.mp4"}).status_code == 400
        assert client.post("/api/sources/url", json={"url": "https://127.0.0.1/video.mp4"}).status_code == 400

        source_id = uuid.uuid4().hex
        with connect() as conn:
            conn.execute(
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (source_id, "test.mp4", "unavailable.mp4", 1, 120, 1280, 720, "h264", "aac", "test", now()),
            )
        endpoint = f"/api/sources/{source_id}/generate"
        cloud = {"provider": "openai", "consent": False}
        assert client.post(endpoint, json=cloud).status_code == 400
        assert client.post(endpoint, json={"provider": "gemini", "consent": False}).status_code == 400
        cloud["consent"] = True
        result = client.post(endpoint, json=cloud)
        assert result.status_code == 200
        with connect() as conn:
            row = conn.execute("SELECT options_json FROM jobs WHERE id=?", (result.json()["id"],)).fetchone()
        assert '"consent_at":' in row["options_json"]

        old_job, timestamp = uuid.uuid4().hex, now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO jobs(id,source_id,kind,status,phase,options_json,created_at,updated_at) VALUES(?,?,?,'failed','failed',?,?,?)",
                (old_job, source_id, "render", '{"edit":{}}', timestamp, timestamp),
            )
            conn.execute(
                "INSERT INTO analysis_chunks(job_id,chunk_index,cache_key,input_tokens,candidates_json,created_at) VALUES(?,?,?,?,?,?)",
                (old_job, 0, "fixture-key", 123, '[{"title":"cached"}]', timestamp),
            )
        retried = client.post(f"/api/jobs/{old_job}/retry", json={})
        assert retried.status_code == 200, retried.text
        with connect() as conn:
            cached = conn.execute("SELECT cache_key,input_tokens,candidates_json FROM analysis_chunks WHERE job_id=?", (retried.json()["id"],)).fetchone()
        assert tuple(cached) == ("fixture-key", 123, '[{"title":"cached"}]')

        manual_source, manual_job, clip_id = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
        manual_transcript = json.dumps([{"start": 0.0, "end": 2.0, "text": "Kalimat uji."}])
        edit = {
            "trim_start": 0, "trim_end": 20, "subtitle_enabled": True, "style": "Clean",
            "resolution": "720", "crop_x": 50, "crop_y": 50, "subtitle_size": 48,
            "subtitle_position": 82, "subtitle_color": "#ffffff", "subtitle_overrides": {},
        }
        with connect() as conn:
            conn.execute(
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,sha256,created_at,transcript_json,transcript_model,transcript_language,transcript_config) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (manual_source, "manual.mp4", f"unavailable-{manual_source}.mp4", 1, 60, 1280, 720, "h264", "test", now(), manual_transcript, "fixture", "id", "auto"),
            )
            conn.execute(
                "INSERT INTO jobs(id,source_id,kind,status,phase,options_json,created_at,updated_at) VALUES(?,?,?,'failed','failed',?,?,?)",
                (manual_job, manual_source, "render", '{"edit":{}}', now(), now()),
            )
            conn.execute(
                "INSERT INTO clips(id,source_id,job_id,start,end,title,reason,rank,edit_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (clip_id, manual_source, manual_job, 0, 20, "test", "test", 1, json.dumps(edit), now()),
            )
        corrected = client.patch(f"/api/clips/{clip_id}", json={"subtitle_overrides": {"0": "Koreksi tersimpan."}})
        assert corrected.status_code == 200 and corrected.json()["subtitle_overrides"]["0"] == "Koreksi tersimpan."
        saved = client.get(f"/api/clips/{clip_id}").json()
        assert saved["clip"]["edit"]["subtitle_overrides"]["0"] == "Koreksi tersimpan."
        assert saved["transcript"] == json.loads(manual_transcript)
        assert (saved["clip"]["start"], saved["clip"]["end"]) == (0, 20)
        assert saved["clip"]["review_status"] == "needs_review"
        assert client.patch(f"/api/clips/{clip_id}", json={"subtitle_caption_mode": "word_pop"}).status_code == 422
        assert client.patch(f"/api/clips/{clip_id}", json={"subtitle_enabled": False}).status_code == 200
        assert client.patch(f"/api/clips/{clip_id}", json={"subtitle_caption_mode": "word_pop"}).status_code == 422
        pending_words = {
            "id": "manual-words", "start": 0, "end": 2, "text": "Kalimat uji.",
            "word_alignment_reviewed": False,
            "words": [
                {"id": "word-one", "text": "Kalimat", "start": None, "end": None},
                {"id": "word-two", "text": "uji.", "start": None, "end": None},
            ],
        }
        pending = client.patch(f"/api/clips/{clip_id}", json={"subtitle_mode": "manual", "subtitle_timebase": "clip", "subtitle_segments": [pending_words]})
        assert pending.status_code == 200, pending.text
        timed_words = {**pending_words, "words": [
            {"id": "word-one", "text": "Kalimat", "start": 0.1, "end": 0.8},
            {"id": "word-two", "text": "uji.", "start": 1.0, "end": 1.8},
        ]}
        timed = client.patch(f"/api/clips/{clip_id}", json={"subtitle_segments": [timed_words]})
        assert timed.status_code == 200, timed.text
        reviewed_words = {**timed_words, "word_alignment_reviewed": True}
        reviewed = client.patch(f"/api/clips/{clip_id}", json={"subtitle_segments": [reviewed_words]})
        assert reviewed.status_code == 200, reviewed.text
        shifted_words = {**reviewed_words, "words": [
            reviewed_words["words"][0], {**reviewed_words["words"][1], "start": 1.1, "end": 1.9},
        ]}
        shifted = client.patch(f"/api/clips/{clip_id}", json={"subtitle_segments": [shifted_words]})
        assert shifted.status_code == 200 and shifted.json()["subtitle_segments"][0]["word_alignment_reviewed"] is False
        reviewed_words = {**shifted_words, "word_alignment_reviewed": True}
        reviewed = client.patch(f"/api/clips/{clip_id}", json={"subtitle_segments": [reviewed_words]})
        assert reviewed.status_code == 200, reviewed.text
        selected_word_pop = client.patch(f"/api/clips/{clip_id}", json={"subtitle_caption_mode": "word_pop", "subtitle_preset": "Word Pop"})
        assert selected_word_pop.status_code == 200, selected_word_pop.text
        assert selected_word_pop.json()["subtitle_caption_mode"] == "word_pop"
        appearance_only = client.patch(f"/api/clips/{clip_id}", json={"subtitle_preset": "Karaoke Highlight"})
        assert appearance_only.status_code == 200 and appearance_only.json()["subtitle_caption_mode"] == "word_pop"
        assert client.patch(f"/api/clips/{clip_id}", json={"subtitle_display_mode": "translated"}).status_code == 422
        untimed_track = {
            "id": "untimed-word-track", "source_type": "manual", "language": "und", "timebase": "clip",
            "segments": [{"id": "untimed-cue", "start": 0, "end": 2, "text": "No word times"}],
        }
        assert client.patch(f"/api/clips/{clip_id}", json={
            "subtitle_tracks": [untimed_track], "subtitle_active_track_id": untimed_track["id"],
            "subtitle_segments": untimed_track["segments"], "subtitle_timebase": "clip",
        }).status_code == 422
        word_track = {
            "id": "reviewed-word-track", "source_type": "manual", "language": "und", "timebase": "clip",
            "segments": [reviewed_words],
        }
        selected_track = client.patch(f"/api/clips/{clip_id}", json={
            "subtitle_tracks": [word_track], "subtitle_active_track_id": word_track["id"],
            "subtitle_segments": [reviewed_words], "subtitle_timebase": "clip",
        })
        assert selected_track.status_code == 200, selected_track.text
        track_edit = {**word_track, "segments": [{
            **reviewed_words, "words": [reviewed_words["words"][0], {**reviewed_words["words"][1], "start": 1.2, "end": 1.95}],
        }]}
        changed_track = client.patch(f"/api/clips/{clip_id}", json={"subtitle_tracks": [track_edit]})
        assert changed_track.status_code == 200
        assert changed_track.json()["subtitle_tracks"][0]["segments"][0]["word_alignment_reviewed"] is False
        reviewed_words = {**track_edit["segments"][0], "word_alignment_reviewed": True}
        track_edit["segments"] = [reviewed_words]
        reviewed_track = client.patch(f"/api/clips/{clip_id}", json={"subtitle_tracks": [track_edit]})
        assert reviewed_track.status_code == 200, reviewed_track.text
        edited_words = {**reviewed_words, "text": "Kalimat baru."}
        changed_text = client.patch(f"/api/clips/{clip_id}", json={"subtitle_segments": [edited_words]})
        assert changed_text.status_code == 200, changed_text.text
        saved_word = changed_text.json()["subtitle_segments"][0]
        assert saved_word["words"] == reviewed_words["words"] and saved_word["word_alignment_reviewed"] is False
        assert client.post(f"/api/clips/{clip_id}/render").status_code == 409
        restored_type = client.patch(f"/api/clips/{clip_id}", json={"subtitle_caption_mode": "sentence"})
        assert restored_type.status_code == 200
        manual_track = {
            "id": "manual-output", "source_type": "manual", "language": "und", "timebase": "output",
            "segments": [{"id": "output-cue", "start": 0.25, "end": 1.25, "text": "Output cue"}],
            "composition_signature": saved["subtitle_status"]["composition_signature"],
            "composition_fingerprint": "0" * 64,
        }
        mapped = client.patch(f"/api/clips/{clip_id}", json={
            "subtitle_tracks": [manual_track], "subtitle_active_track_id": "manual-output",
            "subtitle_segments": manual_track["segments"], "subtitle_timebase": "output",
        })
        assert mapped.status_code == 200, mapped.text
        mapped_track = mapped.json()["subtitle_tracks"][0]
        assert mapped_track["composition_fingerprint"] == saved["subtitle_status"]["composition_fingerprint"]
        assert mapped_track["composition_fingerprint"] == composition_fingerprint(
            "test", saved["subtitle_status"]["composition_signature"],
        )
        assert client.post(f"/api/clips/{clip_id}/review", json={"status": "approved"}).status_code == 409

        rendered = CLIP_DIR / f"review-fixture-{clip_id}.mp4"
        rendered.write_bytes(b"fake-media-for-probe-mock")
        with connect() as conn:
            conn.execute("UPDATE clips SET status='completed',rendered_path=? WHERE id=?", (str(rendered), clip_id))
        with patch("clipper.main.probe", return_value={"video_codec": "h264", "audio_codec": "opus"}):
            invalid = client.post(f"/api/clips/{clip_id}/review", json={"status": "approved"})
        assert invalid.status_code == 409
        with patch("clipper.main.probe", return_value={"video_codec": "h264", "audio_codec": "aac"}):
            approved = client.post(f"/api/clips/{clip_id}/review", json={"status": "approved"})
        assert approved.status_code == 200 and approved.json()["review_status"] == "approved"

        active_render = uuid.uuid4().hex
        with connect() as conn:
            conn.execute(
                "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,options_json,created_at,updated_at) "
                "VALUES(?,?,?,'render','queued','queued',?,?,?)",
                (active_render, manual_source, clip_id, '{"edit":{}}', now(), now()),
            )
        assert client.post(f"/api/clips/{clip_id}/review", json={"status": "needs_revision"}).status_code == 409
        with connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id=?", (active_render,))

        edited = client.patch(f"/api/clips/{clip_id}", json={"crop_x": 60})
        assert edited.status_code == 200
        with connect() as conn:
            state = conn.execute("SELECT status,review_status FROM clips WHERE id=?", (clip_id,)).fetchone()
        assert tuple(state) == ("needs_render", "needs_review")
        assert client.post(f"/api/clips/{clip_id}/review", json={"status": "approved"}).status_code == 409

        with connect() as conn:
            conn.execute("UPDATE clips SET status='completed' WHERE id=?", (clip_id,))
        with patch("clipper.main.probe", return_value={"video_codec": "h264", "audio_codec": "aac"}):
            revised = client.post(f"/api/clips/{clip_id}/review", json={"status": "needs_revision"})
        assert revised.status_code == 200 and revised.json()["review_status"] == "needs_revision"
        with patch("clipper.main.create_job", return_value="render-queued"):
            queued = client.post(f"/api/clips/{clip_id}/render")
        assert queued.status_code == 200
        with connect() as conn:
            state = conn.execute("SELECT status,review_status FROM clips WHERE id=?", (clip_id,)).fetchone()
        assert tuple(state) == ("needs_render", "needs_review")
        rendered.unlink(missing_ok=True)
    print("API privacy, consent, and route checks passed")


if __name__ == "__main__":
    run()
