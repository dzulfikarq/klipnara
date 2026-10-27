import ctypes
import email.utils
import hashlib
import json
import os
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import CLIP_DIR, LEGACY_CLIP_DIR
from .db import connect
from .jobs import now
from .media import MediaError, probe


UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
CHANNEL_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_READ_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
BASE_SCOPES = (UPLOAD_SCOPE, CHANNEL_READ_SCOPE)
ANALYTICS_SCOPES = (ANALYTICS_READ_SCOPE, CHANNEL_READ_SCOPE)
SCOPES = (*BASE_SCOPES, ANALYTICS_READ_SCOPE)
SCOPE = " ".join(SCOPES)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_URL = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK_BYTES = 8 * 1024 * 1024
SHORT_MAX_SECONDS = 180


class YouTubeError(RuntimeError):
    def __init__(self, message, *, status=None, reason=None, retryable=False, code=None):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.retryable = retryable
        self.code = code


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


def oauth_state_cookie_name(state):
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()[:24]
    return f"klipnara_youtube_state_{digest}"


def _credentials():
    client_id, client_secret = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise YouTubeError("YouTube OAuth client is not configured.", code="oauth_client_not_configured")
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


def create_oauth_state(account_id=None, purpose="connect"):
    state = secrets.token_urlsafe(32)
    timestamp = now()
    with connect() as conn:
        conn.execute("DELETE FROM youtube_oauth_states WHERE expires_at<?", (time.time(),))
        conn.execute(
            "INSERT INTO youtube_oauth_states(state_hash,created_at,expires_at,account_id,purpose) VALUES(?,?,?,?,?)",
            (hashlib.sha256(state.encode()).hexdigest(), timestamp, time.time() + 600, account_id, purpose),
        )
    return state


def consume_oauth_state_context(state, browser_state):
    if not state or not browser_state or not secrets.compare_digest(state, browser_state):
        return None
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM youtube_oauth_states WHERE state_hash=?", (state_hash,)).fetchone()
        conn.execute("DELETE FROM youtube_oauth_states WHERE state_hash=?", (state_hash,))
    return dict(row) if row and row["expires_at"] >= time.time() else None


def consume_oauth_state(state, browser_state):
    return consume_oauth_state_context(state, browser_state) is not None


