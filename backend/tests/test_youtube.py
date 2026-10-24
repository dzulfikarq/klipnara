import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-youtube-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import CLIP_DIR
from clipper.db import connect, init_db
from clipper.jobs import now, runner
from clipper.main import app
from clipper import youtube


def _seed_clip(source_id, clip_id, job_id, rendered, review_status="approved"):
    reviewed_hash = hashlib.sha256(rendered.read_bytes()).hexdigest() if review_status == "approved" and rendered.is_file() else None
    with connect() as conn:
        conn.execute(
            "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,sha256,created_at,transcript_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (source_id, "youtube-test.mp4", f"{source_id}.mp4", 1, 40, 720, 1280, "h264", source_id, now(), "[]"),
        )
        conn.execute(
            "INSERT INTO jobs(id,source_id,kind,status,phase,options_json,created_at,updated_at) "
            "VALUES(?,?,?,'failed','failed','{}',?,?)",
            (job_id, source_id, "render", now(), now()),
        )
        conn.execute(
            "INSERT INTO clips(id,source_id,job_id,start,end,title,reason,rank,edit_json,status,review_status,reviewed_render_sha256,rendered_path,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,'completed',?,?,?,?)",
            (clip_id, source_id, job_id, 0, 20, "Manual title", "fixture", 1, "{}", review_status, reviewed_hash, str(rendered), now()),
        )


