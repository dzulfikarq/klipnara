import json
import logging
import os
import platform
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import CLIP_DIR, DATA_DIR, LEGACY_CLIP_DIR, LEGACY_SOURCE_DIR, MAX_UPLOAD_BYTES, MIN_FREE_BYTES, SOURCE_DIR, WORK_DIR
from .db import connect, init_db, unpack
from .jobs import create_job, now, runner
from .media import MediaError, download_url, probe, save_upload
from .providers import ProviderError, check_local


app = FastAPI(title="Klipnara", version="1.0.0", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


class UrlSource(BaseModel):
    url: str = Field(min_length=9, max_length=4096)


class GenerateOptions(BaseModel):
    count: Literal[3, 5, 10] = 5
    duration: Literal["15-30", "30-60", "60-90"] = "30-60"
    style: Literal["Clean", "Bold", "Highlight"] = "Clean"
    subtitle_enabled: bool = True
    resolution: Literal["720", "1080"] = "720"
    focus: Literal["center", "manual"] = "center"
    provider: Literal["local", "openai", "gemini"] = "local"
    language: Literal["auto", "indonesia", "english"] = "auto"
    consent: bool = False


class ClipEdit(BaseModel):
    trim_start: float | None = Field(default=None, ge=0)
    trim_end: float | None = Field(default=None, gt=0)
    subtitle_enabled: bool | None = None
    style: Literal["Clean", "Bold", "Highlight"] | None = None
    resolution: Literal["720", "1080"] | None = None
    crop_x: float | None = Field(default=None, ge=0, le=100)
    crop_y: float | None = Field(default=None, ge=0, le=100)
    subtitle_size: int | None = Field(default=None, ge=20, le=120)
    subtitle_position: int | None = Field(default=None, ge=0, le=100)
    subtitle_color: str | None = None
    subtitle_overrides: dict[str, str] | None = None


class RetryConsent(BaseModel):
    consent: bool = False


@app.on_event("startup")
def startup():
    init_db()
    logger = logging.getLogger("klipnara")
    if not logger.handlers:
        handler = RotatingFileHandler(DATA_DIR / "klipnara.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    runner.start()


def _require_storage(directory=DATA_DIR):
    if min(shutil.disk_usage(path).free for path in {DATA_DIR, WORK_DIR, directory}) < MIN_FREE_BYTES:
        raise HTTPException(507, "Low disk space. Keep at least 1 GiB free for temporary processing files.")


def _source_path(source):
    path = Path(source["path"]).resolve()
    if path.parent not in {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()} or not path.is_file():
        raise HTTPException(404, "Source file not found.")
    return path


def _safe_clip_path(path):
    resolved = Path(path).resolve()
    if resolved.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or not resolved.is_file():
        raise HTTPException(404, "Rendered clip not found.")
    return resolved


def _insert_source(source_id, name, path, size, digest):
    try:
        metadata = probe(path)
        timestamp = now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id, name[:180], str(path.resolve()), size, metadata["duration"], metadata["width"],
                    metadata["height"], metadata["video_codec"], metadata["audio_codec"], digest, timestamp,
                ),
            )
        return metadata
    except MediaError as exc:
        Path(path).unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from None
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/sources/upload")
def upload_source(file: UploadFile = File(...)):
    _require_storage(SOURCE_DIR)
    safe_name = Path((file.filename or "video.mp4").replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    try:
        path, source_id, size, digest = save_upload(file.file, suffix)
    except MediaError as exc:
        raise HTTPException(413 if "limit" in str(exc).lower() else 400, str(exc)) from None
    if size > MAX_UPLOAD_BYTES:
        path.unlink(missing_ok=True)
        raise HTTPException(413, "Video exceeds configured upload limit.")
    try:
        _require_storage(SOURCE_DIR)
        metadata = _insert_source(source_id, safe_name or "Video", path, size, digest)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"id": source_id, "name": safe_name, "size_bytes": size, **metadata}


