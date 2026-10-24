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
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (source_id, "test.mp4", "unavailable.mp4", 1, 120, 1280, 720, "h264", "test", now()),
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
