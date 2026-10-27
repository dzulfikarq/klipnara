import hashlib
import http.client
import json
import math
import os
import shutil
import socket
import ssl
import subprocess
import threading
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import ASSET_DIR, CLIP_DIR, DATA_DIR, LEGACY_CLIP_DIR, LEGACY_SOURCE_DIR, MIN_FREE_BYTES, MOOD_DIR, SOURCE_DIR, WORK_DIR
from .db import connect
from .jobs import now
from .media import MediaError, _PinnedHTTPSConnection, _public_addresses, executable, probe
from . import pexels


router = APIRouter(prefix="/api")
_IMPORTS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pexels-import")
_IMPORT_CANCEL: dict[str, threading.Event] = {}
_IMPORT_LOCK = threading.Lock()
_MAX_IMPORT_BYTES = 512 * 1024**2
_MAX_UPLOAD_BYTES = {"video": 512 * 1024**2, "image": 25 * 1024**2, "audio": 100 * 1024**2}
_MIME_TYPES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
}
_MOOD_TAGS = {"Mellow", "Piano", "Lofi", "Sad", "Happy", "Romantic", "Cinematic", "Motivational", "Calm", "Upbeat"}


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=180)
    favorite: bool | None = None
    artist: str | None = Field(default=None, max_length=160)
    mood_tags: list[str] | None = Field(default=None, max_length=10)
    license_type: str | None = Field(default=None, max_length=100)
    license_notes: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2048)
    attribution_text: str | None = Field(default=None, max_length=500)

    @field_validator("mood_tags")
    @classmethod
    def valid_mood_tags(cls, value):
        if value is not None and any(item not in _MOOD_TAGS for item in value):
            raise ValueError("Mood tag tidak dikenal.")
        return list(dict.fromkeys(value or []))

    @field_validator("source_url")
    @classmethod
    def secure_source_url(cls, value):
        if value is None or not value:
            return value
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError:
            raise ValueError("Source URL HTTPS tidak valid.") from None
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Source URL harus HTTPS.")
        return value


class PexelsImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(pattern=r"^[1-9][0-9]{0,14}$")
    video_file_id: str = Field(pattern=r"^[1-9][0-9]{0,14}$")
    quality: Literal["hd", "sd"]


class PexelsFavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(pattern=r"^[1-9][0-9]{0,14}$")


def _free_space():
    return min(shutil.disk_usage(folder).free for folder in {DATA_DIR, SOURCE_DIR, ASSET_DIR, WORK_DIR, MOOD_DIR, CLIP_DIR})


def _safe_local_path(value, *, allow_assets=True, require_file=True):
    path = Path(value).resolve()
    roots = {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()}
    if allow_assets:
        roots.add(ASSET_DIR.resolve())
    if not any(path != root and path.is_relative_to(root) for root in roots) or (require_file and not path.is_file()):
        raise HTTPException(404, "File asset lokal tidak ditemukan.")
    return path


def _asset_public(row, *, usage=False):
    item = dict(row)
    item.pop("path", None)
    item.pop("sha256", None)
    item["favorite"] = bool(item.get("favorite"))
    item["mood_tags"] = json.loads(item.pop("mood_tags_json", "[]") or "[]")
    item["url"] = f"/api/assets/{item['id']}/file"
    if usage:
        item["drafts"] = _asset_drafts(item)
        item["usage_count"] = len(item["drafts"])
    return item


def _asset_drafts(item):
    with connect() as conn:
        if item.get("source_id"):
            rows = conn.execute(
                "SELECT DISTINCT p.id,p.title FROM mood_assets a JOIN mood_projects p ON p.id=a.project_id WHERE a.source_id=? ORDER BY p.updated_at DESC",
                (item["source_id"],),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT p.id,p.title FROM mood_assets a JOIN mood_projects p ON p.id=a.project_id WHERE a.library_asset_id=? ORDER BY p.updated_at DESC",
                (item["id"],),
            ).fetchall()
    return [dict(row) for row in rows]


def register_source_asset(conn, source_row, *, source="local", provider_asset_id=None, source_url=None,
                          preview_url=None, creator_name=None, creator_url=None, license_reference=None,
                          license_notes=None, attribution_text=None):
    """Register existing source file without copying it."""
    item = dict(source_row)
    conn.execute(
        "INSERT OR IGNORE INTO library_assets(id,kind,source,provider_asset_id,source_url,preview_url,creator_name,creator_url,"
        "license_reference,imported_at,source_id,title,path,mime_type,size_bytes,duration,width,height,sha256,license_notes,"
        "attribution_text,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item["id"], "video", source, provider_asset_id, source_url, preview_url, creator_name, creator_url,
         license_reference, item["created_at"], item["id"], item["name"], item["path"],
         "video/quicktime" if Path(item["path"]).suffix.lower() == ".mov" else "video/mp4",
         item["size_bytes"], item["duration"], item["width"], item["height"], item["sha256"],
         license_notes, attribution_text, item["created_at"]),
    )


