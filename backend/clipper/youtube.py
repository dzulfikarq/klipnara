import ctypes
import email.utils
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import CLIP_DIR, LEGACY_CLIP_DIR
from .db import connect
from .jobs import now
from .media import MediaError, probe


SCOPE = "https://www.googleapis.com/auth/youtube.upload"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_URL = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK_BYTES = 8 * 1024 * 1024
SHORT_MAX_SECONDS = 180


class YouTubeError(RuntimeError):
    def __init__(self, message, *, status=None, reason=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.retryable = retryable


class PublishCancelled(MediaError):
    pass


def configured():
    return bool(os.environ.get("YOUTUBE_CLIENT_ID") and os.environ.get("YOUTUBE_CLIENT_SECRET"))


def redirect_uri():
    return os.environ.get(
        "YOUTUBE_REDIRECT_URI",
        "http://localhost:8000/api/youtube/oauth/callback",
    )


def oauth_start_url():
    try:
        parts = urllib.parse.urlsplit(redirect_uri())
        port = parts.port
    except ValueError:
        raise YouTubeError("YOUTUBE_REDIRECT_URI is malformed.") from None
    if (
        parts.scheme not in {"http", "https"}
        or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parts.username
        or parts.password
        or not port
        or parts.path != "/api/youtube/oauth/callback"
        or parts.query
        or parts.fragment
    ):
        raise YouTubeError("YOUTUBE_REDIRECT_URI must use a local host, explicit port, and exact callback path.")
    return f"{parts.scheme}://{parts.netloc}/api/youtube/oauth/start"


def frontend_accounts_url(result=None):
    target = os.environ.get("YOUTUBE_FRONTEND_URL", "http://localhost:3000/accounts")
    try:
        parts = urllib.parse.urlsplit(target)
    except ValueError:
        parts = urllib.parse.urlsplit("http://localhost:3000/accounts")
    if parts.scheme not in {"http", "https"} or parts.hostname not in {"localhost", "127.0.0.1"} or parts.username or parts.password:
        target = "http://localhost:3000/accounts"
    if result:
        separator = "&" if "?" in target else "?"
        target += separator + urllib.parse.urlencode({"youtube": result})
    return target


def _credentials():
    client_id, client_secret = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise YouTubeError("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in backend environment first.")
    return client_id, client_secret


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data, decrypt=False):
    if os.name != "nt":
        raise YouTubeError("Encrypted YouTube credential storage requires Windows DPAPI.")
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _DataBlob()
    description = None
    crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    if decrypt:
        description = ctypes.c_wchar_p()
        call = crypt32.CryptUnprotectData
        call.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob)]
        args = (ctypes.byref(source), ctypes.byref(description), None, None, None, 1, ctypes.byref(output))
    else:
        call = crypt32.CryptProtectData
        call.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob)]
        args = (ctypes.byref(source), "Klipnara YouTube OAuth", None, None, None, 1, ctypes.byref(output))
    call.restype = ctypes.c_int
    if not call(*args):
        raise YouTubeError(f"Windows could not {'decrypt' if decrypt else 'encrypt'} YouTube credentials (error {ctypes.get_last_error()}).")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(output.pbData)
        if description and description.value:
            kernel32.LocalFree(description)


def encrypt_secret(value):
    return _protect(value.encode("utf-8"))


def decrypt_secret(value):
    return _protect(bytes(value), decrypt=True).decode("utf-8")


def create_oauth_state():
    state = secrets.token_urlsafe(32)
    timestamp = now()
    with connect() as conn:
        conn.execute("DELETE FROM youtube_oauth_states WHERE expires_at<?", (time.time(),))
        conn.execute(
            "INSERT INTO youtube_oauth_states(state_hash,created_at,expires_at) VALUES(?,?,?)",
            (hashlib.sha256(state.encode()).hexdigest(), timestamp, time.time() + 600),
        )
    return state


def consume_oauth_state(state, browser_state):
    if not state or not browser_state or not secrets.compare_digest(state, browser_state):
        return False
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT expires_at FROM youtube_oauth_states WHERE state_hash=?", (state_hash,)).fetchone()
        conn.execute("DELETE FROM youtube_oauth_states WHERE state_hash=?", (state_hash,))
    return bool(row and row["expires_at"] >= time.time())


def authorization_url(state):
    client_id, _ = _credentials()
    oauth_start_url()
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })


def _http(method, url, headers=None, body=None, timeout=30):
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, TimeoutError, OSError):
        raise YouTubeError("YouTube connection timed out or was interrupted.", retryable=True) from None
    with response:
        return response.status, dict(response.headers.items()), response.read()