@app.post("/api/sources/url")
def import_url(body: UrlSource):
    _require_storage(SOURCE_DIR)
    try:
        path, source_id, size, digest = download_url(body.url)
    except MediaError as exc:
        raise HTTPException(400, str(exc)) from None
    parsed = urllib.parse.urlsplit(body.url)
    file_name = Path(urllib.parse.unquote(parsed.path)).name
    name = file_name if file_name.lower().endswith((".mp4", ".mov")) else f"Video dari {parsed.hostname}"
    try:
        _require_storage(SOURCE_DIR)
        metadata = _insert_source(source_id, name, path, size, digest)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"id": source_id, "name": name, "size_bytes": size, **metadata}


@app.get("/api/sources")
def list_sources():
    with connect() as conn:
        rows = conn.execute(
            "SELECT s.id,s.name,s.size_bytes,s.duration,s.width,s.height,s.created_at,s.video_codec,s.audio_codec,"
            "(SELECT count(*) FROM clips c WHERE c.source_id=s.id) AS clip_count,"
            "(SELECT status FROM jobs j WHERE j.source_id=s.id ORDER BY created_at DESC LIMIT 1) AS latest_status "
            "FROM sources s ORDER BY s.created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/sources/{source_id}")
def get_source(source_id: str):
    with connect() as conn:
        source = unpack(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone(), ("transcript_json",))
        if source is None:
            raise HTTPException(404, "Video source not found.")
        clips = [
            unpack(row, ("edit_json",))
            for row in conn.execute("SELECT * FROM clips WHERE source_id=? ORDER BY rank,created_at", (source_id,)).fetchall()
        ]
    for clip in clips:
        clip["rendered"] = bool(clip.pop("rendered_path"))
    source["transcript"] = source.pop("transcript", [])
    source.pop("path", None)
    source.pop("sha256", None)
    source.pop("transcript_model", None)
    return {"source": source, "clips": clips}


@app.get("/api/sources/{source_id}/file")
def source_file(source_id: str):
    with connect() as conn:
        row = conn.execute("SELECT path,name FROM sources WHERE id=?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Video source not found.")
    path = _source_path(dict(row))
    return FileResponse(path, media_type="video/mp4", filename=row["name"], content_disposition_type="inline")


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str):
    with connect() as conn:
        if conn.execute("SELECT 1 FROM jobs WHERE source_id=? AND status IN ('queued','preparing','transcribing','analyzing','rendering')", (source_id,)).fetchone():
            raise HTTPException(409, "Cancel active jobs before deleting this source.")
        clips = conn.execute("SELECT rendered_path FROM clips WHERE source_id=?", (source_id,)).fetchall()
        row = conn.execute("SELECT path FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Video source not found.")
        source_path = Path(row["path"]).resolve()
        if source_path.parent not in {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()}:
            raise HTTPException(500, "Source path is outside the managed storage folder.")
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    source_path.unlink(missing_ok=True)
    for clip in clips:
        if clip["rendered_path"]:
            try:
                _safe_clip_path(clip["rendered_path"]).unlink(missing_ok=True)
            except HTTPException:
                pass
    return {"deleted": True}


@app.post("/api/sources/{source_id}/generate")
def generate(source_id: str, body: GenerateOptions):
    with connect() as conn:
        if not conn.execute("SELECT id FROM sources WHERE id=?", (source_id,)).fetchone():
            raise HTTPException(404, "Video source not found.")
    if body.provider != "local" and not body.consent:
        raise HTTPException(400, "Confirm per-job transcript sharing before using cloud AI.")
    if body.provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(400, "Set OPENAI_API_KEY in backend environment before selecting OpenAI.")
    if body.provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(400, "Set GEMINI_API_KEY in backend environment before selecting Gemini.")
    minimum, maximum = map(int, body.duration.split("-"))
    options = {
        "count": body.count,
        "clip_range": [minimum, maximum],
        "style": body.style,
        "subtitle_enabled": body.subtitle_enabled,
        "resolution": body.resolution,
        "focus": body.focus,
        "provider": body.provider,
        "language": body.language,
        "consent_at": now() if body.provider != "local" and body.consent else None,
    }
    job_id = create_job(source_id, "generate", options)
    return {"id": job_id, "status": "queued"}