def run():
    with patch.dict(os.environ, {
        "YOUTUBE_CLIENT_ID": "test-client-id",
        "YOUTUBE_CLIENT_SECRET": "test-client-secret",
        "YOUTUBE_REDIRECT_URI": "http://127.0.0.1:8000/api/youtube/oauth/callback",
    }), patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            oauth_config = client.get("/api/youtube/config").json()
            assert oauth_config["start_url"] == "http://127.0.0.1:8000/api/youtube/oauth/start"
            protected = youtube.encrypt_secret("token must not appear in plaintext")
            assert b"token must not appear in plaintext" not in protected
            assert youtube.decrypt_secret(protected) == "token must not appear in plaintext"

            legacy_clip, legacy_source, legacy_job = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
            legacy_media = CLIP_DIR / "legacy-approved-fixture.mp4"
            legacy_media.write_bytes(b"legacy approval")
            _seed_clip(legacy_source, legacy_clip, legacy_job, legacy_media)
            with connect() as conn:
                conn.execute("UPDATE clips SET reviewed_render_sha256=NULL WHERE id=?", (legacy_clip,))
            init_db()
            with connect() as conn:
                migrated = conn.execute("SELECT review_status FROM clips WHERE id=?", (legacy_clip,)).fetchone()
            assert migrated["review_status"] == "needs_review"
            legacy_media.unlink(missing_ok=True)

            eligibility_file = CLIP_DIR / "short-eligibility-fixture.mp4"
            eligibility_file.write_bytes(b"fixture")
            eligible_clip = {
                "review_status": "approved", "status": "completed", "rendered_path": str(eligibility_file),
                "reviewed_render_sha256": hashlib.sha256(eligibility_file.read_bytes()).hexdigest(),
            }
            with patch("clipper.youtube.probe", return_value={"video_codec": "h264", "audio_codec": "aac", "duration": 179.9, "width": 1080, "height": 1920}):
                validated, details, digest = youtube.validate_short(eligible_clip)
                assert validated == eligibility_file.resolve() and details["height"] == 1920 and len(digest) == 64
            invalid_cases = [
                ({"video_codec": "h264", "audio_codec": "aac", "duration": 181, "width": 720, "height": 1280}, "duration"),
                ({"video_codec": "h264", "audio_codec": "aac", "duration": 20, "width": 1280, "height": 720}, "aspect"),
                ({"video_codec": "vp9", "audio_codec": "aac", "duration": 20, "width": 720, "height": 1280}, "codec"),
            ]
            for invalid_metadata, _reason in invalid_cases:
                with patch("clipper.youtube.probe", return_value=invalid_metadata):
                    try:
                        youtube.validate_short(eligible_clip)
                    except youtube.YouTubeError:
                        pass
                    else:
                        raise AssertionError(f"Short eligibility accepted invalid media: {_reason}")
            eligibility_file.unlink(missing_ok=True)

            state = youtube.create_oauth_state()
            assert not youtube.consume_oauth_state(state, "wrong-browser")
            assert youtube.consume_oauth_state(state, state)
            assert not youtube.consume_oauth_state(state, state)

            started = client.get("/api/youtube/oauth/start", follow_redirects=False)
            assert started.status_code == 302
            location = urllib.parse.urlsplit(started.headers["location"])
            query = urllib.parse.parse_qs(location.query)
            assert query["scope"] == [youtube.SCOPE]
            assert query["response_type"] == ["code"] and query["access_type"] == ["offline"]
            assert started.headers["set-cookie"].lower().find("httponly") >= 0
            callback_state = query["state"][0]
            token_data = {
                "access_token": "fake-access-token", "refresh_token": "fake-refresh-token",
                "token_type": "Bearer", "expires_in": 3600, "scope": youtube.SCOPE,
            }
            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call",
                return_value=({"items": [{"id": "channel-1", "snippet": {"title": "Private Test Channel"}}]}, {}),
            ):
                callback = client.get(
                    "/api/youtube/oauth/callback?" + urllib.parse.urlencode({"code": "fake-code", "state": callback_state}),
                    follow_redirects=False,
                )
            assert callback.status_code == 303 and "youtube=connected" in callback.headers["location"]
            connected = client.get("/api/youtube/accounts").json()
            assert connected["accounts"][0]["channel_title"] == "Private Test Channel"
            assert connected["accounts"][0]["status"] == "connected"
            assert "token_blob" not in connected["accounts"][0]
            account_id = connected["accounts"][0]["id"]
            channel_id = connected["accounts"][0]["channel_id"]

            # Review gate happens before ffprobe or queue creation.
            unapproved_id = uuid.uuid4().hex
            source_id, parent_job = uuid.uuid4().hex, uuid.uuid4().hex
            _seed_clip(source_id, unapproved_id, parent_job, CLIP_DIR / "unapproved.mp4", "needs_revision")
            body = {"account_id": account_id, "title": "Manual title", "made_for_kids": False, "contains_synthetic_media": False}
            denied = client.post(f"/api/clips/{unapproved_id}/youtube-publications", json=body)
            assert denied.status_code == 409

            media = CLIP_DIR / "approved-youtube-fixture.mp4"
            media.write_bytes(b"fixture" * 40000)
            clip_id, source_id, parent_job = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
            _seed_clip(source_id, clip_id, parent_job, media)
            metadata = {"duration": 40.0, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}
            with patch("clipper.youtube.probe", return_value=metadata):
                queued = client.post(
                    f"/api/clips/{clip_id}/youtube-publications",
                    json={**body, "tags": ["demo", "local"], "description": "manual copy"},
                )
            assert queued.status_code == 200, queued.text
            publication = queued.json()
            assert publication["status"] == "pending" and publication["privacy_status"] == "private"
            assert publication["made_for_kids"] is False and publication["contains_synthetic_media"] is False
            duplicate = client.post(f"/api/clips/{clip_id}/youtube-publications", json=body)
            assert duplicate.status_code == 409

            chunk_size = 256 * 1024
            with patch("clipper.youtube.CHUNK_BYTES", chunk_size), patch("clipper.youtube.probe", return_value=metadata):
                posted_metadata = []
                ranges = []

                def fake_http(method, url, headers=None, body=None, timeout=30):
                    headers = headers or {}
                    if method == "POST" and url.startswith(youtube.UPLOAD_URL):
                        posted_metadata.append(json.loads(body))
                        return 200, {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=fake"}, b""
                    if method == "PUT" and "upload_id=fake" in url:
                        if headers.get("Content-Range") == f"bytes */{publication['file_size']}":
                            return 308, {"Range": f"bytes=0-{chunk_size - 1}"}, b""
                        ranges.append(headers.get("Content-Range"))
                        if len(ranges) == 1:
                            raise youtube.YouTubeError("simulated dropped connection", retryable=True)
                        return 201, {}, json.dumps({"id": "video-test-id", "snippet": {"channelId": channel_id}}).encode()
                    if method == "GET" and url.startswith(youtube.API_URL + "/videos"):
                        return 200, {}, json.dumps({"items": [{
                            "id": "video-test-id",
                            "snippet": {"channelId": channel_id},
                            "status": {"uploadStatus": "processed", "privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False},
                            "processingDetails": {"processingStatus": "succeeded"},
                        }]}).encode()
                    raise AssertionError(f"Unexpected YouTube request: {method} {url}")

                progress = []
                real_upload = youtube.run_upload

                def tracked_upload(publication_id, cancel, callback):
                    return real_upload(
                        publication_id, cancel,
                        lambda sent, total: (progress.append((sent, total)), callback(sent, total)),
                    )

                with patch("clipper.youtube._http", side_effect=fake_http):
                    with connect() as conn:
                        upload_job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (publication["job_id"],)).fetchone())
                    with patch("clipper.youtube.run_upload", side_effect=tracked_upload):
                        runner._process(upload_job, threading.Event())
            final = client.get(f"/api/youtube/publications/{publication['id']}").json()
            assert final["status"] == "published"
            assert final["video_id"] == "video-test-id" and final["video_url"] == "https://youtu.be/video-test-id"
            assert final["uploaded_bytes"] == final["file_size"] and progress[-1] == (final["file_size"], final["file_size"])
            assert ranges == [f"bytes 0-{chunk_size - 1}/{final['file_size']}", f"bytes {chunk_size}-{final['file_size'] - 1}/{final['file_size']}"]
            assert posted_metadata[0]["status"]["privacyStatus"] == "private"
            assert posted_metadata[0]["status"]["containsSyntheticMedia"] is False
            assert posted_metadata[0]["snippet"]["tags"] == ["demo", "local"]
            assert client.post(f"/api/clips/{clip_id}/youtube-publications", json=body).status_code == 409

            with connect() as conn:
                approved_clip = dict(conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())
            media.write_bytes(media.read_bytes() + b"changed after approval")
            with patch("clipper.youtube.probe", return_value={"video_codec": "h264", "audio_codec": "aac", "duration": 40.0, "width": 720, "height": 1280}):
                try:
                    youtube.validate_short(approved_clip)
                except youtube.YouTubeError:
                    pass
                else:
                    raise AssertionError("Modified approved output must be blocked")

            assert client.patch(f"/api/clips/{clip_id}", json={"crop_x": 60}).status_code == 200
            with connect() as conn:
                conn.execute("UPDATE clips SET status='completed' WHERE id=?", (clip_id,))
            with patch("clipper.main.probe", return_value={"video_codec": "h264", "audio_codec": "aac"}):
                reapproved = client.post(f"/api/clips/{clip_id}/review", json={"status": "approved"})
            assert reapproved.status_code == 200
            with patch("clipper.youtube.probe", return_value=metadata):
                revised_output = client.post(f"/api/clips/{clip_id}/youtube-publications", json=body)
            assert revised_output.status_code == 200 and revised_output.json()["status"] == "pending"
            assert client.post(f"/api/youtube/publications/{revised_output.json()['id']}/cancel").status_code == 200

            retry_clip, retry_source, retry_parent_job = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
            retry_media = CLIP_DIR / "retry-youtube-fixture.mp4"
            retry_media.write_bytes(b"resumable retry fixture" * 30000)
            _seed_clip(retry_source, retry_clip, retry_parent_job, retry_media)
            with patch("clipper.youtube.probe", return_value=metadata):
                retry_publication = client.post(f"/api/clips/{retry_clip}/youtube-publications", json=body).json()
            retry_session = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=retry"
            with connect() as conn:
                conn.execute(
                    "UPDATE youtube_publications SET status='failed',upload_session_blob=?,upload_started=1,last_error='network interruption' WHERE id=?",
                    (youtube.encrypt_secret(retry_session), retry_publication["id"]),
                )
                conn.execute("UPDATE jobs SET status='failed',phase='failed' WHERE id=?", (retry_publication["job_id"],))
            with patch("clipper.youtube.probe", return_value=metadata):
                resumed = client.post(f"/api/youtube/publications/{retry_publication['id']}/retry")
            assert resumed.status_code == 200 and resumed.json()["attempts"] == 2
            resumed_ranges = []

            def retry_http(method, url, headers=None, body=None, timeout=30):
                headers = headers or {}
                if method == "PUT" and "upload_id=retry" in url:
                    content_range = headers.get("Content-Range")
                    if content_range.startswith("bytes */"):
                        return 308, {"Range": f"bytes=0-{chunk_size - 1}"}, b""
                    resumed_ranges.append(content_range)
                    return 201, {}, json.dumps({"id": "video-retry-id", "snippet": {"channelId": channel_id}}).encode()
                if method == "GET" and url.startswith(youtube.API_URL + "/videos"):
                    return 200, {}, json.dumps({"items": [{
                        "id": "video-retry-id", "snippet": {"channelId": channel_id},
                        "status": {"uploadStatus": "processed", "privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False},
                        "processingDetails": {"processingStatus": "succeeded"},
                    }]}).encode()
                raise AssertionError(f"Retry started a duplicate session or unexpected request: {method} {url}")

            with patch("clipper.youtube.probe", return_value=metadata), patch("clipper.youtube._http", side_effect=retry_http):
                with connect() as conn:
                    retry_job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (resumed.json()["job_id"],)).fetchone())
                runner._process(retry_job, threading.Event())
            retry_final = client.get(f"/api/youtube/publications/{retry_publication['id']}").json()
            assert retry_final["status"] == "published" and retry_final["video_id"] == "video-retry-id"
            assert resumed_ranges == [f"bytes {chunk_size}-{retry_final['file_size'] - 1}/{retry_final['file_size']}"]

            cancel_clip, cancel_source, cancel_job = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
            cancel_media = CLIP_DIR / "cancel-youtube-fixture.mp4"
            cancel_media.write_bytes(b"cancel fixture")
            _seed_clip(cancel_source, cancel_clip, cancel_job, cancel_media)
            with patch("clipper.youtube.probe", return_value=metadata):
                pending = client.post(f"/api/clips/{cancel_clip}/youtube-publications", json=body).json()
            cancelled = client.post(f"/api/youtube/publications/{pending['id']}/cancel")
            assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
            with connect() as conn:
                job_status = conn.execute("SELECT status FROM jobs WHERE id=?", (pending["job_id"],)).fetchone()["status"]
            assert job_status == "cancelled"

            # An expired resumable session after a PUT attempt is reconciled and never re-uploaded automatically.
            uncertain_clip, uncertain_source, uncertain_job = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
            uncertain_media = CLIP_DIR / "uncertain-youtube-fixture.mp4"
            uncertain_media.write_bytes(b"uncertain fixture")
            _seed_clip(uncertain_source, uncertain_clip, uncertain_job, uncertain_media)
            with patch("clipper.youtube.probe", return_value=metadata):
                uncertain = client.post(f"/api/clips/{uncertain_clip}/youtube-publications", json=body).json()
            with connect() as conn:
                conn.execute(
                    "UPDATE youtube_publications SET upload_session_blob=?,upload_started=1 WHERE id=?",
                    (youtube.encrypt_secret("https://www.googleapis.com/upload/youtube/v3/videos?upload_id=expired"), uncertain["id"]),
                )
            with patch("clipper.youtube.probe", return_value=metadata), patch(
                "clipper.youtube._http", return_value=(404, {}, b"")
            ):
                try:
                    youtube.run_upload(uncertain["id"], threading.Event(), lambda *_: None)
                except youtube.YouTubeError:
                    pass
                else:
                    raise AssertionError("Expired resumable session must fail closed")
            uncertain_state = client.get(f"/api/youtube/publications/{uncertain['id']}").json()
            assert uncertain_state["status"] == "failed" and uncertain_state["reconciliation_required"]
            assert client.post(f"/api/youtube/publications/{uncertain['id']}/retry").status_code == 409

            with connect() as conn:
                conn.execute("UPDATE youtube_accounts SET expires_at=0 WHERE id=?", (account_id,))
            with patch("clipper.youtube._json_call", side_effect=youtube.YouTubeError("expired", status=400, reason="invalid_grant")):
                try:
                    youtube._refresh(account_id)
                except youtube.YouTubeError:
                    pass
                else:
                    raise AssertionError("invalid_grant must reject expired refresh token")
            assert client.get("/api/youtube/accounts").json()["accounts"][0]["status"] == "expired"
            with patch("clipper.youtube._json_call", return_value=({}, {})):
                disconnected = client.delete(f"/api/youtube/accounts/{account_id}")
            assert disconnected.status_code == 200
            row = next(item for item in client.get("/api/youtube/accounts").json()["accounts"] if item["id"] == account_id)
            assert row["status"] == "disconnected"
            media.unlink(missing_ok=True)
            retry_media.unlink(missing_ok=True)
            cancel_media.unlink(missing_ok=True)
            uncertain_media.unlink(missing_ok=True)
    print("YouTube OAuth, approval gate, resumable upload, reconciliation, cancellation, and account lifecycle checks passed")


if __name__ == "__main__":
    run()