def _response_error(status, body):
    try:
        payload = json.loads(body or b"{}")
        error = payload.get("error", {})
        if isinstance(error, str):
            reason, message = error, payload.get("error_description", error)
        else:
            details = error.get("errors", [])
            reason = details[0].get("reason") if details else error.get("status")
            message = error.get("message") or str(reason or "YouTube API error")
    except (ValueError, AttributeError, TypeError):
        reason, message = None, "YouTube API returned an unreadable error."
    retryable = status in {408, 429, 500, 502, 503, 504} or reason in {"rateLimitExceeded", "userRateLimitExceeded"}
    return YouTubeError(str(message)[:500], status=status, reason=reason, retryable=retryable)


def _retry_after(headers, fallback):
    value = next((value for key, value in (headers or {}).items() if key.lower() == "retry-after"), None)
    try:
        return min(60.0, max(0.0, float(value))) if value is not None else fallback
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return min(60.0, max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return fallback


def _json_call(method, url, *, token=None, data=None, form=None, headers=None, timeout=30):
    request_headers = dict(headers or {})
    body = None
    if form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(form).encode()
    elif data is not None:
        request_headers["Content-Type"] = "application/json; charset=UTF-8"
        body = json.dumps(data).encode()
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    status, response_headers, raw = _http(method, url, request_headers, body, timeout)
    if status < 200 or status >= 300:
        raise _response_error(status, raw)
    if not raw:
        return {}, response_headers
    try:
        return json.loads(raw), response_headers
    except ValueError:
        raise YouTubeError("YouTube returned an invalid JSON response.") from None


def _api_url(path, params=None):
    return API_URL + path + ("?" + urllib.parse.urlencode(params or {}) if params else "")


def _exchange_code(code):
    client_id, client_secret = _credentials()
    payload, _ = _json_call("POST", TOKEN_URL, form={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
    })
    return payload


def _refresh(account_id, *, force=False):
    with connect() as conn:
        row = conn.execute("SELECT * FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
    if not row or row["status"] == "disconnected" or not row["token_blob"]:
        raise YouTubeError("YouTube account is disconnected. Connect it again.")
    tokens = json.loads(decrypt_secret(row["token_blob"]))
    if not force and row["expires_at"] and row["expires_at"] > time.time() + 60:
        return tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        _set_account_status(account_id, "expired", "Google did not provide a refresh token; reconnect the account.")
        raise YouTubeError("YouTube authorization expired. Reconnect the account.", status=401, reason="invalid_grant")
    client_id, client_secret = _credentials()
    try:
        fresh, _ = _json_call("POST", TOKEN_URL, form={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
    except YouTubeError as exc:
        if exc.reason == "invalid_grant":
            _set_account_status(account_id, "expired", "Refresh token expired or revoked. Reconnect the account.")
        elif exc.reason in {"invalid_client", "unauthorized_client"}:
            _set_account_status(account_id, "error", "OAuth client configuration rejected by Google.")
        raise
    if not fresh.get("access_token"):
        raise YouTubeError("Google refresh response omitted access token.")
    tokens.update(fresh)
    tokens["refresh_token"] = fresh.get("refresh_token") or refresh_token
    expires = time.time() + int(fresh.get("expires_in", 3600))
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_accounts SET token_blob=?,expires_at=?,status='connected',error_message=NULL,updated_at=? "
            "WHERE id=? AND status!='disconnected'",
            (encrypt_secret(json.dumps(tokens)), expires, now(), account_id),
        )
    return tokens["access_token"]


def _set_account_status(account_id, status, message=None):
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_accounts SET status=?,error_message=?,updated_at=? WHERE id=? AND status!='disconnected'",
            (status, message, now(), account_id),
        )


def connect_account(code):
    token_data = _exchange_code(code)
    granted = token_data.get("scope", "")
    if granted and SCOPE not in granted.split():
        raise YouTubeError("Google did not grant the required youtube.upload scope.")
    access_token = token_data.get("access_token")
    if not access_token:
        raise YouTubeError("Google OAuth response omitted access token.")
    channels, _ = _json_call(
        "GET", _api_url("/channels", {"part": "snippet", "mine": "true", "maxResults": 50}), token=access_token,
    )
    items = channels.get("items") or []
    if not items:
        raise YouTubeError("Google account has no YouTube channel available to this OAuth grant.")
    channel = items[0]
    channel_id = channel.get("id")
    channel_title = channel.get("snippet", {}).get("title")
    if not channel_id or not channel_title:
        raise YouTubeError("YouTube did not return channel identity.")
    refresh_token = token_data.get("refresh_token")
    with connect() as conn:
        previous = conn.execute("SELECT id,token_blob FROM youtube_accounts WHERE channel_id=?", (channel_id,)).fetchone()
    if not refresh_token and previous and previous["token_blob"]:
        old_tokens = json.loads(decrypt_secret(previous["token_blob"]))
        refresh_token = old_tokens.get("refresh_token")
    if not refresh_token:
        raise YouTubeError("Google omitted refresh token. Revoke Klipnara access in Google Account settings, then connect again.")
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_data.get("token_type", "Bearer"),
    }
    account_id = previous["id"] if previous else uuid.uuid4().hex
    timestamp = now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO youtube_accounts(id,channel_id,channel_title,status,token_blob,expires_at,error_message,created_at,updated_at) "
            "VALUES(?,?,?,'connected',?,?,NULL,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET channel_title=excluded.channel_title,status='connected',"
            "token_blob=excluded.token_blob,expires_at=excluded.expires_at,error_message=NULL,updated_at=excluded.updated_at",
            (account_id, channel_id, channel_title, encrypt_secret(json.dumps(tokens)), time.time() + int(token_data.get("expires_in", 3600)), timestamp, timestamp),
        )
    return {"id": account_id, "channel_id": channel_id, "channel_title": channel_title, "status": "connected"}