@app.get("/api/clips")
def list_clips():
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT c.id,c.source_id,c.start,c.end,c.title,c.reason,c.rank,c.status,(c.rendered_path IS NOT NULL) AS rendered,c.created_at,s.name AS source_name "
                "FROM clips c JOIN sources s ON s.id=c.source_id ORDER BY c.created_at DESC,c.rank"
            ).fetchall()
        ]


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str):
    with connect() as conn:
        clip = unpack(conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone(), ("edit_json",))
        if clip is None:
            raise HTTPException(404, "Clip not found.")
        source_row = conn.execute("SELECT * FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
        source = dict(source_row)
        jobs = [dict(row) for row in conn.execute("SELECT * FROM jobs WHERE clip_id=? ORDER BY created_at DESC", (clip_id,)).fetchall()]
    clip["rendered"] = bool(clip.pop("rendered_path"))
    segments = json.loads(source.pop("transcript_json") or "[]")
    source.pop("path", None)
    source.pop("sha256", None)
    source.pop("transcript_model", None)
    return {"clip": clip, "source": source, "transcript": segments, "jobs": jobs}


@app.patch("/api/clips/{clip_id}")
def edit_clip(clip_id: str, body: ClipEdit):
    with connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clip not found.")
        if conn.execute("SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')", (clip_id,)).fetchone():
            raise HTTPException(409, "Wait for the active render to finish or cancel it before editing.")
        clip = dict(row)
        edit = json.loads(clip["edit_json"])
        changes = body.model_dump(exclude_unset=True)
        color = changes.get("subtitle_color")
        if color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise HTTPException(422, "Subtitle color must be a hex RGB value.")
        overrides = changes.get("subtitle_overrides")
        if overrides is not None and any(len(str(text)) > 500 for text in overrides.values()):
            raise HTTPException(422, "Subtitle text limit is 500 characters per segment.")
        next_style = changes.get("style")
        if next_style and next_style != edit["style"] and "subtitle_color" not in changes:
            if next_style == "Highlight" and edit["subtitle_color"].lower() == "#ffffff":
                changes["subtitle_color"] = "#ffd700"
            elif edit["style"] == "Highlight" and edit["subtitle_color"].lower() == "#ffd700":
                changes["subtitle_color"] = "#ffffff"
        edit.update(changes)
        length = clip["end"] - clip["start"]
        edit.setdefault("trim_start", 0)
        edit.setdefault("trim_end", length)
        if not (0 <= edit["trim_start"] < edit["trim_end"] <= length):
            raise HTTPException(422, "Trim range must stay inside the candidate clip.")
        next_status = "needs_render" if clip["rendered_path"] else "ready"
        conn.execute("UPDATE clips SET edit_json=?,status=? WHERE id=?", (json.dumps(edit), next_status, clip_id))
    return edit


@app.post("/api/clips/{clip_id}/render")
def render_clip(clip_id: str):
    _require_storage(CLIP_DIR)
    with connect() as conn:
        clip = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if clip is None:
            raise HTTPException(404, "Clip not found.")
        if conn.execute("SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')", (clip_id,)).fetchone():
            raise HTTPException(409, "A render for this clip is already queued or running.")
        if conn.execute("SELECT transcript_json FROM sources WHERE id=?", (clip["source_id"],)).fetchone()["transcript_json"] is None:
            raise HTTPException(409, "Generate transcript before rendering subtitles.")
        edit = json.loads(clip["edit_json"])
    job_id = create_job(clip["source_id"], "render", {"edit": edit}, clip_id)
    return {"id": job_id, "status": "queued"}


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: str):
    with connect() as conn:
        row = conn.execute("SELECT rendered_path FROM clips WHERE id=?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Clip not found.")
    if not row["rendered_path"]:
        raise HTTPException(409, "Clip has not been rendered yet.")
    path = _safe_clip_path(row["rendered_path"])
    return FileResponse(path, media_type="video/mp4", filename=f"clip-{clip_id[:8]}.mp4")


