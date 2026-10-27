import base64
import hashlib
import http.client
import json
import os
import re
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .config import CLIP_DIR, LEGACY_CLIP_DIR
from .db import connect
from .jobs import now
from .media import MediaError, probe
from . import youtube


PLATFORMS = {"tiktok", "instagram"}
TIKTOK_SCOPES = ("user.info.basic", "video.upload")
INSTAGRAM_SCOPES = ("pages_show_list", "pages_read_engagement", "instagram_basic", "instagram_content_publish")
META_VERSION = os.environ.get("META_GRAPH_API_VERSION", "v26.0")
if not re.fullmatch(r"v\d+\.\d+", META_VERSION):
    META_VERSION = "v26.0"


class PlatformError(ValueError):
    def __init__(self, message, status=400, code="platform_error", retryable=False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


class PlatformCancelled(PlatformError):
    pass


def _platform(platform):
    if platform not in PLATFORMS:
        raise PlatformError("Unsupported social platform.", 404, "platform_not_found")
    return platform


def _redirect_uri(platform):
    name = "TIKTOK_REDIRECT_URI" if platform == "tiktok" else "META_REDIRECT_URI"
    default = f"http://localhost:8000/api/platforms/{platform}/oauth/callback"
    value = os.environ.get(name, default)
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        return value, "Callback URI is malformed."
    if (parts.scheme not in {"http", "https"} or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parts.username or parts.password or not port or parts.path != f"/api/platforms/{platform}/oauth/callback"
            or parts.query or parts.fragment):
        return value, "Callback must use a loopback host, explicit port, and exact backend callback path."
    if platform == "tiktok" and parts.scheme != "https":
        return value, "TikTok Login Kit requires a registered HTTPS callback; no public tunnel is created by Klipnara."
    return value, None


def _credentials(platform):
    if platform == "tiktok":
        return os.environ.get("TIKTOK_CLIENT_KEY"), os.environ.get("TIKTOK_CLIENT_SECRET")
    return os.environ.get("META_APP_ID"), os.environ.get("META_APP_SECRET")


def _oauth_config(platform):
    callback, redirect_error = _redirect_uri(platform)
    client_id, client_secret = _credentials(platform)
    if platform == "tiktok":
        configured = bool(client_id and client_secret)
        config_id = None
        scopes = list(TIKTOK_SCOPES)
    else:
        config_id = os.environ.get("META_LOGIN_CONFIG_ID")
        configured = bool(client_id and client_secret and config_id)
        scopes = list(INSTAGRAM_SCOPES)
    return {
        "platform": platform, "configured": configured, "oauth_ready": configured and not redirect_error,
        "redirect_uri": callback if not redirect_error else None, "redirect_error": redirect_error,
        "scopes": scopes, "login_configured": bool(config_id) if platform == "instagram" else None,
    }


def _api_json(method, url, *, form=None, data=None, params=None, token=None, timeout=20):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=UTF-8"
    else:
        data = None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise PlatformError("Provider response exceeded the local size limit.", 502, "provider_response_too_large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("unexpected response")
        error = result.get("error")
        if error and not (isinstance(error, dict) and error.get("code") in {"ok", ""}):
            raise PlatformError("Provider rejected the request; check app permissions and account eligibility.", 502, "provider_rejected")
        return result
    except PlatformError:
        raise
    except urllib.error.HTTPError as exc:
        code = "provider_unauthorized" if exc.code == 401 else "provider_http_error"
        raise PlatformError(f"Provider request failed (HTTP {exc.code}).", 502, code,
                            retryable=exc.code in {408, 429, 500, 502, 503, 504}) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        raise PlatformError("Provider is unavailable or returned an invalid response.", 502, "provider_unavailable", retryable=True) from None


def _meta_url(path):
    return f"https://graph.facebook.com/{META_VERSION}/{path.lstrip('/')}"


def _make_state(platform):
    state = secrets.token_urlsafe(32)
    verifier_blob = None
    params = {}
    if platform == "tiktok":
        verifier = secrets.token_urlsafe(64)
        verifier_blob = youtube.encrypt_secret(verifier)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode("ascii").rstrip("=")
        params = {"code_challenge": challenge, "code_challenge_method": "S256"}
    with connect() as conn:
        conn.execute("DELETE FROM platform_oauth_states WHERE expires_at<?", (time.time(),))
        conn.execute(
            "INSERT INTO platform_oauth_states(platform,state_hash,verifier_blob,created_at,expires_at) VALUES(?,?,?,?,?)",
            (platform, hashlib.sha256(state.encode()).hexdigest(), verifier_blob, now(), time.time() + 600),
        )
    return state, params


def oauth_state_cookie_name(platform, state):
    platform = _platform(platform)
    digest = hashlib.sha256((state or "").encode("utf-8")).hexdigest()[:24]
    return f"klipnara_{platform}_state_{digest}"


def oauth_start(platform):
    platform = _platform(platform)
    config = _oauth_config(platform)
    if not config["oauth_ready"]:
        reason = config["redirect_error"] or "Provider OAuth credentials or Login Kit configuration are missing."
        raise PlatformError(reason, 409, "oauth_not_configured")
    callback = config["redirect_uri"]
    state, extra = _make_state(platform)
    if platform == "tiktok":
        client_key, _ = _credentials(platform)
        query = {
            "client_key": client_key, "response_type": "code", "scope": ",".join(TIKTOK_SCOPES),
            "redirect_uri": callback, "state": state, **extra,
        }
        url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(query)
    else:
        app_id, _ = _credentials(platform)
        query = {
            "client_id": app_id, "redirect_uri": callback, "state": state,
            "response_type": "code", "config_id": os.environ["META_LOGIN_CONFIG_ID"],
            "override_default_response_type": "true", "scope": ",".join(INSTAGRAM_SCOPES),
        }
        url = f"https://www.facebook.com/{META_VERSION}/dialog/oauth?" + urllib.parse.urlencode(query)
    return {"url": url, "state": state, "secure_cookie": callback.startswith("https:")}


def consume_oauth_state(platform, state, browser_state):
    platform = _platform(platform)
    if not state or not browser_state or not secrets.compare_digest(state, browser_state):
        raise PlatformError("OAuth state validation failed. Restart connection from Connected Accounts.", 400, "oauth_state_invalid")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT verifier_blob,expires_at FROM platform_oauth_states WHERE platform=? AND state_hash=?",
            (platform, state_hash),
        ).fetchone()
        if not row or row["expires_at"] < time.time():
            conn.execute("DELETE FROM platform_oauth_states WHERE platform=? AND state_hash=?", (platform, state_hash))
            raise PlatformError("OAuth state expired or was already used.", 400, "oauth_state_expired")
        conn.execute("DELETE FROM platform_oauth_states WHERE platform=? AND state_hash=?", (platform, state_hash))
    verifier = youtube.decrypt_secret(row["verifier_blob"]) if row["verifier_blob"] else None
    return verifier


def _store_account(platform, platform_id, display_name, username, token_data, scopes, details,
                   *, authorization_id=None, authorization_tokens=None, provider_subject_id=None):
    access_token = token_data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise PlatformError("Provider did not return an access token.", 502, "oauth_token_missing")
    timestamp = now()
    expires_in = token_data.get("expires_in")
    expires_at = time.time() + int(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else None
    granted = set(scopes)
    with connect() as conn:
        previous = conn.execute(
            "SELECT id,token_blob,scopes_json,authorization_id,is_default FROM platform_accounts WHERE platform=? AND platform_account_id=?",
            (platform, str(platform_id)),
        ).fetchone()
    if previous:
        previous_scopes = set(json.loads(previous["scopes_json"] or "[]"))
        if not previous_scopes.issubset(granted):
            raise PlatformError("Provider returned narrower permissions. Existing authorization remains unchanged; reconnect without removing permissions.", 409, "oauth_scope_downgrade_blocked")
        if previous["token_blob"]:
            try:
                prior_tokens = json.loads(youtube.decrypt_secret(previous["token_blob"]))
            except Exception:
                raise PlatformError("Existing encrypted provider credentials could not be read; no account was changed.", 503, "token_storage_failed") from None
            token_data = {**prior_tokens, **token_data}
        if not authorization_id:
            authorization_id = previous["authorization_id"]
    authorization_id = authorization_id or uuid.uuid4().hex
    try:
        encrypted = youtube.encrypt_secret(json.dumps(token_data))
        grant_data = authorization_tokens or token_data
        encrypted_grant = youtube.encrypt_secret(json.dumps(grant_data))
    except Exception:
        raise PlatformError("Windows DPAPI could not protect the provider token. No connection was saved.", 503, "token_storage_failed") from None
    account_id = previous["id"] if previous else uuid.uuid4().hex
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        default_row = conn.execute(
            "SELECT id FROM platform_accounts WHERE platform=? AND status='connected' AND is_default=1",
            (platform,),
        ).fetchone()
        is_default = int(bool(previous and previous["is_default"]) or not default_row)
        conn.execute(
            "INSERT INTO oauth_authorizations(id,provider,provider_subject_id,credentials_blob,granted_scopes_json,expires_at,token_status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,'active',?,?) ON CONFLICT(id) DO UPDATE SET provider_subject_id=excluded.provider_subject_id,"
            "credentials_blob=excluded.credentials_blob,granted_scopes_json=excluded.granted_scopes_json,expires_at=excluded.expires_at,"
            "token_status='active',updated_at=excluded.updated_at",
            (authorization_id, platform, provider_subject_id, encrypted_grant, json.dumps(sorted(granted)), expires_at, timestamp, timestamp),
        )
        conn.execute(
            "INSERT INTO platform_accounts(id,platform,platform_account_id,display_name,username,status,token_blob,expires_at,scopes_json,details_json,authorization_id,is_default,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'connected',?,?,?,?,?,?,?,?) ON CONFLICT(platform,platform_account_id) DO UPDATE SET "
            "display_name=excluded.display_name,username=excluded.username,status='connected',token_blob=excluded.token_blob,"
            "expires_at=excluded.expires_at,scopes_json=excluded.scopes_json,details_json=excluded.details_json,"
            "authorization_id=excluded.authorization_id,is_default=MAX(platform_accounts.is_default,excluded.is_default),"
            "error_message=NULL,updated_at=excluded.updated_at",
            (account_id, platform, str(platform_id), str(display_name), username, encrypted, expires_at,
             json.dumps(sorted(granted)), json.dumps(details or {}, ensure_ascii=False), authorization_id,
             is_default, timestamp, timestamp),
        )
        row = conn.execute("SELECT id FROM platform_accounts WHERE platform=? AND platform_account_id=?", (platform, str(platform_id))).fetchone()
    return row["id"]


def _account_tokens(account, platform):
    if account["token_blob"]:
        try:
            destination_tokens = json.loads(youtube.decrypt_secret(account["token_blob"]))
        except Exception:
            raise PlatformError("Stored platform authorization could not be read. Reconnect the account.", 503, "token_storage_failed") from None
    else:
        destination_tokens = {}
    if platform == "tiktok" and account["authorization_id"]:
        with connect() as conn:
            grant = conn.execute("SELECT provider,credentials_blob,token_status FROM oauth_authorizations WHERE id=?", (account["authorization_id"],)).fetchone()
        if not grant or grant["provider"] != platform or grant["token_status"] != "active" or not grant["credentials_blob"]:
            raise PlatformError("TikTok authorization is unavailable or belongs to another provider.", 401, "authorization_mismatch")
        try:
            return json.loads(youtube.decrypt_secret(grant["credentials_blob"]))
        except Exception:
            raise PlatformError("Stored TikTok authorization could not be read. Reconnect the account.", 503, "token_storage_failed") from None
    if platform == "instagram" and account["authorization_id"]:
        with connect() as conn:
            grant = conn.execute("SELECT provider,credentials_blob,token_status FROM oauth_authorizations WHERE id=?", (account["authorization_id"],)).fetchone()
        if not grant or grant["provider"] != platform or grant["token_status"] != "active" or not grant["credentials_blob"]:
            raise PlatformError("Meta authorization is unavailable or belongs to another provider.", 401, "authorization_mismatch")
        try:
            destination_tokens.update(json.loads(youtube.decrypt_secret(grant["credentials_blob"])))
        except Exception:
            raise PlatformError("Stored Meta authorization could not be read. Reconnect the account.", 503, "token_storage_failed") from None
    return destination_tokens


def _set_account_status(account_id, status, message):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = conn.execute("SELECT platform,is_default FROM platform_accounts WHERE id=?", (account_id,)).fetchone()
        conn.execute(
            "UPDATE platform_accounts SET status=?,error_message=?,is_default=CASE WHEN ?='connected' THEN is_default ELSE 0 END,updated_at=? WHERE id=? AND status!='disconnected'",
            (status, message[:500], status, now(), account_id),
        )
        if account and account["is_default"] and status != "connected":
            next_account = conn.execute(
                "SELECT id FROM platform_accounts WHERE platform=? AND status='connected' ORDER BY created_at,id LIMIT 1",
                (account["platform"],),
            ).fetchone()
            if next_account:
                conn.execute("UPDATE platform_accounts SET is_default=1 WHERE id=?", (next_account["id"],))


def _required_scopes(platform):
    return set(TIKTOK_SCOPES if platform == "tiktok" else INSTAGRAM_SCOPES)


def _refresh_platform_account(account, tokens, platform):
    client_id, client_secret = _credentials(platform)
    authorization_tokens = None
    try:
        if platform == "tiktok":
            refresh_token = tokens.get("refresh_token")
            if not refresh_token or not client_id or not client_secret:
                raise PlatformError("TikTok authorization expired. Reconnect the account.", 401, "account_expired")
            response = _api_json("POST", "https://open.tiktokapis.com/v2/oauth/token/", form={
                "client_key": client_id, "client_secret": client_secret, "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            })
            fresh = response.get("data") or {}
            if not fresh.get("access_token"):
                raise PlatformError("TikTok refresh response omitted access token.", 502, "token_refresh_failed")
            tokens.update(fresh)
            tokens["refresh_token"] = fresh.get("refresh_token") or refresh_token
            scope = fresh.get("scope")
            prior_scopes = set(json.loads(account["scopes_json"] or "[]"))
            granted = set(scope.split(",")) if isinstance(scope, str) else prior_scopes
            if not prior_scopes.issubset(granted):
                raise PlatformError("TikTok refresh returned narrower permissions. Reconnect before publishing.", 403, "account_scope_insufficient")
            expires_in = fresh.get("expires_in", 86400)
            authorization_tokens = tokens
        else:
            user_token = tokens.get("user_access_token")
            if not user_token or not client_id or not client_secret:
                raise PlatformError("Meta authorization expired. Reconnect the Instagram account.", 401, "account_expired")
            fresh = _api_json("GET", _meta_url("oauth/access_token"), params={
                "grant_type": "fb_exchange_token", "client_id": client_id,
                "client_secret": client_secret, "fb_exchange_token": user_token,
            })
            user_token = fresh.get("access_token")
            if not user_token:
                raise PlatformError("Meta refresh response omitted access token.", 502, "token_refresh_failed")
            pages = _api_json("GET", _meta_url("me/accounts"), params={
                "fields": "id,access_token,instagram_business_account{id}", "access_token": user_token,
            }).get("data", [])
            details = json.loads(account["details_json"] or "{}")
            page = next((item for item in pages if str(item.get("id")) == str(details.get("page_id"))
                         and str((item.get("instagram_business_account") or {}).get("id")) == account["platform_account_id"]), None)
            if not page or not page.get("access_token"):
                raise PlatformError("Meta no longer returns the linked Instagram Professional account. Reconnect it.", 401, "account_expired")
            tokens = {"access_token": page["access_token"], "token_type": "Bearer"}
            authorization_tokens = {"user_access_token": user_token, "token_type": "Bearer"}
            granted = set(json.loads(account["scopes_json"] or "[]"))
            expires_in = fresh.get("expires_in")
        encrypted = youtube.encrypt_secret(json.dumps(tokens))
        encrypted_grant = youtube.encrypt_secret(json.dumps(authorization_tokens or tokens))
        expires_at = time.time() + int(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else None
        with connect() as conn:
            if account.get("authorization_id"):
                conn.execute(
                    "UPDATE oauth_authorizations SET credentials_blob=?,granted_scopes_json=?,expires_at=?,token_status='active',updated_at=? WHERE id=? AND provider=?",
                    (encrypted_grant, json.dumps(sorted(granted)), expires_at, now(), account["authorization_id"], platform),
                )
            conn.execute(
                "UPDATE platform_accounts SET token_blob=?,expires_at=?,status='connected',error_message=NULL,scopes_json=?,updated_at=? WHERE id=?",
                (encrypted, expires_at, json.dumps(sorted(granted)), now(), account["id"]),
            )
        account["expires_at"] = expires_at
        return tokens["access_token"]
    except PlatformError as exc:
        if exc.code in {"account_expired", "provider_unauthorized"}:
            _set_account_status(account["id"], "expired", "Provider rejected authorization. Reconnect the account.")
        raise
    except Exception:
        raise PlatformError("Could not refresh platform authorization. Reconnect the account.", 502, "token_refresh_failed") from None


def _platform_access_token(account_id, platform, *, force_refresh=False):
    with connect() as conn:
        account = conn.execute("SELECT * FROM platform_accounts WHERE id=? AND platform=?", (account_id, platform)).fetchone()
    if not account or account["status"] != "connected" or not account["token_blob"]:
        raise PlatformError("Reconnect this platform account before publishing.", 401, "account_not_connected")
    scopes = set(json.loads(account["scopes_json"] or "[]"))
    if not _required_scopes(platform).issubset(scopes):
        raise PlatformError("This account lacks required publishing permissions. Reconnect and grant requested scopes.", 403, "account_scope_insufficient")
    try:
        tokens = _account_tokens(dict(account), platform)
    except PlatformError:
        _set_account_status(account_id, "error", "Encrypted provider credentials could not be read.")
        raise
    except Exception:
        _set_account_status(account_id, "error", "Encrypted provider credentials could not be read.")
        raise PlatformError("Stored platform authorization could not be read. Reconnect the account.", 503, "token_storage_failed") from None
    expires_at = account["expires_at"]
    if force_refresh or expires_at and expires_at <= time.time() + 60:
        return _refresh_platform_account(dict(account), tokens, platform)
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token:
        _set_account_status(account_id, "error", "Stored provider credentials did not contain an access token.")
        raise PlatformError("Stored platform authorization is incomplete. Reconnect the account.", 503, "token_storage_failed")
    return token


def _authorized_json(account_id, platform, method, url, *, form=None, data=None, params=None):
    token = _platform_access_token(account_id, platform)
    try:
        return _api_json(method, url, form=form, data=data, params=params, token=token)
    except PlatformError as exc:
        if exc.code != "provider_unauthorized":
            raise
    token = _platform_access_token(account_id, platform, force_refresh=True)
    return _api_json(method, url, form=form, data=data, params=params, token=token)


def _verify_destination_identity(account_id, platform):
    platform = _platform(platform)
    with connect() as conn:
        account = conn.execute(
            "SELECT platform_account_id,status,authorization_id FROM platform_accounts WHERE id=? AND platform=?",
            (account_id, platform),
        ).fetchone()
    if not account or account["status"] != "connected":
        raise PlatformError("Selected platform account is no longer connected.", 409, "account_not_connected")
    if platform == "tiktok":
        result = _authorized_json(account_id, platform, "GET", "https://open.tiktokapis.com/v2/user/info/", params={"fields": "open_id"})
        identity = (result.get("data") or {}).get("user") or {}
        matches = str(identity.get("open_id") or "") == account["platform_account_id"]
    else:
        result = _authorized_json(account_id, platform, "GET", _meta_url(account["platform_account_id"]), params={"fields": "id"})
        matches = str(result.get("id") or "") == account["platform_account_id"]
    if not matches:
        _set_account_status(account_id, "error", "Provider identity no longer matches this destination.")
        raise PlatformError("Provider identity does not match the selected destination; upload blocked.", 409, "account_identity_mismatch")


def complete_oauth(platform, code, state, browser_state):
    platform = _platform(platform)
    verifier = consume_oauth_state(platform, state, browser_state)
    callback, redirect_error = _redirect_uri(platform)
    if redirect_error:
        raise PlatformError(redirect_error, 409, "oauth_redirect_invalid")
    client_id, client_secret = _credentials(platform)
    if not code or len(code) > 4096:
        raise PlatformError("Provider did not return a valid authorization code.", 400, "oauth_code_invalid")
    if platform == "tiktok":
        token_response = _api_json("POST", "https://open.tiktokapis.com/v2/oauth/token/", form={
            "client_key": client_id, "client_secret": client_secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": callback, "code_verifier": verifier or "",
        })
        token_data = token_response.get("data") or {}
        scopes = str(token_data.get("scope") or "").split(",")
        access = token_data.get("access_token")
        user_response = _api_json("GET", "https://open.tiktokapis.com/v2/user/info/", params={"fields": "open_id,display_name,avatar_url"}, token=access)
        user = (user_response.get("data") or {}).get("user") or {}
        if not user.get("open_id") or user["open_id"] != token_data.get("open_id"):
            raise PlatformError("TikTok account identity could not be verified against OAuth token.", 409, "account_identity_mismatch")
        _store_account("tiktok", user["open_id"], user.get("display_name") or "TikTok account", None,
                       token_data, scopes, {"avatar_url": user.get("avatar_url")}, provider_subject_id=user["open_id"])
        return {"accounts_added": 1}

    token_response = _api_json("GET", _meta_url("oauth/access_token"), params={
        "client_id": client_id, "client_secret": client_secret, "redirect_uri": callback, "code": code,
    })
    user_token = token_response.get("access_token")
    if not user_token:
        raise PlatformError("Meta did not return an access token.", 502, "oauth_token_missing")
    identity = _api_json("GET", _meta_url("me"), params={"fields": "id"}, token=user_token)
    subject_id = identity.get("id")
    if not isinstance(subject_id, (str, int)) or not str(subject_id):
        raise PlatformError("Meta authorization identity could not be verified.", 502, "account_identity_mismatch")
    permissions = _api_json("GET", _meta_url("me/permissions"), params={"access_token": user_token}).get("data", [])
    scopes = [item.get("permission") for item in permissions if item.get("status") == "granted"]
    pages = _api_json("GET", _meta_url("me/accounts"), params={
        "fields": "id,name,access_token,instagram_business_account{id,username,profile_picture_url}", "access_token": user_token,
    }).get("data", [])
    eligible = []
    for page in pages:
        instagram = page.get("instagram_business_account") or {}
        if instagram.get("id") and page.get("access_token"):
            eligible.append((page, instagram))
    if not eligible:
        raise PlatformError("No linked Instagram Professional account was found. Link one to a Facebook Page and grant required permissions.", 409, "instagram_professional_account_required")
    with connect() as conn:
        existing_grant = conn.execute(
            "SELECT id FROM oauth_authorizations WHERE provider='instagram' AND provider_subject_id=? AND token_status='active' ORDER BY updated_at DESC LIMIT 1",
            (str(subject_id),),
        ).fetchone()
    authorization_id = existing_grant["id"] if existing_grant else uuid.uuid4().hex
    authorization_tokens = {"user_access_token": user_token, "token_type": "Bearer"}
    count = 0
    for page, instagram in eligible:
        page_token = {"access_token": page["access_token"], "token_type": "Bearer"}
        page_token["expires_in"] = token_response.get("expires_in")
        _store_account("instagram", instagram["id"], instagram.get("username") or page.get("name") or "Instagram account",
                       instagram.get("username"), page_token, scopes,
                       {"page_id": page.get("id"), "page_name": page.get("name"), "avatar_url": instagram.get("profile_picture_url"), "login_type": "facebook_login_for_business"},
                       authorization_id=authorization_id, authorization_tokens=authorization_tokens,
                       provider_subject_id=str(subject_id))
        count += 1
    return {"accounts_added": count}


def frontend_accounts_url(platform, result):
    target = os.environ.get("YOUTUBE_FRONTEND_URL", "http://localhost:3000/accounts")
    try:
        parts = urllib.parse.urlsplit(target)
    except ValueError:
        parts = urllib.parse.urlsplit("http://localhost:3000/accounts")
    if parts.scheme not in {"http", "https"} or parts.hostname not in {"localhost", "127.0.0.1"} or parts.username or parts.password:
        target = "http://localhost:3000/accounts"
    separator = "&" if "?" in target else "?"
    return target + separator + urllib.parse.urlencode({platform: result})


def disconnect_account(platform, account_id):
    platform = _platform(platform)
    with connect() as conn:
        row = conn.execute("SELECT * FROM platform_accounts WHERE id=? AND platform=?", (account_id, platform)).fetchone()
        if not row:
            raise PlatformError("Connected platform account not found.", 404, "account_not_found")
        row = dict(row)
        shared_grant = bool(row["authorization_id"] and conn.execute(
            "SELECT 1 FROM platform_accounts WHERE authorization_id=? AND id!=? AND status!='disconnected' LIMIT 1",
            (row["authorization_id"], account_id),
        ).fetchone())
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        queued = conn.execute("SELECT id FROM platform_upload_jobs WHERE account_id=? AND status='queued'", (account_id,)).fetchall()
        for job in queued:
            conn.execute(
                "UPDATE platform_upload_jobs SET status='cancelled',phase='cancelled',last_error='Account disconnected before transfer started.',updated_at=? WHERE id=? AND status='queued'",
                (now(), job["id"]),
            )
            conn.execute(
                "INSERT INTO platform_upload_events(id,upload_job_id,event_type,message,details_json,occurred_at) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, job["id"], "cancelled", "Queued job cancelled because its destination account was disconnected.", "{}", now()),
            )
        conn.execute("UPDATE platform_accounts SET status='disconnected',token_blob=NULL,expires_at=NULL,error_message=NULL,is_default=0,updated_at=? WHERE id=?",
                     (now(), account_id))
        if row["is_default"]:
            next_account = conn.execute(
                "SELECT id FROM platform_accounts WHERE platform=? AND status='connected' ORDER BY created_at,id LIMIT 1",
                (platform,),
            ).fetchone()
            if next_account:
                conn.execute("UPDATE platform_accounts SET is_default=1 WHERE id=?", (next_account["id"],))
    remote_revoked = False
    if row["token_blob"] or row["authorization_id"]:
        try:
            tokens = _account_tokens(row, platform)
            if shared_grant:
                remote_revoked = False
            elif platform == "tiktok" and all(_credentials(platform)):
                client_key, client_secret = _credentials(platform)
                _api_json("POST", "https://open.tiktokapis.com/v2/oauth/revoke/", form={
                    "client_key": client_key, "client_secret": client_secret, "token": tokens["access_token"],
                })
                remote_revoked = True
            elif platform == "instagram" and tokens.get("user_access_token"):
                response = _api_json("DELETE", _meta_url("me/permissions"), params={"access_token": tokens["user_access_token"]})
                remote_revoked = response.get("success") is True
        except Exception:
            remote_revoked = False
    with connect() as conn:
        if row["authorization_id"] and not shared_grant:
            conn.execute("UPDATE oauth_authorizations SET credentials_blob=NULL,token_status='revoked',updated_at=? WHERE id=?",
                         (now(), row["authorization_id"]))
    return {"id": account_id, "status": "disconnected", "remote_revoked": remote_revoked, "shared_authorization_preserved": shared_grant}


def set_default_account(platform, account_id):
    platform = _platform(platform)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = conn.execute("SELECT id,status FROM platform_accounts WHERE id=? AND platform=?", (account_id, platform)).fetchone()
        if not account:
            raise PlatformError("Connected platform account not found.", 404, "account_not_found")
        if account["status"] != "connected":
            raise PlatformError("Reconnect this platform account before making it default.", 409, "account_unavailable")
        conn.execute("UPDATE platform_accounts SET is_default=0 WHERE platform=? AND is_default=1", (platform,))
        conn.execute("UPDATE platform_accounts SET is_default=1,updated_at=? WHERE id=?", (now(), account_id))
    return _safe_account_row(account_id, platform)


def _safe_account_row(account_id, platform):
    with connect() as conn:
        row = conn.execute("SELECT * FROM platform_accounts WHERE id=? AND platform=?", (account_id, platform)).fetchone()
    if not row:
        raise PlatformError("Connected platform account not found.", 404, "account_not_found")
    return _safe_account(row)


def _safe_account(row):
    item = dict(row)
    scopes = json.loads(item.pop("scopes_json") or "[]")
    details = json.loads(item.pop("details_json") or "{}")
    item.pop("token_blob", None)
    item.pop("authorization_id", None)
    item["granted_scopes"] = scopes
    item["details"] = details
    item["is_default"] = bool(item.get("is_default"))
    item["scopes_verified"] = True
    item["upload_ready"] = (
        item["status"] == "connected" and _required_scopes(item["platform"]).issubset(set(scopes))
        and (item["platform"] != "instagram" or details.get("login_type") == "facebook_login_for_business")
    )
    return item


def platform_status():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM platform_accounts ORDER BY created_at DESC").fetchall()
    accounts = {platform: [] for platform in PLATFORMS}
    for row in rows:
        accounts[row["platform"]].append(_safe_account(row))
    youtube_accounts = youtube.list_accounts()
    return {
        "platforms": [
            {
                "id": "youtube", "name": "YouTube Shorts", "configured": youtube.configured(),
                "oauth_ready": youtube.configured(), "callback_uri": youtube.redirect_uri(), "accounts": youtube_accounts,
                "readiness": "existing_uploader" if youtube.configured() and any(a["status"] == "connected" and a["upload_ready"] for a in youtube_accounts) else "connect_required",
                "upload_methods": ["youtube_resumable"], "publish_now": True, "scheduling": "provider_native",
                "manual_export_available": True, "reason": None,
            },
            _social_status("tiktok", "TikTok", accounts["tiktok"]),
            _social_status("instagram", "Instagram Reels", accounts["instagram"]),
        ]
    }


def _social_status(platform, name, accounts):
    config = _oauth_config(platform)
    callback = config["redirect_uri"] or "http://localhost:8000"
    parts = urllib.parse.urlsplit(callback)
    upload_accounts = [item for item in accounts if item["upload_ready"]]
    authorized = bool(upload_accounts)
    if platform == "tiktok":
        integration = "inbox_upload_conditional" if authorized else "oauth_manual_only"
        reason = (
            "Authorized TikTok Inbox transfer is available for selected account; creator must finish in TikTok. This does not publish automatically."
            if authorized else "OAuth can verify accounts. Grant user.info.basic and video.upload before Inbox transfer is enabled; manual export remains available."
        )
        restrictions = ["Direct Post remains disabled; no video.publish requested. App audit and creator eligibility are not inferred.", "Inbox transfer is not Published; creator must finish the post in TikTok."]
    else:
        integration = "resumable_publish_conditional" if authorized else "oauth_manual_only"
        reason = (
            "Facebook Login for Business account and required scopes verified; local resumable upload can publish Reels. Provider app review, Page authorization, and current account eligibility remain provider-controlled."
            if authorized else "OAuth can verify linked Instagram Professional accounts. Grant required Facebook Login for Business permissions before API upload is enabled; manual export remains available."
        )
        restrictions = ["Requires linked Instagram Professional account and approved permissions/Page publishing authorization.", "Local resumable flow is Facebook Login for Business only; Instagram Login video_url flow is not enabled."]
    return {
        **config, "id": platform, "name": name, "accounts": accounts,
        "oauth_start_url": f"{parts.scheme}://{parts.netloc}/api/platforms/{platform}/oauth/start",
        "readiness": "conditional" if authorized else "manual_only", "integration_status": integration,
        "authorized_account": authorized,
        "upload_methods": (["tiktok_inbox", "manual_export"] if platform == "tiktok" else ["instagram_resumable", "manual_export"]) if authorized else ["manual_export"],
        "publish_now": authorized and platform == "instagram",
        "scheduling": "unsupported", "status_verification": authorized,
        "manual_export_available": True, "reason": reason, "restrictions": restrictions,
        "direct_post_eligible": False if platform == "tiktok" else None,
        "local_file_upload": authorized if platform == "instagram" else None,
    }


def _metadata_defaults(platform):
    return {"caption": "", "hashtags": [], **({"privacy_level": "SELF_ONLY", "disable_comment": False, "disable_duet": False, "disable_stitch": False, "ai_generated": None} if platform == "tiktok" else {"share_to_feed": True, "ai_generated": None})}


def _clean_metadata(platform, payload):
    platform = _platform(platform)
    if not isinstance(payload, dict):
        raise PlatformError("Platform metadata must be an object.", 422, "metadata_invalid")
    allowed = set(_metadata_defaults(platform))
    unknown = set(payload) - allowed
    if unknown:
        raise PlatformError(f"Unsupported {platform} metadata field: {sorted(unknown)[0]}.", 422, "metadata_field_invalid")
    result = {**_metadata_defaults(platform), **payload}
    caption = result.get("caption")
    hashtags = result.get("hashtags")
    if not isinstance(caption, str) or len(caption) > 2200 or any(ord(ch) < 32 and ch not in "\r\n\t" or ord(ch) == 127 for ch in caption):
        raise PlatformError("Caption must be at most 2,200 characters without control characters.", 422, "caption_invalid")
    if not isinstance(hashtags, list) or len(hashtags) > 30:
        raise PlatformError("Use at most 30 hashtags.", 422, "hashtags_invalid")
    if any(not isinstance(item, str) for item in hashtags):
        raise PlatformError("Each hashtag must be text.", 422, "hashtags_invalid")
    normalized, seen = [], set()
    for item in hashtags:
        value = item.strip().lstrip("#").strip()
        if not value:
            continue
        if any(ch.isspace() or ord(ch) < 32 or ch in "#<>" for ch in value):
            raise PlatformError("Each hashtag must be one word without control characters.", 422, "hashtag_invalid")
        if value.casefold() not in seen:
            normalized.append(value)
            seen.add(value.casefold())
    rendered_caption = "\n\n".join(part for part in (caption.strip(), " ".join(f"#{item}" for item in normalized)) if part)
    if len(rendered_caption) > 2200:
        raise PlatformError("Caption plus hashtags cannot exceed 2,200 characters.", 422, "caption_too_long")
    result["caption"], result["hashtags"] = caption.strip(), normalized
    if platform == "tiktok":
        if result["privacy_level"] not in {"SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"}:
            raise PlatformError("Choose a valid TikTok privacy option.", 422, "privacy_invalid")
        for key in ("disable_comment", "disable_duet", "disable_stitch"):
            if not isinstance(result[key], bool):
                raise PlatformError(f"{key} must be true or false.", 422, "metadata_invalid")
    else:
        if not isinstance(result["share_to_feed"], bool):
            raise PlatformError("share_to_feed must be true or false.", 422, "metadata_invalid")
    if result["ai_generated"] is not None and not isinstance(result["ai_generated"], bool):
        raise PlatformError("AI disclosure must be selected or left unset.", 422, "metadata_invalid")
    return result


def get_metadata(content_type, content_id, platform, account_id=None):
    platform = _platform(platform)
    with connect() as conn:
        if youtube._load_content(conn, content_type, content_id) is None:
            raise PlatformError("Publishing content not found.", 404, "content_not_found")
        row = conn.execute(
            "SELECT metadata_json,updated_at FROM platform_metadata_drafts WHERE content_type=? AND content_id=? AND platform=?",
            (content_type, content_id, platform),
        ).fetchone()
        account_row = conn.execute(
            "SELECT metadata_json,updated_at FROM platform_account_metadata_drafts WHERE content_type=? AND content_id=? AND platform=? AND account_id=?",
            (content_type, content_id, platform, account_id),
        ).fetchone() if account_id else None
        if account_id and not conn.execute("SELECT 1 FROM platform_accounts WHERE id=? AND platform=?", (account_id, platform)).fetchone():
            raise PlatformError("Selected platform account was not found.", 404, "account_not_found")
    metadata = {**_metadata_defaults(platform), **(json.loads(row["metadata_json"]) if row else {})}
    if account_row:
        metadata.update(json.loads(account_row["metadata_json"]))
    if account_id:
        metadata["account_id"] = account_id
    return {"content_type": content_type, "content_id": content_id, "platform": platform,
            "metadata": metadata,
            "updated_at": account_row["updated_at"] if account_row else row["updated_at"] if row else None}


def save_metadata(content_type, content_id, platform, payload, account_id=None):
    platform = _platform(platform)
    account_id = account_id or payload.pop("account_id", None)
    metadata = _clean_metadata(platform, payload)
    timestamp = now()
    with connect() as conn:
        if youtube._load_content(conn, content_type, content_id) is None:
            raise PlatformError("Publishing content not found.", 404, "content_not_found")
        if account_id:
            if not conn.execute("SELECT 1 FROM platform_accounts WHERE id=? AND platform=?", (account_id, platform)).fetchone():
                raise PlatformError("Selected platform account was not found.", 404, "account_not_found")
            conn.execute(
                "INSERT INTO platform_account_metadata_drafts(content_type,content_id,platform,account_id,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(content_type,content_id,platform,account_id) DO UPDATE SET metadata_json=excluded.metadata_json,updated_at=excluded.updated_at",
                (content_type, content_id, platform, account_id, json.dumps(metadata, ensure_ascii=False), timestamp, timestamp),
            )
        else:
            conn.execute(
                "INSERT INTO platform_metadata_drafts(content_type,content_id,platform,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(content_type,content_id,platform) DO UPDATE SET metadata_json=excluded.metadata_json,updated_at=excluded.updated_at",
                (content_type, content_id, platform, json.dumps(metadata, ensure_ascii=False), timestamp, timestamp),
            )
    return get_metadata(content_type, content_id, platform, account_id)


def _approved_media(content_type, content_id):
    with connect() as conn:
        content = youtube._load_content(conn, content_type, content_id)
    if not content:
        raise PlatformError("Publishing content not found.", 404, "content_not_found")
    if content.get("status") != "completed" or content.get("review_status") != "approved":
        raise PlatformError("Approve current completed output before platform preparation or upload.", 409, "approval_required")
    try:
        path = Path(content.get("rendered_path") or content.get("path") or "").resolve()
        if path.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or path.suffix.lower() != ".mp4" or not path.is_file() or path.stat().st_size <= 0:
            raise PlatformError("Final MP4 is missing or outside managed output storage.", 409, "media_invalid")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint = digest.hexdigest()
        if not content.get("reviewed_render_sha256") or not secrets.compare_digest(content["reviewed_render_sha256"], fingerprint):
            raise PlatformError("Approved render changed. Review current MP4 again before export.", 409, "fingerprint_mismatch")
        media = probe(path)
    except PlatformError:
        raise
    except (OSError, MediaError, KeyError, ValueError):
        raise PlatformError("Final MP4 failed local media validation.", 409, "media_invalid") from None
    return content, path, fingerprint, media


def _validate_platform_media(platform, path, media):
    size = path.stat().st_size
    frame_rate = media.get("frame_rate")
    if media.get("video_codec") not in {"h264", "hevc"} or media.get("audio_codec") != "aac":
        raise PlatformError("Social API upload requires H.264/HEVC video with AAC audio.", 409, "media_codec_unsupported")
    if frame_rate is None or not 23 <= frame_rate <= 60:
        raise PlatformError("Social API upload requires verified frame rate between 23 and 60 FPS.", 409, "media_frame_rate_unsupported")
    sample_rate, channels = media.get("audio_sample_rate"), media.get("audio_channels")
    if sample_rate is None or sample_rate > 48000 or channels not in {1, 2}:
        raise PlatformError("Social API upload requires mono/stereo AAC audio at 48 kHz or lower.", 409, "media_audio_unsupported")
    width, height = media["width"], media["height"]
    if platform == "tiktok":
        if size > 4 * 1024**3 or not 3 <= media["duration"] <= 600:
            raise PlatformError("TikTok Inbox accepts videos up to 4 GiB and 3–600 seconds.", 409, "media_limits_exceeded")
        if min(width, height) < 360 or max(width, height) > 4096:
            raise PlatformError("TikTok requires both dimensions 360–4096 pixels.", 409, "media_dimensions_unsupported")
    else:
        aspect = width / height
        if size > 300 * 1024**2 or not 3 <= media["duration"] <= 900:
            raise PlatformError("Instagram Reels requires a video up to 300 MB and 3–900 seconds.", 409, "media_limits_exceeded")
        if width > 1920 or not 0.01 <= aspect <= 10:
            raise PlatformError("Instagram Reels dimensions/aspect ratio exceed supported limits.", 409, "media_dimensions_unsupported")
    return size


def _upload_job_event(job_id, event_type, message, details=None):
    with connect() as conn:
        conn.execute(
            "INSERT INTO platform_upload_events(id,upload_job_id,event_type,message,details_json,occurred_at) VALUES(?,?,?,?,?,?)",
            (uuid.uuid4().hex, job_id, event_type, message[:500], json.dumps(details or {}, ensure_ascii=False), now()),
        )


def update_platform_upload(job_id, *, status=None, phase=None, progress=..., uploaded_bytes=None,
                           upload_started=None, remote_id=..., session_blob=..., provider_data=None,
                           next_poll_at=..., last_error=None, published_at=None, attempts=None,
                           processing_checks=None):
    fields, values = [], []
    if status is not None:
        fields.append("status=?"); values.append(status)
    if phase is not None:
        fields.append("phase=?"); values.append(phase)
    if progress is not ...:
        fields.append("progress=?"); values.append(progress)
    if uploaded_bytes is not None:
        fields.append("uploaded_bytes=?"); values.append(uploaded_bytes)
    if upload_started is not None:
        fields.append("upload_started=?"); values.append(int(upload_started))
    if remote_id is not ...:
        fields.append("remote_id=?"); values.append(remote_id)
    if session_blob is not ...:
        fields.append("session_blob=?"); values.append(session_blob)
    if provider_data is not None:
        fields.append("provider_data_json=?"); values.append(json.dumps(provider_data, ensure_ascii=False))
    if next_poll_at is not ...:
        fields.append("next_poll_at=?"); values.append(next_poll_at)
    if last_error is not None:
        fields.append("last_error=?"); values.append(last_error[:500] if last_error else None)
    if published_at is not None:
        fields.append("published_at=?"); values.append(published_at)
    if attempts is not None:
        fields.append("attempts=?"); values.append(attempts)
    if processing_checks is not None:
        fields.append("processing_checks=?"); values.append(processing_checks)
    fields.append("updated_at=?"); values.extend([now(), job_id])
    with connect() as conn:
        conn.execute(f"UPDATE platform_upload_jobs SET {','.join(fields)} WHERE id=?", values)


def _upload_job(job_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM platform_upload_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise PlatformError("Platform upload job not found.", 404, "upload_job_not_found")
    item = dict(row)
    item["metadata"] = json.loads(item.pop("metadata_json"))
    item["provider_data"] = json.loads(item.pop("provider_data_json") or "{}")
    return item


def _approved_upload_media(job):
    _, path, fingerprint, media = _approved_media(job["content_type"], job["content_id"])
    if not secrets.compare_digest(fingerprint, job["media_sha256"]):
        raise PlatformError("Approved output changed after queueing. Review current MP4 before upload.", 409, "fingerprint_mismatch")
    size = _validate_platform_media(job["platform"], path, media)
    return path, media, size


def enqueue_platform_upload(content_type, content_id, platform, payload):
    platform = _platform(platform)
    if payload.get("confirmed") is not True or payload.get("rights_confirmed") is not True:
        raise PlatformError("Explicit upload and platform-specific rights confirmation are required.", 400, "confirmation_required")
    account_id = payload.get("account_id")
    if not isinstance(account_id, str) or not account_id or len(account_id) > 64:
        raise PlatformError("Select a connected platform account.", 422, "account_required")
    content, path, fingerprint, media = _approved_media(content_type, content_id)
    file_size = _validate_platform_media(platform, path, media)
    with connect() as conn:
        account_row = conn.execute("SELECT * FROM platform_accounts WHERE id=? AND platform=?", (account_id, platform)).fetchone()
    if not account_row:
        raise PlatformError("Selected platform account was not found.", 404, "account_not_found")
    account = _safe_account(account_row)
    account["authorization_id"] = account_row["authorization_id"]
    if not account["upload_ready"]:
        raise PlatformError("Selected platform account lacks verified upload scopes or is not connected.", 409, "account_not_upload_ready")
    method = "tiktok_inbox" if platform == "tiktok" else "instagram_resumable"
    saved_metadata = get_metadata(content_type, content_id, platform, account_id)["metadata"]
    saved_metadata.pop("account_id", None)
    metadata_override = payload.get("metadata")
    metadata = _clean_metadata(platform, {**saved_metadata, **(metadata_override if isinstance(metadata_override, dict) else {})})
    metadata.update({"rights_confirmed": True, "media_validation": {
        key: media.get(key) for key in ("duration", "width", "height", "video_codec", "audio_codec", "frame_rate")
    }})
    timestamp = now()
    job_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM platform_upload_jobs WHERE platform=? AND account_id=? AND content_type=? AND content_id=? AND media_sha256=? AND upload_method=?",
            (platform, account_id, content_type, content_id, fingerprint, method),
        ).fetchone()
        if existing:
            if existing["status"] in {"queued", "uploading", "processing", "awaiting_manual_action", "published", "needs_reconciliation"}:
                return _public_upload_job(dict(existing), account["display_name"], duplicate=True)
            raise PlatformError("This output already has a failed/cancelled upload record. Inspect or retry it from Publishing History.", 409, "upload_exists")
        conn.execute(
            "INSERT INTO platform_upload_jobs(id,platform,account_id,target_account_id,authorization_id,confirmed_at,content_type,content_id,media_sha256,metadata_json,file_size,upload_method,status,phase,progress,provider_data_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'queued','queued',0,'{}',?,?)",
            (job_id, platform, account_id, account["platform_account_id"], account["authorization_id"], timestamp,
             content_type, content_id, fingerprint, json.dumps(metadata, ensure_ascii=False), file_size, method, timestamp, timestamp),
        )
    _upload_job_event(job_id, "queued", f"Queued {method}; no provider upload has started.", {"media_sha256": fingerprint})
    return {
        "id": job_id, "platform": platform, "content_type": content_type, "content_id": content_id,
        "status": "queued", "upload_method": method, "upload_started": False, "media_sha256": fingerprint,
        "message": "TikTok Inbox transfer queued; creator action is required before any post." if platform == "tiktok"
                   else "Instagram Reels resumable publishing queued; Published will require provider confirmation.",
    }


def enqueue_platform_uploads(content_type, content_id, platform, payload):
    account_ids = payload.get("account_ids") or ([payload.get("account_id")] if payload.get("account_id") else [])
    if not account_ids or any(not isinstance(item, str) or not item for item in account_ids):
        raise PlatformError("Select one or more connected platform accounts.", 422, "account_required")
    if len(set(account_ids)) != len(account_ids):
        raise PlatformError("Each platform destination can be selected only once.", 422, "duplicate_destination")
    metadata_by_account = payload.get("metadata_by_account") or {}
    destinations = []
    for account_id in account_ids:
        request = {**payload, "account_id": account_id, "metadata": metadata_by_account.get(account_id)}
        try:
            destinations.append({"account_id": account_id, "status": "queued", "job": enqueue_platform_upload(content_type, content_id, platform, request)})
        except PlatformError as exc:
            destinations.append({"account_id": account_id, "status": "failed", "error": {"code": exc.code, "message": str(exc)}})
    return {"platform": platform, "destinations": destinations}


def _stream_file(url, method, path, start, end, headers, cancel, progress_callback, total):
    try:
        parsed = urllib.parse.urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise PlatformError("Provider returned an invalid media upload URL.", 502, "upload_url_invalid") from None
    allowed = host and (host.endswith(".tiktokapis.com") or host == "rupload.facebook.com")
    if parsed.scheme != "https" or not allowed or parsed.username or parsed.password or port not in (None, 443):
        raise PlatformError("Provider returned an unsafe media upload URL.", 502, "upload_url_invalid")
    connection = http.client.HTTPSConnection(host, port or 443, timeout=120, context=ssl.create_default_context())
    sent = 0
    try:
        connection.putrequest(method, urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, "")), skip_accept_encoding=True)
        for name, value in {**headers, "Content-Length": str(end - start), "Connection": "close"}.items():
            connection.putheader(name, str(value))
        connection.endheaders()
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start
            while remaining:
                if cancel.is_set():
                    raise PlatformCancelled("Upload cancelled while bytes may be in flight.", 409, "upload_cancelled")
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise PlatformError("Approved MP4 changed during upload.", 409, "media_changed")
                connection.send(chunk)
                sent += len(chunk)
                remaining -= len(chunk)
                progress_callback(start + sent, total)
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise PlatformError("Provider upload response exceeded the local size limit.", 502, "provider_response_too_large")
        return response.status, dict(response.getheaders()), raw
    except PlatformError:
        raise
    except (OSError, http.client.HTTPException, TimeoutError):
        raise PlatformError("Media transfer was interrupted; provider status must be reconciled before retry.", 502, "upload_interrupted", retryable=True) from None
    finally:
        connection.close()


def _validate_upload_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise PlatformError("TikTok returned an invalid upload URL.", 502, "upload_url_invalid") from None
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".tiktokapis.com") or parsed.username or parsed.password or port not in (None, 443):
        raise PlatformError("TikTok returned an unsafe upload URL.", 502, "upload_url_invalid")
    return url


def _tiktok_init(job, size, cancel):
    chunk_size, chunk_count = _tiktok_chunk_plan(size)
    if cancel.is_set():
        raise PlatformCancelled("Upload cancelled before provider initialization.", 409, "upload_cancelled")
    update_platform_upload(job["id"], phase="initializing", upload_started=True, progress=0, next_poll_at=None)
    result = _authorized_json(job["account_id"], "tiktok", "POST", "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/", data={
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": chunk_count},
    })
    data = result.get("data") or {}
    publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
    if not isinstance(publish_id, str) or not publish_id or len(publish_id) > 64 or not isinstance(upload_url, str) or len(upload_url) > 256:
        raise PlatformError("TikTok returned incomplete Inbox upload information.", 502, "provider_response_invalid", retryable=True)
    _validate_upload_url(upload_url)
    provider_data = {**job["provider_data"], "chunk_size": chunk_size, "chunk_count": chunk_count, "upload_url_expires_at": time.time() + 3600}
    update_platform_upload(job["id"], phase="uploading_file", remote_id=publish_id,
                           session_blob=youtube.encrypt_secret(upload_url), provider_data=provider_data,
                           upload_started=True, uploaded_bytes=0, progress=0, last_error="")
    _upload_job_event(job["id"], "upload_initialized", "TikTok accepted Inbox transfer initialization.", {"publish_id": publish_id})
    return publish_id, upload_url


def _tiktok_chunk_plan(size):
    chunk_size = size if size <= 64 * 1024**2 else 32 * 1024**2
    return chunk_size, max(1, (size + chunk_size - 1) // chunk_size)


def _tiktok_status(job):
    result = _authorized_json(job["account_id"], "tiktok", "POST", "https://open.tiktokapis.com/v2/post/publish/status/fetch/", data={
        "publish_id": job["remote_id"],
    })
    data = result.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        raise PlatformError("TikTok returned an invalid Inbox status.", 502, "provider_response_invalid", retryable=True)
    return data


def _save_tiktok_status(job, data, *, poll=False):
    remote_status = data["status"]
    provider_data = {**job["provider_data"], "last_status": remote_status}
    uploaded = data.get("uploaded_bytes")
    if isinstance(uploaded, int) and 0 <= uploaded <= job["file_size"]:
        update_platform_upload(job["id"], uploaded_bytes=uploaded, provider_data=provider_data)
    if remote_status == "PUBLISH_COMPLETE":
        post_ids = data.get("publicaly_available_post_id") or []
        provider_data["post_ids"] = [str(item) for item in post_ids if isinstance(item, (str, int))][:10]
        update_platform_upload(job["id"], status="published", phase="published", progress=1,
                               provider_data=provider_data, next_poll_at=None, last_error="", published_at=now())
        _upload_job_event(job["id"], "published", "TikTok confirmed creator completed the Inbox post.", {"post_ids": provider_data["post_ids"]})
        return "published"
    if remote_status == "SEND_TO_USER_INBOX":
        checks = int(provider_data.get("inbox_checks", 0)) + (1 if poll else 0)
        provider_data["inbox_checks"] = checks
        next_poll = time.time() + min(86400, 600 * (2 ** min(checks, 7))) if checks < 20 else None
        update_platform_upload(job["id"], status="awaiting_manual_action", phase="awaiting_manual_action",
                               provider_data=provider_data, next_poll_at=next_poll, last_error="", processing_checks=checks)
        if job["status"] != "awaiting_manual_action":
            _upload_job_event(job["id"], "awaiting_manual_action", "TikTok Inbox transfer delivered; creator must review and post in TikTok.")
        return "awaiting_manual_action"
    if remote_status == "FAILED":
        reason = data.get("fail_reason")
        safe_reason = reason if isinstance(reason, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", reason) else "provider_failure"
        provider_data["confirmed_terminal"] = True
        update_platform_upload(job["id"], status="failed", phase="failed", provider_data=provider_data,
                               next_poll_at=None, last_error=f"TikTok confirmed Inbox transfer failed: {safe_reason}.")
        _upload_job_event(job["id"], "failed", f"TikTok confirmed Inbox transfer failed: {safe_reason}.")
        return "failed"
    if remote_status in {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"}:
        checks = int(provider_data.get("processing_checks", 0)) + (1 if poll else 0)
        if checks >= 30:
            update_platform_upload(job["id"], status="needs_reconciliation", phase="processing_timeout",
                                   provider_data=provider_data, next_poll_at=None, processing_checks=checks,
                                   last_error="TikTok transfer remains processing after 30 checks. Reconcile before retry.")
            return "needs_reconciliation"
        provider_data["processing_checks"] = checks
        next_poll = time.time() + min(300, 15 * (2 ** min(checks, 4)))
        update_platform_upload(job["id"], status="processing", phase=remote_status.lower(),
                               provider_data=provider_data, next_poll_at=next_poll, last_error="", processing_checks=checks)
        return "processing"
    update_platform_upload(job["id"], status="needs_reconciliation", phase="unknown_provider_status",
                           provider_data=provider_data, next_poll_at=None,
                           last_error="TikTok returned an unknown status. Check account and provider before retry.")
    return "needs_reconciliation"


def _run_tiktok_upload(job, path, size, cancel, progress_callback):
    upload_url = youtube.decrypt_secret(job["session_blob"]) if job["session_blob"] else None
    if not job["remote_id"]:
        _, upload_url = _tiktok_init(job, size, cancel)
        job = _upload_job(job["id"])
    else:
        status = _tiktok_status(job)
        result = _save_tiktok_status(job, status, poll=False)
        if result != "processing" or status.get("status") != "PROCESSING_UPLOAD":
            return
        job = _upload_job(job["id"])
        upload_url = youtube.decrypt_secret(job["session_blob"]) if job["session_blob"] else None
    if not upload_url:
        raise PlatformError("TikTok upload session URL is missing; reconcile provider status before retry.", 409, "upload_session_missing")
    _validate_upload_url(upload_url)
    if job["provider_data"].get("upload_url_expires_at", 0) < time.time():
        update_platform_upload(job["id"], status="needs_reconciliation", phase="upload_session_expired", next_poll_at=None,
                               last_error="TikTok upload URL expired. Check provider status; automatic re-initialization is blocked.")
        return
    status_data = _tiktok_status(job)
    if status_data.get("status") != "PROCESSING_UPLOAD":
        _save_tiktok_status(job, status_data)
        return
    offset = status_data.get("uploaded_bytes", job["uploaded_bytes"])
    if not isinstance(offset, int) or not 0 <= offset <= size:
        raise PlatformError("TikTok returned out-of-range transfer progress.", 502, "provider_progress_invalid")
    chunk_size = int(job["provider_data"].get("chunk_size") or size)
    if offset != size and offset % chunk_size != 0:
        update_platform_upload(job["id"], status="needs_reconciliation", phase="unaligned_resume_offset",
                               uploaded_bytes=offset, next_poll_at=None,
                               last_error="TikTok reported a non-chunk-aligned offset. Automatic resend blocked.")
        return
    update_platform_upload(job["id"], status="uploading", phase="uploading_file", uploaded_bytes=offset,
                           progress=offset / size, next_poll_at=None)
    progress_callback(offset, size)
    transient = 0
    while offset < size:
        if cancel.is_set():
            raise PlatformCancelled("Upload cancelled while provider may have accepted bytes.", 409, "upload_cancelled")
        chunk_index = offset // chunk_size
        chunk_count = int(job["provider_data"].get("chunk_count") or 1)
        chunk_end = size if chunk_index >= chunk_count - 1 else min(size, offset + chunk_size)
        headers = {"Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{chunk_end - 1}/{size}"}
        try:
            response_status, _, _ = _stream_file(upload_url, "PUT", path, offset, chunk_end, headers, cancel, progress_callback, size)
        except PlatformError as exc:
            if not exc.retryable:
                raise
            reconciled = _tiktok_status(job)
            remote_offset = reconciled.get("uploaded_bytes")
            if not isinstance(remote_offset, int) or not offset <= remote_offset <= size:
                raise PlatformError("TikTok transfer outcome is unknown. Reconcile before retry.", 502, "upload_outcome_unknown") from None
            if remote_offset == offset:
                transient += 1
                if transient > 2:
                    raise PlatformError("TikTok accepted no additional bytes after retries. Reconcile before retry.", 502, "upload_outcome_unknown") from None
                time.sleep(min(2 ** transient, 4))
                continue
            offset = remote_offset
        else:
            expected = 201 if chunk_end == size else 206
            if response_status not in {expected, 200 if chunk_end == size else expected}:
                raise PlatformError(f"TikTok media transfer failed (HTTP {response_status}).", 502, "provider_upload_failed", retryable=response_status >= 500)
            offset = chunk_end
            transient = 0
        update_platform_upload(job["id"], uploaded_bytes=offset, progress=offset / size)
        progress_callback(offset, size)
        if offset != size and offset % chunk_size:
            update_platform_upload(job["id"], status="needs_reconciliation", phase="unaligned_resume_offset",
                                   next_poll_at=None, last_error="TikTok returned non-chunk-aligned transfer progress.")
            return
    _upload_job_event(job["id"], "upload_complete", "TikTok acknowledged all media bytes; checking Inbox status.")
    _save_tiktok_status(_upload_job(job["id"]), _tiktok_status(_upload_job(job["id"])))


def _instagram_status(job):
    result = _authorized_json(job["account_id"], "instagram", "GET", _meta_url(job["remote_id"]),
                              params={"fields": "id,status_code"})
    status = result.get("status_code")
    if not isinstance(status, str):
        raise PlatformError("Meta returned an invalid Instagram container status.", 502, "provider_response_invalid", retryable=True)
    return status


def _instagram_mark_published(job, media_id=None):
    provider_data = {**job["provider_data"]}
    if media_id:
        provider_data["published_media_id"] = str(media_id)
    update_platform_upload(job["id"], status="published", phase="published", progress=1,
                           uploaded_bytes=job["file_size"], provider_data=provider_data,
                           published_at=now(), next_poll_at=None, last_error="")
    _upload_job_event(job["id"], "published", "Instagram confirmed the Reels media publication.",
                      {"media_id": str(media_id) if media_id else None})


def _instagram_publish(job):
    update_platform_upload(job["id"], phase="publishing", status="uploading", next_poll_at=None)
    _upload_job_event(job["id"], "publish_requested", "Container is ready; requested Instagram media publication.")
    result = _authorized_json(job["account_id"], "instagram", "POST",
                              _meta_url(f"{job['target_account_id']}/media_publish"),
                              form={"creation_id": job["remote_id"]})
    media_id = result.get("id")
    if not isinstance(media_id, (str, int)) or not str(media_id):
        raise PlatformError("Meta accepted the publish request without returning a media ID; reconcile before retry.", 502, "publish_outcome_unknown", retryable=True)
    _instagram_mark_published(_upload_job(job["id"]), media_id)


def _save_instagram_status(job, status, *, poll=False):
    provider_data = {**job["provider_data"], "last_status": status}
    if status in {"PUBLISHED", "PUBLISH_COMPLETE"}:
        _instagram_mark_published(job)
        return status
    if status in {"ERROR", "EXPIRED"}:
        provider_data["confirmed_terminal"] = True
        update_platform_upload(job["id"], status="failed", phase="failed", provider_data=provider_data,
                               next_poll_at=None, last_error=f"Instagram container is {status.lower()}; no Published confirmation.")
        _upload_job_event(job["id"], "failed", f"Instagram container is {status.lower()}.")
        return status
    if status == "FINISHED":
        if job["phase"] in {"publishing", "publish_reconciliation"}:
            provider_data["publish_reconciled"] = True
            update_platform_upload(job["id"], status="needs_reconciliation", phase="publish_reconciled",
                                   provider_data=provider_data, next_poll_at=None,
                                   last_error="Meta reports container ready but has not confirmed publication. Retry requires explicit confirmation.")
        else:
            update_platform_upload(job["id"], status="processing", phase="container_ready",
                                   provider_data=provider_data, next_poll_at=time.time(), last_error="")
        return status
    if status == "IN_PROGRESS":
        checks = int(provider_data.get("processing_checks", 0)) + (1 if poll else 0)
        provider_data["processing_checks"] = checks
        publish_reconciliation = job["phase"] in {"publishing", "publish_reconciliation"}
        if checks >= 5:
            update_platform_upload(job["id"], status="needs_reconciliation",
                                   phase="publish_reconciliation" if publish_reconciliation else "processing_timeout",
                                   provider_data=provider_data, next_poll_at=None, processing_checks=checks,
                                   last_error="Instagram container remains in progress after five checks. Reconcile before retry.")
            return status
        update_platform_upload(job["id"], status="processing",
                               phase="publish_reconciliation" if publish_reconciliation else "container_processing",
                               provider_data=provider_data, next_poll_at=time.time() + 60, last_error="", processing_checks=checks)
        return status
    publish_reconciliation = job["phase"] in {"publishing", "publish_reconciliation"}
    update_platform_upload(job["id"], status="needs_reconciliation",
                           phase="publish_reconciliation" if publish_reconciliation else "unknown_provider_status",
                           provider_data=provider_data, next_poll_at=None,
                           last_error="Meta returned an unknown container status. Check provider before retry.")
    return "UNKNOWN"


def _instagram_create_container(job, cancel):
    metadata = job["metadata"]
    caption = "\n\n".join(part for part in (metadata.get("caption", ""),
                                              " ".join(f"#{tag}" for tag in metadata.get("hashtags", []))) if part)
    form = {"media_type": "REELS", "caption": caption,
            "share_to_feed": str(bool(metadata.get("share_to_feed", True))).lower()}
    if metadata.get("ai_generated") is not None:
        form["is_ai_generated"] = str(bool(metadata["ai_generated"])).lower()
    if cancel.is_set():
        raise PlatformCancelled("Upload cancelled before container creation.", 409, "upload_cancelled")
    update_platform_upload(job["id"], phase="creating_container", upload_started=True, progress=0, next_poll_at=None)
    result = _authorized_json(job["account_id"], "instagram", "POST",
                              _meta_url(f"{job['target_account_id']}/media?upload_type=resumable"), form=form)
    container_id = result.get("id")
    if not isinstance(container_id, (str, int)) or not str(container_id):
        raise PlatformError("Meta did not return an Instagram media container ID.", 502, "provider_response_invalid", retryable=True)
    container_id = str(container_id)
    provider_data = {**job["provider_data"], "login_type": "facebook_login_for_business"}
    update_platform_upload(job["id"], remote_id=container_id, phase="media_upload", uploaded_bytes=0,
                           session_blob=None, provider_data=provider_data, upload_started=True)
    _upload_job_event(job["id"], "container_created", "Instagram resumable Reels container created.", {"container_id": container_id})
    return _upload_job(job["id"])


def _run_instagram_upload(job, path, size, cancel, progress_callback):
    if not job["remote_id"]:
        job = _instagram_create_container(job, cancel)
    else:
        status = _instagram_status(job)
        if status in {"PUBLISHED", "PUBLISH_COMPLETE", "ERROR", "EXPIRED"}:
            _save_instagram_status(job, status)
            return
        if status == "FINISHED":
            if job["phase"] != "publishing":
                _save_instagram_status(job, status)
                job = _upload_job(job["id"])
            _instagram_publish(job)
            return
        _save_instagram_status(job, status)
        return
    offset = job["uploaded_bytes"]
    if offset < size:
        token = _platform_access_token(job["account_id"], "instagram")
        url = f"https://rupload.facebook.com/ig-api-upload/{META_VERSION}/{job['remote_id']}"
        headers = {"Authorization": f"OAuth {token}", "offset": str(offset), "file_size": str(size),
                   "Content-Type": "application/octet-stream"}
        update_platform_upload(job["id"], status="uploading", phase="media_upload", upload_started=True,
                               progress=offset / size, next_poll_at=None)
        response_status, _, raw = _stream_file(url, "POST", path, offset, size, headers, cancel, progress_callback, size)
        if response_status < 200 or response_status >= 300:
            raise PlatformError(f"Instagram media transfer failed (HTTP {response_status}).", 502, "provider_upload_failed", retryable=response_status >= 500)
        try:
            response_data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            response_data = {}
        if response_data.get("success") is not True:
            raise PlatformError("Meta did not confirm completion of the resumable media transfer.", 502, "upload_outcome_unknown", retryable=True)
        update_platform_upload(job["id"], uploaded_bytes=size, progress=1, phase="container_processing")
        progress_callback(size, size)
        _upload_job_event(job["id"], "upload_complete", "Meta acknowledged all resumable media bytes.")
    status = _instagram_status(_upload_job(job["id"]))
    job = _upload_job(job["id"])
    result = _save_instagram_status(job, status)
    if result == "FINISHED":
        _instagram_publish(_upload_job(job["id"]))


def run_platform_upload(job_id, cancel, progress_callback):
    job = _upload_job(job_id)
    if job["status"] != "uploading":
        return
    path, _, size = _approved_upload_media(job)
    with connect() as conn:
        account = conn.execute(
            "SELECT platform_account_id,status,authorization_id FROM platform_accounts WHERE id=? AND platform=?",
            (job["account_id"], job["platform"]),
        ).fetchone()
        authorization = conn.execute("SELECT provider,token_status FROM oauth_authorizations WHERE id=?", (job["authorization_id"],)).fetchone() if job.get("authorization_id") else None
    if not account or account["platform_account_id"] != job["target_account_id"]:
        raise PlatformError("Publishing intent identity no longer matches selected provider account.", 409, "account_identity_mismatch")
    if account["status"] != "connected":
        raise PlatformError("Selected platform account disconnected before worker started.", 409, "account_not_connected")
    if job.get("authorization_id") and (not authorization or authorization["provider"] != job["platform"] or authorization["token_status"] != "active" or account["authorization_id"] != job["authorization_id"]):
        raise PlatformError("Publishing intent authorization no longer matches selected account. Reconnect and create a new intent.", 409, "authorization_mismatch")
    _verify_destination_identity(job["account_id"], job["platform"])
    if cancel.is_set():
        raise PlatformCancelled("Upload cancelled before provider transfer.", 409, "upload_cancelled")
    _upload_job_event(job_id, "upload_started", "Platform worker revalidated current approval fingerprint and account scopes.")
    if job["platform"] == "tiktok":
        _run_tiktok_upload(job, path, size, cancel, progress_callback)
    else:
        _run_instagram_upload(job, path, size, cancel, progress_callback)


def fail_platform_upload(job_id, error, *, cancelled=False):
    try:
        job = _upload_job(job_id)
    except PlatformError:
        return
    if job["status"] in {"published", "awaiting_manual_action", "processing", "needs_reconciliation"}:
        return
    message = str(error)[:500] or "Platform upload failed."
    uncertain = bool(job["upload_started"] or job["remote_id"])
    status = "needs_reconciliation" if uncertain else "cancelled" if cancelled else "failed"
    phase = ("publish_reconciliation" if job["platform"] == "instagram" and job["phase"] == "publishing"
             else "reconciliation_required") if status == "needs_reconciliation" else status
    update_platform_upload(job_id, status=status, phase=phase, progress=None, next_poll_at=None,
                           last_error=message)
    _upload_job_event(job_id, status, message, {"remote_id_known": bool(job["remote_id"]), "upload_started": bool(job["upload_started"])})


def next_due_platform_upload():
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM platform_upload_jobs WHERE status IN ('processing','awaiting_manual_action') AND next_poll_at<=? "
            "ORDER BY next_poll_at LIMIT 1", (time.time(),),
        ).fetchone()
    return row["id"] if row else None


def poll_platform_upload(job_id):
    job = _upload_job(job_id)
    if job["status"] not in {"processing", "awaiting_manual_action"}:
        return _public_upload_job(job)
    try:
        if job["platform"] == "tiktok":
            data = _tiktok_status(job)
            status = _save_tiktok_status(job, data, poll=True)
            uploaded = data.get("uploaded_bytes")
            current = _upload_job(job_id)
            if status == "processing" and data["status"] == "PROCESSING_UPLOAD" and isinstance(uploaded, int) and uploaded < current["file_size"]:
                url = youtube.decrypt_secret(current["session_blob"]) if current["session_blob"] else None
                if url and current["provider_data"].get("upload_url_expires_at", 0) > time.time():
                    update_platform_upload(job_id, status="queued", phase="uploading_file", next_poll_at=None,
                                           last_error="TikTok confirmed partial transfer; resuming from provider byte count.")
                    _upload_job_event(job_id, "upload_resumed", "TikTok status confirmed partial transfer offset.", {"uploaded_bytes": uploaded})
        else:
            status = _instagram_status(job)
            was_publishing = job["phase"] in {"publishing", "publish_reconciliation"}
            _save_instagram_status(job, status, poll=True)
            current = _upload_job(job_id)
            if status == "FINISHED" and not was_publishing:
                update_platform_upload(job_id, status="queued", phase="container_ready", next_poll_at=None, last_error="")
                _upload_job_event(job_id, "container_ready", "Instagram confirmed Reels container ready; continuing publication.")
    except PlatformError as exc:
        current = _upload_job(job_id)
        if current["status"] in {"processing", "awaiting_manual_action"}:
            checks = int(current["processing_checks"]) + 1
            delay = min(3600, 60 * (2 ** min(checks, 5)))
            update_platform_upload(job_id, next_poll_at=time.time() + delay, last_error=str(exc), processing_checks=checks)
    return _public_upload_job(_upload_job(job_id))


def reconcile_platform_upload(job_id):
    job = _upload_job(job_id)
    if not job["remote_id"]:
        raise PlatformError("Provider did not return an operation ID. Check the provider app before explicitly retrying.", 409, "remote_id_missing")
    if job["platform"] == "tiktok":
        data = _tiktok_status(job)
        state = _save_tiktok_status(job, data, poll=False)
        current = _upload_job(job_id)
        offset = data.get("uploaded_bytes")
        if state == "processing" and data["status"] == "PROCESSING_UPLOAD" and isinstance(offset, int) and offset < current["file_size"]:
            update_platform_upload(job_id, status="queued", phase="uploading_file", uploaded_bytes=offset,
                                   progress=offset / current["file_size"], next_poll_at=None,
                                   last_error="Provider confirmed resumable offset; continuing upload.")
            _upload_job_event(job_id, "reconciled_resume", "TikTok confirmed upload offset; queued safe resume.", {"uploaded_bytes": offset})
    else:
        state = _instagram_status(job)
        was_publishing = job["phase"] in {"publishing", "publish_reconciliation"}
        _save_instagram_status(job, state)
        if state == "FINISHED" and not was_publishing:
            update_platform_upload(job_id, status="queued", phase="container_ready", next_poll_at=None, last_error="")
            _upload_job_event(job_id, "reconciled_container_ready", "Meta confirmed container is ready; continuing publication.")
    return _public_upload_job(_upload_job(job_id))


def retry_platform_upload(job_id, payload):
    if payload.get("confirmed") is not True or payload.get("rights_confirmed") is not True:
        raise PlatformError("Confirm current platform rights and review possible duplicate risk before retry.", 400, "confirmation_required")
    job = _upload_job(job_id)
    if job["status"] not in {"failed", "cancelled", "needs_reconciliation"}:
        raise PlatformError("Only failed, cancelled, or reconciled jobs can be retried.", 409, "upload_not_retryable")
    provider_data = dict(job["provider_data"])
    reuse_remote = False
    if job["remote_id"]:
        remote_status = provider_data.get("last_status")
        if job["platform"] == "tiktok" and remote_status == "PROCESSING_UPLOAD" and job["session_blob"]:
            reuse_remote = True
        elif job["platform"] == "instagram" and remote_status == "FINISHED" and provider_data.get("publish_reconciled"):
            reuse_remote = True
        elif job["platform"] == "instagram" and remote_status == "IN_PROGRESS" and job["phase"] == "processing_timeout":
            if payload.get("duplicate_risk_confirmed") is not True:
                raise PlatformError("Instagram container remains in progress. Confirm abandonment of this incomplete container before creating a fresh one.", 409, "duplicate_risk_confirmation_required")
            provider_data["abandoned_container_id"] = job["remote_id"]
            provider_data["duplicate_risk_acknowledged_at"] = now()
        elif not provider_data.get("confirmed_terminal") and job["status"] in {"needs_reconciliation", "cancelled", "failed"}:
            raise PlatformError("Check provider status before retry. This operation may already have completed.", 409, "reconciliation_required")
    elif job["upload_started"]:
        if payload.get("duplicate_risk_confirmed") is not True:
            raise PlatformError("Provider may have accepted the request without returning an operation ID. Confirm possible duplicate risk before retry.", 409, "duplicate_risk_confirmation_required")
        provider_data["duplicate_risk_acknowledged_at"] = now()
    if not reuse_remote:
        provider_data = {key: value for key, value in provider_data.items()
                         if key in {"login_type", "abandoned_container_id", "duplicate_risk_acknowledged_at"}}
        remote_id, session_blob, uploaded_bytes, started = None, None, 0, False
        phase = "queued"
    else:
        remote_id, session_blob, uploaded_bytes, started = job["remote_id"], job["session_blob"], job["uploaded_bytes"], True
        phase = "publishing" if job["platform"] == "instagram" and provider_data.get("last_status") == "FINISHED" else "media_upload" if job["platform"] == "instagram" else "uploading_file"
    update_platform_upload(job_id, status="queued", phase=phase, progress=uploaded_bytes / job["file_size"] if job["file_size"] else 0,
                           upload_started=started, remote_id=remote_id, session_blob=session_blob,
                           uploaded_bytes=uploaded_bytes, provider_data=provider_data, next_poll_at=None,
                           attempts=job["attempts"] + 1, last_error="")
    _upload_job_event(job_id, "retry_queued", "User explicitly confirmed platform retry.", {"remote_session_reused": reuse_remote})
    return _public_upload_job(_upload_job(job_id))


def prepare_manual_export(content_type, content_id, platform, payload):
    platform = _platform(platform)
    if payload.get("confirmed") is not True or payload.get("rights_confirmed") is not True:
        raise PlatformError("Explicit export and content-rights confirmation are required.", 400, "confirmation_required")
    content, path, fingerprint, media = _approved_media(content_type, content_id)
    override = payload.get("metadata")
    metadata = _clean_metadata(platform, override) if isinstance(override, dict) else get_metadata(content_type, content_id, platform)["metadata"]
    metadata["rights_confirmed"] = True
    metadata["media_validation"] = {key: media.get(key) for key in ("duration", "width", "height", "video_codec", "audio_codec")}
    timestamp, job_id = now(), uuid.uuid4().hex
    with connect() as conn:
        stale = conn.execute(
            "SELECT id FROM platform_publications WHERE platform=? AND content_type=? AND content_id=? AND media_sha256<>? AND status='prepared_manual'",
            (platform, content_type, content_id, fingerprint),
        ).fetchall()
        for old in stale:
            conn.execute(
                "UPDATE platform_publications SET status='needs_reconciliation',last_error='Approved output changed after this manual export was prepared.',updated_at=? WHERE id=?",
                (timestamp, old["id"]),
            )
            conn.execute(
                "INSERT INTO platform_publishing_events(id,publication_id,event_type,message,details_json,occurred_at) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, old["id"], "fingerprint_changed", "Old manual export invalidated; output changed.", "{}", timestamp),
            )
        existing = conn.execute(
            "SELECT id,status FROM platform_publications WHERE platform=? AND content_type=? AND content_id=? AND media_sha256=?",
            (platform, content_type, content_id, fingerprint),
        ).fetchone()
        if existing and existing["status"] != "prepared_manual":
            conn.execute(
                "UPDATE platform_publications SET metadata_json=?,status='prepared_manual',last_error=NULL,updated_at=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), timestamp, existing["id"]),
            )
            conn.execute(
                "INSERT INTO platform_publishing_events(id,publication_id,event_type,message,details_json,occurred_at) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, existing["id"], "prepared_manual", "Revalidated manual export after current approval and fingerprint checks.", "{}", timestamp),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO platform_publications(id,platform,content_type,content_id,media_sha256,metadata_json,upload_method,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'manual_export','prepared_manual',?,?)",
                (job_id, platform, content_type, content_id, fingerprint, json.dumps(metadata, ensure_ascii=False), timestamp, timestamp),
            )
        row = conn.execute("SELECT * FROM platform_publications WHERE platform=? AND content_type=? AND content_id=? AND media_sha256=?",
                           (platform, content_type, content_id, fingerprint)).fetchone()
        if row["id"] == job_id:
            conn.execute(
                "INSERT INTO platform_publishing_events(id,publication_id,event_type,message,details_json,occurred_at) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, job_id, "prepared_manual", "Prepared for manual posting; no upload or publication occurred.",
                 json.dumps({"fingerprint": fingerprint}, ensure_ascii=False), timestamp),
            )
    return {"id": row["id"], "platform": platform, "content_type": content_type, "content_id": content_id,
            "status": row["status"], "upload_method": row["upload_method"], "media_sha256": fingerprint,
            "caption": "\n\n".join(part for part in (metadata["caption"], " ".join(f"#{tag}" for tag in metadata["hashtags"])) if part),
            "download_url": f"/api/platform-publications/{row['id']}/download",
            "message": "Prepared for Manual Posting. No API upload or publication occurred."}


def manual_export_file(publication_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT platform,content_type,content_id,media_sha256,status,upload_method FROM platform_publications WHERE id=?",
            (publication_id,),
        ).fetchone()
    if not row or row["upload_method"] != "manual_export":
        raise PlatformError("Manual export not found.", 404, "publication_not_found")
    if row["status"] != "prepared_manual":
        raise PlatformError("This export is no longer valid. Prepare the current approved render again.", 409, "export_stale")
    try:
        _, path, fingerprint, _ = _approved_media(row["content_type"], row["content_id"])
    except PlatformError as exc:
        fingerprint = None
        if exc.code not in {"approval_required", "fingerprint_mismatch", "media_invalid", "content_not_found"}:
            raise
    if fingerprint != row["media_sha256"]:
        timestamp = now()
        with connect() as conn:
            conn.execute(
                "UPDATE platform_publications SET status='needs_reconciliation',last_error='Approved output changed or approval expired after export preparation.',updated_at=? WHERE id=? AND status='prepared_manual'",
                (timestamp, publication_id),
            )
            conn.execute(
                "INSERT INTO platform_publishing_events(id,publication_id,event_type,message,details_json,occurred_at) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, publication_id, "fingerprint_changed", "Manual export invalidated; output approval or fingerprint no longer matches.", "{}", timestamp),
            )
        raise PlatformError("Approved output changed after preparation. Review and prepare a new manual export.", 409, "export_stale") from None
    return path


def _public_upload_job(job, account_name=None, *, duplicate=False, events=None):
    item = dict(job)
    metadata = item.pop("metadata", None) or json.loads(item.pop("metadata_json", "{}"))
    provider_data = item.pop("provider_data", None)
    if provider_data is None:
        provider_data = json.loads(item.pop("provider_data_json", "{}") or "{}")
    item.pop("session_blob", None)
    item["metadata"] = metadata
    item["account_name"] = account_name or item.get("account_name")
    item["provider_status"] = provider_data.get("last_status")
    item["duplicate"] = duplicate
    if events is None:
        with connect() as conn:
            events = conn.execute(
                "SELECT id,event_type,message,details_json,occurred_at FROM platform_upload_events WHERE upload_job_id=? ORDER BY occurred_at DESC LIMIT 30",
                (item["id"],),
            ).fetchall()
    item["events"] = []
    for row in events:
        event = dict(row)
        details = event.pop("details", None)
        if details is None:
            details = json.loads(event.pop("details_json", "{}"))
        event["details"] = details
        item["events"].append(event)
    return item


def list_platform_publications():
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.*,a.display_name AS account_name FROM platform_publications p LEFT JOIN platform_accounts a ON a.id=p.account_id ORDER BY p.created_at DESC LIMIT 500"
        ).fetchall()
        upload_rows = conn.execute(
            "SELECT j.*,a.display_name AS account_name FROM platform_upload_jobs j JOIN platform_accounts a ON a.id=j.account_id ORDER BY j.created_at DESC LIMIT 500"
        ).fetchall()
        manual_ids = [row["id"] for row in rows]
        upload_ids = [row["id"] for row in upload_rows]
        manual_events = conn.execute(
            f"SELECT id,publication_id,event_type,message,details_json,occurred_at FROM platform_publishing_events WHERE publication_id IN ({','.join('?' for _ in manual_ids)}) ORDER BY occurred_at DESC"
            if manual_ids else "SELECT id,publication_id,event_type,message,details_json,occurred_at FROM platform_publishing_events WHERE 0",
            manual_ids,
        ).fetchall()
        upload_events = conn.execute(
            f"SELECT id,upload_job_id,event_type,message,details_json,occurred_at FROM platform_upload_events WHERE upload_job_id IN ({','.join('?' for _ in upload_ids)}) ORDER BY occurred_at DESC"
            if upload_ids else "SELECT id,upload_job_id,event_type,message,details_json,occurred_at FROM platform_upload_events WHERE 0",
            upload_ids,
        ).fetchall()
    manual_events_by_id = {}
    for event in manual_events:
        manual_events_by_id.setdefault(event["publication_id"], []).append({
            "id": event["id"], "event_type": event["event_type"], "message": event["message"],
            "details": json.loads(event["details_json"]), "occurred_at": event["occurred_at"],
        })
    upload_events_by_id = {}
    for event in upload_events:
        upload_events_by_id.setdefault(event["upload_job_id"], []).append(event)
    items = [{**{key: value for key, value in dict(row).items() if key != "metadata_json"},
              "metadata": json.loads(row["metadata_json"]), "events": manual_events_by_id.get(row["id"], [])} for row in rows]
    items.extend(_public_upload_job(dict(row), events=upload_events_by_id.get(row["id"], [])) for row in upload_rows)
    return sorted(items, key=lambda item: item["created_at"], reverse=True)[:500]
