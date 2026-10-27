import hashlib
import json
import os
import struct
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
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


def _seed_mood_render(project_id, render_id, job_id, rendered):
    reviewed_hash = hashlib.sha256(rendered.read_bytes()).hexdigest()
    with connect() as conn:
        conn.execute(
            "INSERT INTO mood_projects(id,title,composition_json,created_at,updated_at) VALUES(?,?,?,?,?)",
            (project_id, "Mood test", "{}", now(), now()),
        )
        conn.execute(
            "INSERT INTO mood_jobs(id,project_id,render_id,kind,status,phase,options_json,created_at,updated_at) "
            "VALUES(?,?,?,'mood_render','completed','completed','{}',?,?)",
            (job_id, project_id, render_id, now(), now()),
        )
        conn.execute(
            "INSERT INTO mood_renders(id,project_id,job_id,path,status,review_status,reviewed_render_sha256,composition_json,created_at,updated_at) "
            "VALUES(?,?,?,?,'completed','approved',?,'{}',?,?)",
            (render_id, project_id, job_id, str(rendered), reviewed_hash, now(), now()),
        )


def _expect_oauth_error(expected_code, action):
    try:
        action()
    except youtube.YouTubeError as exc:
        assert exc.code == expected_code, (expected_code, exc.code, str(exc))
    else:
        raise AssertionError(f"Expected OAuth error code {expected_code}")


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
            expired_state = "expired-oauth-state"
            with connect() as conn:
                conn.execute(
                    "INSERT INTO youtube_oauth_states(state_hash,created_at,expires_at) VALUES(?,?,?)",
                    (hashlib.sha256(expired_state.encode()).hexdigest(), now(), time.time() - 1),
                )
            assert not youtube.consume_oauth_state(expired_state, expired_state)
            assert not youtube.consume_oauth_state(expired_state, expired_state)

            started = client.get("/api/youtube/oauth/start", follow_redirects=False)
            assert started.status_code == 302
            location = urllib.parse.urlsplit(started.headers["location"])
            query = urllib.parse.parse_qs(location.query)
            assert query["scope"] == [youtube.SCOPE]
            assert set(query["scope"][0].split()) == set(youtube.SCOPES)
            assert query["redirect_uri"] == ["http://127.0.0.1:8000/api/youtube/oauth/callback"]
            assert query["response_type"] == ["code"] and query["access_type"] == ["offline"]
            assert query["prompt"] == ["select_account"]
            assert query["include_granted_scopes"] == ["true"]
            state_cookie = started.headers["set-cookie"].lower()
            assert "httponly" in state_cookie and "samesite=lax" in state_cookie
            assert "path=/api/youtube/oauth/callback" in state_cookie and "max-age=600" in state_cookie
            assert "secure" not in state_cookie
            callback_state = query["state"][0]
            concurrent_starts = [client.get("/api/youtube/oauth/start", follow_redirects=False) for _ in range(2)]
            concurrent_queries = [urllib.parse.parse_qs(urllib.parse.urlsplit(item.headers["location"]).query) for item in concurrent_starts]
            concurrent_cookie_names = [item.headers["set-cookie"].split("=", 1)[0] for item in concurrent_starts]
            assert concurrent_queries[0]["state"] != concurrent_queries[1]["state"]
            assert concurrent_cookie_names[0] != concurrent_cookie_names[1]
            token_data = {
                "access_token": "fake-access-token", "refresh_token": "fake-refresh-token",
                "token_type": "Bearer", "expires_in": 3600, "scope": youtube.SCOPE,
            }

            with patch("clipper.youtube._json_call", return_value=(token_data, {})) as token_exchange:
                assert youtube._exchange_code("single-use-code") == token_data
            exchange_form = token_exchange.call_args.kwargs["form"]
            assert exchange_form["redirect_uri"] == query["redirect_uri"][0]
            assert exchange_form["code"] == "single-use-code" and exchange_form["grant_type"] == "authorization_code"
            with patch("clipper.youtube._json_call", side_effect=youtube.YouTubeError("mismatch", status=400, reason="redirect_uri_mismatch")):
                _expect_oauth_error("oauth_redirect_uri_mismatch", lambda: youtube._exchange_code("bad-code"))

            with patch("clipper.youtube._exchange_code", return_value={**token_data, "scope": youtube.UPLOAD_SCOPE}), patch(
                "clipper.youtube._json_call",
            ) as channel_lookup:
                _expect_oauth_error("oauth_scope_insufficient", lambda: youtube.connect_account("upload-only-code"))
                channel_lookup.assert_not_called()
            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call", return_value=({"items": []}, {}),
            ):
                _expect_oauth_error("youtube_channel_not_found", lambda: youtube.connect_account("no-channel-code"))
            with connect() as conn:
                assert conn.execute("SELECT COUNT(*) AS count FROM youtube_accounts").fetchone()["count"] == 0
            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call", side_effect=youtube.YouTubeError("forbidden", status=403, reason="accessNotConfigured"),
            ):
                _expect_oauth_error("youtube_api_failed", lambda: youtube.connect_account("api-error-code"))
            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call", side_effect=youtube.YouTubeError("insufficient permissions", status=403, reason="insufficientPermissions"),
            ):
                _expect_oauth_error("oauth_scope_insufficient", lambda: youtube.connect_account("scope-error-code"))
            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call",
                return_value=({"items": [{"id": "channel-storage-test", "snippet": {"title": "Storage Test"}}]}, {}),
            ), patch("clipper.youtube.encrypt_secret", side_effect=youtube.YouTubeError("DPAPI unavailable")):
                _expect_oauth_error("oauth_token_storage_failed", lambda: youtube.connect_account("storage-error-code"))
            with connect() as conn:
                assert conn.execute("SELECT 1 FROM youtube_accounts WHERE channel_id='channel-storage-test'").fetchone() is None

            with patch.dict(os.environ, {"YOUTUBE_REDIRECT_URI": "https://localhost:8443/api/youtube/oauth/callback"}), patch(
                "clipper.youtube.create_oauth_state", return_value="secure-cookie-state",
            ):
                secure_start = client.get("/api/youtube/oauth/start", follow_redirects=False)
            assert "secure" in secure_start.headers["set-cookie"].lower()

            invalid_state_callback = client.get(
                "/api/youtube/oauth/callback?" + urllib.parse.urlencode({"code": "ignored-code", "state": "wrong-state"}),
                follow_redirects=False,
            )
            assert "youtube=oauth_state_invalid" in invalid_state_callback.headers["location"]
            assert "ignored-code" not in invalid_state_callback.headers["location"]

            failed_start = client.get("/api/youtube/oauth/start", follow_redirects=False)
            failed_query = urllib.parse.parse_qs(urllib.parse.urlsplit(failed_start.headers["location"]).query)
            with patch("clipper.youtube._exchange_code", side_effect=youtube.YouTubeError(
                "token failure", code="oauth_token_exchange_failed",
            )):
                failed_callback = client.get(
                    "/api/youtube/oauth/callback?" + urllib.parse.urlencode({"code": "fake-code", "state": failed_query["state"][0]}),
                    follow_redirects=False,
                )
            assert "youtube=oauth_token_exchange_failed" in failed_callback.headers["location"]
            assert "fake-code" not in failed_callback.headers["location"]

            unexpected_start = client.get("/api/youtube/oauth/start", follow_redirects=False)
            unexpected_query = urllib.parse.parse_qs(urllib.parse.urlsplit(unexpected_start.headers["location"]).query)
            with patch("clipper.youtube.connect_account", side_effect=RuntimeError("private-secret-sentinel")):
                unexpected_callback = client.get(
                    "/api/youtube/oauth/callback?" + urllib.parse.urlencode({"code": "unexpected-code", "state": unexpected_query["state"][0]}),
                    follow_redirects=False,
                )
            assert "youtube=oauth_connection_failed" in unexpected_callback.headers["location"]
            assert "private-secret-sentinel" not in unexpected_callback.headers["location"]
            assert "unexpected-code" not in unexpected_callback.headers["location"]

            channel_start = client.get("/api/youtube/oauth/start", follow_redirects=False)
            channel_query = urllib.parse.parse_qs(urllib.parse.urlsplit(channel_start.headers["location"]).query)
            with patch("clipper.youtube.connect_account", side_effect=youtube.YouTubeError(
                "channel not found", code="youtube_channel_not_found",
            )):
                channel_callback = client.get(
                    "/api/youtube/oauth/callback?" + urllib.parse.urlencode({"code": "private-code", "state": channel_query["state"][0]}),
                    follow_redirects=False,
                )
            assert "youtube=youtube_channel_not_found" in channel_callback.headers["location"]
            assert "private-code" not in channel_callback.headers["location"]

            started = client.get("/api/youtube/oauth/start", follow_redirects=False)
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(started.headers["location"]).query)
            callback_state = query["state"][0]
            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call",
                return_value=({"items": [{"id": "channel-1", "snippet": {"title": "Private Test Channel"}}]}, {}),
            ):
                callback = client.get(
                    "/api/youtube/oauth/callback?" + urllib.parse.urlencode({"code": "fake-code", "state": callback_state}),
                    follow_redirects=False,
                )
            assert callback.status_code == 303 and "youtube=connected" in callback.headers["location"]
            assert all(secret not in callback.headers["location"] for secret in (
                "fake-code", "fake-access-token", "fake-refresh-token", callback_state,
            ))
            connected = client.get("/api/youtube/accounts").json()
            assert connected["accounts"][0]["channel_title"] == "Private Test Channel"
            assert connected["accounts"][0]["status"] == "connected"
            assert connected["accounts"][0]["analytics_ready"] is True
            assert connected["accounts"][0]["upload_ready"] is True
            assert connected["accounts"][0]["scopes_verified"] is True
            assert "token_blob" not in connected["accounts"][0]
            with connect() as conn:
                stored_token_blob = conn.execute("SELECT token_blob FROM youtube_accounts WHERE id=?", (connected["accounts"][0]["id"],)).fetchone()["token_blob"]
            assert b"fake-refresh-token" not in stored_token_blob
            assert json.loads(youtube.decrypt_secret(stored_token_blob))["refresh_token"] == "fake-refresh-token"
            account_id = connected["accounts"][0]["id"]
            channel_id = connected["accounts"][0]["channel_id"]
            with connect() as conn:
                conn.execute("UPDATE youtube_accounts SET authorization_id=NULL,is_default=0 WHERE id=?", (account_id,))
            init_db()
            with connect() as conn:
                migrated_account = conn.execute(
                    "SELECT a.authorization_id,a.is_default,g.provider,g.credentials_blob,g.granted_scopes_json "
                    "FROM youtube_accounts a JOIN oauth_authorizations g ON g.id=a.authorization_id WHERE a.id=?",
                    (account_id,),
                ).fetchone()
            assert migrated_account["authorization_id"] == f"legacy-youtube-{account_id}"
            assert migrated_account["provider"] == "youtube" and migrated_account["credentials_blob"]
            assert migrated_account["is_default"] == 1
            assert set(json.loads(migrated_account["granted_scopes_json"])) == set(youtube.SCOPES)

            analytics_start = client.get("/api/youtube/oauth/start", params={"account_id": account_id}, follow_redirects=False)
            analytics_query = urllib.parse.parse_qs(urllib.parse.urlsplit(analytics_start.headers["location"]).query)
            assert set(analytics_query["scope"][0].split()) == set(youtube.ANALYTICS_SCOPES)
            assert analytics_query["include_granted_scopes"] == ["true"]
            with connect() as conn:
                existing_credentials = conn.execute("SELECT token_blob FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()["token_blob"]
            narrowed_grant = {**token_data, "scope": " ".join(youtube.ANALYTICS_SCOPES)}
            with patch("clipper.youtube._exchange_code", return_value=narrowed_grant):
                _expect_oauth_error("oauth_scope_downgrade_blocked", lambda: youtube.connect_account("narrow-analytics-code", expected_channel_id=channel_id))
            with connect() as conn:
                assert conn.execute("SELECT token_blob FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()["token_blob"] == existing_credentials

            analytics_start = client.get("/api/youtube/oauth/start", params={"account_id": account_id}, follow_redirects=False)
            analytics_query = urllib.parse.parse_qs(urllib.parse.urlsplit(analytics_start.headers["location"]).query)
            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call",
                return_value=({"items": [{"id": channel_id, "snippet": {"title": "Private Test Channel"}}]}, {}),
            ):
                analytics_callback = client.get(
                    "/api/youtube/oauth/callback?" + urllib.parse.urlencode({"code": "analytics-code", "state": analytics_query["state"][0]}),
                    follow_redirects=False,
                )
            assert "youtube=analytics_enabled" in analytics_callback.headers["location"]

            with patch("clipper.youtube._exchange_code", return_value=token_data), patch(
                "clipper.youtube._json_call",
                return_value=({"items": [
                    {"id": "channel-a", "snippet": {"title": "A"}},
                    {"id": "channel-b", "snippet": {"title": "B"}},
                ]}, {}),
            ):
                try:
                    youtube.connect_account("multiple-channel-code")
                except youtube.YouTubeError as exc:
                    assert "multiple channels" in str(exc)
                else:
                    raise AssertionError("Multiple OAuth channels must fail closed")

            with patch("clipper.youtube._authorized_json", return_value={
                "items": [{"id": channel_id, "snippet": {"title": "Verified Channel", "thumbnails": {"default": {"url": "https://example.test/avatar.jpg"}}}}],
            }):
                verified = client.post(f"/api/youtube/accounts/{account_id}/verify")
            assert verified.status_code == 200
            assert verified.json()["channel_title"] == "Verified Channel" and verified.json()["verified_at"]

            # Review gate happens before ffprobe or queue creation.
            unapproved_id = uuid.uuid4().hex
            source_id, parent_job = uuid.uuid4().hex, uuid.uuid4().hex
            _seed_clip(source_id, unapproved_id, parent_job, CLIP_DIR / "unapproved.mp4", "needs_revision")
            body = {"account_id": account_id, "title": "Manual title", "made_for_kids": False, "contains_synthetic_media": False, "confirmed": True, "rights_confirmed": True}
            unconfirmed = client.post(f"/api/clips/{unapproved_id}/youtube-publications", json={**body, "confirmed": False})
            assert unconfirmed.status_code == 400
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
            with connect() as conn:
                conn.execute(
                    "UPDATE youtube_publications SET authorization_id=NULL,target_channel_id=NULL WHERE id=?",
                    (publication["id"],),
                )
            init_db()
            with connect() as conn:
                migrated_publication = conn.execute(
                    "SELECT authorization_id,target_channel_id FROM youtube_publications WHERE id=?",
                    (publication["id"],),
                ).fetchone()
            assert migrated_publication["authorization_id"] == migrated_account["authorization_id"]
            assert migrated_publication["target_channel_id"] == channel_id
            attribution = publication["attribution"]
            assert attribution["version"] == 1 and attribution["source_workflow"] == "unknown"
            assert attribution["subtitle_type"] == "Off" and "rendered_sha256" not in attribution
            with connect() as conn:
                saved_attribution = conn.execute(
                    "SELECT attribution_json FROM youtube_publications WHERE id=?", (publication["id"],),
                ).fetchone()["attribution_json"]
                conn.execute("UPDATE clips SET edit_json=? WHERE id=?", (json.dumps({"subtitle_enabled": True, "subtitle_caption_mode": "word_pop"}), clip_id))
                assert conn.execute(
                    "SELECT attribution_json FROM youtube_publications WHERE id=?", (publication["id"],),
                ).fetchone()["attribution_json"] == saved_attribution
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
                    if method == "GET" and url.startswith(youtube.API_URL + "/channels"):
                        return 200, {}, json.dumps({"items": [{"id": channel_id, "snippet": {"title": "Verified Channel"}}]}).encode()
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

            try:
                youtube._normalize_publish_at("2030-01-01T12:00:00", "private")
            except youtube.YouTubeError as exc:
                assert "timezone offset" in str(exc)
            else:
                raise AssertionError("Naive local schedule must be rejected")
            future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
            normalized_schedule = youtube._normalize_publish_at(future, "private")
            assert normalized_schedule.endswith("Z")
            try:
                youtube._normalize_publish_at(future, "public")
            except youtube.YouTubeError:
                pass
            else:
                raise AssertionError("Native schedule must require private visibility")

            mood_media = CLIP_DIR / "approved-mood-publish-fixture.mp4"
            mood_media.write_bytes(b"approved mood render fixture" * 500)
            mood_project, mood_render, mood_job = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
            _seed_mood_render(mood_project, mood_render, mood_job, mood_media)
            mood_metadata = {"duration": 30.0, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"}
            scheduled_body = {
                **body, "title": "Scheduled mood", "publish_at": future, "hashtags": ["localfirst", "#Video"],
                "category_id": "22", "video_language": "en-US",
            }
            with patch("clipper.youtube.probe", return_value=mood_metadata):
                mood_response = client.post(f"/api/publishing/mood_render/{mood_render}/youtube", json=scheduled_body)
            assert mood_response.status_code == 200, mood_response.text
            mood_publication = mood_response.json()
            assert mood_publication["content_type"] == "mood_render" and mood_publication["publish_at"].endswith("Z")
            assert mood_publication["hashtags"] == ["#localfirst", "#Video"]
            assert client.delete(f"/api/mood-projects/{mood_project}").status_code == 409
            with connect() as conn:
                upload_job = dict(conn.execute("SELECT * FROM youtube_upload_jobs WHERE id=?", (mood_publication["job_id"],)).fetchone())
                assert conn.execute("SELECT 1 FROM jobs WHERE id=?", (mood_publication["job_id"],)).fetchone() is None
                assert conn.execute("SELECT 1 FROM sources WHERE id=?", (mood_render,)).fetchone() is None
            upload_job["queue"] = "youtube_upload"
            with patch("clipper.youtube.run_upload") as mocked_upload:
                runner._process(upload_job, threading.Event())
            mocked_upload.assert_called_once()
            with connect() as conn:
                publication_row = dict(conn.execute("SELECT * FROM youtube_publications WHERE id=?", (mood_publication["id"],)).fetchone())
                conn.execute(
                    "UPDATE youtube_publications SET status='processing',remote_status='uploaded',video_id='scheduled-video',"
                    "video_url='https://youtu.be/scheduled-video' WHERE id=?",
                    (mood_publication["id"],),
                )
            scheduled_resource = {"items": [{
                "id": "scheduled-video", "snippet": {"channelId": channel_id},
                "status": {"uploadStatus": "processed", "privacyStatus": "private", "publishAt": mood_publication["publish_at"], "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False},
                "processingDetails": {"processingStatus": "succeeded"},
            }]}
            with patch("clipper.youtube._authorized_json", return_value=scheduled_resource):
                youtube._poll_video(youtube._load_publication(mood_publication["id"]))
            with connect() as conn:
                scheduled_state = conn.execute("SELECT status,remote_status,published_at FROM youtube_publications WHERE id=?", (mood_publication["id"],)).fetchone()
                conn.execute(
                    "UPDATE youtube_publications SET publish_at=?,remote_status='scheduled' WHERE id=?",
                    ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), mood_publication["id"]),
                )
            assert scheduled_state["status"] == "processing" and scheduled_state["remote_status"] == "scheduled" and scheduled_state["published_at"] is None
            published_resource = {"items": [{
                "id": "scheduled-video", "snippet": {"channelId": channel_id, "publishedAt": "2026-10-28T12:00:00Z"},
                "status": {"uploadStatus": "processed", "privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False},
                "processingDetails": {"processingStatus": "succeeded"},
            }]}
            with patch("clipper.youtube._authorized_json", return_value=published_resource):
                youtube._poll_video(youtube._load_publication(mood_publication["id"]))
            with connect() as conn:
                scheduled_state = conn.execute("SELECT status,remote_status FROM youtube_publications WHERE id=?", (mood_publication["id"],)).fetchone()
            assert scheduled_state["status"] == "published" and scheduled_state["remote_status"] == "published"
            authorized_body = []
            with patch("clipper.youtube._authorized_http", return_value=(200, {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=schedule"}, b"")) as authorized, patch(
                "clipper.youtube._save_session"
            ):
                youtube._new_session(publication_row, account_id)
                authorized_body.append(json.loads(authorized.call_args.args[4]))
            assert authorized_body[0]["status"]["privacyStatus"] == "private"
            assert authorized_body[0]["status"]["publishAt"].endswith("Z")
            assert authorized_body[0]["snippet"]["categoryId"] == "22"
            assert authorized_body[0]["snippet"]["defaultLanguage"] == "en-US"

            jpeg = b"\xff\xd8\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 720, 1280) + b"\x03" + b"\x01\x11\x00" * 3 + b"\xff\xd9"
            with patch("clipper.youtube.probe", return_value=mood_metadata):
                thumbnail_response = client.post(
                    f"/api/publishing/mood_render/{mood_render}/thumbnail",
                    files={"file": ("preview.jpg", jpeg, "image/jpeg")},
                )
            assert thumbnail_response.status_code == 200, thumbnail_response.text
            assert thumbnail_response.json()["remote_status"] == "local"
            with connect() as conn:
                conn.execute("UPDATE youtube_publications SET video_id='mood-video-test' WHERE id=?", (mood_publication["id"],))
            thumbnail_payload = {"items": [{"default": {"url": "https://i.ytimg.com/vi/mood-video-test/default.jpg"}}]}
            with patch("clipper.youtube._authorized_http", return_value=(200, {}, json.dumps(thumbnail_payload).encode())):
                applied_thumbnail = client.post(f"/api/youtube/publications/{mood_publication['id']}/thumbnail")
            assert applied_thumbnail.status_code == 200 and applied_thumbnail.json()["applied"] is True
            with connect() as conn:
                thumbnail_state = conn.execute("SELECT remote_status FROM publishing_thumbnails WHERE content_id=?", (mood_render,)).fetchone()
            assert thumbnail_state["remote_status"] == "applied"

            with patch("clipper.youtube.probe", return_value=mood_metadata), patch(
                "clipper.youtube._authorized_http", return_value=(403, {}, b'{"error":{"message":"forbidden","errors":[{"reason":"forbidden"}]}}'),
            ):
                failed_thumbnail = client.post(f"/api/youtube/publications/{mood_publication['id']}/thumbnail")
            assert failed_thumbnail.status_code == 403
            with connect() as conn:
                thumbnail_state = conn.execute("SELECT remote_status,remote_error FROM publishing_thumbnails WHERE content_id=?", (mood_render,)).fetchone()
            assert thumbnail_state["remote_status"] == "failed" and thumbnail_state["remote_error"]

            content_response = client.get("/api/publishing/content")
            assert content_response.status_code == 200, content_response.text
            assert isinstance(content_response.json(), list)
            assert client.get("/api/publishing/calendar").json()
            assert client.get(f"/api/publishing/events?content_type=mood_render&content_id={mood_render}").json()
            assert client.put(f"/api/publishing/mood_render/{mood_render}/metadata", json={"title": "Draft title", "tags": ["mood"]}).status_code == 200
            template = client.post("/api/publishing/metadata-templates", json={"name": "Manual test", "metadata": {"category_id": "22", "tags": ["mood"]}})
            assert template.status_code == 200
            assert client.delete(f"/api/publishing/metadata-templates/{template.json()['id']}").status_code == 200

            secondary_account_id, secondary_channel_id = uuid.uuid4().hex, "channel-secondary"
            secondary_authorization_id = uuid.uuid4().hex
            secondary_expiry = time.time() + 3600
            with connect() as conn:
                conn.execute(
                    "INSERT INTO oauth_authorizations(id,provider,credentials_blob,granted_scopes_json,expires_at,token_status,created_at,updated_at) "
                    "VALUES(?,'youtube',?,?,?,'active',?,?)",
                    (secondary_authorization_id, stored_token_blob, json.dumps(youtube.SCOPES), secondary_expiry, now(), now()),
                )
                conn.execute(
                    "INSERT INTO youtube_accounts(id,channel_id,channel_title,status,token_blob,expires_at,channel_avatar_url,verified_at,granted_scopes_json,authorization_id,is_default,created_at,updated_at) "
                    "VALUES(?,?,?,'connected',?,?,NULL,?,?,?,0,?,?)",
                    (secondary_account_id, secondary_channel_id, "Secondary Channel", stored_token_blob, secondary_expiry,
                     now(), json.dumps(youtube.SCOPES), secondary_authorization_id, now(), now()),
                )
            assert client.post(f"/api/youtube/accounts/{secondary_account_id}/default").json()["is_default"] is True
            multi_media = CLIP_DIR / "multi-account-youtube-fixture.mp4"
            multi_media.write_bytes(b"multi-account fixture" * 3000)
            multi_clip_id, multi_source_id, multi_parent_id = (uuid.uuid4().hex for _ in range(3))
            _seed_clip(multi_source_id, multi_clip_id, multi_parent_id, multi_media)
            secondary_draft = client.put(
                f"/api/publishing/clip/{multi_clip_id}/metadata?account_id={secondary_account_id}",
                json={"title": "Saved secondary title", "tags": ["secondary"]},
            )
            assert secondary_draft.status_code == 200
            assert client.get(
                f"/api/publishing/clip/{multi_clip_id}/metadata?account_id={secondary_account_id}"
            ).json()["metadata"]["title"] == "Saved secondary title"
            multi_body = {
                "account_ids": [account_id, secondary_account_id], "title": "Shared title", "made_for_kids": None,
                "contains_synthetic_media": None, "confirmed": True, "rights_confirmed": True,
                "metadata_by_account": {
                    account_id: {"title": "Primary title", "made_for_kids": False, "contains_synthetic_media": False},
                    secondary_account_id: {"title": "Secondary title", "made_for_kids": True, "contains_synthetic_media": False},
                },
            }
            with patch("clipper.youtube.probe", return_value=metadata):
                multi_result = client.post(f"/api/publishing/clip/{multi_clip_id}/youtube", json=multi_body)
            assert multi_result.status_code == 200, multi_result.text
            assert [item["status"] for item in multi_result.json()["destinations"]] == ["queued", "queued"]
            snapshots = [item["publication"] for item in multi_result.json()["destinations"]]
            assert [(item["account_id"], item["target_channel_id"], item["title"]) for item in snapshots] == [
                (account_id, channel_id, "Primary title"), (secondary_account_id, secondary_channel_id, "Secondary title"),
            ]
            assert [item["made_for_kids"] for item in snapshots] == [False, True]
            denied_multi = client.post(f"/api/publishing/clip/{multi_clip_id}/youtube", json={**multi_body, "rights_confirmed": False})
            assert denied_multi.status_code == 400
            partial_media = CLIP_DIR / "partial-destination-youtube-fixture.mp4"
            partial_media.write_bytes(b"partial destination fixture" * 1000)
            partial_clip_id, partial_source_id, partial_job_id = (uuid.uuid4().hex for _ in range(3))
            _seed_clip(partial_source_id, partial_clip_id, partial_job_id, partial_media)
            partial_body = {
                **multi_body,
                "metadata_by_account": {
                    account_id: {"title": "Valid destination", "made_for_kids": False, "contains_synthetic_media": False},
                    secondary_account_id: {"title": 123, "made_for_kids": True, "contains_synthetic_media": False},
                },
            }
            with patch("clipper.youtube.probe", return_value=metadata):
                partial_result = client.post(f"/api/publishing/clip/{partial_clip_id}/youtube", json=partial_body)
            assert partial_result.status_code == 200
            assert [item["status"] for item in partial_result.json()["destinations"]] == ["queued", "failed"]
            with patch("clipper.youtube._account_tokens", return_value={"access_token": "mock", "refresh_token": "mock-refresh"}), \
                    patch("clipper.youtube._json_call", return_value=({}, {})):
                disconnected_secondary = client.delete(f"/api/youtube/accounts/{secondary_account_id}")
            assert disconnected_secondary.status_code == 200
            with connect() as conn:
                secondary_publication = conn.execute(
                    "SELECT status FROM youtube_publications WHERE id=?", (snapshots[1]["id"],),
                ).fetchone()
                secondary_job = conn.execute(
                    "SELECT status FROM jobs WHERE id=?", (snapshots[1]["job_id"],),
                ).fetchone()
            assert secondary_publication["status"] == "cancelled" and secondary_job["status"] == "cancelled"
            assert client.get(f"/api/youtube/publications/{snapshots[1]['id']}").status_code == 200

            with connect() as conn:
                conn.execute("UPDATE youtube_accounts SET expires_at=0 WHERE id=?", (account_id,))
            with patch("clipper.youtube._json_call", side_effect=youtube.YouTubeError("expired", status=400, reason="invalid_grant")):
                try:
                    youtube._refresh(account_id)
                except youtube.YouTubeError:
                    pass
                else:
                    raise AssertionError("invalid_grant must reject expired refresh token")
            assert next(item for item in client.get("/api/youtube/accounts").json()["accounts"] if item["id"] == account_id)["status"] == "expired"
            assert client.delete(f"/api/youtube/accounts/{account_id}/record").status_code == 409
            with patch("clipper.youtube._json_call", return_value=({}, {})):
                disconnected = client.delete(f"/api/youtube/accounts/{account_id}")
            assert disconnected.status_code == 200
            row = next(item for item in client.get("/api/youtube/accounts").json()["accounts"] if item["id"] == account_id)
            assert row["status"] == "disconnected"
            assert client.delete(f"/api/youtube/accounts/{account_id}/record").status_code == 409

            deletable_id = uuid.uuid4().hex
            with connect() as conn:
                conn.execute(
                    "INSERT INTO youtube_accounts(id,channel_id,channel_title,status,created_at,updated_at) "
                    "VALUES(?,?,?,'disconnected',?,?)",
                    (deletable_id, f"channel-{deletable_id}", "Disconnected test account", now(), now()),
                )
            deleted = client.delete(f"/api/youtube/accounts/{deletable_id}/record")
            assert deleted.status_code == 200 and deleted.json() == {"id": deletable_id, "deleted": True}
            assert all(item["id"] != deletable_id for item in client.get("/api/youtube/accounts").json()["accounts"])
            media.unlink(missing_ok=True)
            multi_media.unlink(missing_ok=True)
            partial_media.unlink(missing_ok=True)
            retry_media.unlink(missing_ok=True)
            cancel_media.unlink(missing_ok=True)
            uncertain_media.unlink(missing_ok=True)
            mood_media.unlink(missing_ok=True)
    print("YouTube OAuth, approval gate, resumable upload, reconciliation, cancellation, and account lifecycle checks passed")


if __name__ == "__main__":
    run()