def list_accounts():
    with connect() as conn:
        rows = conn.execute(
            "SELECT id,channel_id,channel_title,status,expires_at,error_message,created_at,updated_at "
            "FROM youtube_accounts ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def disconnect_account(account_id):
    with connect() as conn:
        row = conn.execute("SELECT token_blob FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        raise YouTubeError("Connected YouTube account not found.", status=404)
    revoked = False
    if row["token_blob"]:
        try:
            tokens = json.loads(decrypt_secret(row["token_blob"]))
            _json_call("POST", REVOKE_URL, form={"token": tokens.get("refresh_token") or tokens.get("access_token")})
            revoked = True
        except YouTubeError:
            pass
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_accounts SET status='disconnected',token_blob=NULL,expires_at=NULL,error_message=NULL,updated_at=? WHERE id=?",
            (now(), account_id),
        )
    return {"id": account_id, "status": "disconnected", "remote_revoked": revoked}


def _authorized_json(account_id, method, url, *, data=None, timeout=30):
    token = _refresh(account_id)
    try:
        return _json_call(method, url, token=token, data=data, timeout=timeout)[0]
    except YouTubeError as exc:
        if exc.status != 401:
            raise
    token = _refresh(account_id, force=True)
    try:
        return _json_call(method, url, token=token, data=data, timeout=timeout)[0]
    except YouTubeError as exc:
        if exc.status == 401:
            _set_account_status(account_id, "error", "Google rejected refreshed YouTube authorization.")
        raise


def validate_short(clip):
    if clip["review_status"] != "approved":
        raise YouTubeError("Clip must be Approved before publishing.", status=409)
    if clip["status"] != "completed" or not clip["rendered_path"]:
        raise YouTubeError("Render final must be complete before publishing.", status=409)
    path = Path(clip["rendered_path"]).resolve()
    if path.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or not path.is_file():
        raise YouTubeError("Final MP4 is missing or outside Klipnara clip storage.", status=409)
    try:
        metadata = probe(path)
    except Exception as exc:
        raise YouTubeError(f"Final MP4 failed validation: {exc}", status=409) from None
    if path.suffix.lower() != ".mp4" or path.stat().st_size <= 0:
        raise YouTubeError("Final output must be a non-empty MP4.", status=409)
    if metadata["video_codec"] != "h264" or metadata["audio_codec"] != "aac":
        raise YouTubeError("Final MP4 must contain H.264 video and AAC audio.", status=409)
    if metadata["height"] < metadata["width"]:
        raise YouTubeError("YouTube Shorts require square or portrait video.", status=409)
    if metadata["duration"] > SHORT_MAX_SECONDS:
        raise YouTubeError("YouTube Shorts must be 180 seconds or shorter.", status=409)
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(chunk)
    digest = digest.hexdigest()
    if not clip.get("reviewed_render_sha256") or clip["reviewed_render_sha256"] != digest:
        raise YouTubeError("Approved render changed or lacks review fingerprint. Review the current final MP4 again.", status=409)
    return path, metadata, digest


def _validate_metadata(payload):
    title = payload.title.strip()
    description = payload.description.strip()
    tags = []
    seen = set()
    for item in payload.tags:
        tag = item.strip()
        key = tag.casefold()
        if tag and key not in seen:
            tags.append(tag)
            seen.add(key)
    if not title:
        raise YouTubeError("Video title is required.", status=422)
    if sum(len(tag) for tag in tags) > 500:
        raise YouTubeError("YouTube tags have a 500-character combined limit.", status=422)
    return title, description, tags


def _insert_upload_job(conn, job_id, publication_id, source_id, clip_id, timestamp):
    conn.execute(
        "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
        "VALUES(?,?,?,'youtube_upload','queued','queued',NULL,'Menunggu antrean YouTube',?,?,?)",
        (job_id, source_id, clip_id, json.dumps({"publication_id": publication_id}), timestamp, timestamp),
    )


def enqueue_publication(clip_id, payload):
    title, description, tags = _validate_metadata(payload)
    publication_id, job_id, timestamp = uuid.uuid4().hex, uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        clip = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if clip is None:
            raise YouTubeError("Clip not found.", status=404)
        account = conn.execute("SELECT * FROM youtube_accounts WHERE id=?", (payload.account_id,)).fetchone()
        if not account or account["status"] != "connected" or not account["token_blob"]:
            raise YouTubeError("Connect a YouTube account before publishing.", status=409)
        if conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')",
            (clip_id,),
        ).fetchone():
            raise YouTubeError("Wait for the active render before publishing.", status=409)
        path, metadata, digest = validate_short(dict(clip))
        existing = conn.execute(
            "SELECT status FROM youtube_publications WHERE account_id=? AND rendered_sha256=? "
            "AND status IN ('pending','uploading','processing','published') ORDER BY created_at DESC LIMIT 1",
            (payload.account_id, digest),
        ).fetchone()
        if existing:
            raise YouTubeError(f"This clip already has a {existing['status']} YouTube publication for this account.", status=409)
        failed = conn.execute(
            "SELECT id FROM youtube_publications WHERE account_id=? AND rendered_sha256=? AND status='failed' "
            "ORDER BY created_at DESC LIMIT 1",
            (payload.account_id, digest),
        ).fetchone()
        if failed:
            raise YouTubeError("Retry or reconcile the previous failed publication before creating another.", status=409)
        conn.execute(
            "INSERT INTO youtube_publications(id,account_id,clip_id,clip_title,status,title,description,tags_json,"
            "privacy_status,made_for_kids,contains_synthetic_media,rendered_path,rendered_sha256,file_size,duration,width,height,"
            "job_id,created_at,updated_at) VALUES(?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                publication_id, payload.account_id, clip_id, clip["title"], title, description,
                json.dumps(tags, ensure_ascii=False), payload.privacy_status, int(payload.made_for_kids),
                int(payload.contains_synthetic_media), str(path), digest, path.stat().st_size,
                metadata["duration"], metadata["width"], metadata["height"], job_id, timestamp, timestamp,
            ),
        )
        _insert_upload_job(conn, job_id, publication_id, clip["source_id"], clip_id, timestamp)
    return get_publication(publication_id)


