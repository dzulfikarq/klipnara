import copy
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict


API_ROOT = "https://api.pexels.com/v1"
DOWNLOAD_HOSTS = {"videos.pexels.com", "player.vimeo.com"}
_CACHE_TTL = 300
_CACHE_LIMIT = 100
_cache = OrderedDict()
_cache_lock = threading.Lock()


class PexelsError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _api_json(path, params=None):
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        raise PexelsError(503, "PEXELS_API_KEY belum dikonfigurasi di backend.")
    url = f"{API_ROOT}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": key, "Accept": "application/json"})
    try:
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=12) as response:
            if response.status != 200:
                raise PexelsError(response.status, f"Pexels API returned HTTP {response.status}.")
            payload = response.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024:
                raise PexelsError(502, "Pexels response exceeded the safe size limit.")
    except urllib.error.HTTPError as exc:
        status = exc.code
        messages = {
            401: "Pexels rejected the backend API key (401).",
            403: "Pexels denied this API request (403).",
            404: "Pexels resource was not found (404).",
            429: "Pexels rate limit reached (429). Wait before retrying.",
        }
        raise PexelsError(status, messages.get(status, f"Pexels API request failed ({status}).")) from None
    except (OSError, TimeoutError, urllib.error.URLError):
        raise PexelsError(504, "Pexels API timed out or could not be reached.") from None
    try:
        result = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PexelsError(502, "Pexels returned invalid JSON.") from None
    if not isinstance(result, dict):
        raise PexelsError(502, "Pexels returned an invalid response.")
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_page_url(value, video_id):
    if not isinstance(value, str):
        return f"https://www.pexels.com/video/{video_id}/"
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return f"https://www.pexels.com/video/{video_id}/"
    if (parsed.scheme == "https" and parsed.hostname in {"www.pexels.com", "pexels.com"}
            and port in (None, 443) and not parsed.username and not parsed.password
            and re.match(r"^/video/", parsed.path)):
        return urllib.parse.urlunsplit(("https", "www.pexels.com", parsed.path, "", ""))
    return f"https://www.pexels.com/video/{video_id}/"


def _safe_profile_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme == "https" and parsed.hostname in {"www.pexels.com", "pexels.com"}
            and port in (None, 443) and not parsed.username and not parsed.password and parsed.path.startswith("/@")):
        return urllib.parse.urlunsplit(("https", "www.pexels.com", parsed.path, "", ""))
    return None


def _safe_preview_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme == "https" and parsed.hostname in {"images.pexels.com", "static-videos.pexels.com"}
            and port in (None, 443) and not parsed.username and not parsed.password and parsed.path not in {"", "/"}):
        return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
    return None


def _safe_media_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https" and parsed.hostname in DOWNLOAD_HOSTS and port in (None, 443)
        and not parsed.username and not parsed.password and not parsed.fragment
        and parsed.path and parsed.path != "/"
    )


def parse_video(video):
    if not isinstance(video, dict) or type(video.get("id")) is not int or video["id"] < 1:
        return None
    user = video.get("user") if isinstance(video.get("user"), dict) else {}
    try:
        duration = int(video.get("duration"))
        width, height = int(video.get("width")), int(video.get("height"))
    except (TypeError, ValueError):
        return None
    if duration < 1 or width < 1 or height < 1:
        return None
    files = []
    raw_files = video.get("video_files")
    if isinstance(raw_files, list):
        for item in raw_files:
            if not isinstance(item, dict) or item.get("file_type") != "video/mp4" or not _safe_media_url(item.get("link")):
                continue
            if item.get("quality") not in {"hd", "sd"}:
                continue
            if type(item.get("id")) is not int or item["id"] < 1:
                continue
            try:
                file_width, file_height = int(item.get("width")), int(item.get("height"))
            except (TypeError, ValueError):
                continue
            if min(file_width, file_height) < 1:
                continue
            files.append({
                "id": item["id"], "quality": item["quality"], "width": file_width,
                "height": file_height, "fps": item.get("fps"), "link": item["link"],
            })
    video_id = str(video["id"])
    return {
        "id": video_id,
        "title": f"Pexels video {video_id}",
        "duration": duration,
        "width": width,
        "height": height,
        "orientation": "portrait" if height > width else "landscape" if width > height else "square",
        "page_url": _safe_page_url(video.get("url"), video_id),
        "preview_url": _safe_preview_url(video.get("image")),
        "creator_name": str(user.get("name") or "")[:160] or None,
        "creator_url": _safe_profile_url(user.get("url")),
        "video_files": files,
    }


def search_videos(query, orientation=None, size=None, page=1, per_page=30, locale="id-ID"):
    params = {"query": query, "page": page, "per_page": per_page, "locale": locale}
    if orientation:
        params["orientation"] = orientation
    if size:
        params["size"] = size
    cache_key = tuple(sorted(params.items()))
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(cache_key)
        if entry and entry[0] > now:
            _cache.move_to_end(cache_key)
            return copy.deepcopy(entry[1])
        if entry:
            del _cache[cache_key]
    payload = _api_json("/videos/search", params)
    raw = payload.get("videos")
    if not isinstance(raw, list):
        raise PexelsError(502, "Pexels response did not contain a video list.")
    videos = [parsed for item in raw if (parsed := parse_video(item))]
    try:
        response = {
            "videos": videos,
            "page": max(1, int(payload.get("page", page))),
            "per_page": max(1, int(payload.get("per_page", per_page))),
            "total_results": max(0, int(payload.get("total_results", len(videos)))),
        }
    except (TypeError, ValueError):
        raise PexelsError(502, "Pexels returned invalid pagination metadata.") from None
    with _cache_lock:
        _cache[cache_key] = (now + _CACHE_TTL, copy.deepcopy(response))
        _cache.move_to_end(cache_key)
        while len(_cache) > _CACHE_LIMIT:
            _cache.popitem(last=False)
    return response


def video_metadata(video_id):
    if not re.fullmatch(r"[1-9][0-9]{0,14}", str(video_id)):
        raise PexelsError(422, "Pexels video ID is invalid.")
    payload = _api_json(f"/videos/videos/{video_id}")
    video = parse_video(payload)
    if not video:
        raise PexelsError(404, "Pexels video metadata is invalid or missing.")
    return video


def video_file(video_id, file_id):
    if not re.fullmatch(r"[1-9][0-9]{0,14}", str(file_id)):
        raise PexelsError(422, "Pexels video file ID is invalid.")
    video = video_metadata(video_id)
    item = next((value for value in video["video_files"] if str(value["id"]) == str(file_id)), None)
    if not item:
        raise PexelsError(404, "Selected Pexels MP4 quality is unavailable.")
    return video, item
