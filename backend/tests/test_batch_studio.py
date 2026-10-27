import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-batch-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import SOURCE_DIR
from clipper.db import connect, init_db
from clipper.jobs import now, runner
from clipper.main import app
from clipper.batch_studio import batch_job_finished, batch_job_started


def _source():
    source_id = uuid.uuid4().hex
    path = SOURCE_DIR / f"{source_id}.mp4"
    path.write_bytes(b"synthetic batch source; ffprobe is intentionally not used")
    with connect() as conn:
        conn.execute(
            "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (source_id, path.name, str(path), path.stat().st_size, 100, 1280, 720, "h264", "aac", "fixture-sha", now()),
        )
    return source_id


def _quote(text="Small steps still move us forward."):
    return {
        "id": uuid.uuid4().hex, "title": "Small steps", "text": text,
        "segments": [{"text": text, "order": 1}], "mood": "calm", "tone": "natural",
        "visual_keywords": ["calm", "reflection"], "music_mood": "calm",
    }


def _free_space(*_args):
    return SimpleNamespace(free=3 * 1024**3)


def run():
    with patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            source_id = _source()
            invalid = client.post("/api/batches/clips", json={
                "name": "too many", "source_id": source_id,
                "items": [{"name": f"Clip {index}", "start": 0, "end": 10} for index in range(11)],
            })
            assert invalid.status_code == 422, invalid.text

            created = client.post("/api/batches/clips", json={
                "name": "Serial clips", "source_id": source_id,
                "shared_settings": {"resolution": "720", "fps": 30, "quality": "balanced"},
                "items": [
                    {"name": "First", "start": 0, "end": 12},
                    {"name": "Second", "start": 20, "end": 32},
                ],
            })
            assert created.status_code == 200, created.text
            batch = created.json()
            assert batch["total"] == 2 and batch["status"] == "draft"
            assert all(item["status"] == "ready" and item["editor_url"].endswith(f"?batch={batch['id']}") for item in batch["items"])

            with patch("clipper.batch_studio.shutil.disk_usage", side_effect=_free_space):
                started = client.post(f"/api/batches/{batch['id']}/start")
            assert started.status_code == 200, started.text
            first = started.json()["items"][0]
            assert client.post(f"/api/jobs/{first['job']['id']}/cancel").status_code == 409
            with connect() as conn:
                render_jobs = conn.execute("SELECT id,status FROM jobs WHERE kind='render'").fetchall()
            assert len(render_jobs) == 1 and render_jobs[0]["id"] == first["job"]["id"]

            batch_job_started(first["job"]["id"])
            with connect() as conn:
                conn.execute("UPDATE clips SET status='completed',rendered_path='fixture.mp4' WHERE id=?", (first["clip_id"],))
                conn.execute("UPDATE jobs SET status='completed',phase='completed',progress=1 WHERE id=?", (first["job"]["id"],))
            batch_job_finished(first["job"]["id"])
            middle = client.get(f"/api/batches/{batch['id']}").json()
            assert middle["status"] == "running" and middle["completed_count"] == 1
            assert middle["items"][1]["job"]["status"] == "queued"
            with connect() as conn:
                active_render_count = conn.execute("SELECT count(*) FROM jobs WHERE kind='render' AND status='queued'").fetchone()[0]
            assert active_render_count == 1

            second = middle["items"][1]
            batch_job_started(second["job"]["id"])
            with connect() as conn:
                conn.execute("UPDATE clips SET status='completed',rendered_path='fixture-2.mp4' WHERE id=?", (second["clip_id"],))
                conn.execute("UPDATE jobs SET status='completed',phase='completed',progress=1 WHERE id=?", (second["job"]["id"],))
            batch_job_finished(second["job"]["id"])
            final = client.get(f"/api/batches/{batch['id']}").json()
            assert final["status"] == "completed" and final["completed_count"] == 2
            assert all(item["review_status"] == "needs_review" for item in final["items"])

            pausable = client.post("/api/batches/clips", json={
                "name": "Paused clips", "source_id": source_id,
                "items": [{"name": "A", "start": 0, "end": 8}, {"name": "B", "start": 8, "end": 16}],
            }).json()
            with patch("clipper.batch_studio.shutil.disk_usage", side_effect=_free_space):
                client.post(f"/api/batches/{pausable['id']}/start")
            paused = client.post(f"/api/batches/{pausable['id']}/pause").json()
            assert paused["status"] == "paused"
            assert all(item["status"] == "queued" and item["job"] is None for item in paused["items"])
            added = client.post(f"/api/batches/{pausable['id']}/items", json={"name": "C", "start": 24, "end": 32})
            assert added.status_code == 200 and added.json()["total"] == 3
            assert added.json()["items"][-1]["status"] == "queued"
            ordered_ids = [item["id"] for item in added.json()["items"]][::-1]
            reordered = client.patch(f"/api/batches/{pausable['id']}/items/order", json={"item_ids": ordered_ids})
            assert reordered.status_code == 200, reordered.text
            removed_id = reordered.json()["items"][0]["id"]
            removed = client.delete(f"/api/batches/{pausable['id']}/items/{removed_id}")
            assert removed.status_code == 200 and removed.json()["total"] == 2
            assert client.post(f"/api/batches/{pausable['id']}/resume").status_code == 200

            retryable = client.post("/api/batches/clips", json={
                "name": "Retry clip", "source_id": source_id,
                "items": [{"name": "Retry", "start": 40, "end": 50}],
            }).json()
            with patch("clipper.batch_studio.shutil.disk_usage", side_effect=_free_space):
                queued = client.post(f"/api/batches/{retryable['id']}/start").json()
            failed_item = queued["items"][0]
            with connect() as conn:
                conn.execute("UPDATE jobs SET status='failed',phase='failed',message='synthetic render failure' WHERE id=?", (failed_item["job"]["id"],))
            batch_job_finished(failed_item["job"]["id"])
            failed = client.get(f"/api/batches/{retryable['id']}").json()
            assert failed["status"] == "completed_with_errors" and failed["failed_count"] == 1
            assert client.post(f"/api/jobs/{failed_item['job']['id']}/retry", json={}).status_code == 409
            with patch("clipper.batch_studio.shutil.disk_usage", side_effect=_free_space):
                retried = client.post(f"/api/batches/{retryable['id']}/items/{failed_item['id']}/retry")
            assert retried.status_code == 200, retried.text
            assert retried.json()["items"][0]["retry_count"] == 1

            mood_project = client.post("/api/mood-projects", json={})
            assert mood_project.status_code == 200, mood_project.text
            project_id = mood_project.json()["project"]["id"]
            quotes = [_quote("Small steps still move us forward."), _quote("Rest also belongs to progress.")]
            mood_batch = client.post(f"/api/mood-projects/{project_id}/batches", json={
                "name": "Manual mood batch", "items": [
                    {"name": quote["title"], "quote": quote} for quote in quotes
                ],
            })
            assert mood_batch.status_code == 200, mood_batch.text
            mood_items = mood_batch.json()["items"]
            assert len(mood_items) == 2 and all(item["mood_project_id"] for item in mood_items)
            duplicate = client.post(f"/api/batches/{mood_batch.json()['id']}/items/{mood_items[0]['id']}/duplicate")
            assert duplicate.status_code == 200, duplicate.text
            assert duplicate.json()["total"] == 3
            with connect() as conn:
                project_count = conn.execute("SELECT count(*) FROM mood_projects").fetchone()[0]
                generation_count = conn.execute("SELECT count(*) FROM mood_generations").fetchone()[0]
                linked_assets = conn.execute("SELECT count(*) FROM mood_assets WHERE project_id IN (SELECT mood_project_id FROM video_batch_items WHERE batch_id=?)", (mood_batch.json()["id"],)).fetchone()[0]
            assert project_count >= 4 and generation_count == 0 and linked_assets == 0
            with patch("clipper.batch_studio.shutil.disk_usage", side_effect=_free_space):
                mood_started = client.post(f"/api/batches/{mood_batch.json()['id']}/start").json()
            mood_job_id = mood_started["items"][0]["job"]["id"]
            assert client.post(f"/api/mood-jobs/{mood_job_id}/cancel").status_code == 409

            deleted = client.delete(f"/api/batches/{pausable['id']}")
            assert deleted.status_code == 409  # queued render created by resume must not be detached
            cancelled = client.post(f"/api/batches/{pausable['id']}/cancel")
            assert cancelled.status_code == 200
            deleted = client.delete(f"/api/batches/{pausable['id']}")
            assert deleted.status_code == 200 and deleted.json()["outputs_preserved"] is True

            interrupted = client.post("/api/batches/clips", json={
                "name": "Restart recovery", "source_id": source_id,
                "items": [{"name": "Interrupted", "start": 60, "end": 70}],
            }).json()
            with patch("clipper.batch_studio.shutil.disk_usage", side_effect=_free_space):
                queued = client.post(f"/api/batches/{interrupted['id']}/start").json()
            interrupted_item = queued["items"][0]
            with connect() as conn:
                conn.execute("UPDATE jobs SET status='rendering',phase='rendering' WHERE id=?", (interrupted_item["job"]["id"],))
                conn.execute("UPDATE clips SET status='rendering' WHERE id=?", (interrupted_item["clip_id"],))
            init_db()
            recovered = client.get(f"/api/batches/{interrupted['id']}").json()
            assert recovered["status"] == "paused" and recovered["items"][0]["status"] == "failed"
            with connect() as conn:
                clip_status = conn.execute("SELECT status FROM clips WHERE id=?", (interrupted_item["clip_id"],)).fetchone()[0]
            assert clip_status == "ready"

    print("Batch persistence, sequential scheduling, pause/resume, retry, Mood draft reuse, and guards covered")


if __name__ == "__main__":
    run()