def _public_publication(row):
    item = dict(row)
    item.pop("rendered_path", None)
    item.pop("rendered_sha256", None)
    item.pop("upload_session_blob", None)
    item["tags"] = json.loads(item.pop("tags_json"))
    item["made_for_kids"] = bool(item["made_for_kids"])
    item["contains_synthetic_media"] = bool(item["contains_synthetic_media"])
    item["upload_started"] = bool(item["upload_started"])
    item["reconciliation_required"] = bool(item["reconciliation_required"])
    item["progress"] = min(1.0, item["uploaded_bytes"] / item["file_size"]) if item["file_size"] else 0
    return item


def get_publication(publication_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT p.*,a.channel_title,j.status AS job_status,j.progress AS job_progress "
            "FROM youtube_publications p JOIN youtube_accounts a ON a.id=p.account_id "
            "LEFT JOIN jobs j ON j.id=p.job_id WHERE p.id=?",
            (publication_id,),
        ).fetchone()
    if row is None:
        raise YouTubeError("YouTube publication not found.", status=404)
    return _public_publication(row)


def list_publications():
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.*,a.channel_title,j.status AS job_status,j.progress AS job_progress "
            "FROM youtube_publications p JOIN youtube_accounts a ON a.id=p.account_id "
            "LEFT JOIN jobs j ON j.id=p.job_id ORDER BY p.created_at DESC LIMIT 100"
        ).fetchall()
    return [_public_publication(row) for row in rows]


