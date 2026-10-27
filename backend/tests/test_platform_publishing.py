import base64
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

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-platform-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import CLIP_DIR
from clipper.db import connect, init_db
from clipper.jobs import now
from clipper.main import app
from clipper import platform_publishing, youtube


def _seed_clip():
    media = CLIP_DIR / f"platform-{uuid.uuid4().hex}.mp4"
    media.write_bytes(b"mock approved mp4")
    source_id, clip_id, job_id = (uuid.uuid4().hex for _ in range(3))
    timestamp = now()
    fingerprint = hashlib.sha256(media.read_bytes()).hexdigest()
    with connect() as conn:
        conn.execute(
            "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,sha256,created_at,transcript_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (source_id, "platform-test.mp4", f"{source_id}.mp4", 10, 40, 720, 1280, "h264", source_id, timestamp, "[]"),
        )
        conn.execute(
            "INSERT INTO jobs(id,source_id,kind,status,phase,options_json,created_at,updated_at) VALUES(?,?,?,'completed','completed','{}',?,?)",
            (job_id, source_id, "quick_clip", timestamp, timestamp),
        )
        conn.execute(
            "INSERT INTO clips(id,source_id,job_id,start,end,title,reason,rank,edit_json,status,review_status,reviewed_render_sha256,rendered_path,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,'completed','approved',?,?,?)",
            (clip_id, source_id, job_id, 0, 20, "Platform test", "fixture", 1, "{}", fingerprint, str(media), timestamp),
        )
    return clip_id, media