def authorization_url(state, scopes=None):
    client_id, _ = _credentials()
    oauth_start_url()
    scopes = tuple(scopes or SCOPES)
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "select_account",
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
    try:
        payload, _ = _json_call("POST", TOKEN_URL, form={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
    except YouTubeError as exc:
        error_code = {
            "redirect_uri_mismatch": "oauth_redirect_uri_mismatch",
            "invalid_client": "oauth_client_rejected",
            "unauthorized_client": "oauth_client_rejected",
            "invalid_grant": "oauth_code_rejected",
        }.get(exc.reason, "oauth_token_exchange_failed")
        messages = {
            "oauth_redirect_uri_mismatch": "Google rejected the callback URI during token exchange.",
            "oauth_client_rejected": "Google rejected the configured OAuth client.",
            "oauth_code_rejected": "Google rejected the authorization code; it may be expired or already used.",
            "oauth_token_exchange_failed": "Google token exchange failed.",
        }
        raise YouTubeError(messages[error_code], status=exc.status, reason=exc.reason, retryable=exc.retryable, code=error_code) from None
    except Exception:
        raise YouTubeError("Google token exchange failed.", code="oauth_token_exchange_failed") from None
    if not isinstance(payload, dict):
        raise YouTubeError("Google returned an invalid token response.", code="oauth_token_exchange_failed")
    return payload


def _granted_scopes(token_data):
    scope = token_data.get("scope")
    if isinstance(scope, str):
        return set(scope.split())
    access_token = token_data.get("access_token")
    if not access_token:
        raise YouTubeError("Google OAuth response omitted access token.", code="oauth_token_exchange_failed")
    try:
        payload, _ = _json_call(
            "GET", TOKEN_INFO_URL + "?" + urllib.parse.urlencode({"access_token": access_token}), timeout=10,
        )
    except YouTubeError:
        raise YouTubeError(
            "Google did not return granted scopes and scope verification failed.",
            code="oauth_scope_verification_failed",
        ) from None
    scopes = payload.get("scope") if isinstance(payload, dict) else None
    if not isinstance(scopes, str):
        raise YouTubeError(
            "Google did not return verifiable granted scopes.", code="oauth_scope_verification_failed",
        )
    return set(scopes.split())


def _account_tokens(account):
    keys = set(account.keys())
    authorization_id = account["authorization_id"] if "authorization_id" in keys else None
    if authorization_id:
        with connect() as conn:
            authorization = conn.execute(
                "SELECT provider,credentials_blob,token_status FROM oauth_authorizations WHERE id=?",
                (authorization_id,),
            ).fetchone()
        if not authorization or authorization["provider"] != "youtube" or authorization["token_status"] != "active" or not authorization["credentials_blob"]:
            raise YouTubeError("YouTube authorization is unavailable or belongs to another provider.", status=401, code="authorization_mismatch")
        if authorization["credentials_blob"]:
            return json.loads(decrypt_secret(authorization["credentials_blob"]))
    if account["token_blob"]:
        return json.loads(decrypt_secret(account["token_blob"]))
    raise YouTubeError("YouTube authorization credentials are unavailable.", status=401, code="authorization_missing")


def _refresh(account_id, *, force=False):
    with connect() as conn:
        row = conn.execute("SELECT * FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
    if not row or row["status"] == "disconnected" or not (row["authorization_id"] or row["token_blob"]):
        raise YouTubeError("YouTube account is disconnected. Connect it again.")
    try:
        tokens = _account_tokens(row)
    except Exception:
        _set_account_status(account_id, "error", "Encrypted YouTube authorization could not be read.")
        raise YouTubeError("Stored YouTube authorization could not be read. Reconnect the account.", status=503, code="token_storage_failed") from None
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
    encrypted = encrypt_secret(json.dumps(tokens))
    with connect() as conn:
        if row["authorization_id"]:
            conn.execute(
                "UPDATE oauth_authorizations SET credentials_blob=?,expires_at=?,token_status='active',updated_at=? WHERE id=? AND provider='youtube'",
                (encrypted, expires, now(), row["authorization_id"]),
            )
        conn.execute(
            "UPDATE youtube_accounts SET token_blob=?,expires_at=?,status='connected',error_message=NULL,updated_at=? "
            "WHERE id=? AND status!='disconnected'",
            (encrypted, expires, now(), account_id),
        )
    return tokens["access_token"]


def _set_account_status(account_id, status, message=None):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = conn.execute("SELECT is_default FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
        conn.execute(
            "UPDATE youtube_accounts SET status=?,error_message=?,is_default=CASE WHEN ?='connected' THEN is_default ELSE 0 END,updated_at=? WHERE id=? AND status!='disconnected'",
            (status, message, status, now(), account_id),
        )
        if account and account["is_default"] and status != "connected":
            next_account = conn.execute("SELECT id FROM youtube_accounts WHERE status='connected' ORDER BY created_at,id LIMIT 1").fetchone()
            if next_account:
                conn.execute("UPDATE youtube_accounts SET is_default=1 WHERE id=?", (next_account["id"],))


def connect_account(code, *, expected_channel_id=None):
    try:
        token_data = _exchange_code(code)
    except YouTubeError:
        raise
    except Exception:
        raise YouTubeError("Google token exchange failed.", code="oauth_token_exchange_failed") from None
    if not isinstance(token_data, dict):
        raise YouTubeError("Google returned an invalid token response.", code="oauth_token_exchange_failed")
    access_token = token_data.get("access_token")
    if not access_token:
        raise YouTubeError("Google OAuth response omitted access token.", code="oauth_token_exchange_failed")
    granted_scopes = _granted_scopes(token_data)
    if CHANNEL_READ_SCOPE not in granted_scopes:
        raise YouTubeError(
            "Google did not grant YouTube read access required to verify channel identity.",
            code="oauth_scope_insufficient",
        )
    if UPLOAD_SCOPE not in granted_scopes:
        raise YouTubeError(
            "Google did not grant YouTube upload access. Existing publishing credentials remain unchanged.",
            code="oauth_scope_insufficient",
        )
    previous = None
    previous_scopes = set()
    if expected_channel_id:
        with connect() as conn:
            previous = conn.execute(
                "SELECT id,channel_id,token_blob,authorization_id,is_default,granted_scopes_json,status FROM youtube_accounts WHERE channel_id=?",
                (expected_channel_id,),
            ).fetchone()
        if not previous or previous["status"] != "connected" or not previous["token_blob"]:
            raise YouTubeError("Reconnect the selected channel before enabling Analytics.", status=409, code="oauth_account_unavailable")
        if previous["granted_scopes_json"]:
            previous_scopes = set(json.loads(previous["granted_scopes_json"]))
        if not previous_scopes.issubset(granted_scopes):
            raise YouTubeError(
                "Google returned a narrower grant. Existing credentials remain unchanged; reconnect without removing permissions.",
                code="oauth_scope_downgrade_blocked",
            )
    try:
        channel_params = {"part": "snippet", "id": expected_channel_id} if expected_channel_id else {
            "part": "snippet", "mine": "true", "maxResults": 50,
        }
        channels, _ = _json_call(
            "GET", _api_url("/channels", channel_params), token=access_token,
        )
    except YouTubeError as exc:
        error_code = "oauth_scope_insufficient" if exc.reason in {"insufficientPermissions", "insufficient_scope"} else "youtube_api_failed"
        message = (
            "YouTube rejected channel lookup because the grant lacks required read access."
            if error_code == "oauth_scope_insufficient"
            else "YouTube channel lookup failed."
        )
        raise YouTubeError(message, status=exc.status, reason=exc.reason, retryable=exc.retryable, code=error_code) from None
    except Exception:
        raise YouTubeError("YouTube channel lookup failed.", code="youtube_api_failed") from None
    if not isinstance(channels, dict):
        raise YouTubeError("YouTube returned an invalid channel response.", code="youtube_api_failed")
    items = channels.get("items") or []
    if not isinstance(items, list):
        raise YouTubeError("YouTube returned an invalid channel list.", code="youtube_api_failed")
    if not items:
        raise YouTubeError("This Google account has no YouTube channel available to Klipnara.", code="youtube_channel_not_found")
    if len(items) > 1:
        raise YouTubeError(
            "Google returned multiple channels. Klipnara will not guess the target channel.",
            code="youtube_multiple_channels",
        )
    channel = items[0]
    if not isinstance(channel, dict):
        raise YouTubeError("YouTube returned an invalid channel identity.", code="youtube_api_failed")
    channel_id = channel.get("id")
    snippet = channel.get("snippet") or {}
    if not isinstance(snippet, dict):
        raise YouTubeError("YouTube returned an invalid channel identity.", code="youtube_api_failed")
    channel_title = snippet.get("title")
    thumbnails = snippet.get("thumbnails") or {}
    if not isinstance(thumbnails, dict):
        thumbnails = {}
    thumbnail = thumbnails.get("default") or thumbnails.get("medium") or {}
    channel_avatar_url = thumbnail.get("url") if isinstance(thumbnail, dict) else None
    if not isinstance(channel_id, str) or not channel_id or not isinstance(channel_title, str) or not channel_title:
        raise YouTubeError("YouTube returned incomplete channel identity.", code="youtube_api_failed")
    if expected_channel_id and channel_id != expected_channel_id:
        raise YouTubeError(
            "OAuth grant resolved to a different YouTube channel. Existing connection was not changed.",
            status=409,
            code="youtube_channel_mismatch",
        )
    refresh_token = token_data.get("refresh_token")
    try:
        if previous is None:
            with connect() as conn:
                previous = conn.execute(
                    "SELECT id,channel_id,token_blob,authorization_id,is_default,granted_scopes_json,status FROM youtube_accounts WHERE channel_id=?",
                    (channel_id,),
                ).fetchone()
            if previous and previous["granted_scopes_json"]:
                previous_scopes = set(json.loads(previous["granted_scopes_json"]))
            if previous_scopes and not previous_scopes.issubset(granted_scopes):
                raise YouTubeError(
                    "Google returned a narrower grant. Existing credentials remain unchanged; reconnect without removing permissions.",
                    code="oauth_scope_downgrade_blocked",
                )
    except YouTubeError:
        raise
    except Exception:
        raise YouTubeError("Could not safely inspect existing encrypted channel credentials.", code="oauth_token_storage_failed") from None
    if not refresh_token and previous and (previous["token_blob"] or previous["authorization_id"]):
        try:
            old_tokens = _account_tokens(previous)
        except Exception:
            raise YouTubeError("Could not safely reuse existing encrypted channel credentials.", code="oauth_token_storage_failed") from None
        refresh_token = old_tokens.get("refresh_token")
    if not refresh_token:
        raise YouTubeError("Google omitted a refresh token. Revoke Klipnara access in Google Account settings, then consent again.", code="oauth_refresh_token_missing")
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_data.get("token_type", "Bearer"),
    }
    try:
        account_id = previous["id"] if previous else uuid.uuid4().hex
        authorization_id = previous["authorization_id"] if previous and previous["authorization_id"] else uuid.uuid4().hex
        timestamp = now()
        encrypted_tokens = encrypt_secret(json.dumps(tokens))
        expires_at = time.time() + int(token_data.get("expires_in", 3600))
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current_default = conn.execute("SELECT id FROM youtube_accounts WHERE status='connected' AND is_default=1").fetchone()
            is_default = int(bool(previous and previous["is_default"]) or not current_default)
            conn.execute(
                "INSERT INTO oauth_authorizations(id,provider,credentials_blob,granted_scopes_json,expires_at,token_status,created_at,updated_at) "
                "VALUES(?,'youtube',?,?,?,'active',?,?) ON CONFLICT(id) DO UPDATE SET credentials_blob=excluded.credentials_blob,"
                "granted_scopes_json=excluded.granted_scopes_json,expires_at=excluded.expires_at,token_status='active',updated_at=excluded.updated_at",
                (authorization_id, encrypted_tokens, json.dumps(sorted(granted_scopes)), expires_at, timestamp, timestamp),
            )
            conn.execute(
                "INSERT INTO youtube_accounts(id,channel_id,channel_title,status,token_blob,expires_at,error_message,channel_avatar_url,verified_at,granted_scopes_json,authorization_id,is_default,created_at,updated_at) "
                "VALUES(?,?,?,'connected',?,?,NULL,?,?,?,?,?,?,?) "
                "ON CONFLICT(channel_id) DO UPDATE SET channel_title=excluded.channel_title,status='connected',"
                "token_blob=excluded.token_blob,expires_at=excluded.expires_at,error_message=NULL,"
                "channel_avatar_url=excluded.channel_avatar_url,verified_at=excluded.verified_at,"
                "granted_scopes_json=excluded.granted_scopes_json,authorization_id=excluded.authorization_id,"
                "is_default=MAX(youtube_accounts.is_default,excluded.is_default),updated_at=excluded.updated_at",
                (
                    account_id, channel_id, channel_title, encrypted_tokens,
                    expires_at, channel_avatar_url, timestamp, json.dumps(sorted(granted_scopes)),
                    authorization_id, is_default, timestamp, timestamp,
                ),
            )
    except Exception:
        raise YouTubeError(
            "Channel was verified, but encrypted token storage failed; no new connection was saved.",
            code="oauth_token_storage_failed",
        ) from None
    return {
        "id": account_id, "channel_id": channel_id, "channel_title": channel_title,
        "channel_avatar_url": channel_avatar_url, "verified_at": timestamp, "status": "connected",
        "granted_scopes": sorted(granted_scopes),
        "analytics_ready": set(ANALYTICS_SCOPES).issubset(granted_scopes),
        "upload_ready": UPLOAD_SCOPE in granted_scopes,
    }


def list_accounts():
    with connect() as conn:
        rows = conn.execute(
            "SELECT id,channel_id,channel_title,channel_avatar_url,verified_at,status,expires_at,error_message,"
            "granted_scopes_json,is_default,created_at,updated_at "
            "FROM youtube_accounts ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        scopes_json = item.pop("granted_scopes_json")
        scopes = json.loads(scopes_json) if scopes_json else []
        item["granted_scopes"] = scopes
        item["scopes_verified"] = scopes_json is not None
        item["is_default"] = bool(item["is_default"])
        item["analytics_ready"] = set(ANALYTICS_SCOPES).issubset(scopes)
        item["upload_ready"] = UPLOAD_SCOPE in scopes if scopes_json is not None else None
        result.append(item)
    return result


def verify_account(account_id):
    with connect() as conn:
        account = conn.execute("SELECT * FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
    if not account or account["status"] != "connected" or not account["token_blob"]:
        raise YouTubeError("Reconnect the YouTube account before verifying its channel.", status=409)
    payload = _authorized_json(
        account_id, "GET", _api_url("/channels", {"part": "snippet", "mine": "true", "maxResults": 50}),
    )
    channel = next((item for item in payload.get("items", []) if item.get("id") == account["channel_id"]), None)
    if not channel:
        _set_account_status(account_id, "error", "Connected Google grant no longer verifies the stored YouTube channel.")
        raise YouTubeError("YouTube channel identity could not be verified. Reconnect the intended channel.", status=409)
    snippet = channel.get("snippet") or {}
    thumbnails = snippet.get("thumbnails") or {}
    avatar = (thumbnails.get("default") or thumbnails.get("medium") or {}).get("url")
    timestamp = now()
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_accounts SET channel_title=?,channel_avatar_url=?,verified_at=?,status='connected',"
            "error_message=NULL,updated_at=? WHERE id=?",
            (snippet.get("title") or account["channel_title"], avatar, timestamp, timestamp, account_id),
        )
    return next(row for row in list_accounts() if row["id"] == account_id)


def disconnect_account(account_id):
    with connect() as conn:
        row = conn.execute("SELECT id,channel_id,token_blob,authorization_id,is_default FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        raise YouTubeError("Connected YouTube account not found.", status=404)
    revoked = False
    shared_grant = False
    if row["authorization_id"]:
        with connect() as conn:
            shared_grant = conn.execute(
                "SELECT 1 FROM youtube_accounts WHERE authorization_id=? AND id!=? AND status!='disconnected' LIMIT 1",
                (row["authorization_id"], account_id),
            ).fetchone() is not None
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        queued = conn.execute(
            "SELECT id,job_id,content_type,clip_id FROM youtube_publications WHERE account_id=? AND status='pending' AND upload_started=0",
            (account_id,),
        ).fetchall()
        for publication in queued:
            conn.execute(
                "UPDATE youtube_publications SET status='cancelled',last_error='Account disconnected before upload started.',updated_at=? WHERE id=? AND status='pending'",
                (now(), publication["id"]),
            )
            conn.execute("UPDATE jobs SET status='cancelled',phase='cancelled',message='Account disconnected before upload.',updated_at=? WHERE id=? AND status='queued'",
                         (now(), publication["job_id"]))
            conn.execute("UPDATE youtube_upload_jobs SET status='cancelled',phase='cancelled',message='Account disconnected before upload.',updated_at=? WHERE id=? AND status='queued'",
                         (now(), publication["job_id"]))
            conn.execute(
                "INSERT INTO publishing_events(id,content_type,content_id,publication_id,event_type,message,occurred_at) VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, publication["content_type"], publication["clip_id"], publication["id"],
                 "cancelled", "Queued upload cancelled because its destination account was disconnected.", now()),
            )
        conn.execute(
            "UPDATE youtube_accounts SET status='disconnected',token_blob=NULL,expires_at=NULL,error_message=NULL,is_default=0,updated_at=? WHERE id=?",
            (now(), account_id),
        )
        if row["is_default"]:
            next_account = conn.execute(
                "SELECT id FROM youtube_accounts WHERE status='connected' ORDER BY created_at,id LIMIT 1",
            ).fetchone()
            if next_account:
                conn.execute("UPDATE youtube_accounts SET is_default=1 WHERE id=?", (next_account["id"],))
    if not shared_grant and (row["token_blob"] or row["authorization_id"]):
        try:
            tokens = _account_tokens(row)
            _json_call("POST", REVOKE_URL, form={"token": tokens.get("refresh_token") or tokens.get("access_token")})
            revoked = True
        except YouTubeError:
            pass
    with connect() as conn:
        if row["authorization_id"] and not shared_grant:
            conn.execute("UPDATE oauth_authorizations SET credentials_blob=NULL,token_status='revoked',updated_at=? WHERE id=?",
                         (now(), row["authorization_id"]))
    from .youtube_analytics import clear_channel_cache
    clear_channel_cache(row["channel_id"])
    return {"id": account_id, "status": "disconnected", "remote_revoked": revoked}


def delete_disconnected_account(account_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT channel_id,status FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise YouTubeError("YouTube account not found.", status=404, code="account_not_found")
        if row["status"] != "disconnected":
            raise YouTubeError("Disconnect the YouTube account before deleting it.", status=409, code="account_not_disconnected")
        if conn.execute("SELECT 1 FROM youtube_publications WHERE account_id=? LIMIT 1", (account_id,)).fetchone():
            raise YouTubeError("YouTube account has publishing history; deletion is blocked to preserve it.", status=409, code="account_has_history")
        conn.execute("DELETE FROM youtube_oauth_states WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM youtube_analytics_cache WHERE channel_id=?", (row["channel_id"],))
        conn.execute("DELETE FROM youtube_accounts WHERE id=?", (account_id,))
    return {"id": account_id, "deleted": True}


def set_default_account(account_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = conn.execute("SELECT id,status FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
        if not account:
            raise YouTubeError("Connected YouTube account not found.", status=404, code="account_not_found")
        if account["status"] != "connected":
            raise YouTubeError("Reconnect this YouTube account before making it default.", status=409, code="account_unavailable")
        conn.execute("UPDATE youtube_accounts SET is_default=0 WHERE is_default=1")
        conn.execute("UPDATE youtube_accounts SET is_default=1,updated_at=? WHERE id=?", (now(), account_id))
    return next(item for item in list_accounts() if item["id"] == account_id)


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


def _file_fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publication_event(publication_id, event_type, message, details=None):
    with connect() as conn:
        row = conn.execute("SELECT content_type,clip_id FROM youtube_publications WHERE id=?", (publication_id,)).fetchone()
        if row:
            conn.execute(
                "INSERT INTO publishing_events(id,content_type,content_id,publication_id,event_type,message,details_json,occurred_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, row["content_type"], row["clip_id"], publication_id, event_type,
                 message[:500], json.dumps(details or {}, ensure_ascii=False), now()),
            )


def list_publishing_content():
    with connect() as conn:
        rows = conn.execute(
            "SELECT 'clip' AS content_type,c.id AS content_id,c.title,c.status,c.review_status,"
            "c.rendered_path AS path,c.start,c.end,s.name AS source_name,NULL AS project_id,NULL AS project_title,"
            "c.created_at,COALESCE(j.updated_at,c.created_at) AS updated_at FROM clips c "
            "JOIN sources s ON s.id=c.source_id LEFT JOIN jobs j ON j.id=c.job_id "
            "WHERE c.rendered_path IS NOT NULL "
            "UNION ALL "
            "SELECT 'mood_render' AS content_type,r.id AS content_id,p.title,r.status,r.review_status,"
            "r.path, NULL AS start,NULL AS end,NULL AS source_name,p.id AS project_id,p.title AS project_title,"
            "r.created_at,r.updated_at FROM mood_renders r JOIN mood_projects p ON p.id=r.project_id "
            "WHERE r.path IS NOT NULL ORDER BY updated_at DESC LIMIT 300"
        ).fetchall()
        drafts = {
            (row["content_type"], row["content_id"]): json.loads(row["metadata_json"])
            for row in conn.execute("SELECT content_type,content_id,metadata_json FROM publishing_metadata_drafts")
        }
        thumbnails = {
            (row["content_type"], row["content_id"]): dict(row)
            for row in conn.execute("SELECT * FROM publishing_thumbnails")
        }
    result = []
    for row in rows:
        item = dict(row)
        path = Path(item.pop("path")).resolve()
        valid_path = path.parent in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} and path.is_file()
        stats = path.stat() if valid_path else None
        item["file_size"] = stats.st_size if stats else None
        thumbnail = thumbnails.get((item["content_type"], item["content_id"]))
        thumb_path = Path(thumbnail["path"]).resolve() if thumbnail else None
        thumb_ok = bool(
            thumbnail and thumb_path.is_file() and stats
            and thumbnail["render_size"] == stats.st_size
            and thumbnail["render_mtime_ns"] == stats.st_mtime_ns
        )
        item["thumbnail_url"] = f"/api/publishing/{item['content_type']}/{item['content_id']}/thumbnail" if thumb_ok else None
        item["thumbnail_remote_status"] = thumbnail["remote_status"] if thumbnail else None
        item["thumbnail_error"] = thumbnail["remote_error"] if thumbnail else None
        item["metadata"] = drafts.get((item["content_type"], item["content_id"]), {})
        item["eligible"] = bool(valid_path and item["status"] == "completed" and item["review_status"] == "approved")
        item["editor_url"] = f"/clips/{item['content_id']}" if item["content_type"] == "clip" else f"/mood?id={item['project_id']}"
        item["output_url"] = f"/api/clips/{item['content_id']}/file" if item["content_type"] == "clip" else f"/api/mood-renders/{item['content_id']}/file"
        result.append(item)
    return result


def _metadata_keys(payload):
    allowed = {
        "account_id", "title", "description", "tags", "hashtags", "privacy_status", "publish_at",
        "category_id", "video_language", "made_for_kids", "contains_synthetic_media",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise YouTubeError(f"Unsupported publishing metadata field: {sorted(unknown)[0]}.", status=422)
    result = {key: payload[key] for key in allowed if key in payload}
    for key in ("tags", "hashtags"):
        if key in result and (not isinstance(result[key], list) or len(result[key]) > 100):
            raise YouTubeError(f"{key} must be a list with at most 100 entries.", status=422)
    return result


def get_metadata_draft(content_type, content_id, account_id=None):
    with connect() as conn:
        content = _load_content(conn, content_type, content_id)
        if content is None:
            raise YouTubeError("Publishing content not found.", status=404)
        base_row = conn.execute(
            "SELECT metadata_json,updated_at FROM publishing_metadata_drafts WHERE content_type=? AND content_id=?",
            (content_type, content_id),
        ).fetchone()
        row = conn.execute(
            "SELECT metadata_json,updated_at FROM youtube_account_metadata_drafts WHERE content_type=? AND content_id=? AND account_id=?",
            (content_type, content_id, account_id),
        ).fetchone() if account_id else None
        if account_id and not conn.execute("SELECT 1 FROM youtube_accounts WHERE id=?", (account_id,)).fetchone():
            raise YouTubeError("YouTube destination account not found.", status=404, code="account_not_found")
    metadata = json.loads(base_row["metadata_json"]) if base_row else {"title": content["title"]}
    if row:
        metadata.update(json.loads(row["metadata_json"]))
    if account_id:
        metadata["account_id"] = account_id
    return {
        "content_type": content_type, "content_id": content_id,
        "metadata": metadata,
        "updated_at": row["updated_at"] if row else base_row["updated_at"] if base_row else None,
    }


def save_metadata_draft(content_type, content_id, payload, account_id=None):
    values = _metadata_keys(payload)
    account_id = account_id or values.get("account_id")
    timestamp = now()
    with connect() as conn:
        if _load_content(conn, content_type, content_id) is None:
            raise YouTubeError("Publishing content not found.", status=404)
        if account_id:
            if not conn.execute("SELECT 1 FROM youtube_accounts WHERE id=?", (account_id,)).fetchone():
                raise YouTubeError("YouTube destination account not found.", status=404, code="account_not_found")
            values.pop("account_id", None)
            conn.execute(
                "INSERT INTO youtube_account_metadata_drafts(content_type,content_id,account_id,metadata_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(content_type,content_id,account_id) DO UPDATE SET metadata_json=excluded.metadata_json,updated_at=excluded.updated_at",
                (content_type, content_id, account_id, json.dumps(values, ensure_ascii=False), timestamp, timestamp),
            )
        else:
            conn.execute(
                "INSERT INTO publishing_metadata_drafts(content_type,content_id,metadata_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(content_type,content_id) DO UPDATE SET metadata_json=excluded.metadata_json,updated_at=excluded.updated_at",
                (content_type, content_id, json.dumps(values, ensure_ascii=False), timestamp, timestamp),
            )
    return get_metadata_draft(content_type, content_id, account_id)


def list_metadata_templates():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM publishing_metadata_templates ORDER BY name COLLATE NOCASE").fetchall()
    return [{**dict(row), "metadata": json.loads(row["template_json"])} for row in rows]


def save_metadata_template(name, payload, template_id=None):
    name = str(name).strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise YouTubeError("Template name must be 1–80 characters without control characters.", status=422)
    values = _metadata_keys(payload)
    timestamp = now()
    template_id = template_id or uuid.uuid4().hex
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO publishing_metadata_templates(id,name,template_json,created_at,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,template_json=excluded.template_json,updated_at=excluded.updated_at",
                (template_id, name, json.dumps(values, ensure_ascii=False), timestamp, timestamp),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise YouTubeError("A metadata template already uses this name.", status=409) from None
            raise
    return next(item for item in list_metadata_templates() if item["id"] == template_id)


def delete_metadata_template(template_id):
    with connect() as conn:
        changed = conn.execute("DELETE FROM publishing_metadata_templates WHERE id=?", (template_id,)).rowcount
    if not changed:
        raise YouTubeError("Metadata template not found.", status=404)
    return {"deleted": True}


def list_publishing_events(content_type=None, content_id=None, publication_id=None):
    where, values = [], []
    if content_type:
        where.append("content_type=?")
        values.append(content_type)
    if content_id:
        where.append("content_id=?")
        values.append(content_id)
    if publication_id:
        where.append("publication_id=?")
        values.append(publication_id)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM publishing_events" + clause + " ORDER BY occurred_at DESC LIMIT 500", values).fetchall()
    return [{**dict(row), "details": json.loads(row["details_json"])} for row in rows]


def publishing_calendar(start=None, end=None):
    query = "SELECT p.*,a.channel_title FROM youtube_publications p JOIN youtube_accounts a ON a.id=p.account_id WHERE p.publish_at IS NOT NULL"
    values = []
    if start:
        query += " AND publish_at>=?"
        values.append(start)
    if end:
        query += " AND publish_at<=?"
        values.append(end)
    query += " ORDER BY publish_at LIMIT 500"
    with connect() as conn:
        rows = conn.execute(query, values).fetchall()
    return [_public_publication(row) for row in rows]


def _image_dimensions(data, mime_type):
    if mime_type == "image/png":
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            return None
        return struct.unpack(">II", data[16:24])
    if mime_type != "image/jpeg" or len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    offset = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)}:
            continue
        if offset + 2 > len(data):
            break
        segment_length = struct.unpack(">H", data[offset:offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if marker in sof and segment_length >= 7:
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return width, height
        offset += segment_length
    return None


def save_local_thumbnail(content_type, content_id, data, mime_type):
    if mime_type not in {"image/jpeg", "image/png"} or not data or len(data) > 2 * 1024 * 1024:
        raise YouTubeError("Thumbnail must be JPEG or PNG and no larger than 2 MiB.", status=422)
    dimensions = _image_dimensions(data, mime_type)
    if not dimensions:
        raise YouTubeError("Thumbnail image is malformed.", status=422)
    width, height = dimensions
    if width < 640 or height < 360 or width > 3840 or height > 2160 or not 1.6 <= width / height <= 1.9:
        raise YouTubeError("Thumbnail must be at least 640×360 and use a landscape 16:9-like aspect ratio.", status=422)
    with connect() as conn:
        content = _load_content(conn, content_type, content_id)
        if content is None:
            raise YouTubeError("Publishing content not found.", status=404)
    render_path, _metadata, _digest = validate_render(content)
    render_stat = render_path.stat()
    directory = (CLIP_DIR / "publishing-thumbnails").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    extension = ".jpg" if mime_type == "image/jpeg" else ".png"
    path = (directory / f"{content_type}-{content_id}{extension}").resolve()
    if path.parent != directory:
        raise YouTubeError("Unsafe thumbnail storage path.", status=500)
    path.write_bytes(data)
    with connect() as conn:
        conn.execute(
            "INSERT INTO publishing_thumbnails(content_type,content_id,path,mime_type,size_bytes,width,height,render_size,render_mtime_ns,remote_status,remote_error,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,'local',NULL,?) ON CONFLICT(content_type,content_id) DO UPDATE SET "
            "path=excluded.path,mime_type=excluded.mime_type,size_bytes=excluded.size_bytes,width=excluded.width,height=excluded.height,"
            "render_size=excluded.render_size,render_mtime_ns=excluded.render_mtime_ns,remote_status='local',remote_error=NULL,updated_at=excluded.updated_at",
            (content_type, content_id, str(path), mime_type, len(data), width, height, render_stat.st_size, render_stat.st_mtime_ns, now()),
        )
    return {"content_type": content_type, "content_id": content_id, "width": width, "height": height, "size_bytes": len(data), "remote_status": "local"}


def local_thumbnail(content_type, content_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM publishing_thumbnails WHERE content_type=? AND content_id=?", (content_type, content_id)).fetchone()
    if not row:
        raise YouTubeError("Thumbnail not found.", status=404)
    path = Path(row["path"]).resolve()
    base = (CLIP_DIR / "publishing-thumbnails").resolve()
    if path.parent != base or not path.is_file():
        raise YouTubeError("Thumbnail file is missing or outside managed storage.", status=404)
    with connect() as conn:
        content = _load_content(conn, content_type, content_id)
    if not content:
        raise YouTubeError("Publishing content not found.", status=404)
    render = Path(content["rendered_path"]).resolve()
    stats = render.stat() if render.is_file() else None
    if not stats or stats.st_size != row["render_size"] or stats.st_mtime_ns != row["render_mtime_ns"]:
        raise YouTubeError("Thumbnail belongs to an older render. Upload a thumbnail for the current approved output.", status=409)
    return path, row["mime_type"]


def apply_publication_thumbnail(publication_id):
    publication = _load_publication(publication_id)
    if not publication["video_id"]:
        raise YouTubeError("YouTube video ID is not available; wait for upload to finish.", status=409)
    with connect() as conn:
        content = _load_content(conn, publication["content_type"], publication["clip_id"])
    if content is None:
        raise YouTubeError("Publishing output was deleted.", status=409)
    render_path, _metadata, digest = validate_render(content)
    if str(render_path) != publication["rendered_path"] or digest != publication["rendered_sha256"]:
        raise YouTubeError("This thumbnail is for a different render than the selected YouTube video.", status=409)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM publishing_thumbnails WHERE content_type=? AND content_id=?",
            (publication["content_type"], publication["clip_id"]),
        ).fetchone()
    if not row:
        raise YouTubeError("Upload a local thumbnail before setting it on YouTube.", status=404)
    path, mime_type = local_thumbnail(publication["content_type"], publication["clip_id"])
    data = path.read_bytes()
    with connect() as conn:
        conn.execute(
            "UPDATE publishing_thumbnails SET remote_status='pending',remote_error=NULL,updated_at=? WHERE content_type=? AND content_id=?",
            (now(), publication["content_type"], publication["clip_id"]),
        )
    url = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?" + urllib.parse.urlencode({"videoId": publication["video_id"], "uploadType": "media"})
    try:
        status, _headers, raw = _authorized_http(
            publication["account_id"], "POST", url,
            {"Content-Type": mime_type, "Content-Length": str(len(data))}, data,
        )
        if status < 200 or status >= 300:
            raise _response_error(status, raw)
        payload = json.loads(raw or b"{}")
        items = payload.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict) or not any(
            key in items[0] for key in ("default", "medium", "high", "standard", "maxres")
        ):
            raise YouTubeError("YouTube did not confirm the thumbnail update.")
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                "UPDATE publishing_thumbnails SET remote_status='failed',remote_error=?,updated_at=? WHERE content_type=? AND content_id=?",
                (str(exc)[:500], now(), publication["content_type"], publication["clip_id"]),
            )
        _publication_event(publication_id, "thumbnail_failed", str(exc), {"remote_status": "failed"})
        if isinstance(exc, YouTubeError):
            raise
        raise YouTubeError("Thumbnail upload failed; YouTube did not confirm the change.") from None
    with connect() as conn:
        conn.execute(
            "UPDATE publishing_thumbnails SET remote_status='applied',remote_error=NULL,updated_at=? WHERE content_type=? AND content_id=?",
            (now(), publication["content_type"], publication["clip_id"]),
        )
    _publication_event(publication_id, "thumbnail_applied", "YouTube confirmed custom thumbnail update.")
    return {"applied": True, "thumbnail": payload["items"][0]}


def validate_render(content):
    if content["review_status"] != "approved":
        raise YouTubeError("Output must be Approved before publishing.", status=409)
    if content["status"] != "completed" or not content["rendered_path"]:
        raise YouTubeError("Final render must be complete before publishing.", status=409)
    path = Path(content["rendered_path"]).resolve()
    if path.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or not path.is_file():
        raise YouTubeError("Final MP4 is missing or outside Klipnara managed storage.", status=409)
    try:
        metadata = probe(path)
    except Exception:
        raise YouTubeError("Final MP4 failed media validation.", status=409) from None
    if path.suffix.lower() != ".mp4" or path.stat().st_size <= 0:
        raise YouTubeError("Final output must be a non-empty MP4.", status=409)
    if metadata["video_codec"] != "h264" or metadata["audio_codec"] != "aac":
        raise YouTubeError("Final MP4 must contain H.264 video and AAC audio.", status=409)
    if metadata["height"] < metadata["width"]:
        raise YouTubeError("YouTube Shorts require square or portrait video.", status=409)
    if metadata["duration"] > SHORT_MAX_SECONDS:
        raise YouTubeError("This uploader accepts square/portrait outputs up to 180 seconds.", status=409)
    digest = _file_fingerprint(path)
    if not content.get("reviewed_render_sha256") or content["reviewed_render_sha256"] != digest:
        raise YouTubeError("Approved render changed or lacks review fingerprint. Review the current final MP4 again.", status=409)
    return path, metadata, digest


def validate_short(clip):
    return validate_render(clip)


def _validate_metadata(payload):
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    raw_title, raw_description = payload.get("title", ""), payload.get("description", "")
    raw_hashtags, raw_tags = payload.get("hashtags", []), payload.get("tags", [])
    if not isinstance(raw_title, str) or not isinstance(raw_description, str):
        raise YouTubeError("YouTube title and description must be text.", status=422)
    if not isinstance(raw_hashtags, list) or len(raw_hashtags) > 100 or any(not isinstance(item, str) for item in raw_hashtags):
        raise YouTubeError("Hashtags must be a list of at most 100 text values.", status=422)
    if not isinstance(raw_tags, list) or len(raw_tags) > 100 or any(not isinstance(item, str) for item in raw_tags):
        raise YouTubeError("Tags must be a list of at most 100 text values.", status=422)
    title = raw_title.strip()
    description = raw_description.strip()
    hashtags = []
    seen_hashtags = set()
    for item in raw_hashtags:
        value = item.strip().lstrip("#").strip()
        if not value:
            continue
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char in "#<>" for char in value):
            raise YouTubeError("Hashtags must be one word without spaces or control characters.", status=422)
        normalized = "#" + value
        if normalized.casefold() not in seen_hashtags:
            hashtags.append(normalized)
            seen_hashtags.add(normalized.casefold())
    tags = []
    seen = set()
    for item in raw_tags:
        tag = item.strip()
        key = tag.casefold()
        if any(ord(char) < 32 or ord(char) == 127 for char in tag):
            raise YouTubeError("YouTube tags cannot contain control characters.", status=422)
        if tag and key not in seen:
            tags.append(tag)
            seen.add(key)
    if not title:
        raise YouTubeError("Video title is required.", status=422)
    if any(ord(char) < 32 and char not in "\r\n\t" or ord(char) == 127 for char in title + description) or any(char in "\r\n\t" for char in title):
        raise YouTubeError("YouTube title and description cannot contain control characters.", status=422)
    if "<" in title or ">" in title or "<" in description or ">" in description:
        raise YouTubeError("YouTube title and description cannot contain < or >.", status=422)
    if len(title) > 100:
        raise YouTubeError("YouTube title cannot exceed 100 characters.", status=422)
    effective_description = description
    if hashtags:
        effective_description = f"{description}\n\n{' '.join(hashtags)}" if description else " ".join(hashtags)
    if len(effective_description.encode("utf-8")) > 5000:
        raise YouTubeError("YouTube description cannot exceed 5000 UTF-8 bytes, including hashtags.", status=422)
    tag_length = sum(len(tag) + (2 if " " in tag else 0) for tag in tags) + max(0, len(tags) - 1)
    if tag_length > 500:
        raise YouTubeError("YouTube tags have a 500-character combined limit, including spaces and separators.", status=422)
    return title, description, hashtags, tags, effective_description


def _normalize_publish_at(value, privacy_status):
    if value is None:
        return None
    if privacy_status != "private":
        raise YouTubeError("YouTube native scheduling requires Private privacy.", status=422)
    try:
        scheduled = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise YouTubeError("Schedule time must be a valid ISO 8601 timestamp.", status=422) from None
    if scheduled.tzinfo is None or scheduled.utcoffset() is None:
        raise YouTubeError("Schedule time must include a timezone offset.", status=422)
    scheduled = scheduled.astimezone(timezone.utc).replace(microsecond=0)
    if scheduled <= datetime.now(timezone.utc) + timedelta(minutes=2):
        raise YouTubeError("Schedule must be at least two minutes in the future. Check local timezone and confirm again.", status=422)
    return scheduled.isoformat().replace("+00:00", "Z")


def _insert_upload_job(conn, job_id, publication_id, source_id, clip_id, timestamp):
    if source_id:
        conn.execute(
            "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,?,?,'youtube_upload','queued','queued',NULL,'Menunggu antrean YouTube',?,?,?)",
            (job_id, source_id, clip_id, json.dumps({"publication_id": publication_id}), timestamp, timestamp),
        )
    else:
        conn.execute(
            "INSERT INTO youtube_upload_jobs(id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,'youtube_upload','queued','queued',NULL,'Menunggu antrean YouTube',?,?,?)",
            (job_id, json.dumps({"publication_id": publication_id}), timestamp, timestamp),
        )


def _load_content(conn, content_type, content_id):
    if content_type == "clip":
        row = conn.execute("SELECT * FROM clips WHERE id=?", (content_id,)).fetchone()
        return dict(row) if row else None
    if content_type == "mood_render":
        row = conn.execute(
            "SELECT r.id,r.path AS rendered_path,r.status,r.review_status,r.reviewed_render_sha256,"
            "p.title,p.id AS project_id,r.job_id,j.updated_at AS rendered_at,r.composition_json,r.created_at,r.updated_at FROM mood_renders r "
            "JOIN mood_projects p ON p.id=r.project_id LEFT JOIN mood_jobs j ON j.id=r.job_id WHERE r.id=?",
            (content_id,),
        ).fetchone()
        if row:
            item = dict(row)
            item["id"] = content_id
            return item
    return None


def _production_snapshot(conn, content_type, content_id, content, media):
    snapshot = {
        "version": 1,
        "content_type": content_type,
        "duration": media["duration"],
        "resolution": f"{media['width']}x{media['height']}",
        "render_id": content_id if content_type == "mood_render" else None,
    }
    if content_type == "mood_render":
        composition = json.loads(content.get("composition_json") or "{}")
        visual = composition.get("visual") or {}
        music = composition.get("music") or {}
        background = composition.get("background") or {}
        visual = visual if isinstance(visual, dict) else {}
        music = music if isinstance(music, dict) else {}
        background = background if isinstance(background, dict) else {}
        batch = conn.execute(
            "SELECT b.id,b.type,i.fingerprint FROM video_batch_items i JOIN video_batches b ON b.id=i.batch_id "
            "WHERE i.job_id=? ORDER BY i.updated_at DESC LIMIT 1", (content.get("job_id"),),
        ).fetchone() if content.get("job_id") else None
        source_workflow = "mood_quotes"
        if batch:
            source_workflow = "batch_output"
            snapshot.update({
                "batch_id": batch["id"], "batch_type": batch["type"],
                "batch_fingerprint": batch["fingerprint"], "base_workflow": "mood_quotes",
            })
        snapshot.update({
            "source_workflow": source_workflow,
            "base_workflow": snapshot.get("base_workflow", source_workflow),
            "subtitle_type": "Off",
            "caption_preset": None,
            "visual_preset": visual.get("preset_id"),
            "fps": composition.get("fps"),
            "number_of_scenes": len(composition.get("segments") or []) or 1,
            "audio_settings": {
                "music": {key: music.get(key) for key in ("muted", "volume", "offset", "trim_start", "trim_end", "fade_in", "fade_out", "loop")},
                "background_audio": {"muted": background.get("mute_audio"), "volume": background.get("audio_volume")},
            },
            "rendered_at": content.get("rendered_at") or content.get("created_at"),
        })
        return snapshot

    clip = conn.execute("SELECT edit_json,job_id,created_at FROM clips WHERE id=?", (content_id,)).fetchone()
    parent = conn.execute("SELECT kind,options_json,updated_at FROM jobs WHERE id=?", (clip["job_id"],)).fetchone() if clip else None
    edit = json.loads(clip["edit_json"] or "{}") if clip else {}
    render_job = conn.execute(
        "SELECT id,options_json,updated_at FROM jobs WHERE clip_id=? AND kind='render' AND status='completed' "
        "ORDER BY updated_at DESC LIMIT 1", (content_id,),
    ).fetchone()
    if render_job:
        render_edit = json.loads(render_job["options_json"] or "{}").get("edit")
        if isinstance(render_edit, dict):
            edit = render_edit
    parent_options = json.loads(parent["options_json"] or "{}") if parent else {}
    audio = edit.get("audio") if isinstance(edit.get("audio"), dict) else {}
    batch = conn.execute(
        "SELECT b.id,b.type,i.fingerprint FROM video_batch_items i JOIN video_batches b ON b.id=i.batch_id "
        "WHERE i.clip_id=? ORDER BY i.updated_at DESC LIMIT 1", (content_id,),
    ).fetchone()
    workflow = "unknown"
    if batch:
        workflow = "batch_output"
        snapshot["batch_id"] = batch["id"]
        snapshot["batch_type"] = batch["type"]
        snapshot["batch_fingerprint"] = batch["fingerprint"]
        snapshot["base_workflow"] = "quick_clip" if batch["type"] == "video_clips" else "mood_quotes"
    elif parent and parent["kind"] == "generate":
        workflow = "ai_smart_clip"
    elif parent and parent["kind"] == "quick_clip":
        workflow = "youtube_clip" if parent_options.get("youtube_reference") else "quick_clip"
    snapshot.update({
        "source_workflow": workflow,
        "base_workflow": snapshot.get("base_workflow", workflow),
        "subtitle_type": (
            "Off" if not edit.get("subtitle_enabled", False) or edit.get("subtitle_mode") == "off"
            else {"sentence": "Standard", "phrase": "Phrase by Phrase", "word": "Word by Word", "karaoke": "Karaoke Highlight", "word_pop": "Word Pop"}
                 .get(edit.get("subtitle_caption_mode"), "Standard")
        ),
        "caption_preset": edit.get("subtitle_preset"),
        "visual_preset": edit.get("style"),
        "fps": edit.get("fps"),
        "number_of_scenes": len(edit.get("scenes") or []) or 1,
        "hook_scene_duration": next((scene["source_end"] - scene["source_start"]
                                      for scene in (edit.get("scenes") or [])
                                      if scene.get("role") == "hook" and isinstance(scene.get("source_start"), (int, float))
                                      and isinstance(scene.get("source_end"), (int, float))), None),
        "audio_settings": {key: audio.get(key) for key in (
            "volume", "muted", "fade_in", "fade_out", "normalize", "target_lufs", "limiter",
        )},
        "render_job_id": render_job["id"] if render_job else None,
        "rendered_at": render_job["updated_at"] if render_job else (parent["updated_at"] if parent else clip["created_at"] if clip else None),
    })
    return snapshot


def enqueue_publication(content_type, content_id, payload):
    if content_type not in {"clip", "mood_render"}:
        raise YouTubeError("Unsupported publishing content type.", status=422)
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if payload.get("confirmed") is not True or payload.get("rights_confirmed") is not True:
        raise YouTubeError("Explicit publishing and rights confirmation are required.", status=400, code="confirmation_required")
    title, description, hashtags, tags, effective_description = _validate_metadata(payload)
    privacy_status = payload.get("privacy_status", "private")
    if privacy_status not in {"private", "unlisted", "public"}:
        raise YouTubeError("Choose a valid YouTube privacy setting.", status=422)
    publish_at = _normalize_publish_at(payload.get("publish_at"), privacy_status)
    category_id = str(payload.get("category_id") or "22")
    if category_id not in {"1", "2", "10", "15", "17", "19", "20", "22", "23", "24", "25", "26", "27", "28"}:
        raise YouTubeError("Choose a numeric YouTube category ID.", status=422)
    language = payload.get("video_language")
    if language is not None and (not isinstance(language, str) or len(language) > 35 or not all(part.isalnum() and 1 <= len(part) <= 8 for part in language.split("-"))):
        raise YouTubeError("Video language must use a valid BCP-47 style code.", status=422)
    if type(payload.get("made_for_kids")) is not bool or type(payload.get("contains_synthetic_media")) is not bool:
        raise YouTubeError("Audience and realistic synthetic-content declarations are required.", status=422)
    account_id = payload.get("account_id")
    publication_id, job_id, timestamp = uuid.uuid4().hex, uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        content = _load_content(conn, content_type, content_id)
        if content is None:
            raise YouTubeError("Publishing content not found.", status=404)
        account = conn.execute("SELECT * FROM youtube_accounts WHERE id=?", (account_id,)).fetchone()
        if not account or account["status"] != "connected" or not account["token_blob"]:
            raise YouTubeError("Connect a YouTube account before publishing.", status=409)
        if not account["granted_scopes_json"] or UPLOAD_SCOPE not in json.loads(account["granted_scopes_json"]):
            raise YouTubeError("YouTube upload permission was not granted. Reconnect the account and allow uploads.", status=403, code="youtube_upload_scope_required")
        active_render = conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')",
            (content_id,),
        ).fetchone() if content_type == "clip" else conn.execute(
            "SELECT 1 FROM mood_jobs WHERE render_id=? AND status IN ('queued','preparing','rendering')",
            (content_id,),
        ).fetchone()
        if active_render:
            raise YouTubeError("Wait for the active render before publishing.", status=409)
        path, metadata, digest = validate_render(content)
        existing = conn.execute(
            "SELECT status FROM youtube_publications WHERE account_id=? AND rendered_sha256=? "
            "AND status IN ('pending','uploading','processing','published') ORDER BY created_at DESC LIMIT 1",
            (account_id, digest),
        ).fetchone()
        if existing:
            raise YouTubeError(f"This output already has a {existing['status']} YouTube publication for this account.", status=409)
        failed = conn.execute(
            "SELECT id FROM youtube_publications WHERE account_id=? AND rendered_sha256=? AND status='failed' "
            "ORDER BY created_at DESC LIMIT 1",
            (account_id, digest),
        ).fetchone()
        if failed:
            raise YouTubeError("Retry or reconcile the previous failed publication before creating another.", status=409)
        attribution = _production_snapshot(conn, content_type, content_id, content, metadata)
        conn.execute(
        "INSERT INTO youtube_publications(id,account_id,authorization_id,target_channel_id,clip_id,clip_title,status,title,description,tags_json,"
            "privacy_status,made_for_kids,contains_synthetic_media,content_type,category_id,video_language,hashtags_json,publish_at,"
            "rendered_path,rendered_sha256,file_size,duration,width,height,attribution_json,job_id,created_at,updated_at) "
        "VALUES(" + ",".join("?" for _ in range(28)) + ")",
        (
            publication_id, account_id, account["authorization_id"], account["channel_id"], content_id,
            content["title"], "pending", title, effective_description,
                json.dumps(tags, ensure_ascii=False), privacy_status, int(payload["made_for_kids"]),
                int(payload["contains_synthetic_media"]), content_type, category_id, language,
                json.dumps(hashtags, ensure_ascii=False), publish_at, str(path), digest, path.stat().st_size,
                metadata["duration"], metadata["width"], metadata["height"], json.dumps(attribution),
                job_id, timestamp, timestamp,
            ),
        )
        source_id = content.get("source_id") if content_type == "clip" else None
        _insert_upload_job(conn, job_id, publication_id, source_id, content_id, timestamp)
        conn.execute(
            "INSERT INTO publishing_events(id,content_type,content_id,publication_id,event_type,message,occurred_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, content_type, content_id, publication_id, "publish_requested",
             "Upload accepted into local queue after approval and fingerprint checks.", timestamp),
        )
    return get_publication(publication_id)


def enqueue_publications(content_type, content_id, payload):
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    account_ids = payload.get("account_ids") or ([payload.get("account_id")] if payload.get("account_id") else [])
    if payload.get("confirmed") is not True or payload.get("rights_confirmed") is not True:
        raise YouTubeError("Explicit publishing and rights confirmation are required.", status=400, code="confirmation_required")
    if not account_ids or any(not isinstance(item, str) or not item for item in account_ids):
        raise YouTubeError("Select one or more YouTube channels.", status=422, code="account_required")
    if len(set(account_ids)) != len(account_ids):
        raise YouTubeError("Each YouTube destination can be selected only once.", status=422, code="duplicate_destination")
    metadata_by_account = payload.get("metadata_by_account") or {}
    destinations = []
    for account_id in account_ids:
        override = metadata_by_account.get(account_id)
        metadata_fields = {"title", "description", "tags", "hashtags", "privacy_status", "publish_at", "category_id", "video_language", "made_for_kids", "contains_synthetic_media"}
        request = {**payload, **({key: value for key, value in override.items() if key in metadata_fields} if isinstance(override, dict) else {})}
        request["account_id"] = account_id
        request["confirmed"] = True
        request["rights_confirmed"] = True
        try:
            destinations.append({"account_id": account_id, "status": "queued", "publication": enqueue_publication(content_type, content_id, request)})
        except YouTubeError as exc:
            destinations.append({"account_id": account_id, "status": "failed", "error": {"code": exc.code or "youtube_publish_failed", "message": str(exc)}})
    return {"destinations": destinations}


def _public_publication(row):
    item = dict(row)
    item.pop("rendered_path", None)
    item.pop("rendered_sha256", None)
    item.pop("upload_session_blob", None)
    attribution_json = item.pop("attribution_json", None)
    item["attribution"] = json.loads(attribution_json) if attribution_json else None
    item["tags"] = json.loads(item.pop("tags_json"))
    item["hashtags"] = json.loads(item.pop("hashtags_json", "[]"))
    item["content_id"] = item["clip_id"]
    item["intent_id"] = item["id"]
    item["made_for_kids"] = bool(item["made_for_kids"])
    item["contains_synthetic_media"] = bool(item["contains_synthetic_media"])
    item["upload_started"] = bool(item["upload_started"])
    item["reconciliation_required"] = bool(item["reconciliation_required"])
    item["progress"] = min(1.0, item["uploaded_bytes"] / item["file_size"]) if item["file_size"] else 0
    return item


def get_publication(publication_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT p.*,a.channel_title,COALESCE(j.status,u.status) AS job_status,COALESCE(j.progress,u.progress) AS job_progress "
            "FROM youtube_publications p JOIN youtube_accounts a ON a.id=p.account_id "
            "LEFT JOIN jobs j ON j.id=p.job_id LEFT JOIN youtube_upload_jobs u ON u.id=p.job_id WHERE p.id=?",
            (publication_id,),
        ).fetchone()
    if row is None:
        raise YouTubeError("YouTube publication not found.", status=404)
    return _public_publication(row)


def list_publications():
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.*,a.channel_title,COALESCE(j.status,u.status) AS job_status,COALESCE(j.progress,u.progress) AS job_progress "
            "FROM youtube_publications p JOIN youtube_accounts a ON a.id=p.account_id "
            "LEFT JOIN jobs j ON j.id=p.job_id LEFT JOIN youtube_upload_jobs u ON u.id=p.job_id "
            "ORDER BY p.created_at DESC LIMIT 500"
        ).fetchall()
    return [_public_publication(row) for row in rows]


def cancel_publication(publication_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT p.status,p.upload_started,p.job_id,COALESCE(j.status,u.status) AS job_status,"
            "u.id AS source_less_job FROM youtube_publications p LEFT JOIN jobs j ON j.id=p.job_id "
            "LEFT JOIN youtube_upload_jobs u ON u.id=p.job_id WHERE p.id=?",
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
            table = "youtube_upload_jobs" if row["source_less_job"] else "jobs"
            conn.execute(
                f"UPDATE {table} SET status='cancelled',phase='cancelled',message='Publishing dibatalkan sebelum upload.',updated_at=? WHERE id=? AND status='queued'",
                (now(), row["job_id"]),
            )
        publication = conn.execute("SELECT content_type,clip_id FROM youtube_publications WHERE id=?", (publication_id,)).fetchone()
        conn.execute(
            "INSERT INTO publishing_events(id,content_type,content_id,publication_id,event_type,message,occurred_at) VALUES(?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, publication["content_type"], publication["clip_id"], publication_id,
             "cancelled", "Queued upload cancelled before media transfer.", now()),
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
                "UPDATE youtube_publications SET status='processing',remote_status='processing',next_poll_at=0,last_error=NULL,updated_at=? WHERE id=?",
                (now(), publication_id),
            )
        else:
            account = conn.execute("SELECT status,token_blob FROM youtube_accounts WHERE id=?", (row["account_id"],)).fetchone()
            if not account or account["status"] != "connected" or not account["token_blob"]:
                raise YouTubeError("Reconnect the YouTube account before retrying.", status=409)
            content = _load_content(conn, row["content_type"], row["clip_id"])
            if content is None:
                raise YouTubeError("Original render was deleted. Retry is blocked.", status=409)
            path, metadata, digest = validate_render(content)
            if str(path) != row["rendered_path"] or digest != row["rendered_sha256"]:
                raise YouTubeError("Approved render changed. Approve the current output before publishing again.", status=409)
            if row["publish_at"]:
                _normalize_publish_at(row["publish_at"], row["privacy_status"])
            job_id, timestamp = uuid.uuid4().hex, now()
            conn.execute(
                "UPDATE youtube_publications SET status='pending',remote_status=NULL,attempts=attempts+1,last_error=NULL,job_id=?,updated_at=? WHERE id=?",
                (job_id, timestamp, publication_id),
            )
            source_id = content.get("source_id") if row["content_type"] == "clip" else None
            _insert_upload_job(conn, job_id, publication_id, source_id, row["clip_id"], timestamp)
            conn.execute(
                "INSERT INTO publishing_events(id,content_type,content_id,publication_id,event_type,message,occurred_at) VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, row["content_type"], row["clip_id"], publication_id,
                 "retry_requested", "Safe retry accepted; saved session will be reconciled before sending bytes.", timestamp),
            )
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
        "categoryId": publication["category_id"],
    }
    if publication.get("video_language"):
        snippet["defaultLanguage"] = publication["video_language"]
        snippet["defaultAudioLanguage"] = publication["video_language"]
    tags = json.loads(publication["tags_json"])
    if tags:
        snippet["tags"] = tags
    body = {
        "snippet": snippet,
        "status": {
            "privacyStatus": "private" if publication.get("publish_at") else publication["privacy_status"],
            "selfDeclaredMadeForKids": bool(publication["made_for_kids"]),
            "containsSyntheticMedia": bool(publication["contains_synthetic_media"]),
        },
    }
    if publication.get("publish_at"):
        body["status"]["publishAt"] = publication["publish_at"]
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
            "UPDATE youtube_publications SET status='uploading',remote_status='uploading',updated_at=? WHERE id=? AND status='pending'",
            (now(), publication_id),
        ).rowcount
    if not changed:
        raise PublishCancelled("Job cancelled.")
    _publication_event(publication_id, "upload_started", "Resumable upload started after final render verification.")


