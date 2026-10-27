import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_MAX_URL_LENGTH = 2048
_MAX_METADATA_BYTES = 256 * 1024
_MAX_SAFE_SECONDS = 9_007_199_254_740_991


def _timestamp(value):
    value = value.strip().lower()
    if value.isdigit():
        seconds = int(value)
        return seconds if seconds <= _MAX_SAFE_SECONDS else None
    if ":" in value:
        parts = value.split(":")
        if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
            return None
        numbers = [int(part) for part in parts]
        if numbers[-1] >= 60 or len(numbers) == 3 and numbers[1] >= 60:
            return None
        seconds = numbers[0] * (3600 if len(numbers) == 3 else 60) + (numbers[1] * 60 if len(numbers) == 3 else 0) + numbers[-1]
        return seconds if seconds <= _MAX_SAFE_SECONDS else None
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", value)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if seconds >= 60 or hours and minutes >= 60:
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return total if total <= _MAX_SAFE_SECONDS else None


def parse_youtube_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_URL_LENGTH or any(ord(char) < 32 for char in value):
        raise ValueError("Paste a valid YouTube video URL (maximum 2048 characters).")
    raw = value.strip()
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw):
        raw = "https://" + raw
    try:
        parsed = urllib.parse.urlsplit(raw)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
    except ValueError:
        raise ValueError("YouTube URL is malformed.") from None
    if parsed.scheme.lower() not in {"http", "https"} or hostname not in _YOUTUBE_HOSTS or parsed.username or parsed.password or port is not None:
        raise ValueError("Use a standard YouTube or youtu.be URL; other hosts are not accepted.")

    path = parsed.path.rstrip("/")
    video_id = None
    if hostname == "youtu.be":
        parts = path.split("/")
        video_id = parts[1] if len(parts) == 2 and not parts[0] else None
    elif path == "/watch":
        ids = query.get("v", [])
        video_id = ids[0] if len(ids) == 1 else None
    elif path.startswith("/shorts/"):
        parts = path.split("/")
        video_id = parts[2] if len(parts) == 3 else None
    if not video_id or not _VIDEO_ID.fullmatch(video_id):
        raise ValueError("YouTube video ID is missing or invalid.")

    start_seconds = None
    for key in ("t", "start"):
        values = query.get(key, [])
        if len(values) == 1:
            start_seconds = _timestamp(values[0])
            if start_seconds is not None:
                break
    return {
        "video_id": video_id,
        "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
        "start_seconds": start_seconds,
    }


def _duration_seconds(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value or "")
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if 0 < total <= _MAX_SAFE_SECONDS else None


def _metadata_failure(status, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    error = payload.get("error")
    errors = error.get("errors", []) if isinstance(error, dict) else []
    if not isinstance(errors, list):
        errors = []
    reasons = {
        item.get("reason")
        for item in errors
        if isinstance(item, dict) and isinstance(item.get("reason"), str)
    }
    if status == 429 or reasons.intersection({"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}):
        return {"metadata": None, "metadata_status": "quota_exceeded", "metadata_message": "Metadata quota terbatas; preview YouTube tetap dapat dicoba."}
    if status == 404 or "videoNotFound" in reasons:
        return {"metadata": None, "metadata_status": "unavailable", "metadata_message": "Metadata publik tidak ditemukan; preview tetap dicoba dan video belum dinyatakan tersedia."}
    if status == 403:
        return {"metadata": None, "metadata_status": "api_error", "metadata_message": "YouTube Data API menolak permintaan; preview tetap dapat dicoba."}
    return {"metadata": None, "metadata_status": "api_error", "metadata_message": "Metadata YouTube tidak tersedia saat ini; preview tetap dapat dicoba."}


def _read_payload(response):
    data = response.read(_MAX_METADATA_BYTES + 1)
    if len(data) > _MAX_METADATA_BYTES:
        raise ValueError("YouTube metadata response exceeded size limit.")
    return json.loads(data)


def _thumbnail(snippet):
    thumbnails = snippet.get("thumbnails") or {}
    if not isinstance(thumbnails, dict):
        return None
    for size in ("maxres", "standard", "high", "medium", "default"):
        thumbnail = thumbnails.get(size)
        url = thumbnail.get("url") if isinstance(thumbnail, dict) else None
        try:
            parsed = urllib.parse.urlsplit(url or "")
        except ValueError:
            continue
        if parsed.scheme == "https" and parsed.hostname in {"i.ytimg.com", "img.youtube.com"}:
            return url
    return None


def fetch_youtube_metadata(video_id):
    if not _VIDEO_ID.fullmatch(video_id or ""):
        raise ValueError("YouTube video ID is invalid.")
    api_key = os.environ.get("YOUTUBE_DATA_API_KEY", "").strip()
    if not api_key:
        return {"metadata": None, "metadata_status": "not_configured", "metadata_message": "Metadata judul/channel belum dikonfigurasi; preview tetap dapat digunakan."}

    query = urllib.parse.urlencode({"part": "snippet,contentDetails,status", "id": video_id, "key": api_key})
    request = urllib.request.Request(
        f"https://www.googleapis.com/youtube/v3/videos?{query}",
        headers={"Accept": "application/json", "User-Agent": "Klipnara/2.5"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = _read_payload(response)
    except urllib.error.HTTPError as exc:
        try:
            payload = _read_payload(exc)
        except (ValueError, json.JSONDecodeError, OSError):
            payload = None
        return _metadata_failure(exc.code, payload)
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"metadata": None, "metadata_status": "network_error", "metadata_message": "Tidak dapat menghubungi YouTube Data API; preview tetap dapat dicoba."}
    except (ValueError, json.JSONDecodeError):
        return {"metadata": None, "metadata_status": "api_error", "metadata_message": "Respons metadata YouTube tidak valid; preview tetap dapat dicoba."}

    items = payload.get("items") if isinstance(payload, dict) else None
    item = items[0] if isinstance(items, list) and items else None
    snippet = item.get("snippet") if isinstance(item, dict) else None
    details = item.get("contentDetails") if isinstance(item, dict) else None
    status = item.get("status") if isinstance(item, dict) else None
    if not isinstance(snippet, dict) or not isinstance(details, dict):
        return {"metadata": None, "metadata_status": "unavailable", "metadata_message": "Metadata publik tidak tersedia; video mungkin privat, dihapus, atau dibatasi."}
    return {
        "metadata": {
            "title": str(snippet.get("title") or "")[:200] or None,
            "channel": str(snippet.get("channelTitle") or "")[:200] or None,
            "thumbnail_url": _thumbnail(snippet),
            "duration_seconds": _duration_seconds(details.get("duration")),
            "embeddable": status.get("embeddable") if isinstance(status, dict) and type(status.get("embeddable")) is bool else None,
        },
        "metadata_status": "available",
        "metadata_message": None,
    }