@app.get("/api/clips/{clip_id}/file")
def preview_clip(clip_id: str):
    with connect() as conn:
        row = conn.execute("SELECT rendered_path FROM clips WHERE id=?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Clip not found.")
    if not row["rendered_path"]:
        raise HTTPException(409, "Clip has not been rendered yet.")
    return FileResponse(_safe_clip_path(row["rendered_path"]), media_type="video/mp4", content_disposition_type="inline")


@app.delete("/api/clips/{clip_id}")
def delete_clip(clip_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clip not found.")
        if conn.execute("SELECT 1 FROM jobs WHERE clip_id=? AND status IN ('queued','preparing','rendering')", (clip_id,)).fetchone():
            raise HTTPException(409, "Cancel active render before deleting this clip.")
        rendered = row["rendered_path"]
        conn.execute("DELETE FROM clips WHERE id=?", (clip_id,))
    if rendered:
        try:
            _safe_clip_path(rendered).unlink(missing_ok=True)
        except HTTPException:
            pass
    return {"deleted": True}


@app.get("/api/jobs")
def list_jobs():
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT j.id,j.source_id,j.clip_id,j.kind,j.status,j.phase,j.progress,j.message,j.created_at,j.updated_at,s.name AS source_name "
                "FROM jobs j JOIN sources s ON s.id=j.source_id ORDER BY j.created_at DESC LIMIT 30"
            ).fetchall()
        ]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Job not found.")
        job = dict(row)
        usage = [dict(item) for item in conn.execute("SELECT provider,model,input_tokens,output_tokens,created_at FROM provider_usage WHERE job_id=?", (job_id,)).fetchall()]
    job.pop("options_json", None)
    job["usage"] = usage
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not runner.cancel(job_id):
        raise HTTPException(409, "Job is not queued or running.")
    return {"cancelled": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, body: RetryConsent):
    with connect() as conn:
        old = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if old is None:
        raise HTTPException(404, "Job not found.")
    if old["status"] not in {"failed", "cancelled"}:
        raise HTTPException(409, "Only failed or cancelled jobs can be retried.")
    options = json.loads(old["options_json"])
    if options.get("provider") in {"openai", "gemini"}:
        if not body.consent:
            raise HTTPException(400, "Cloud retry requires fresh per-job consent.")
        options["consent_at"] = now()
    new_id = create_job(old["source_id"], old["kind"], options, old["clip_id"])
    return {"id": new_id, "status": "queued"}


@app.get("/api/settings")
def settings():
    capabilities = _capabilities()
    return {
        "capabilities": capabilities,
        "providers": {
            "local": {"model": os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b"), "available": capabilities["ollama_connected"]},
            "openai": {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "key_configured": bool(os.environ.get("OPENAI_API_KEY"))},
            "gemini": {"model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"), "key_configured": bool(os.environ.get("GEMINI_API_KEY"))},
        },
        "data_dir": str(DATA_DIR),
        "source_dir": str(SOURCE_DIR),
        "clip_dir": str(CLIP_DIR),
        "free_bytes": min(shutil.disk_usage(path).free for path in {DATA_DIR, WORK_DIR, SOURCE_DIR, CLIP_DIR}),
    }


@app.post("/api/providers/{provider}/test")
def test_provider(provider: Literal["local", "openai", "gemini"]):
    if provider == "local":
        try:
            models = check_local()
            return {"connected": True, "models": models}
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from None
        except Exception:
            raise HTTPException(503, "Ollama lokal tidak terjangkau. Tidak ada cloud fallback otomatis.") from None
    key_name = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"
    if not os.environ.get(key_name):
        raise HTTPException(400, f"{key_name} belum disetel di environment backend.")
    return {"connected": None, "message": "API key tersedia di backend; koneksi diuji saat pengguna menyetujui job cloud."}