def _probe_asset_file(path, kind):
    if kind == "video":
        return probe(path)
    try:
        result = subprocess.run(
            [executable("ffprobe", "FFPROBE_PATH"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raise HTTPException(400, "ffprobe tidak dapat membaca file. Pastikan format didukung dan file tidak rusak.") from None
    streams = payload.get("streams", [])
    stream_type = "audio" if kind == "audio" else "video"
    stream = next((item for item in streams if item.get("codec_type") == stream_type), None)
    if not stream:
        raise HTTPException(400, "File tidak berisi stream media yang sesuai dengan jenis asset.")
    if kind == "image":
        try:
            width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Dimensi gambar tidak valid.") from None
        if min(width, height) < 1 or max(width, height) > 12000 or width * height > 40_000_000:
            raise HTTPException(400, "Dimensi gambar tidak didukung.")
        return {"duration": None, "width": width, "height": height, "video_codec": None, "audio_codec": None}
    try:
        duration = float(payload.get("format", {}).get("duration") or stream.get("duration") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Durasi audio tidak valid.") from None
    if not math.isfinite(duration) or duration <= 0 or duration > 4 * 60 * 60:
        raise HTTPException(400, "Durasi audio harus lebih dari 0 dan maksimal 4 jam.")
    return {"duration": duration, "width": None, "height": None, "video_codec": None, "audio_codec": stream.get("codec_name")}


def register_local_upload(file, kind, *, title=None, artist=None, mood_tags=None, license_type=None,
                          license_notes=None, source_url=None, attribution_text=None):
    safe_name = Path((getattr(file, "filename", None) or "asset").replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    allowed = {
        "video": {".mp4", ".mov"},
        "image": {".jpg", ".jpeg", ".png", ".webp"},
        "audio": {".mp3", ".wav", ".m4a"},
    }
    if kind not in allowed or suffix not in allowed[kind]:
        raise HTTPException(415, "Format file tidak didukung untuk jenis asset ini.")
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    asset_id = uuid.uuid4().hex
    root = SOURCE_DIR if kind == "video" else ASSET_DIR
    temporary = root / f".upload-{asset_id}{suffix}.part"
    final_path = root / f"{asset_id}{suffix}"
    digest, size = hashlib.sha256(), 0
    try:
        with temporary.open("xb") as output:
            while block := file.file.read(1024 * 1024):
                size += len(block)
                if size > _MAX_UPLOAD_BYTES[kind]:
                    raise HTTPException(413, "File melebihi batas ukuran untuk jenis asset ini.")
                if _free_space() < MIN_FREE_BYTES + len(block):
                    raise HTTPException(507, "Sisakan minimal 1 GiB ruang kosong untuk file sementara dan render.")
                digest.update(block)
                output.write(block)
        if not size:
            raise HTTPException(400, "File yang diunggah kosong.")
        metadata = _probe_asset_file(temporary, kind)
        timestamp = now()
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM library_assets WHERE kind=? AND sha256=? ORDER BY created_at LIMIT 1", (kind, digest.hexdigest())
            ).fetchone()
            if existing and Path(existing["path"]).is_file():
                temporary.unlink(missing_ok=True)
                return _asset_public(dict(existing), usage=True)
            os.replace(temporary, final_path)
            if kind == "video":
                conn.execute(
                    "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (asset_id, (title or Path(safe_name).stem)[:180], str(final_path.resolve()), size,
                     metadata["duration"], metadata["width"], metadata["height"], metadata["video_codec"],
                     metadata["audio_codec"], digest.hexdigest(), timestamp),
                )
            conn.execute(
                "INSERT INTO library_assets(id,kind,source,imported_at,source_id,title,path,mime_type,size_bytes,duration,width,height,"
                "sha256,artist,mood_tags_json,license_type,license_notes,source_url,attribution_text,created_at) "
                "VALUES(?,?,'local',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, kind, timestamp, asset_id if kind == "video" else None,
                 (title or Path(safe_name).stem)[:180], str(final_path.resolve()), _MIME_TYPES[suffix], size,
                 metadata["duration"], metadata["width"], metadata["height"], digest.hexdigest(), artist,
                 json.dumps(mood_tags or [], ensure_ascii=False), license_type, license_notes, source_url,
                 attribution_text, timestamp),
            )
            row = conn.execute("SELECT * FROM library_assets WHERE id=?", (asset_id,)).fetchone()
        return _asset_public(dict(row), usage=True)
    except HTTPException:
        temporary.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    except Exception:
        temporary.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise


def _safe_download_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        raise MediaError("Pexels media URL is invalid.") from None
    if (parsed.scheme != "https" or parsed.hostname not in pexels.DOWNLOAD_HOSTS or port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment or not parsed.path or parsed.path == "/"):
        raise MediaError("Pexels media URL host is not allowed.")
    return parsed


class ImportCancelled(Exception):
    pass


def _download_pexels(url, temporary, job_id, cancel_event):
    current = url
    for redirect in range(4):
        parsed = _safe_download_url(current)
        host = parsed.hostname.lower().rstrip(".")
        address = _public_addresses(host)
        connection = _PinnedHTTPSConnection(host, address, timeout=30)
        try:
            request_path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request("GET", request_path, headers={"User-Agent": "Klipnara/2.7", "Accept": "video/mp4,application/octet-stream"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect == 3:
                    raise MediaError("Pexels media redirected too many times.")
                current = urllib.parse.urljoin(current, location)
                _safe_download_url(current)
                continue
            if response.status != 200:
                raise MediaError(f"Pexels media server returned HTTP {response.status}.")
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
            if content_type not in {"video/mp4", "application/octet-stream", "binary/octet-stream"}:
                raise MediaError("Pexels returned an unsupported media format.")
            try:
                total = int(response.getheader("Content-Length")) if response.getheader("Content-Length") else None
            except ValueError:
                raise MediaError("Pexels returned an invalid content length.") from None
            if total is not None and (total <= 0 or total > _MAX_IMPORT_BYTES):
                raise MediaError("Pexels video exceeds the 512 MiB import limit.")
            downloaded = 0
            with temporary.open("xb") as output:
                while block := response.read(1024 * 1024):
                    if cancel_event.is_set():
                        raise ImportCancelled()
                    downloaded += len(block)
                    if downloaded > _MAX_IMPORT_BYTES:
                        raise MediaError("Pexels video exceeds the 512 MiB import limit.")
                    if _free_space() < MIN_FREE_BYTES + len(block):
                        raise MediaError("Sisakan minimal 1 GiB ruang kosong untuk file sementara dan render.")
                    output.write(block)
                    progress = min(0.9, downloaded / total * 0.9) if total else None
                    with connect() as conn:
                        conn.execute(
                            "UPDATE asset_import_jobs SET bytes_downloaded=?,total_bytes=?,progress=?,updated_at=? WHERE id=?",
                            (downloaded, total, progress, now(), job_id),
                        )
            if not downloaded:
                raise MediaError("Pexels returned an empty video file.")
            return downloaded
        except (OSError, http.client.HTTPException, ssl.SSLError, socket.error) as exc:
            temporary.unlink(missing_ok=True)
            raise MediaError(f"Download Pexels gagal ({type(exc).__name__}).") from None
        finally:
            connection.close()
    raise MediaError("Pexels media redirected too many times.")


def _set_import(job_id, *, status=None, phase=None, progress=..., message=None, asset_id=...):
    fields, values = [], []
    for key, value in (("status", status), ("phase", phase), ("progress", progress), ("message", message), ("asset_id", asset_id)):
        if value is not ...:
            fields.append(f"{key}=?")
            values.append(value)
    fields.append("updated_at=?")
    values.append(now())
    values.append(job_id)
    with connect() as conn:
        conn.execute(f"UPDATE asset_import_jobs SET {','.join(fields)} WHERE id=?", values)


def _import_pexels(job_id):
    with _IMPORT_LOCK:
        cancel = _IMPORT_CANCEL.get(job_id) or threading.Event()
        _IMPORT_CANCEL[job_id] = cancel
    temporary_dir = SOURCE_DIR / f".pexels-import-{job_id}"
    temporary = temporary_dir / "video.part"
    final_path = SOURCE_DIR / f"{job_id}.mp4"
    created_final = False
    try:
        with connect() as conn:
            job = conn.execute("SELECT * FROM asset_import_jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            return
        if cancel.is_set() or job["cancel_requested"]:
            raise ImportCancelled()
        temporary_dir.mkdir(parents=True, exist_ok=True)
        _set_import(job_id, status="downloading", phase="metadata", progress=0, message="Memvalidasi pilihan video di Pexels")
        video, selected = pexels.video_file(job["provider_asset_id"], job["video_file_id"])
        if selected["quality"] != job["quality"]:
            raise MediaError("Kualitas video Pexels tidak cocok dengan pilihan.")
        if cancel.is_set():
            raise ImportCancelled()
        _set_import(job_id, phase="downloading", progress=0, message="Mengunduh video pilihan dari Pexels")
        size = _download_pexels(selected["link"], temporary, job_id, cancel)
        if cancel.is_set():
            raise ImportCancelled()
        _set_import(job_id, status="probing", phase="validating", progress=0.92, message="Memvalidasi video dan menyimpan ke library")
        metadata = probe(temporary)
        if metadata["duration"] > 4 * 60 * 60:
            raise MediaError("Video melebihi batas durasi 4 jam.")
        digest = hashlib.sha256()
        with temporary.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        timestamp = now()
        name = f"Pexels {job['provider_asset_id']} - {video['creator_name'] or 'Video'}.mp4"[:180]
        attribution = f"Video by {video['creator_name']} on Pexels" if video["creator_name"] else "Video from Pexels"
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if cancel.is_set() or conn.execute("SELECT cancel_requested FROM asset_import_jobs WHERE id=?", (job_id,)).fetchone()[0]:
                raise ImportCancelled()
            existing = conn.execute(
                "SELECT * FROM library_assets WHERE source='pexels' AND provider_asset_id=?", (job["provider_asset_id"],)
            ).fetchone()
            if existing:
                existing_path = Path(existing["path"])
                if existing_path.is_file():
                    conn.execute(
                        "UPDATE asset_import_jobs SET status='ready',phase='ready',progress=1,asset_id=?,message='Asset Pexels sudah tersedia; tidak diunduh ulang.',updated_at=? WHERE id=?",
                        (existing["id"], timestamp, job_id),
                    )
                    return
                raise MediaError("Pexels asset tercatat tetapi file lokalnya hilang. Hapus record lama sebelum impor ulang.")
            same_file = conn.execute(
                "SELECT * FROM library_assets WHERE kind='video' AND sha256=? ORDER BY created_at LIMIT 1",
                (digest.hexdigest(),),
            ).fetchone()
            if same_file and Path(same_file["path"]).is_file():
                conn.execute(
                    "UPDATE library_assets SET source='pexels',provider_asset_id=COALESCE(provider_asset_id,?),"
                    "source_url=COALESCE(source_url,?),preview_url=COALESCE(preview_url,?),"
                    "creator_name=COALESCE(creator_name,?),creator_url=COALESCE(creator_url,?),"
                    "license_reference=COALESCE(license_reference,?),license_type=COALESCE(license_type,'Pexels License'),"
                    "license_notes=COALESCE(license_notes,?),attribution_text=COALESCE(attribution_text,?) WHERE id=?",
                    (job["provider_asset_id"], video["page_url"], video["preview_url"], video["creator_name"],
                     video["creator_url"], "https://www.pexels.com/license/",
                     "Check license and model/property-release risks for people, logos, and brands.", attribution, same_file["id"]),
                )
                conn.execute(
                    "UPDATE asset_import_jobs SET status='ready',phase='ready',progress=1,bytes_downloaded=?,total_bytes=?,"
                    "asset_id=?,message='File identik sudah tersedia; media tidak disalin ulang.',updated_at=? WHERE id=?",
                    (size, size, same_file["id"], timestamp, job_id),
                )
                return
            try:
                os.link(temporary, final_path)
            except FileExistsError:
                raise MediaError("File tujuan impor sudah ada; job berhenti tanpa menimpa file.") from None
            except OSError as exc:
                raise MediaError(f"Tidak dapat mendaftarkan file impor ({type(exc).__name__}).") from None
            created_final = True
            source_row = {
                "id": job_id, "name": name, "path": str(final_path.resolve()), "size_bytes": size,
                "duration": metadata["duration"], "width": metadata["width"], "height": metadata["height"],
                "video_codec": metadata["video_codec"], "audio_codec": metadata["audio_codec"],
                "sha256": digest.hexdigest(), "created_at": timestamp,
            }
            conn.execute(
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, name, source_row["path"], size, metadata["duration"], metadata["width"], metadata["height"],
                 metadata["video_codec"], metadata["audio_codec"], digest.hexdigest(), timestamp),
            )
            conn.execute(
                "INSERT INTO library_assets(id,kind,source,provider_asset_id,source_url,preview_url,creator_name,creator_url,"
                "license_reference,imported_at,source_id,title,path,mime_type,size_bytes,duration,width,height,sha256,license_type,"
                "license_notes,attribution_text,created_at) VALUES(?,'video','pexels',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, job["provider_asset_id"], video["page_url"], video["preview_url"], video["creator_name"],
                 video["creator_url"], "https://www.pexels.com/license/", timestamp, job_id, name, source_row["path"],
                 "video/mp4", size, metadata["duration"], metadata["width"], metadata["height"], digest.hexdigest(),
                 "Pexels License", "Check license and model/property-release risks for people, logos, and brands.", attribution, timestamp),
            )
            conn.execute(
                "UPDATE asset_import_jobs SET status='ready',phase='ready',progress=1,bytes_downloaded=?,total_bytes=COALESCE(total_bytes,?),"
                "asset_id=?,message='Video valid dan tersedia di Asset Library serta Source Library.',updated_at=? WHERE id=?",
                (size, size, job_id, timestamp, job_id),
            )
    except ImportCancelled:
        _set_import(job_id, status="cancelled", phase="cancelled", progress=None, message="Impor dibatalkan pengguna.")
    except pexels.PexelsError as exc:
        _set_import(job_id, status="failed", phase="failed", progress=None, message=str(exc))
    except (MediaError, HTTPException) as exc:
        _set_import(job_id, status="failed", phase="failed", progress=None, message=str(exc.detail if isinstance(exc, HTTPException) else exc))
    except Exception:
        _set_import(job_id, status="failed", phase="failed", progress=None, message="Impor gagal. Coba lagi; API key dan path internal tidak ditampilkan.")
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        with connect() as conn:
            source = conn.execute("SELECT 1 FROM sources WHERE id=?", (job_id,)).fetchone()
        if created_final and source is None:
            final_path.unlink(missing_ok=True)
        with _IMPORT_LOCK:
            _IMPORT_CANCEL.pop(job_id, None)


def _submit_import(job_id):
    event = threading.Event()
    with _IMPORT_LOCK:
        _IMPORT_CANCEL[job_id] = event
    _IMPORTS.submit(_import_pexels, job_id)


def _pexels_error(exc):
    raise HTTPException(exc.status, str(exc)) from None


@router.get("/assets/stock/search")
def search_stock_videos(
    query: str = Query(min_length=1, max_length=120),
    orientation: Literal["portrait", "landscape", "square"] | None = None,
    size: Literal["small", "medium", "large"] | None = None,
    page: int = Query(default=1, ge=1, le=1000),
    per_page: int = Query(default=30, ge=1, le=80),
    min_duration: int | None = Query(default=None, ge=0, le=14400),
    max_duration: int | None = Query(default=None, ge=1, le=14400),
):
    query = query.strip()
    if not query:
        raise HTTPException(422, "Masukkan kata pencarian.")
    if min_duration is not None and max_duration is not None and min_duration > max_duration:
        raise HTTPException(422, "Batas durasi minimum harus di bawah batas maksimum.")
    try:
        result = pexels.search_videos(query, orientation, size, page, per_page)
    except pexels.PexelsError as exc:
        _pexels_error(exc)
    videos = [video for video in result["videos"]
              if (min_duration is None or video["duration"] >= min_duration)
              and (max_duration is None or video["duration"] <= max_duration)]
    ids = [video["id"] for video in videos]
    favorites, imported = set(), {}
    if ids:
        marks = ",".join("?" for _ in ids)
        with connect() as conn:
            favorites = {row["provider_asset_id"] for row in conn.execute(
                f"SELECT provider_asset_id FROM asset_provider_favorites WHERE provider='pexels' AND provider_asset_id IN ({marks})", ids,
            ).fetchall()}
            imported = {row["provider_asset_id"]: row["id"] for row in conn.execute(
                f"SELECT id,provider_asset_id FROM library_assets WHERE source='pexels' AND provider_asset_id IN ({marks})", ids,
            ).fetchall()}
            imported.update({row["provider_asset_id"]: row["asset_id"] for row in conn.execute(
                f"SELECT provider_asset_id,asset_id FROM asset_import_jobs WHERE status='ready' AND asset_id IS NOT NULL AND provider_asset_id IN ({marks}) ORDER BY updated_at",
                ids,
            ).fetchall()})
    for video in videos:
        video["favorite"] = video["id"] in favorites
        video["imported"] = video["id"] in imported
        video["asset_id"] = imported.get(video["id"])
    return {**result, "videos": videos}


@router.get("/assets/stock/videos/{video_id}")
def get_stock_video(video_id: str):
    try:
        video = pexels.video_metadata(video_id)
    except pexels.PexelsError as exc:
        _pexels_error(exc)
    return video


@router.get("/assets/stock/favorites")
def list_stock_favorites():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM asset_provider_favorites WHERE provider='pexels' ORDER BY created_at DESC").fetchall()
    return [dict(row) | {"favorite": True} for row in rows]


@router.post("/assets/stock/favorites")
def save_stock_favorite(body: PexelsFavoriteRequest):
    try:
        video = pexels.video_metadata(body.video_id)
    except pexels.PexelsError as exc:
        _pexels_error(exc)
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO asset_provider_favorites(provider,provider_asset_id,source_url,preview_url,creator_name,creator_url,"
            "duration,width,height,orientation,created_at) VALUES('pexels',?,?,?,?,?,?,?,?,?,?)",
            (video["id"], video["page_url"], video["preview_url"], video["creator_name"], video["creator_url"],
             video["duration"], video["width"], video["height"], video["orientation"], now()),
        )
        row = conn.execute("SELECT * FROM asset_provider_favorites WHERE provider='pexels' AND provider_asset_id=?", (video["id"],)).fetchone()
    return dict(row) | {"favorite": True}


@router.delete("/assets/stock/favorites/{video_id}")
def delete_stock_favorite(video_id: str):
    with connect() as conn:
        if not conn.execute("DELETE FROM asset_provider_favorites WHERE provider='pexels' AND provider_asset_id=?", (video_id,)).rowcount:
            raise HTTPException(404, "Favorit Pexels tidak ditemukan.")
    return {"deleted": True}


@router.post("/assets/stock/imports")
def create_stock_import(body: PexelsImportRequest):
    if not os.environ.get("PEXELS_API_KEY", "").strip():
        raise HTTPException(503, "PEXELS_API_KEY belum dikonfigurasi di backend.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute("SELECT id FROM asset_import_jobs WHERE status IN ('queued','downloading','probing') LIMIT 1").fetchone()
        existing = conn.execute(
            "SELECT id,path FROM library_assets WHERE source='pexels' AND provider_asset_id=?", (body.video_id,)
        ).fetchone()
        if active:
            raise HTTPException(409, "Satu impor Pexels sudah berjalan. Tunggu sampai selesai atau batalkan.")
        if existing and Path(existing["path"]).is_file():
            return {"asset": _asset_public(dict(conn.execute("SELECT * FROM library_assets WHERE id=?", (existing["id"],)).fetchone()), usage=True), "reused": True}
        prior_import = conn.execute(
            "SELECT a.* FROM asset_import_jobs j JOIN library_assets a ON a.id=j.asset_id "
            "WHERE j.provider_asset_id=? AND j.status='ready' ORDER BY j.updated_at DESC LIMIT 1", (body.video_id,),
        ).fetchone()
        if prior_import and Path(prior_import["path"]).is_file():
            return {"asset": _asset_public(dict(prior_import), usage=True), "reused": True}
        job_id, timestamp = uuid.uuid4().hex, now()
        conn.execute(
            "INSERT INTO asset_import_jobs(id,provider_asset_id,video_file_id,quality,status,phase,progress,message,created_at,updated_at) "
            "VALUES(?,?,?,?,'queued','queued',0,'Menunggu impor Pexels',?,?)",
            (job_id, body.video_id, body.video_file_id, body.quality, timestamp, timestamp),
        )
    _submit_import(job_id)
    return {"id": job_id, "status": "queued", "phase": "queued", "progress": 0, "bytes_downloaded": 0,
            "total_bytes": None, "message": "Menunggu impor Pexels"}


@router.get("/assets/stock/imports/{job_id}")
def get_stock_import(job_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM asset_import_jobs WHERE id=?", (job_id,)).fetchone()
        asset = conn.execute("SELECT * FROM library_assets WHERE id=?", (row["asset_id"],)).fetchone() if row and row["asset_id"] else None
    if row is None:
        raise HTTPException(404, "Job impor asset tidak ditemukan.")
    item = {key: row[key] for key in ("id", "status", "phase", "progress", "bytes_downloaded", "total_bytes", "message", "created_at", "updated_at")}
    if asset:
        item["asset"] = _asset_public(dict(asset), usage=True)
    return item


@router.post("/assets/stock/imports/{job_id}/cancel")
def cancel_stock_import(job_id: str):
    with connect() as conn:
        row = conn.execute("SELECT status FROM asset_import_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Job impor asset tidak ditemukan.")
        if row["status"] not in {"queued", "downloading", "probing"}:
            raise HTTPException(409, "Hanya impor yang menunggu atau berjalan yang dapat dibatalkan.")
        conn.execute("UPDATE asset_import_jobs SET cancel_requested=1,updated_at=? WHERE id=?", (now(), job_id))
    with _IMPORT_LOCK:
        event = _IMPORT_CANCEL.get(job_id)
        if event:
            event.set()
    return {"cancel_requested": True}


@router.post("/assets/stock/imports/{job_id}/retry")
def retry_stock_import(job_id: str):
    if not os.environ.get("PEXELS_API_KEY", "").strip():
        raise HTTPException(503, "PEXELS_API_KEY belum dikonfigurasi di backend.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM asset_import_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Job impor asset tidak ditemukan.")
        if row["status"] not in {"failed", "cancelled"}:
            raise HTTPException(409, "Hanya impor gagal/dibatalkan yang dapat dicoba ulang.")
        if conn.execute("SELECT 1 FROM asset_import_jobs WHERE status IN ('queued','downloading','probing') LIMIT 1").fetchone():
            raise HTTPException(409, "Satu impor Pexels lain sedang berjalan.")
        conn.execute("UPDATE asset_import_jobs SET status='queued',phase='queued',progress=0,bytes_downloaded=0,total_bytes=NULL,"
                     "cancel_requested=0,message='Menunggu retry impor Pexels',updated_at=? WHERE id=?", (now(), job_id))
    shutil.rmtree(SOURCE_DIR / f".pexels-import-{job_id}", ignore_errors=True)
    _submit_import(job_id)
    return {"id": job_id, "status": "queued", "phase": "queued", "progress": 0, "bytes_downloaded": 0,
            "total_bytes": None, "message": "Menunggu retry impor Pexels"}


@router.get("/assets")
def list_assets(
    kind: Literal["video", "image", "audio"] | None = None,
    favorite: bool | None = None,
    mood: Literal["Mellow", "Piano", "Lofi", "Sad", "Happy", "Romantic", "Cinematic", "Motivational", "Calm", "Upbeat"] | None = None,
    query: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=40, ge=1, le=100),
):
    clauses, values = [], []
    if kind:
        clauses.append("kind=?")
        values.append(kind)
    if favorite is not None:
        clauses.append("favorite=?")
        values.append(int(favorite))
    if mood:
        clauses.append("mood_tags_json LIKE ?")
        values.append(f'%"{mood}"%')
    if query.strip():
        clauses.append("(title LIKE ? OR creator_name LIKE ? OR artist LIKE ? OR source LIKE ?)")
        value = f"%{query.strip()}%"
        values.extend([value] * 4)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        total = conn.execute(f"SELECT count(*) FROM library_assets {where}", values).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM library_assets {where} ORDER BY favorite DESC,COALESCE(last_used_at,imported_at) DESC LIMIT ? OFFSET ?",
            [*values, per_page, (page - 1) * per_page],
        ).fetchall()
    return {"items": [_asset_public(dict(row), usage=True) for row in rows], "total": total, "page": page, "per_page": per_page}


@router.get("/assets/storage")
def asset_storage():
    with connect() as conn:
        rows = conn.execute("SELECT kind,count(*) AS count,COALESCE(sum(size_bytes),0) AS bytes FROM library_assets GROUP BY kind").fetchall()
        total = conn.execute("SELECT count(*),COALESCE(sum(size_bytes),0) FROM library_assets").fetchone()
    counts = {row["kind"]: {"count": row["count"], "bytes": row["bytes"]} for row in rows}
    for kind in ("video", "image", "audio"):
        counts.setdefault(kind, {"count": 0, "bytes": 0})
    return {"count": total[0], "bytes": total[1], "by_kind": counts, "free_bytes": _free_space()}


@router.post("/assets/upload")
def upload_library_asset(
    kind: Literal["video", "image", "audio"] = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=180),
    artist: str | None = Form(default=None, max_length=160),
    mood_tags: str = Form(default="", max_length=500),
    license_type: str | None = Form(default=None, max_length=100),
    license_notes: str | None = Form(default=None, max_length=2000),
    source_url: str | None = Form(default=None, max_length=2048),
    attribution_text: str | None = Form(default=None, max_length=500),
):
    tags = list(dict.fromkeys(tag.strip() for tag in mood_tags.split(",") if tag.strip()))
    if any(tag not in _MOOD_TAGS for tag in tags):
        raise HTTPException(422, "Mood tag tidak dikenal.")
    if source_url:
        try:
            parsed = urllib.parse.urlsplit(source_url)
        except ValueError:
            raise HTTPException(422, "Source URL HTTPS tidak valid.") from None
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(422, "Source URL harus HTTPS.")
    return register_local_upload(file, kind, title=title, artist=artist, mood_tags=tags, license_type=license_type,
                                 license_notes=license_notes, source_url=source_url, attribution_text=attribution_text)


@router.get("/assets/{asset_id}/file")
def asset_file(asset_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM library_assets WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Asset tidak ditemukan.")
    path = _safe_local_path(row["path"])
    return FileResponse(path, media_type=row["mime_type"], filename=row["title"], content_disposition_type="inline")


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM library_assets WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Asset tidak ditemukan.")
    return _asset_public(dict(row), usage=True)


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: str, body: AssetPatch):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(422, "Tidak ada metadata yang diubah.")
    mapping = {"title": "title", "favorite": "favorite", "artist": "artist", "license_type": "license_type",
               "license_notes": "license_notes", "source_url": "source_url", "attribution_text": "attribution_text", "mood_tags": "mood_tags_json"}
    fields, values = [], []
    for key, value in updates.items():
        if key == "title" and (value is None or not value.strip()):
            raise HTTPException(422, "Nama asset tidak boleh kosong.")
        if key == "favorite" and value is None:
            raise HTTPException(422, "Favorite harus bernilai true atau false.")
        if key == "source_url" and value:
            try:
                parsed = urllib.parse.urlsplit(value)
            except ValueError:
                raise HTTPException(422, "Source URL HTTPS tidak valid.") from None
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise HTTPException(422, "Source URL harus HTTPS.")
        if key == "mood_tags":
            value = json.dumps(value or [], ensure_ascii=False)
        if key == "favorite":
            value = int(value)
        fields.append(f"{mapping[key]}=?")
        values.append(value.strip() if key in {"title", "artist", "license_type", "license_notes", "attribution_text"} and isinstance(value, str) else value)
    with connect() as conn:
        if not conn.execute("UPDATE library_assets SET " + ",".join(fields) + " WHERE id=?", [*values, asset_id]).rowcount:
            raise HTTPException(404, "Asset tidak ditemukan.")
        row = conn.execute("SELECT * FROM library_assets WHERE id=?", (asset_id,)).fetchone()
    return _asset_public(dict(row), usage=True)


def _safe_clip_path(path):
    resolved = Path(path).resolve()
    if resolved.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or not resolved.is_file():
        raise HTTPException(404, "File render terkait tidak ditemukan.")
    return resolved


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM library_assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Asset tidak ditemukan.")
        item = dict(row)
        path = _safe_local_path(item["path"], require_file=False)
        if item["source_id"]:
            source_id = item["source_id"]
            if conn.execute("SELECT 1 FROM jobs WHERE source_id=? AND status IN ('queued','preparing','transcribing','analyzing','rendering')", (source_id,)).fetchone():
                raise HTTPException(409, "Batalkan job video aktif sebelum menghapus asset.")
            references = conn.execute(
                "SELECT p.title FROM mood_assets a JOIN mood_projects p ON p.id=a.project_id WHERE a.source_id=? ORDER BY p.updated_at DESC",
                (source_id,),
            ).fetchall()
            if references:
                names = ", ".join(row["title"] for row in references[:3])
                raise HTTPException(409, f"Asset masih dipakai {len(references)} draft Mood Quotes ({names}). Lepas asset dari draft terlebih dahulu.")
            clips = conn.execute("SELECT rendered_path FROM clips WHERE source_id=?", (source_id,)).fetchall()
            source = conn.execute("SELECT path FROM sources WHERE id=?", (source_id,)).fetchone()
            if source is None:
                raise HTTPException(409, "Source video tidak tersedia; data perlu diperiksa sebelum dihapus.")
            source_path = _safe_local_path(source["path"], allow_assets=False, require_file=False)
            clip_paths = []
            for clip in clips:
                if clip["rendered_path"]:
                    try:
                        clip_paths.append(_safe_clip_path(clip["rendered_path"]))
                    except HTTPException:
                        continue
            conn.execute("DELETE FROM library_assets WHERE id=?", (asset_id,))
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        else:
            references = conn.execute(
                "SELECT p.title FROM mood_assets a JOIN mood_projects p ON p.id=a.project_id WHERE a.library_asset_id=? ORDER BY p.updated_at DESC",
                (asset_id,),
            ).fetchall()
            if references:
                names = ", ".join(row["title"] for row in references[:3])
                raise HTTPException(409, f"Asset masih dipakai {len(references)} draft Mood Quotes ({names}). Lepas asset dari draft terlebih dahulu.")
            conn.execute("DELETE FROM library_assets WHERE id=?", (asset_id,))
            source_path, clip_paths = path, []
    source_path.unlink(missing_ok=True)
    for clip_path in clip_paths:
        clip_path.unlink(missing_ok=True)
    return {"deleted": True}