def cancel_publication(publication_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT p.status,p.upload_started,p.job_id,j.status AS job_status FROM youtube_publications p "
            "LEFT JOIN jobs j ON j.id=p.job_id WHERE p.id=?",
            (publication_id,),
        ).fetchone()
        if row is None:
            raise YouTubeError("YouTube publication not found.", status=404)
        if row["status"] != "pending" or row["upload_started"] or row["job_status"] not in {"queued", "preparing"}:
            raise YouTubeError("Publishing can only be cancelled before upload starts.", status=409)
        conn.execute(
            "UPDATE youtube_publications SET status='cancelled',last_error=NULL,updated_at=? WHERE id=? AND status='pending'",
            (now(), publication_id),
        )
        if row["job_status"] == "queued":
            conn.execute(
                "UPDATE jobs SET status='cancelled',phase='cancelled',message='Publishing dibatalkan sebelum upload.',updated_at=? WHERE id=? AND status='queued'",
                (now(), row["job_id"]),
            )
    return get_publication(publication_id)


def retry_publication(publication_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM youtube_publications WHERE id=?", (publication_id,)).fetchone()
        if row is None:
            raise YouTubeError("YouTube publication not found.", status=404)
        if row["status"] != "failed":
            raise YouTubeError("Only failed publications can be retried.", status=409)
        if row["reconciliation_required"]:
            raise YouTubeError("Upload outcome is uncertain. Check YouTube Studio before any new upload; automatic retry is blocked.", status=409)
        if row["video_id"]:
            conn.execute(
                "UPDATE youtube_publications SET status='processing',next_poll_at=0,last_error=NULL,updated_at=? WHERE id=?",
                (now(), publication_id),
            )
        else:
            account = conn.execute("SELECT status,token_blob FROM youtube_accounts WHERE id=?", (row["account_id"],)).fetchone()
            if not account or account["status"] != "connected" or not account["token_blob"]:
                raise YouTubeError("Reconnect the YouTube account before retrying.", status=409)
            clip = conn.execute("SELECT * FROM clips WHERE id=?", (row["clip_id"],)).fetchone()
            if clip is None:
                raise YouTubeError("Original clip was deleted. Retry is blocked.", status=409)
            path, metadata, digest = validate_short(dict(clip))
            if str(path) != row["rendered_path"] or digest != row["rendered_sha256"]:
                raise YouTubeError("Approved final render changed. Approve the current render before publishing again.", status=409)
            job_id, timestamp = uuid.uuid4().hex, now()
            conn.execute(
                "UPDATE youtube_publications SET status='pending',attempts=attempts+1,last_error=NULL,job_id=?,updated_at=? WHERE id=?",
                (job_id, timestamp, publication_id),
            )
            _insert_upload_job(conn, job_id, publication_id, clip["source_id"], row["clip_id"], timestamp)
    return get_publication(publication_id)


def _load_publication(publication_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM youtube_publications WHERE id=?", (publication_id,)).fetchone()
    if row is None:
        raise YouTubeError("YouTube publication not found.", status=404)
    return dict(row)


def _save_progress(publication_id, uploaded_bytes):
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_publications SET uploaded_bytes=?,updated_at=? WHERE id=? AND status IN ('pending','uploading')",
            (uploaded_bytes, now(), publication_id),
        )


def _save_session(publication_id, session_url):
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_publications SET upload_session_blob=?,updated_at=? WHERE id=?",
            (encrypt_secret(session_url), now(), publication_id),
        )


def _session_url(row):
    if not row["upload_session_blob"]:
        return None
    url = decrypt_secret(row["upload_session_blob"])
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise YouTubeError("Stored resumable upload session URI is invalid.") from None
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".googleapis.com") or parsed.username or parsed.password or port not in (None, 443):
        raise YouTubeError("Stored resumable upload session URI is invalid.")
    return url


def _authorized_http(account_id, method, url, headers, body=None, *, timeout=60, refresh_on_401=True):
    token = _refresh(account_id)
    request_headers = {**headers, "Authorization": f"Bearer {token}"}
    result = _http(method, url, request_headers, body, timeout)
    if result[0] == 401 and refresh_on_401:
        token = _refresh(account_id, force=True)
        request_headers["Authorization"] = f"Bearer {token}"
        result = _http(method, url, request_headers, body, timeout)
        if result[0] == 401:
            _set_account_status(account_id, "error", "Google rejected refreshed YouTube authorization.")
    return result