def _capabilities():
    cpu = platform.processor() or platform.machine()
    os_name = platform.platform()
    ram = None
    gpu = []
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            script = (
                "$os=Get-CimInstance Win32_OperatingSystem; $cpu=Get-CimInstance Win32_Processor; "
                "$gpu=Get-CimInstance Win32_VideoController; "
                "[pscustomobject]@{os=$os.Caption;cpu=$cpu.Name;ram=$os.TotalVisibleMemorySize;"
                "gpu=@($gpu|ForEach-Object {if($_.AdapterRAM){\"$($_.Name) - $([math]::Round($_.AdapterRAM/1GB,1)) GB VRAM\"}else{$_.Name}})}|ConvertTo-Json -Compress"
            )
            try:
                output = subprocess.run([powershell, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=5, check=True).stdout
                data = json.loads(output)
                os_name = data.get("os") or os_name
                cpu = data.get("cpu") or cpu
                ram = int(data["ram"]) * 1024 if data.get("ram") else None
                gpu = data.get("gpu", [])
                if isinstance(gpu, str):
                    gpu = [gpu]
            except (subprocess.SubprocessError, json.JSONDecodeError, ValueError, KeyError):
                pass
    else:
        try:
            with open("/proc/meminfo", encoding="utf-8") as memory:
                ram = int(next(line.split()[1] for line in memory if line.startswith("MemTotal:"))) * 1024
        except (OSError, StopIteration, ValueError):
            pass
    def locate(variable, default):
        candidate = os.environ.get(variable, default)
        return shutil.which(candidate) or (str(Path(candidate).resolve()) if Path(candidate).is_file() else None)

    ffmpeg_binary = locate("FFMPEG_PATH", "ffmpeg")
    ffmpeg_available = bool(ffmpeg_binary)
    ffmpeg_version, encoders, filters = None, "", ""
    if ffmpeg_available:
        try:
            ffmpeg_version = subprocess.run([ffmpeg_binary, "-version"], capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
            encoders = subprocess.run([ffmpeg_binary, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
            filters = subprocess.run([ffmpeg_binary, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    ollama = False
    try:
        url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
        if urllib.parse.urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}:
            with urllib.request.urlopen(url, timeout=1) as response:
                ollama = response.status == 200
    except Exception:
        pass
    opencl_available, vulkan_available = False, False
    clinfo = locate("CLINFO_PATH", "clinfo")
    vulkaninfo = locate("VULKANINFO_PATH", "vulkaninfo")
    try:
        if clinfo:
            output = subprocess.run([clinfo, "--list"], capture_output=True, text=True, timeout=5).stdout
            opencl_available = "OpenCL" in output and ("GPU" in output or "Radeon" in output)
        if vulkaninfo:
            output = subprocess.run([vulkaninfo, "--summary"], capture_output=True, text=True, timeout=5).stdout
            vulkan_available = "deviceName" in output
    except (OSError, subprocess.SubprocessError):
        pass
    free = min(shutil.disk_usage(path).free for path in {DATA_DIR, WORK_DIR, SOURCE_DIR, CLIP_DIR})
    return {
        "os": os_name,
        "cpu": cpu,
        "logical_cores": os.cpu_count(),
        "ram_bytes": ram,
        "gpus": gpu or ["Tidak diketahui"],
        "disk_free_bytes": free,
        "ffmpeg_available": ffmpeg_available,
        "ffmpeg_version": ffmpeg_version,
        "ffprobe_available": bool(shutil.which(os.environ.get("FFPROBE_PATH", "ffprobe"))),
        "libx264_available": "libx264" in encoders,
        "libass_available": " ass " in filters,
        "h264_amf_listed": "h264_amf" in encoders,
        "opencl_runtime_detected": opencl_available,
        "vulkan_runtime_detected": vulkan_available,
        "ollama_connected": ollama,
        "whisper_cpp_available": bool(locate("WHISPER_CPP_PATH", "whisper-cli")),
        "whisper_model_configured": bool(os.environ.get("WHISPER_MODEL_PATH") and Path(os.environ["WHISPER_MODEL_PATH"]).is_file()),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@app.get("/api/system/capabilities")
def system_capabilities():
    return _capabilities()