def run():
    chunk_size, chunk_count = platform_publishing._tiktok_chunk_plan(65 * 1024**2)
    assert chunk_size == 32 * 1024**2 and chunk_count == 3
    with patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": "", "YOUTUBE_CLIENT_SECRET": ""}), patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            state_config = {
                "TIKTOK_CLIENT_KEY": "test-key",
                "TIKTOK_CLIENT_SECRET": "test-secret",
                "TIKTOK_REDIRECT_URI": "https://localhost:8443/api/platforms/tiktok/oauth/callback",
            }
            with patch.dict(os.environ, state_config), patch("clipper.youtube.encrypt_secret", return_value=b"encrypted-verifier"), \
                    patch("clipper.platform_publishing.secrets.token_urlsafe", side_effect=["mock-state", "mock-verifier"]):
                start = platform_publishing.oauth_start("tiktok")
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(start["url"]).query)
            assert query["scope"] == ["user.info.basic,video.upload"]
            assert "video.publish" not in query["scope"][0] and start["secure_cookie"] is True
            expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(b"mock-verifier").digest()).decode().rstrip("=")
            assert query["code_challenge"] == [expected_challenge] and query["code_challenge_method"] == ["S256"]
            with patch("clipper.youtube.decrypt_secret", return_value="mock-verifier"):
                assert platform_publishing.consume_oauth_state("tiktok", start["state"], start["state"]) == "mock-verifier"
                try:
                    platform_publishing.consume_oauth_state("tiktok", start["state"], start["state"])
                except platform_publishing.PlatformError as exc:
                    assert exc.code == "oauth_state_expired"
                else:
                    raise AssertionError("OAuth state must be one-use")

            success_tokens = {"data": {"access_token": "mock-access", "refresh_token": "mock-refresh", "open_id": "creator-1",
                                        "expires_in": 3600, "scope": "user.info.basic,video.upload"}}
            with patch.dict(os.environ, state_config), patch("clipper.youtube.encrypt_secret", return_value=b"encrypted"), \
                    patch("clipper.youtube.decrypt_secret", return_value="mock-verifier"), \
                    patch("clipper.platform_publishing._api_json", side_effect=[
                        success_tokens, {"data": {"user": {"open_id": "creator-1", "display_name": "Mock Creator"}}},
                    ]) as api_call:
                oauth = platform_publishing.oauth_start("tiktok")
                connected = platform_publishing.complete_oauth("tiktok", "mock-code", oauth["state"], oauth["state"])
                assert connected["accounts_added"] == 1 and api_call.call_count == 2
            with connect() as conn:
                legacy_account_id = conn.execute(
                    "SELECT id FROM platform_accounts WHERE platform='tiktok' AND platform_account_id='creator-1'",
                ).fetchone()["id"]
                conn.execute("UPDATE platform_accounts SET authorization_id=NULL,is_default=0 WHERE id=?", (legacy_account_id,))
            init_db()
            with connect() as conn:
                migrated_social = conn.execute(
                    "SELECT a.authorization_id,a.is_default,g.provider,g.credentials_blob,g.granted_scopes_json "
                    "FROM platform_accounts a JOIN oauth_authorizations g ON g.id=a.authorization_id WHERE a.id=?",
                    (legacy_account_id,),
                ).fetchone()
            assert migrated_social["authorization_id"] == f"legacy-tiktok-{legacy_account_id}"
            assert migrated_social["provider"] == "tiktok" and migrated_social["credentials_blob"]
            assert migrated_social["is_default"] == 1
            assert set(json.loads(migrated_social["granted_scopes_json"])) == set(platform_publishing.TIKTOK_SCOPES)
            with connect() as conn:
                connected_row = conn.execute("SELECT * FROM platform_accounts WHERE platform='tiktok' AND platform_account_id='creator-1'").fetchone()
            assert connected_row["display_name"] == "Mock Creator" and connected_row["token_blob"] != b"mock-access"

            with patch.dict(os.environ, state_config), patch("clipper.youtube.encrypt_secret", return_value=b"encrypted"), \
                    patch("clipper.youtube.decrypt_secret", return_value="mock-verifier"), \
                    patch("clipper.platform_publishing._api_json", side_effect=platform_publishing.PlatformError("rejected", 502, "provider_rejected")):
                failed_oauth = platform_publishing.oauth_start("tiktok")
                try:
                    platform_publishing.complete_oauth("tiktok", "mock-code", failed_oauth["state"], failed_oauth["state"])
                except platform_publishing.PlatformError as exc:
                    assert exc.code == "provider_rejected"
                else:
                    raise AssertionError("Provider OAuth failure must not connect an account")

            clip_id, media = _seed_clip()
            media_probe = {"duration": 20, "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac",
                           "frame_rate": 30.0, "audio_sample_rate": 44100, "audio_channels": 2}
            with patch("clipper.platform_publishing.probe", return_value=media_probe):
                saved_tiktok = client.put(f"/api/publishing/clip/{clip_id}/platform-metadata/tiktok", json={
                    "caption": "TikTok caption", "hashtags": ["localfirst", "shorts"], "privacy_level": "SELF_ONLY",
                    "disable_comment": False, "disable_duet": False, "disable_stitch": False,
                })
                saved_instagram = client.put(f"/api/publishing/clip/{clip_id}/platform-metadata/instagram", json={
                    "caption": "Instagram caption", "hashtags": ["reels"], "share_to_feed": True, "ai_generated": False,
                })
                assert saved_tiktok.status_code == 200 and saved_instagram.status_code == 200
                assert saved_tiktok.json()["metadata"]["caption"] != saved_instagram.json()["metadata"]["caption"]
                invalid = client.put(f"/api/publishing/clip/{clip_id}/platform-metadata/tiktok", json={"hashtags": ["two words"]})
                assert invalid.status_code == 422

                body = {"confirmed": True, "rights_confirmed": True}
                first = client.post(f"/api/publishing/clip/{clip_id}/platforms/tiktok/manual-export", json=body)
                repeat = client.post(f"/api/publishing/clip/{clip_id}/platforms/tiktok/manual-export", json=body)
                second = client.post(f"/api/publishing/clip/{clip_id}/platforms/instagram/manual-export", json=body)
                assert first.status_code == repeat.status_code == second.status_code == 200
                assert first.json()["id"] == repeat.json()["id"]
                assert first.json()["id"] != second.json()["id"]
                assert first.json()["status"] == "prepared_manual"
                assert "No API upload" in first.json()["message"]
                download = client.get(first.json()["download_url"])
                assert download.status_code == 200 and download.content == b"mock approved mp4"

                tiktok_account_id = connected_row["id"]
                queued = client.post(f"/api/publishing/clip/{clip_id}/platforms/tiktok/upload", json={
                    "account_id": tiktok_account_id, **body,
                })
                repeated = client.post(f"/api/publishing/clip/{clip_id}/platforms/tiktok/upload", json={
                    "account_id": tiktok_account_id, **body,
                })
                assert queued.status_code == 200 and repeated.status_code == 200
                assert queued.json()["id"] == repeated.json()["id"] and repeated.json()["duplicate"] is True
                tiktok_job_id = queued.json()["id"]
                with connect() as conn:
                    conn.execute("UPDATE platform_upload_jobs SET status='uploading',phase='preparing' WHERE id=?", (tiktok_job_id,))

                def init_tiktok_upload(job, size, cancel):
                    platform_publishing.update_platform_upload(
                        job["id"], remote_id="mock-publish-id", session_blob=b"encrypted-upload",
                        provider_data={"chunk_size": size, "chunk_count": 1, "upload_url_expires_at": time.time() + 3600},
                        upload_started=True,
                    )
                    return "mock-publish-id", "https://open-upload.tiktokapis.com/mock-upload"

                with patch("clipper.platform_publishing.probe", return_value=media_probe), \
                        patch("clipper.platform_publishing._platform_access_token", return_value="mock-token"), \
                        patch("clipper.platform_publishing._verify_destination_identity"), \
                        patch("clipper.platform_publishing._tiktok_init", side_effect=init_tiktok_upload), \
                        patch("clipper.platform_publishing._tiktok_status", side_effect=[
                            {"status": "PROCESSING_UPLOAD", "uploaded_bytes": 0},
                            {"status": "SEND_TO_USER_INBOX", "uploaded_bytes": media.stat().st_size},
                        ]), \
                        patch("clipper.platform_publishing._stream_file", return_value=(201, {}, b"")) as stream_file:
                    platform_publishing.run_platform_upload(tiktok_job_id, threading.Event(), lambda *_: None)
                tiktok_job = platform_publishing._upload_job(tiktok_job_id)
                assert tiktok_job["status"] == "awaiting_manual_action"
                assert tiktok_job["uploaded_bytes"] == media.stat().st_size and tiktok_job["published_at"] is None
                assert "session_blob" not in client.get("/api/platform-publications").json()[0]
                assert stream_file.call_args.args[0] == "https://open-upload.tiktokapis.com/mock-upload"
                with patch("clipper.platform_publishing._tiktok_status", return_value={"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["post-1"]}):
                    platform_publishing.poll_platform_upload(tiktok_job_id)
                assert platform_publishing._upload_job(tiktok_job_id)["status"] == "published"

                second_tiktok_id = uuid.uuid4().hex
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO platform_accounts(id,platform,platform_account_id,display_name,username,status,token_blob,scopes_json,details_json,authorization_id,is_default,created_at,updated_at) "
                        "VALUES(?,'tiktok','creator-2','Second Creator','second.creator','connected',?,?,?,?,0,?,?)",
                        (second_tiktok_id, connected_row["token_blob"], connected_row["scopes_json"], "{}",
                         connected_row["authorization_id"], now(), now()),
                    )
                assert platform_publishing.set_default_account("tiktok", second_tiktok_id)["is_default"] is True
                account_draft = client.put(
                    f"/api/publishing/clip/{clip_id}/platform-metadata/tiktok?account_id={second_tiktok_id}",
                    json={"caption": "Second account draft", "hashtags": ["second"]},
                )
                assert account_draft.status_code == 200
                assert client.get(
                    f"/api/publishing/clip/{clip_id}/platform-metadata/tiktok?account_id={second_tiktok_id}"
                ).json()["metadata"]["caption"] == "Second account draft"
                multi_platform_clip, _ = _seed_clip()
                with patch("clipper.platform_publishing.probe", return_value=media_probe):
                    multi_platform = platform_publishing.enqueue_platform_uploads(
                        "clip", multi_platform_clip, "tiktok", {
                            "account_ids": [tiktok_account_id, second_tiktok_id], "confirmed": True, "rights_confirmed": True,
                            "metadata_by_account": {
                                tiktok_account_id: {"caption": "First destination"},
                                second_tiktok_id: {"caption": "Second destination"},
                            },
                        },
                    )
                assert [item["status"] for item in multi_platform["destinations"]] == ["queued", "queued"]
                destination_jobs = [platform_publishing._upload_job(item["job"]["id"]) for item in multi_platform["destinations"]]
                assert [item["metadata"]["caption"] for item in destination_jobs] == ["First destination", "Second destination"]
                disconnected = platform_publishing.disconnect_account("tiktok", second_tiktok_id)
                assert disconnected["shared_authorization_preserved"] is True
                assert platform_publishing._upload_job(destination_jobs[1]["id"])["status"] == "cancelled"
                assert platform_publishing._upload_job(destination_jobs[0]["id"])["status"] == "queued"
                assert platform_publishing._safe_account_row(tiktok_account_id, "tiktok")["is_default"] is True

                with patch("clipper.platform_publishing._authorized_json", return_value={"data": {"user": {"open_id": "creator-1"}}},
                ) as identity_check:
                    platform_publishing._verify_destination_identity(tiktok_account_id, "tiktok")
                assert identity_check.call_args.args == (
                    tiktok_account_id, "tiktok", "GET", "https://open.tiktokapis.com/v2/user/info/",
                )
                assert identity_check.call_args.kwargs["params"] == {"fields": "open_id"}
                with patch("clipper.platform_publishing._authorized_json", return_value={"data": {"user": {"open_id": "wrong-creator"}}},
                ):
                    try:
                        platform_publishing._verify_destination_identity(tiktok_account_id, "tiktok")
                    except platform_publishing.PlatformError as exc:
                        assert exc.code == "account_identity_mismatch"
                    else:
                        raise AssertionError("Provider identity mismatch must block selected destination")
                with connect() as conn:
                    conn.execute("UPDATE platform_accounts SET status='connected',error_message=NULL WHERE id=?", (tiktok_account_id,))
                platform_publishing.set_default_account("tiktok", tiktok_account_id)

                instagram_scopes = platform_publishing.INSTAGRAM_SCOPES
                instagram_account_id = uuid.uuid4().hex
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO platform_accounts(id,platform,platform_account_id,display_name,username,status,token_blob,scopes_json,details_json,created_at,updated_at) "
                        "VALUES(?,'instagram','ig-business-1','Mock Reels','mock.reels','connected',?,?,?,?,?,?)",
                        (instagram_account_id, b"encrypted-token", None, json.dumps(instagram_scopes),
                         json.dumps({"page_id": "page-1", "login_type": "facebook_login_for_business"}), now(), now()),
                    )
                instagram = client.post(f"/api/publishing/clip/{clip_id}/platforms/instagram/upload", json={
                    "account_id": instagram_account_id, **body,
                })
                assert instagram.status_code == 200
                instagram_job_id = instagram.json()["id"]
                with connect() as conn:
                    conn.execute("UPDATE platform_upload_jobs SET status='uploading',phase='preparing' WHERE id=?", (instagram_job_id,))
                with patch("clipper.platform_publishing.probe", return_value=media_probe), \
                        patch("clipper.platform_publishing._platform_access_token", return_value="mock-token"), \
                        patch("clipper.platform_publishing._verify_destination_identity"), \
                        patch("clipper.platform_publishing._authorized_json", side_effect=[
                            {"id": "mock-container"}, {"status_code": "FINISHED"}, {"id": "mock-media-id"},
                        ]) as instagram_request, \
                        patch("clipper.platform_publishing._stream_file", return_value=(200, {}, b'{"success":true}')) as instagram_stream:
                    platform_publishing.run_platform_upload(instagram_job_id, threading.Event(), lambda *_: None)
                instagram_job = platform_publishing._upload_job(instagram_job_id)
                assert instagram_job["status"] == "published" and instagram_job["published_at"]
                assert instagram_stream.call_args.args[0] == f"https://rupload.facebook.com/ig-api-upload/{platform_publishing.META_VERSION}/mock-container"
                create_url = instagram_request.call_args_list[0].args[3]
                create_form = instagram_request.call_args_list[0].kwargs["form"]
                assert "upload_type=resumable" in create_url and "upload_type" not in create_form
                assert instagram_request.call_args_list[1].kwargs["params"] == {"fields": "id,status_code"}
                assert create_form["is_ai_generated"] == "false"

                publish_recovery_clip, _ = _seed_clip()
                with patch("clipper.platform_publishing.probe", return_value=media_probe):
                    publish_recovery = platform_publishing.enqueue_platform_upload("clip", publish_recovery_clip, "instagram", {
                        "account_id": instagram_account_id, **body,
                    })
                with connect() as conn:
                    conn.execute(
                        "UPDATE platform_upload_jobs SET status='needs_reconciliation',phase='publish_reconciliation',"
                        "remote_id='ambiguous-container',upload_started=1 WHERE id=?", (publish_recovery["id"],),
                    )
                with patch("clipper.platform_publishing._instagram_status", return_value="IN_PROGRESS"):
                    reconciled = platform_publishing.reconcile_platform_upload(publish_recovery["id"])
                assert reconciled["status"] == "processing" and reconciled["phase"] == "publish_reconciliation"
                with patch("clipper.platform_publishing._instagram_status", return_value="FINISHED"):
                    reconciled = platform_publishing.poll_platform_upload(publish_recovery["id"])
                assert reconciled["status"] == "needs_reconciliation" and reconciled["phase"] == "publish_reconciled"
                retried = platform_publishing.retry_platform_upload(publish_recovery["id"], body)
                assert retried["status"] == "queued" and retried["phase"] == "publishing"
                with connect() as conn:
                    conn.execute("UPDATE platform_upload_jobs SET status='uploading' WHERE id=?", (publish_recovery["id"],))
                with patch("clipper.platform_publishing.probe", return_value=media_probe), \
                        patch("clipper.platform_publishing._platform_access_token", return_value="mock-token"), \
                        patch("clipper.platform_publishing._verify_destination_identity"), \
                        patch("clipper.platform_publishing._instagram_status", return_value="FINISHED"), \
                        patch("clipper.platform_publishing._authorized_json", return_value={"id": "confirmed-retry-media"}) as retry_publish:
                    platform_publishing.run_platform_upload(publish_recovery["id"], threading.Event(), lambda *_: None)
                assert retry_publish.call_count == 1 and platform_publishing._upload_job(publish_recovery["id"])["status"] == "published"

                incomplete_clip, _ = _seed_clip()
                with patch("clipper.platform_publishing.probe", return_value=media_probe):
                    incomplete = platform_publishing.enqueue_platform_upload("clip", incomplete_clip, "instagram", {
                        "account_id": instagram_account_id, **body,
                    })
                with connect() as conn:
                    conn.execute(
                        "UPDATE platform_upload_jobs SET status='needs_reconciliation',phase='processing_timeout',"
                        "remote_id='incomplete-container',upload_started=1,provider_data_json=? WHERE id=?",
                        (json.dumps({"last_status": "IN_PROGRESS", "login_type": "facebook_login_for_business"}), incomplete["id"]),
                    )
                try:
                    platform_publishing.retry_platform_upload(incomplete["id"], body)
                except platform_publishing.PlatformError as exc:
                    assert exc.code == "duplicate_risk_confirmation_required"
                else:
                    raise AssertionError("Incomplete Instagram container abandonment must confirm risk")
                abandoned = platform_publishing.retry_platform_upload(incomplete["id"], {
                    **body, "duplicate_risk_confirmed": True,
                })
                assert abandoned["status"] == "queued" and abandoned["remote_id"] is None

                recovery_clip_id, recovery_media = _seed_clip()
                with patch("clipper.platform_publishing.probe", return_value=media_probe):
                    recovery = platform_publishing.enqueue_platform_upload("clip", recovery_clip_id, "tiktok", {
                        "account_id": tiktok_account_id, **body,
                    })
                with connect() as conn:
                    conn.execute("UPDATE platform_upload_jobs SET status='uploading',phase='uploading_file',upload_started=1 WHERE id=?", (recovery["id"],))
                init_db()
                recovered = platform_publishing._upload_job(recovery["id"])
                assert recovered["status"] == "needs_reconciliation" and recovered["phase"] == "interrupted"
                try:
                    platform_publishing.retry_platform_upload(recovery["id"], body)
                except platform_publishing.PlatformError as exc:
                    assert exc.code == "duplicate_risk_confirmation_required"
                else:
                    raise AssertionError("Ambiguous transfer retry must confirm duplicate risk")
                with patch("clipper.platform_publishing._tiktok_status"):
                    try:
                        platform_publishing.reconcile_platform_upload(recovery["id"])
                    except platform_publishing.PlatformError as exc:
                        assert exc.code == "remote_id_missing"
                    else:
                        raise AssertionError("Missing provider operation ID must not be auto-retried")
                assert recovery_media.exists()

                media.write_bytes(b"changed after approval")
                stale = client.get(first.json()["download_url"])
                assert stale.status_code == 409
                rows = client.get("/api/platform-publications").json()
                stale_row = next(row for row in rows if row["id"] == first.json()["id"])
                assert stale_row["status"] == "needs_reconciliation"
                assert next(row for row in rows if row["id"] == second.json()["id"])["status"] == "prepared_manual"
            media.unlink(missing_ok=True)

            with patch("clipper.platform_publishing.youtube.configured", return_value=False):
                status = client.get("/api/publishing/platforms").json()
            tiktok = next(item for item in status["platforms"] if item["id"] == "tiktok")
            assert tiktok["readiness"] == "conditional" and tiktok["upload_methods"] == ["tiktok_inbox", "manual_export"]
            assert tiktok["direct_post_eligible"] is False
            assert "video.publish" not in tiktok["scopes"]
            assert not any(row.get("session_blob") for row in client.get("/api/platform-publications").json())
    print("Platform OAuth, metadata, manual export, mocked transfers, reconciliation, and status checks passed")


if __name__ == "__main__":
    run()