def _new_session(publication, account_id):
    snippet = {
        "title": publication["title"],
        "description": publication["description"],
        "categoryId": "22",
    }
    tags = json.loads(publication["tags_json"])
    if tags:
        snippet["tags"] = tags
    body = {
        "snippet": snippet,
        "status": {
            "privacyStatus": publication["privacy_status"],
            "selfDeclaredMadeForKids": bool(publication["made_for_kids"]),
            "containsSyntheticMedia": bool(publication["contains_synthetic_media"]),
        },
    }
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(publication["file_size"]),
        "X-Upload-Content-Type": "video/mp4",
    }
    url = UPLOAD_URL + "?" + urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status"})
    status, response_headers, raw = _authorized_http(account_id, "POST", url, headers, json.dumps(body).encode())
    if status < 200 or status >= 300:
        raise _response_error(status, raw)
    session = next((value for key, value in response_headers.items() if key.lower() == "location"), None)
    if not session:
        raise YouTubeError("YouTube did not return resumable upload session URI.")
    try:
        parsed = urllib.parse.urlsplit(session)
        port = parsed.port
    except ValueError:
        raise YouTubeError("YouTube returned an invalid upload session URI.") from None
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".googleapis.com") or parsed.username or parsed.password or port not in (None, 443):
        raise YouTubeError("YouTube returned an unsafe upload session URI.")
    _save_session(publication["id"], session)
    return session


def _session_status(publication, account_id, session):
    headers = {"Content-Length": "0", "Content-Range": f"bytes */{publication['file_size']}"}
    status, response_headers, raw = _authorized_http(account_id, "PUT", session, headers, b"", timeout=60)
    if status == 308:
        range_header = next((value for key, value in response_headers.items() if key.lower() == "range"), "")
        if not range_header:
            offset = 0
        else:
            try:
                offset = int(range_header.rsplit("-", 1)[1]) + 1
            except (ValueError, IndexError):
                raise YouTubeError("YouTube returned invalid resumable Range header.") from None
            if not 0 <= offset <= publication["file_size"]:
                raise YouTubeError("YouTube returned out-of-range upload progress.")
        _save_progress(publication["id"], offset)
        return offset, None, False
    if status in {200, 201}:
        try:
            return publication["file_size"], json.loads(raw), False
        except ValueError:
            raise YouTubeError("YouTube completed upload without a readable video resource.") from None
    if status in {404, 410}:
        return 0, None, True
    raise _response_error(status, raw)


def _transition_uploading(publication_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute(
            "UPDATE youtube_publications SET status='uploading',updated_at=? WHERE id=? AND status='pending'",
            (now(), publication_id),
        ).rowcount
    if not changed:
        raise PublishCancelled("Job cancelled.")


def _set_video_id(publication_id, video):
    video_id = video.get("id") if isinstance(video, dict) else None
    if not video_id:
        with connect() as conn:
            conn.execute(
                "UPDATE youtube_publications SET status='failed',reconciliation_required=1,last_error=?,updated_at=? WHERE id=?",
                ("Upload completed but YouTube omitted video ID. Reconcile in YouTube Studio before retry.", now(), publication_id),
            )
        raise YouTubeError("Upload response omitted video ID; automatic retry is blocked.")
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_publications SET status='processing',video_id=?,video_url=?,uploaded_bytes=file_size,"
            "next_poll_at=0,last_error=NULL,updated_at=? WHERE id=?",
            (video_id, f"https://youtu.be/{video_id}", now(), publication_id),
        )


def _fail_publication(publication_id, message, reconciliation_required=False):
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_publications SET status='failed',last_error=?,"
            "reconciliation_required=MAX(reconciliation_required,?),updated_at=? WHERE id=? AND status NOT IN ('published','cancelled')",
            (str(message)[:500], int(reconciliation_required), now(), publication_id),
        )


def _schedule_processing(publication, message=None):
    checks = int(publication.get("processing_checks", 0)) + 1
    delay = min(15 * (2 ** min(checks, 4)), 240)
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_publications SET status='processing',processing_checks=?,next_poll_at=?,last_error=?,updated_at=? WHERE id=?",
            (checks, time.time() + delay, message, now(), publication["id"]),
        )


def _verify_source_unchanged(publication):
    with connect() as conn:
        clip = conn.execute("SELECT * FROM clips WHERE id=?", (publication["clip_id"],)).fetchone()
    if clip is None:
        raise YouTubeError("Clip was deleted before upload.", status=409)
    path, metadata, digest = validate_short(dict(clip))
    if (
        str(path) != publication["rendered_path"]
        or digest != publication["rendered_sha256"]
        or clip["review_status"] != "approved"
    ):
        raise YouTubeError("Approved render changed before upload. Approve the current final render first.", status=409)
    return path