def _set_video_id(publication_id, video):
    video_id = video.get("id") if isinstance(video, dict) else None
    if not video_id:
        message = "Upload completed but YouTube omitted video ID. Reconcile in YouTube Studio before retry."
        with connect() as conn:
            conn.execute(
                "UPDATE youtube_publications SET status='failed',reconciliation_required=1,last_error=?,updated_at=? WHERE id=?",
                (message, now(), publication_id),
            )
        _publication_event(publication_id, "reconciliation_required", message, {"reconciliation_required": True})
        raise YouTubeError("Upload response omitted video ID; automatic retry is blocked.")
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_publications SET status='processing',remote_status='uploaded',video_id=?,video_url=?,uploaded_bytes=file_size,"
            "next_poll_at=0,last_error=NULL,updated_at=? WHERE id=?",
            (video_id, f"https://youtu.be/{video_id}", now(), publication_id),
        )
    _publication_event(publication_id, "upload_complete", "YouTube accepted video bytes; remote processing/status verification started.", {"video_id": video_id})


def _fail_publication(publication_id, message, reconciliation_required=False):
    with connect() as conn:
        changed = conn.execute(
            "UPDATE youtube_publications SET status='failed',last_error=?,"
            "reconciliation_required=MAX(reconciliation_required,?),updated_at=? WHERE id=? AND status NOT IN ('published','cancelled')",
            (str(message)[:500], int(reconciliation_required), now(), publication_id),
        ).rowcount
    if changed:
        _publication_event(publication_id, "failed", str(message), {"reconciliation_required": bool(reconciliation_required)})