def _mark_uncertain(publication_id):
    message = "Resumable session expired after upload bytes may have been sent. Check YouTube Studio; automatic retry is blocked to prevent duplicates."
    _fail_publication(publication_id, message, reconciliation_required=True)
    raise YouTubeError(message)


def _upload_file(publication, account_id, session, path, cancel, progress_callback):
    total = publication["file_size"]
    offset = int(publication["uploaded_bytes"])
    transient_attempts = 0
    while offset < total:
        if cancel.is_set():
            raise PublishCancelled("Job cancelled.")
        if not publication["upload_started"]:
            with connect() as conn:
                conn.execute("UPDATE youtube_publications SET upload_started=1,updated_at=? WHERE id=?", (now(), publication["id"]))
            publication["upload_started"] = 1
        chunk_end = min(total, offset + CHUNK_BYTES)
        with path.open("rb") as media:
            media.seek(offset)
            chunk = media.read(chunk_end - offset)
        if len(chunk) != chunk_end - offset:
            raise YouTubeError("Rendered MP4 changed while publishing.")
        headers = {
            "Content-Length": str(len(chunk)),
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes {offset}-{chunk_end - 1}/{total}",
        }
        try:
            status, response_headers, raw = _authorized_http(
                account_id, "PUT", session, headers, chunk, timeout=120, refresh_on_401=False,
            )
        except YouTubeError as exc:
            if not exc.retryable:
                raise
            status, response_headers, raw = exc.status or 0, {}, b""
        if status == 401:
            _refresh(account_id, force=True)
            transient_attempts += 1
        elif status == 308:
            range_header = next((value for key, value in response_headers.items() if key.lower() == "range"), "")
            if not range_header:
                next_offset = 0
            else:
                try:
                    next_offset = int(range_header.rsplit("-", 1)[1]) + 1
                except (ValueError, IndexError):
                    raise YouTubeError("YouTube returned invalid resumable Range header.") from None
            if not 0 <= next_offset <= total:
                raise YouTubeError("YouTube returned out-of-range upload progress.")
            if next_offset > offset:
                transient_attempts = 0
            else:
                transient_attempts += 1
                if transient_attempts > 5:
                    raise YouTubeError("YouTube made no resumable upload progress after repeated attempts.", retryable=True)
                time.sleep(min(2 ** transient_attempts, 16))
            offset = next_offset
            _save_progress(publication["id"], offset)
            progress_callback(offset, total)
            continue
        elif status in {200, 201}:
            try:
                resource = json.loads(raw)
            except ValueError:
                resource = {}
            _set_video_id(publication["id"], resource)
            progress_callback(total, total)
            return
        elif status:
            error = _response_error(status, raw)
            if not error.retryable:
                raise error
            transient_attempts += 1
        else:
            transient_attempts += 1
        if transient_attempts > 5:
            raise YouTubeError("Upload interrupted after repeated transient errors; retry will reconcile session.", retryable=True)
        delay = _retry_after(response_headers, min(2 ** transient_attempts, 16))
        try:
            acknowledged, resource, expired = _session_status(publication, account_id, session)
        except YouTubeError as exc:
            if not exc.retryable:
                raise
            time.sleep(delay)
            continue
        if resource:
            _set_video_id(publication["id"], resource)
            progress_callback(total, total)
            return
        if expired:
            _mark_uncertain(publication["id"])
        offset = acknowledged
        _save_progress(publication["id"], offset)
        progress_callback(offset, total)
        if offset == chunk_end:
            transient_attempts = 0
        else:
            time.sleep(_retry_after(response_headers, delay))
    offset, resource, expired = _session_status(publication, account_id, session)
    if resource:
        _set_video_id(publication["id"], resource)
        progress_callback(total, total)
        return
    if expired:
        _mark_uncertain(publication["id"])
    _save_progress(publication["id"], offset)
    raise YouTubeError("YouTube acknowledged all upload bytes but has not confirmed video ID yet; retry will reconcile.", retryable=True)