def _schedule_processing(publication, message=None, *, scheduled=False):
    checks = int(publication.get("processing_checks", 0)) + 1
    delay = min(15 * (2 ** min(checks, 4)), 240)
    next_poll = time.time() + delay
    remote_status = "scheduled" if scheduled else "processing"
    if scheduled and publication.get("publish_at"):
        try:
            scheduled_at = datetime.fromisoformat(publication["publish_at"].replace("Z", "+00:00")).timestamp()
            if scheduled_at > time.time():
                next_poll = max(next_poll, scheduled_at)
        except (TypeError, ValueError):
            pass
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_publications SET status='processing',remote_status=?,processing_checks=?,next_poll_at=?,last_error=?,updated_at=? WHERE id=?",
            (remote_status, checks, next_poll, message, now(), publication["id"]),
        )


def _verify_source_unchanged(publication):
    with connect() as conn:
        content = _load_content(conn, publication["content_type"], publication["clip_id"])
    if content is None:
        raise YouTubeError("Publishing output was deleted before upload.", status=409)
    path, metadata, digest = validate_render(content)
    if (
        str(path) != publication["rendered_path"]
        or digest != publication["rendered_sha256"]
        or content["review_status"] != "approved"
    ):
        raise YouTubeError("Approved output changed before upload. Approve current final render first.", status=409)
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
            account = conn.execute("SELECT status,channel_id,authorization_id FROM youtube_accounts WHERE id=?", (publication["account_id"],)).fetchone()
            authorization = conn.execute("SELECT provider,token_status FROM oauth_authorizations WHERE id=?", (publication["authorization_id"],)).fetchone() if publication.get("authorization_id") else None
        if not account or account["status"] != "connected":
            raise YouTubeError("Reconnect the selected YouTube account before upload.", status=401, code="account_not_connected")
        if publication.get("target_channel_id") and publication["target_channel_id"] != account["channel_id"]:
            raise YouTubeError("Publishing intent account identity no longer matches its selected channel.", status=409, code="account_identity_mismatch")
        if publication.get("authorization_id") and publication["authorization_id"] != account["authorization_id"]:
            raise YouTubeError("Publishing intent authorization no longer matches its selected channel. Reconcile before retry.", status=409, code="authorization_mismatch")
        if publication.get("authorization_id") and (not authorization or authorization["provider"] != "youtube" or authorization["token_status"] != "active"):
            raise YouTubeError("Selected YouTube authorization is unavailable or belongs to another provider.", status=409, code="authorization_mismatch")
        verify_account(publication["account_id"])
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
    scheduled = bool(publication.get("publish_at"))
    scheduled_confirmation_missing = False
    expected_privacy = "private" if scheduled else publication["privacy_status"]
    if status.get("privacyStatus") not in ({"private", "public"} if scheduled else {expected_privacy}):
        _fail_publication(publication["id"], "YouTube returned a different privacy setting than requested.")
        return
    scheduled_for = None
    if scheduled:
        try:
            expected_schedule = datetime.fromisoformat(publication["publish_at"].replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0)
            scheduled_for = datetime.fromisoformat(publication["publish_at"].replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            _fail_publication(publication["id"], "Saved YouTube schedule time is invalid.")
            return
        if status.get("privacyStatus") == "public" and scheduled_for > datetime.now(timezone.utc):
            _fail_publication(publication["id"], "YouTube made the scheduled video public before its requested time.")
            return
        if status.get("publishAt"):
            try:
                remote_schedule = datetime.fromisoformat(status["publishAt"].replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0)
            except (AttributeError, TypeError, ValueError):
                _fail_publication(publication["id"], "YouTube returned an invalid schedule time.")
                return
            if remote_schedule != expected_schedule:
                _fail_publication(publication["id"], "YouTube did not confirm the requested native schedule time.")
                return
        elif status.get("privacyStatus") != "public":
            scheduled_confirmation_missing = True
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
    if scheduled_confirmation_missing:
        previously_scheduled = publication.get("remote_status") == "scheduled"
        _schedule_processing(
            publication, "Waiting for YouTube to confirm the native schedule time.",
            scheduled=previously_scheduled,
        )
        return
    if upload_status == "processed" and processing in {None, "succeeded"}:
        if scheduled and status.get("privacyStatus") != "public":
            if publication.get("remote_status") != "scheduled":
                _publication_event(publication["id"], "scheduled", "YouTube confirmed native private schedule.", {"publish_at": publication.get("publish_at")})
            _schedule_processing(publication, scheduled=True)
            return
        if scheduled and status.get("privacyStatus") == "public" and scheduled_for:
            _publication_event(publication["id"], "schedule_published", "YouTube made scheduled video public after requested time.", {"publish_at": publication.get("publish_at")})
        with connect() as conn:
            conn.execute(
                "UPDATE youtube_publications SET status='published',remote_status='published',uploaded_bytes=file_size,"
                "published_at=?,next_poll_at=NULL,last_error=NULL,updated_at=? WHERE id=?",
                ((video.get("snippet") or {}).get("publishedAt") or now(), now(), publication["id"]),
            )
        _publication_event(publication["id"], "published", "YouTube processing completed and requested visibility was confirmed.", {"privacy_status": status.get("privacyStatus")})
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