def run_upload(publication_id, cancel, progress_callback):
    try:
        publication = _load_publication(publication_id)
        if publication["status"] == "cancelled":
            raise PublishCancelled("Job cancelled.")
        if publication["status"] != "pending":
            raise YouTubeError("Publication is no longer pending.")
        path = _verify_source_unchanged(publication)
        with connect() as conn:
            account = conn.execute("SELECT status FROM youtube_accounts WHERE id=?", (publication["account_id"],)).fetchone()
        if not account or account["status"] != "connected":
            raise YouTubeError("Reconnect the YouTube account before upload.", status=401)
        if cancel.is_set():
            raise PublishCancelled("Job cancelled.")
        session = _session_url(publication)
        if session:
            offset, completed, expired = _session_status(publication, publication["account_id"], session)
            if completed:
                _set_video_id(publication_id, completed)
                progress_callback(publication["file_size"], publication["file_size"])
                return
            if expired:
                if publication["upload_started"]:
                    _mark_uncertain(publication_id)
                session = None
            else:
                publication["uploaded_bytes"] = offset
        if not session:
            session = _new_session(publication, publication["account_id"])
        if cancel.is_set():
            raise PublishCancelled("Job cancelled.")
        _transition_uploading(publication_id)
        _upload_file(publication, publication["account_id"], session, path, cancel, progress_callback)
        poll_publication(publication_id)
    except PublishCancelled:
        with connect() as conn:
            conn.execute(
                "UPDATE youtube_publications SET status='cancelled',last_error=NULL,updated_at=? WHERE id=? AND status='pending'",
                (now(), publication_id),
            )
        raise
    except YouTubeError as exc:
        _fail_publication(publication_id, str(exc))
        raise
    except Exception:
        _fail_publication(publication_id, "Publishing failed. Check backend log and retry safely.")
        raise


def _poll_video(publication):
    if not publication["video_id"]:
        _fail_publication(publication["id"], "No YouTube video ID to reconcile.", reconciliation_required=True)
        return
    resource = _authorized_json(
        publication["account_id"], "GET",
        _api_url("/videos", {"part": "snippet,status,processingDetails", "id": publication["video_id"]}),
    )
    items = resource.get("items") or []
    if not items:
        _schedule_processing(publication, "YouTube has not returned this video resource yet; checking again.")
        return
    video = items[0]
    account = next((row for row in list_accounts() if row["id"] == publication["account_id"]), None)
    expected_channel = account["channel_id"] if account else None
    actual_channel = (video.get("snippet") or {}).get("channelId")
    status = video.get("status") or {}
    details = video.get("processingDetails") or {}
    processing = details.get("processingStatus")
    if not actual_channel:
        _schedule_processing(publication, "Waiting for YouTube channel identity confirmation.")
        return
    if expected_channel and expected_channel != actual_channel:
        _fail_publication(publication["id"], "YouTube uploaded video to a different channel than selected.")
        return
    if status.get("privacyStatus") != publication["privacy_status"]:
        _fail_publication(publication["id"], "YouTube returned a different privacy setting than requested.")
        return
    if status.get("selfDeclaredMadeForKids") is not None and bool(status["selfDeclaredMadeForKids"]) != bool(publication["made_for_kids"]):
        _fail_publication(publication["id"], "YouTube did not confirm Made for Kids setting.")
        return
    if status.get("containsSyntheticMedia") is not None and bool(status["containsSyntheticMedia"]) != bool(publication["contains_synthetic_media"]):
        _fail_publication(publication["id"], "YouTube did not confirm synthetic-media disclosure setting.")
        return
    upload_status = status.get("uploadStatus")
    if upload_status in {"failed", "rejected", "deleted"} or processing in {"failed", "terminated"}:
        reason = details.get("processingFailureReason") or upload_status or processing
        _fail_publication(publication["id"], f"YouTube processing failed: {reason}.")
        return
    if upload_status == "processed" and processing in {None, "succeeded"}:
        with connect() as conn:
            conn.execute(
                "UPDATE youtube_publications SET status='published',uploaded_bytes=file_size,next_poll_at=NULL,last_error=NULL,updated_at=? WHERE id=?",
                (now(), publication["id"]),
            )
        return
    _schedule_processing(publication)


def poll_publication(publication_id):
    publication = _load_publication(publication_id)
    if publication["status"] != "processing":
        return
    try:
        _poll_video(publication)
    except YouTubeError as exc:
        # Keep confirmed uploads in Processing through transient/network/auth failures.
        checks = int(publication.get("processing_checks", 0)) + 1
        with connect() as conn:
            conn.execute(
                "UPDATE youtube_publications SET status='processing',processing_checks=?,next_poll_at=?,last_error=?,updated_at=? WHERE id=? AND status='processing'",
                (checks, time.time() + min(30 * (2 ** min(checks, 4)), 300), str(exc)[:500], now(), publication_id),
            )


def next_due_publication():
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM youtube_publications WHERE status='processing' AND next_poll_at<=? ORDER BY next_poll_at LIMIT 1",
            (time.time(),),
        ).fetchone()
    return row["id"] if row else None
