import hashlib
import json
import logging
import math
import os
import platform
import re
import shutil
import subprocess
import threading
import traceback
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import CLIP_DIR, DATA_DIR, LEGACY_CLIP_DIR, LEGACY_SOURCE_DIR, MAX_UPLOAD_BYTES, MIN_FREE_BYTES, MOOD_DIR, SOURCE_DIR, WORK_DIR
from .db import connect, init_db, unpack
from .jobs import create_job, now, runner
from .media import (
    MediaError,
    clip_subtitle_segments,
    download_url,
    extract_subtitle_audio,
    local_transcription_available,
    MAX_OUTPUT_SECONDS,
    MAX_SCENES,
    MAX_TRANSITION_SECONDS,
    MIN_TRANSITION_SECONDS,
    MIN_SCENE_SECONDS,
    normalize_scene_transitions,
    output_scenes,
    probe,
    render_subtitle_segments,
    scene_output_duration,
    source_interval_visible,
    save_upload,
    source_subtitle_segments,
    transcript_cache_matches,
    transcribe,
    transcribe_gemini,
    transcribe_openai,
    validate_scene_transitions,
)
from .providers import ProviderError, check_local
from .subtitles import (
    PRESETS, composition_fingerprint, composition_signature, export_subtitle_file, valid_word_alignment,
    parse_subtitle_file, subtitle_content_fingerprint, translation_is_outdated,
)
from . import youtube
from . import youtube_analytics
from . import platform_publishing
from .youtube_clip import fetch_youtube_metadata, parse_youtube_url
from .youtube_import import capabilities as youtube_import_capabilities, validate_import as validate_youtube_import
from .mood_studio import router as mood_studio_router
from .batch_studio import router as batch_studio_router
from .asset_library import register_source_asset, router as asset_library_router


app = FastAPI(title="Klipnara Studio", version="2.11.0", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(mood_studio_router)
app.include_router(asset_library_router)
app.include_router(batch_studio_router)


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


class YouTubeClipReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_url: str = Field(min_length=20, max_length=2048)
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)


class QuickClipRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    resolution: Literal["720", "1080"] = "720"
    youtube_reference: YouTubeClipReference | None = None


class SubtitleSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(max_length=500)
    words: list[dict] | None = Field(default=None, max_length=1000)
    word_alignment_reviewed: bool | None = None
    speaker_id: str | None = Field(default=None, max_length=64)
    source_segment_id: str | None = Field(default=None, max_length=64)
    original_text: str | None = Field(default=None, max_length=500)
    edited: bool = False


class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source_type: Literal["manual", "generated", "imported", "translation"]
    language: str = Field(default="und", min_length=2, max_length=35)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=2048)
    timebase: Literal["output", "source", "clip"]
    segments: list[SubtitleSegment] = Field(default_factory=list, max_length=500)
    transcript_text: str | None = Field(default=None, max_length=100000)
    composition_signature: str | None = Field(default=None, max_length=2048)
    composition_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    source_track_id: str | None = Field(default=None, max_length=64)
    source_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    word_timestamps: bool = False
    speaker_identification: bool = False
    edited: bool = False


class ClipScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    order: int = Field(ge=0, le=11)
    role: Literal["hook", "body", "ending"] = "body"


class ClipCameraKeyframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    frame: int = Field(strict=True, ge=0, le=10_000_000)
    x: float = Field(ge=0, le=100, allow_inf_nan=False)
    y: float = Field(ge=0, le=100, allow_inf_nan=False)
    zoom: float = Field(ge=1, le=2, allow_inf_nan=False)


class ClipSceneCamera(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyframes: list[ClipCameraKeyframe] = Field(default_factory=list, max_length=500)


class ClipCameraSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    interpolation: Literal["hold", "linear", "smooth"] = "smooth"
    scenes: dict[str, ClipSceneCamera] = Field(default_factory=dict, max_length=MAX_SCENES)


SceneTransitionType = Literal[
    "none", "crossfade", "dip_to_black", "zoom_blur",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circleopen", "circleclose", "dissolve", "pixelize", "radial", "fadewhite",
]


class ClipSceneTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: SceneTransitionType = "none"
    duration: float = Field(default=0.5, ge=0.001, le=180)
    timing_mode: Literal["insert_slot", "overlap"] = "overlap"
    smooth_audio: bool = False


class ClipAudioSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    volume: float = Field(default=1, ge=0, le=2)
    muted: bool = False
    fade_in: float = Field(default=0, ge=0, le=10)
    fade_out: float = Field(default=0, ge=0, le=10)
    normalize: bool = False
    target_lufs: float = Field(default=-18, ge=-24, le=-14)
    limiter: bool = False


class ClipTitleOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    text: str = Field(default="", max_length=120)
    font: Literal["Arial", "Georgia", "Segoe UI", "Tahoma", "Trebuchet MS", "Times New Roman"] = "Arial"
    size: int = Field(default=48, ge=20, le=120)
    color: str = Field(default="#ffffff", min_length=7, max_length=7)
    position: float = Field(default=18, ge=10, le=90)
    duration: float = Field(default=3, ge=0.5, le=15)
    fade_in: float = Field(default=0.2, ge=0, le=2)
    fade_out: float = Field(default=0.2, ge=0, le=2)


class YouTubeClipMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=10, max_length=2048)


class YouTubeClipImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=10, max_length=2048)
    start: float
    end: float
    rights_confirmed: bool = False


class YouTubeClipImportRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rights_confirmed: bool = False


class ClipEdit(BaseModel):
    trim_start: float | None = Field(default=None, ge=0)
    trim_end: float | None = Field(default=None, gt=0)
    scene_mode: Literal["single", "multi"] | None = None
    scenes: list[ClipScene] | None = Field(default=None, max_length=MAX_SCENES)
    transitions: dict[str, ClipSceneTransition] | None = Field(default=None, max_length=MAX_SCENES - 1)
    camera: ClipCameraSettings | None = None
    subtitle_enabled: bool | None = None
    subtitle_mode: Literal["off", "manual", "auto", "import"] | None = None
    subtitle_segments: list[SubtitleSegment] | None = Field(default=None, max_length=500)
    subtitle_tracks: list[SubtitleTrack] | None = Field(default=None, max_length=20)
    subtitle_active_track_id: str | None = Field(default=None, max_length=64)
    subtitle_active_translation_id: str | None = Field(default=None, max_length=64)
    subtitle_timebase: Literal["clip", "source", "output"] | None = None
    subtitle_display_mode: Literal["original", "translated", "bilingual"] | None = None
    subtitle_caption_mode: Literal["sentence", "phrase", "word", "karaoke", "word_pop"] | None = None
    subtitle_preset: Literal["Minimal Clean", "Bold Viral", "Karaoke Highlight", "Cinematic", "Podcast Caption", "Yellow Pop", "Soft Purple", "Classic White", "Word Pop"] | None = None
    subtitle_animation: Literal["none", "fade", "pop", "scale"] | None = None
    subtitle_animation_intensity: float | None = Field(default=None, ge=0.05, le=0.2)
    subtitle_animation_duration: int | None = Field(default=None, ge=50, le=250)
    subtitle_font: Literal["Arial", "Georgia", "Segoe UI", "Tahoma", "Trebuchet MS", "Times New Roman"] | None = None
    subtitle_outline_color: str | None = None
    subtitle_highlight_color: str | None = None
    subtitle_outline: float | None = Field(default=None, ge=0, le=8)
    subtitle_shadow: float | None = Field(default=None, ge=0, le=4)
    subtitle_background: bool | None = None
    subtitle_alignment: Literal["top", "center", "bottom"] | None = None
    subtitle_caption_width: int | None = Field(default=None, ge=30, le=100)
    subtitle_safe_margin: int | None = Field(default=None, ge=0, le=20)
    style: Literal["Clean", "Bold", "Highlight"] | None = None
    resolution: Literal["720", "1080"] | None = None
    crop_x: float | None = Field(default=None, ge=0, le=100)
    crop_y: float | None = Field(default=None, ge=0, le=100)
    subtitle_size: int | None = Field(default=None, ge=20, le=120)
    subtitle_position: int | None = Field(default=None, ge=0, le=100)
    subtitle_color: str | None = None
    subtitle_overrides: dict[str, str] | None = None
    audio: ClipAudioSettings | None = None
    title_overlay: ClipTitleOverlay | None = None
    fps: Literal[30, 60] | None = None
    quality: Literal["smaller", "balanced", "high"] | None = None


def _validate_word_timing_draft(segment, maximum_time, timebase):
    words = segment.get("words")
    if words is None:
        return
    if not isinstance(words, list) or len(words) > 1000:
        raise HTTPException(422, "Word timing list must contain at most 1000 words.")
    ids = [word.get("id") if isinstance(word, dict) else None for word in words]
    if any(not isinstance(word_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", word_id) for word_id in ids) or len(ids) != len(set(ids)):
        raise HTTPException(422, "Word timestamp IDs must be valid and unique per segment.")
    pending = segment.get("word_alignment_reviewed") is False
    for word in words:
        if not isinstance(word, dict):
            raise HTTPException(422, "Word timing entries must be objects.")
        text = word.get("text", "")
        if not isinstance(text, str):
            raise HTTPException(422, "Word text must be a string.")
        if (not text and not pending) or len(text) > 500:
            raise HTTPException(422, "Word timing needs non-empty text up to 500 characters.")
        for key in ("start", "end"):
            value = word.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise HTTPException(422, "Word timestamp start and end must be numeric seconds.")
            try:
                if not math.isfinite(value):
                    raise HTTPException(422, "Word timestamp start and end must be finite seconds.")
            except OverflowError:
                raise HTTPException(422, "Word timestamp start and end must be finite seconds.") from None
        if pending and (word.get("start") is None or word.get("end") is None):
            continue
        try:
            start, end = float(word["start"]), float(word["end"])
        except (KeyError, OverflowError, TypeError, ValueError):
            raise HTTPException(422, "Word timestamp needs text, start, end, and stable ID.") from None
        if not math.isfinite(start) or not math.isfinite(end) or not (0 <= start < end <= maximum_time):
            raise HTTPException(422, f"Word timing must use {timebase} seconds and stay inside that timeline.")
    if words and not pending and not valid_word_alignment(segment):
        raise HTTPException(422, "Word text and timing must align in order, stay inside the cue, and not overlap.")


class SubtitleGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["local", "openai"]
    language: Literal["auto", "indonesia", "english"] = "auto"
    consent: bool = False
    scene_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class SubtitleTranscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["local", "openai", "gemini"]
    language: Literal["auto", "indonesia", "english"] = "auto"
    consent: bool = False


class SubtitleTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["openai", "gemini"]
    target_language: Literal["id-ID", "en-US"]
    consent: bool = False


class SubtitleImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["srt", "vtt"]
    text: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    clamp: bool = False


class RetryConsent(BaseModel):
    consent: bool = False


class ClipReview(BaseModel):
    status: Literal["approved", "needs_revision"]


class YouTubePublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str | None = Field(default=None, min_length=1, max_length=64)
    account_ids: list[str] = Field(default_factory=list, max_length=50)
    metadata_by_account: dict[str, dict[str, object]] = Field(default_factory=dict)
    rights_confirmed: bool = False
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    publish_at: str | None = Field(default=None, max_length=40)
    category_id: str = Field(default="22", max_length=3)
    video_language: str | None = Field(default=None, max_length=35)
    made_for_kids: bool | None = None
    contains_synthetic_media: bool | None = None
    confirmed: bool = False


class PublishingMetadataDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    privacy_status: Literal["private", "unlisted", "public"] | None = None
    publish_at: str | None = Field(default=None, max_length=40)
    category_id: str | None = Field(default=None, max_length=3)
    video_language: str | None = Field(default=None, max_length=35)
    made_for_kids: bool | None = None
    contains_synthetic_media: bool | None = None


class PublishingMetadataTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    metadata: PublishingMetadataDraft


class PlatformMetadataDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caption: str = Field(default="", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    privacy_level: Literal["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"] | None = None
    disable_comment: bool | None = None
    disable_duet: bool | None = None
    disable_stitch: bool | None = None
    share_to_feed: bool | None = None
    ai_generated: bool | None = None


class ManualExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool = False
    rights_confirmed: bool = False


class PlatformManualExportRequest(ManualExportRequest):
    metadata: dict[str, object] | None = None


class PlatformUploadRequest(ManualExportRequest):
    account_id: str | None = Field(default=None, min_length=1, max_length=64)
    account_ids: list[str] = Field(default_factory=list, max_length=50)
    metadata_by_account: dict[str, dict[str, object]] = Field(default_factory=dict)


class PlatformRetryRequest(ManualExportRequest):
    duplicate_risk_confirmed: bool = False


class _OAuthAccessLogFilter(logging.Filter):
    def filter(self, record):
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and any(
            path in str(args[2]) for path in ("/api/youtube/oauth/callback", "/api/platforms/tiktok/oauth/callback", "/api/platforms/instagram/oauth/callback")
        ):
            path = str(args[2]).split("?", 1)[0]
            record.args = (*args[:2], path, *args[3:])
        return True


@app.on_event("startup")
def startup():
    init_db()
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _OAuthAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(_OAuthAccessLogFilter())
    logger = logging.getLogger("klipnara")
    if not logger.handlers:
        handler = RotatingFileHandler(DATA_DIR / "klipnara.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    runner.start()


def _require_storage(directory=DATA_DIR):
    if min(shutil.disk_usage(path).free for path in {DATA_DIR, WORK_DIR, MOOD_DIR, directory}) < MIN_FREE_BYTES:
        raise HTTPException(507, "Low disk space. Keep at least 1 GiB free for temporary processing files.")


def _source_path(source):
    path = Path(source["path"]).resolve()
    if path.parent not in {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()} or not path.is_file():
        raise HTTPException(404, "Source file not found.")
    return path


def _assert_batch_item_editable(conn, clip_id):
    item = conn.execute(
        "SELECT i.status,i.job_id,b.status AS batch_status FROM video_batch_items i "
        "JOIN video_batches b ON b.id=i.batch_id WHERE i.clip_id=?",
        (clip_id,),
    ).fetchone()
    paused_pending = item and item["status"] == "queued" and item["batch_status"] == "paused" and item["job_id"] is None
    if item and item["status"] in {"queued", "rendering"} and not paused_pending:
        raise HTTPException(409, "This item is queued in a batch. Pause or wait before editing.")


def _safe_clip_path(path):
    resolved = Path(path).resolve()
    if resolved.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or not resolved.is_file():
        raise HTTPException(404, "Rendered clip not found.")
    return resolved


def _validated_final_mp4(clip):
    if clip["status"] != "completed" or not clip["rendered_path"]:
        raise HTTPException(409, "Render final MP4 sebelum memberi keputusan review.")
    try:
        path = _safe_clip_path(clip["rendered_path"])
        metadata = probe(path)
        if path.suffix.lower() != ".mp4" or path.stat().st_size == 0:
            raise MediaError("Final output is not a non-empty MP4.")
        if metadata["video_codec"] != "h264" or metadata["audio_codec"] != "aac":
            raise MediaError("Final output codec is not H.264/AAC.")
    except (HTTPException, MediaError, OSError):
        raise HTTPException(409, "Final MP4 missing or invalid; render it again before review.") from None
    return path


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@app.get("/api/youtube/config")
def youtube_config():
    try:
        start_url = youtube.oauth_start_url()
        redirect_error = None
    except youtube.YouTubeError as exc:
        start_url, redirect_error = None, str(exc)
    return {
        "configured": youtube.configured(), "scope": youtube.SCOPE,
        "start_url": start_url, "redirect_uri": youtube.redirect_uri(), "redirect_error": redirect_error,
    }


@app.post("/api/youtube-clips/metadata")
def youtube_clip_metadata(body: YouTubeClipMetadataRequest):
    try:
        reference = parse_youtube_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        metadata = fetch_youtube_metadata(reference["video_id"])
    except Exception as exc:
        logging.getLogger("klipnara").warning("YouTube metadata lookup failed: %s", type(exc).__name__)
        metadata = {
            "metadata": None,
            "metadata_status": "api_error",
            "metadata_message": "Metadata YouTube gagal diambil; preview tetap dicoba dan video belum dinyatakan tersedia.",
        }
    return {**reference, **metadata}


@app.get("/api/youtube-clips/import-capabilities")
def youtube_clip_import_capabilities():
    return youtube_import_capabilities()


@app.post("/api/youtube-clips/imports")
def create_youtube_clip_import(body: YouTubeClipImportRequest):
    capability = youtube_import_capabilities()
    if not capability["available"]:
        raise HTTPException(503, capability["reason"] or "Impor otomatis tidak tersedia.")
    try:
        reference = parse_youtube_url(body.url)
        validate_youtube_import(
            reference["canonical_url"], reference["video_id"], body.start, body.end, body.rights_confirmed,
        )
    except (ValueError, MediaError) as exc:
        raise HTTPException(422, str(exc)) from None
    _require_storage(SOURCE_DIR)
    job_id, timestamp = uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO youtube_import_jobs(id,video_id,canonical_url,start_seconds,end_seconds,rights_confirmed,"
            "status,phase,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,?,'queued','preparing',NULL,?,?,?)",
            (job_id, reference["video_id"], reference["canonical_url"], body.start, body.end, int(body.rights_confirmed),
             "Menunggu impor segmen", timestamp, timestamp),
        )
    return {"id": job_id, "status": "queued", "phase": "preparing"}


@app.get("/api/youtube-clips/imports/{job_id}")
def get_youtube_clip_import(job_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM youtube_import_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "YouTube segment import job not found.")
        result = dict(row)
        if result["source_id"]:
            source = conn.execute(
                "SELECT id,name,size_bytes,duration,width,height,video_codec,audio_codec FROM sources WHERE id=?",
                (result["source_id"],),
            ).fetchone()
            result["source"] = dict(source) if source else None
    return result


@app.post("/api/youtube-clips/imports/{job_id}/cancel")
def cancel_youtube_clip_import(job_id: str):
    if not runner.cancel(job_id):
        raise HTTPException(409, "YouTube segment import is not queued or running.")
    return {"cancelled": True}


@app.post("/api/youtube-clips/imports/{job_id}/retry")
def retry_youtube_clip_import(job_id: str, body: YouTubeClipImportRetryRequest):
    capability = youtube_import_capabilities()
    if not capability["available"]:
        raise HTTPException(503, capability["reason"] or "Impor otomatis tidak tersedia.")
    with connect() as conn:
        old = conn.execute("SELECT * FROM youtube_import_jobs WHERE id=?", (job_id,)).fetchone()
    if old is None:
        raise HTTPException(404, "YouTube segment import job not found.")
    if old["status"] not in {"failed", "cancelled"}:
        raise HTTPException(409, "Only failed or cancelled imports can be retried.")
    if not body.rights_confirmed:
        raise HTTPException(400, "Fresh confirmation of content rights is required before retry.")
    new_id, timestamp = uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO youtube_import_jobs(id,video_id,canonical_url,start_seconds,end_seconds,rights_confirmed,"
            "status,phase,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,?,'queued','preparing',NULL,?,?,?)",
            (new_id, old["video_id"], old["canonical_url"], old["start_seconds"], old["end_seconds"],
             1, "Retry menunggu impor segmen", timestamp, timestamp),
        )
    return {"id": new_id, "status": "queued", "phase": "preparing"}


@app.get("/api/youtube/oauth/start")
def youtube_oauth_start(account_id: str | None = None):
    if not youtube.configured():
        raise HTTPException(503, "Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in backend environment first.")
    if account_id:
        with connect() as conn:
            account = conn.execute(
                "SELECT channel_id,status,token_blob FROM youtube_accounts WHERE id=?", (account_id,),
            ).fetchone()
        if not account or account["status"] != "connected" or not account["token_blob"]:
            raise HTTPException(409, "Reconnect this YouTube channel before enabling Analytics.")
        state = youtube.create_oauth_state(account["channel_id"], "analytics")
        scopes = youtube.ANALYTICS_SCOPES
    else:
        state = youtube.create_oauth_state()
        scopes = youtube.SCOPES
    try:
        target = youtube.authorization_url(state, scopes)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 503, str(exc)) from None
    response = RedirectResponse(target, status_code=302)
    state_cookie = youtube.oauth_state_cookie_name(state)
    response.set_cookie(
        state_cookie, state, max_age=600, httponly=True,
        secure=urllib.parse.urlsplit(youtube.redirect_uri()).scheme.lower() == "https", samesite="lax",
        path="/api/youtube/oauth/callback",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/youtube/oauth/callback")
def youtube_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    result = None
    try:
        state_context = youtube.consume_oauth_state_context(
            state, request.cookies.get(youtube.oauth_state_cookie_name(state or "")) or request.cookies.get("klipnara_youtube_state"),
        )
    except Exception:
        logging.getLogger("klipnara").warning("YouTube OAuth state check failed (oauth_state_storage_failed)")
        result = "oauth_state_storage_failed"
        state_context = None
    if result is None:
        if not state_context:
            result = "oauth_state_invalid"
        elif error:
            result = "oauth_cancelled" if error == "access_denied" else "oauth_google_denied"
        elif not code:
            result = "oauth_response_invalid"
        else:
            try:
                if state_context["purpose"] == "analytics":
                    connected = youtube.connect_account(code, expected_channel_id=state_context["account_id"])
                    result = "analytics_enabled" if connected["analytics_ready"] else "analytics_scope_missing"
                else:
                    connected = youtube.connect_account(code)
                    result = "connected" if connected["analytics_ready"] else "connected_analytics_scope_missing"
            except youtube.YouTubeError as exc:
                result = exc.code or "oauth_connection_failed"
                if exc.code:
                    logging.getLogger("klipnara").warning("YouTube OAuth callback failed (%s)", result)
                else:
                    frames = traceback.extract_tb(exc.__traceback__)
                    location = f"{frames[-1].name}:{frames[-1].lineno}" if frames else "unknown"
                    logging.getLogger("klipnara").warning(
                        "YouTube OAuth callback failed unexpectedly (%s at %s)", type(exc).__name__, location,
                    )
            except Exception as exc:
                result = "oauth_connection_failed"
                frames = traceback.extract_tb(exc.__traceback__)
                location = f"{frames[-1].name}:{frames[-1].lineno}" if frames else "unknown"
                logging.getLogger("klipnara").warning(
                    "YouTube OAuth callback failed unexpectedly (%s at %s)", type(exc).__name__, location,
                )
    response = RedirectResponse(youtube.frontend_accounts_url(result), status_code=303)
    response.delete_cookie(youtube.oauth_state_cookie_name(state or ""), path="/api/youtube/oauth/callback")
    response.delete_cookie("klipnara_youtube_state", path="/api/youtube/oauth/callback")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/youtube/accounts")
def youtube_accounts():
    return {"configured": youtube.configured(), "accounts": youtube.list_accounts()}


def _platform_response(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except platform_publishing.PlatformError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": str(exc)}) from None


@app.get("/api/publishing/platforms")
def publishing_platforms():
    return _platform_response(platform_publishing.platform_status)


@app.get("/api/platforms/{platform}/oauth/start")
def platform_oauth_start(platform: Literal["tiktok", "instagram"]):
    result = _platform_response(platform_publishing.oauth_start, platform)
    response = RedirectResponse(result["url"], status_code=302)
    state_cookie = platform_publishing.oauth_state_cookie_name(platform, result["state"])
    response.set_cookie(
        key=state_cookie, value=result["state"], max_age=600, httponly=True,
        secure=result["secure_cookie"], samesite="lax", path=f"/api/platforms/{platform}/oauth/callback",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _platform_oauth_callback(platform, request, code, state, error):
    result = "oauth_connection_failed"
    try:
        browser_state = request.cookies.get(platform_publishing.oauth_state_cookie_name(platform, state or "")) or request.cookies.get(f"klipnara_{platform}_state")
        if error:
            platform_publishing.consume_oauth_state(platform, state, browser_state)
            result = "oauth_denied"
        else:
            platform_publishing.complete_oauth(platform, code, state, browser_state)
            result = "connected"
    except platform_publishing.PlatformError as exc:
        result = exc.code
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        location = f"{frames[-1].name}:{frames[-1].lineno}" if frames else "unknown"
        logging.getLogger("klipnara").warning("%s OAuth callback failed (%s at %s)", platform, type(exc).__name__, location)
    response = RedirectResponse(platform_publishing.frontend_accounts_url(platform, result), status_code=303)
    response.delete_cookie(key=platform_publishing.oauth_state_cookie_name(platform, state or ""), path=f"/api/platforms/{platform}/oauth/callback")
    response.delete_cookie(key=f"klipnara_{platform}_state", path=f"/api/platforms/{platform}/oauth/callback")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/platforms/tiktok/oauth/callback")
def tiktok_oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    return _platform_oauth_callback("tiktok", request, code, state, error)


@app.get("/api/platforms/instagram/oauth/callback")
def instagram_oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    return _platform_oauth_callback("instagram", request, code, state, error)


@app.delete("/api/platforms/{platform}/accounts/{account_id}")
def disconnect_platform_account(platform: Literal["tiktok", "instagram"], account_id: str):
    return _platform_response(platform_publishing.disconnect_account, platform, account_id)


@app.post("/api/platforms/{platform}/accounts/{account_id}/default")
def default_platform_account(platform: Literal["tiktok", "instagram"], account_id: str):
    return _platform_response(platform_publishing.set_default_account, platform, account_id)


def _youtube_analytics_response(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except youtube_analytics.AnalyticsError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": str(exc)}) from None


@app.get("/api/youtube/analytics")
def youtube_analytics_dashboard(
    account_id: str,
    scope: str = "channel",
    start_date: str | None = None,
    end_date: str | None = None,
    force: bool = False,
):
    return _youtube_analytics_response(
        youtube_analytics.dashboard, account_id, scope, start_date, end_date, force,
    )


@app.get("/api/youtube/analytics/publications/{publication_id}")
def youtube_analytics_video_detail(
    publication_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    force: bool = False,
):
    return _youtube_analytics_response(
        youtube_analytics.video_detail, publication_id, start_date, end_date, force,
    )


@app.get("/api/youtube/analytics/publications/{publication_id}/retention")
def youtube_analytics_video_retention(
    publication_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    force: bool = False,
):
    return _youtube_analytics_response(
        youtube_analytics.retention, publication_id, start_date, end_date, force,
    )


@app.delete("/api/youtube/accounts/{account_id}")
def youtube_disconnect_account(account_id: str):
    try:
        return youtube.disconnect_account(account_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.delete("/api/youtube/accounts/{account_id}/record")
def youtube_delete_disconnected_account(account_id: str):
    try:
        return youtube.delete_disconnected_account(account_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.post("/api/youtube/accounts/{account_id}/default")
def youtube_default_account(account_id: str):
    try:
        return youtube.set_default_account(account_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, {"code": exc.code, "message": str(exc)}) from None


@app.post("/api/youtube/accounts/{account_id}/verify")
def youtube_verify_account(account_id: str):
    try:
        return youtube.verify_account(account_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.get("/api/youtube/publications")
def youtube_publications():
    return youtube.list_publications()


@app.get("/api/youtube/publications/{publication_id}")
def youtube_publication(publication_id: str):
    try:
        return youtube.get_publication(publication_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.post("/api/clips/{clip_id}/youtube-publications")
def create_youtube_publication(clip_id: str, body: YouTubePublishRequest):
    try:
        return youtube.enqueue_publication("clip", clip_id, body)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.get("/api/publishing/content")
def publishing_content():
    return youtube.list_publishing_content()


@app.get("/api/platform-publications")
def platform_publications():
    return platform_publishing.list_platform_publications()


@app.get("/api/platform-publications/{publication_id}/download")
def download_platform_manual_export(publication_id: str):
    path = _platform_response(platform_publishing.manual_export_file, publication_id)
    return FileResponse(path, media_type="video/mp4", filename="klipnara-manual-export.mp4")


@app.get("/api/publishing/{content_type}/{content_id}/platform-metadata/{platform}")
def platform_publishing_metadata(content_type: Literal["clip", "mood_render"], content_id: str, platform: Literal["tiktok", "instagram"], account_id: str | None = None):
    return _platform_response(platform_publishing.get_metadata, content_type, content_id, platform, account_id)


@app.put("/api/publishing/{content_type}/{content_id}/platform-metadata/{platform}")
def save_platform_publishing_metadata(
    content_type: Literal["clip", "mood_render"], content_id: str, platform: Literal["tiktok", "instagram"], body: PlatformMetadataDraft, account_id: str | None = None,
):
    return _platform_response(platform_publishing.save_metadata, content_type, content_id, platform, body.model_dump(exclude_unset=True), account_id)


@app.post("/api/publishing/{content_type}/{content_id}/platforms/{platform}/manual-export")
def prepare_platform_manual_export(
    content_type: Literal["clip", "mood_render"], content_id: str, platform: Literal["tiktok", "instagram"], body: PlatformManualExportRequest,
):
    return _platform_response(platform_publishing.prepare_manual_export, content_type, content_id, platform, body.model_dump())


@app.post("/api/publishing/{content_type}/{content_id}/platforms/{platform}/upload")
def enqueue_platform_upload(
    content_type: Literal["clip", "mood_render"], content_id: str, platform: Literal["tiktok", "instagram"], body: PlatformUploadRequest,
):
    result = _platform_response(platform_publishing.enqueue_platform_uploads, content_type, content_id, platform, body.model_dump())
    if any(item["status"] == "queued" for item in result["destinations"]):
        runner.start()
    return result


@app.post("/api/platform-publications/{publication_id}/reconcile")
def reconcile_platform_publication(publication_id: str):
    result = _platform_response(platform_publishing.reconcile_platform_upload, publication_id)
    if result.get("status") == "queued":
        runner.start()
    return result


@app.post("/api/platform-publications/{publication_id}/retry")
def retry_platform_publication(publication_id: str, body: PlatformRetryRequest):
    result = _platform_response(platform_publishing.retry_platform_upload, publication_id, body.model_dump())
    runner.start()
    return result


@app.post("/api/platform-publications/{publication_id}/cancel")
def cancel_platform_publication(publication_id: str):
    if not runner.cancel(publication_id):
        raise HTTPException(409, "Platform transfer cannot be cancelled in its current state.")
    return {"id": publication_id, "status": "cancelled_or_reconciling", "message": "Cancellation accepted; check provider state if transfer had started."}


@app.get("/api/publishing/{content_type}/{content_id}/metadata")
def publishing_metadata(content_type: Literal["clip", "mood_render"], content_id: str, account_id: str | None = None):
    try:
        return youtube.get_metadata_draft(content_type, content_id, account_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.put("/api/publishing/{content_type}/{content_id}/metadata")
def save_publishing_metadata(content_type: Literal["clip", "mood_render"], content_id: str, body: PublishingMetadataDraft, account_id: str | None = None):
    try:
        payload = body.model_dump(exclude_unset=True)
        return youtube.save_metadata_draft(content_type, content_id, payload, account_id or payload.get("account_id"))
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.get("/api/publishing/metadata-templates")
def publishing_metadata_templates():
    return youtube.list_metadata_templates()


@app.post("/api/publishing/metadata-templates")
def create_publishing_metadata_template(body: PublishingMetadataTemplate):
    try:
        return youtube.save_metadata_template(body.name, body.metadata.model_dump(exclude_unset=True))
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.delete("/api/publishing/metadata-templates/{template_id}")
def delete_publishing_metadata_template(template_id: str):
    try:
        return youtube.delete_metadata_template(template_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.get("/api/publishing/events")
def publishing_events(content_type: Literal["clip", "mood_render"] | None = None, content_id: str | None = None, publication_id: str | None = None):
    return youtube.list_publishing_events(content_type, content_id, publication_id)


@app.get("/api/publishing/calendar")
def publishing_calendar(start: str | None = None, end: str | None = None):
    return youtube.publishing_calendar(start, end)


@app.post("/api/publishing/{content_type}/{content_id}/youtube")
def create_publishing_upload(content_type: Literal["clip", "mood_render"], content_id: str, body: YouTubePublishRequest):
    try:
        result = youtube.enqueue_publications(content_type, content_id, body)
        if any(item["status"] == "queued" for item in result["destinations"]):
            runner.start()
        return result
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, {"code": exc.code, "message": str(exc)}) from None


@app.post("/api/publishing/{content_type}/{content_id}/thumbnail")
async def upload_publishing_thumbnail(content_type: Literal["clip", "mood_render"], content_id: str, file: UploadFile = File(...)):
    data = await file.read(2 * 1024 * 1024 + 1)
    try:
        return youtube.save_local_thumbnail(content_type, content_id, data, file.content_type or "")
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.get("/api/publishing/{content_type}/{content_id}/thumbnail")
def get_publishing_thumbnail(content_type: Literal["clip", "mood_render"], content_id: str):
    try:
        path, mime_type = youtube.local_thumbnail(content_type, content_id)
        return FileResponse(path, media_type=mime_type, content_disposition_type="inline")
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.post("/api/youtube/publications/{publication_id}/retry")
def retry_youtube_publication(publication_id: str):
    try:
        return youtube.retry_publication(publication_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.post("/api/youtube/publications/{publication_id}/cancel")
def cancel_youtube_publication(publication_id: str):
    try:
        return youtube.cancel_publication(publication_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


@app.post("/api/youtube/publications/{publication_id}/thumbnail")
def apply_youtube_publication_thumbnail(publication_id: str):
    try:
        return youtube.apply_publication_thumbnail(publication_id)
    except youtube.YouTubeError as exc:
        raise HTTPException(exc.status or 400, str(exc)) from None


def _insert_source(source_id, name, path, size, digest):
    try:
        metadata = probe(path)
        timestamp = now()
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM sources WHERE sha256=? ORDER BY created_at LIMIT 1", (digest,)).fetchone()
            if existing and Path(existing["path"]).is_file():
                Path(path).unlink(missing_ok=True)
                return existing["id"], existing["name"], {
                    "duration": existing["duration"], "width": existing["width"], "height": existing["height"],
                    "video_codec": existing["video_codec"], "audio_codec": existing["audio_codec"],
                }
            conn.execute(
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id, name[:180], str(path.resolve()), size, metadata["duration"], metadata["width"],
                    metadata["height"], metadata["video_codec"], metadata["audio_codec"], digest, timestamp,
                ),
            )
            register_source_asset(conn, {
                "id": source_id, "name": name[:180], "path": str(path.resolve()), "size_bytes": size,
                "duration": metadata["duration"], "width": metadata["width"], "height": metadata["height"],
                "sha256": digest, "created_at": timestamp,
            })
        return source_id, name[:180], metadata
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
        source_id, safe_name, metadata = _insert_source(source_id, safe_name or "Video", path, size, digest)
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
        source_id, name, metadata = _insert_source(source_id, name, path, size, digest)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"id": source_id, "name": name, "size_bytes": size, **metadata}


@app.get("/api/sources")
def list_sources():
    with connect() as conn:
        rows = conn.execute(
            "SELECT s.id,s.name,s.size_bytes,s.duration,s.width,s.height,s.created_at,s.video_codec,s.audio_codec,"
            "COALESCE(a.source,'local') AS asset_source,a.source_url,a.creator_name,a.creator_url,a.license_reference,a.favorite,"
            "(SELECT count(*) FROM clips c WHERE c.source_id=s.id) AS clip_count,"
            "(SELECT status FROM jobs j WHERE j.source_id=s.id AND j.kind NOT IN ('youtube_upload','batch_draft') ORDER BY created_at DESC LIMIT 1) AS latest_status "
            "FROM sources s LEFT JOIN library_assets a ON a.source_id=s.id ORDER BY s.created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/sources/{source_id}")
def get_source(source_id: str):
    with connect() as conn:
        source = unpack(conn.execute(
            "SELECT s.*,a.source AS asset_source,a.provider_asset_id,a.source_url,a.preview_url,a.creator_name,a.creator_url,"
            "a.license_reference,a.license_type,a.license_notes,a.attribution_text,a.favorite,a.last_used_at "
            "FROM sources s LEFT JOIN library_assets a ON a.source_id=s.id WHERE s.id=?", (source_id,),
        ).fetchone(), ("transcript_json",))
        if source is None:
            raise HTTPException(404, "Video source not found.")
        clips = [
            unpack(row, ("edit_json",))
            for row in conn.execute(
                "SELECT c.*,CASE WHEN j.kind='batch_draft' THEN 'quick_clip' ELSE j.kind END AS origin FROM clips c JOIN jobs j ON j.id=c.job_id "
                "WHERE c.source_id=? ORDER BY c.rank,c.created_at",
                (source_id,),
            ).fetchall()
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
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM jobs WHERE source_id=? AND status IN ('queued','preparing','transcribing','analyzing','rendering')", (source_id,)).fetchone():
            raise HTTPException(409, "Cancel active jobs before deleting this source.")
        if conn.execute("SELECT 1 FROM mood_assets WHERE source_id=? LIMIT 1", (source_id,)).fetchone():
            raise HTTPException(409, "Lepas video dari Mood Quotes draft sebelum menghapus source ini.")
        if conn.execute("SELECT 1 FROM video_batches WHERE source_id=? LIMIT 1", (source_id,)).fetchone():
            raise HTTPException(409, "Remove or finish Video Clips batches before deleting this source.")
        clips = conn.execute("SELECT rendered_path FROM clips WHERE source_id=?", (source_id,)).fetchall()
        row = conn.execute("SELECT path FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Video source not found.")
        source_path = Path(row["path"]).resolve()
        if source_path.parent not in {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()}:
            raise HTTPException(500, "Source path is outside the managed storage folder.")
        conn.execute("DELETE FROM library_assets WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    source_path.unlink(missing_ok=True)
    for clip in clips:
        if clip["rendered_path"]:
            try:
                _safe_clip_path(clip["rendered_path"]).unlink(missing_ok=True)
            except HTTPException:
                pass
    return {"deleted": True}


@app.post("/api/sources/{source_id}/quick-clips")
def create_quick_clip(source_id: str, body: QuickClipRequest):
    _require_storage(CLIP_DIR)
    if not math.isfinite(body.start) or not math.isfinite(body.end) or body.end <= body.start:
        raise HTTPException(422, "End Time must be greater than Start Time.")
    youtube_reference = None
    if body.youtube_reference:
        if (body.youtube_reference.start is None) != (body.youtube_reference.end is None):
            raise HTTPException(422, "YouTube reference start/end must be provided together.")
        try:
            parsed_reference = parse_youtube_url(body.youtube_reference.canonical_url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if parsed_reference["canonical_url"] != body.youtube_reference.canonical_url or parsed_reference["video_id"] != body.youtube_reference.video_id:
            raise HTTPException(422, "YouTube reference must use its canonical URL and matching video ID.")
        reference_start = body.start if body.youtube_reference.start is None else body.youtube_reference.start
        reference_end = body.end if body.youtube_reference.end is None else body.youtube_reference.end
        if not math.isfinite(reference_start) or not math.isfinite(reference_end) or reference_start < 0 or reference_end <= reference_start:
            raise HTTPException(422, "YouTube reference timestamps must satisfy 0 ≤ Start < End.")
        with connect() as conn:
            imported_source = conn.execute(
                "SELECT video_id,start_seconds,end_seconds FROM youtube_import_jobs "
                "WHERE source_id=? AND status='ready' LIMIT 1", (source_id,),
            ).fetchone()
        is_matching_import = bool(
            imported_source
            and imported_source["video_id"] == parsed_reference["video_id"]
            and math.isclose(reference_start, imported_source["start_seconds"], abs_tol=0.001)
            and math.isclose(reference_end, imported_source["end_seconds"], abs_tol=0.001)
        )
        youtube_reference = {
            "canonical_url": parsed_reference["canonical_url"],
            "video_id": parsed_reference["video_id"],
            "start": reference_start,
            "end": reference_end,
            "source_association": "auto_imported" if is_matching_import else "user_selected",
        }
        with connect() as conn:
            local_source = conn.execute("SELECT path FROM sources WHERE id=?", (source_id,)).fetchone()
        if local_source is None:
            raise HTTPException(404, "Video source not found.")
        try:
            local_duration = probe(_source_path(dict(local_source)))["duration"]
        except (HTTPException, MediaError, OSError):
            raise HTTPException(409, "Selected local source could not be revalidated; import it again before creating this clip.") from None
        if body.end > local_duration:
            raise HTTPException(422, "End Time exceeds the current local source duration; adjust the range before rendering.")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Clip title is required.")
    job_id, clip_id, timestamp = uuid.uuid4().hex, uuid.uuid4().hex, now()
    edit = {
        "trim_start": 0,
        "trim_end": body.end - body.start,
        "scene_mode": "single",
        "scenes": [{"id": f"scene-{clip_id}", "source_start": body.start, "source_end": body.end, "order": 0, "role": "body"}],
        "subtitle_enabled": False,
        "subtitle_mode": "off",
        "subtitle_segments": [],
        "subtitle_timebase": "clip",
        "style": "Clean",
        "resolution": body.resolution,
        "fps": 30,
        "quality": "balanced",
        "crop_x": 50,
        "crop_y": 50,
        "subtitle_size": 48,
        "subtitle_position": 82,
        "subtitle_color": "#ffffff",
        "subtitle_overrides": {},
        "audio": {"volume": 1, "muted": False, "fade_in": 0, "fade_out": 0, "normalize": False, "target_lufs": -18, "limiter": False},
        "title_overlay": {"enabled": False, "text": "", "font": "Arial", "size": 48, "color": "#ffffff", "position": 18, "duration": 3, "fade_in": 0.2, "fade_out": 0.2},
    }
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source_row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if source_row is None:
            raise HTTPException(404, "Video source not found.")
        source = dict(source_row)
        _source_path(source)
        if body.end > source["duration"]:
            raise HTTPException(422, "End Time cannot exceed source video duration.")
        rank = conn.execute("SELECT COALESCE(MAX(rank),0)+1 AS next_rank FROM clips WHERE source_id=?", (source_id,)).fetchone()["next_rank"]
        job_options = {"edit": edit}
        if youtube_reference:
            job_options["youtube_reference"] = youtube_reference
        conn.execute(
            "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,?,?,'quick_clip','queued','queued',NULL,'Quick Clip menunggu render',?,?,?)",
            (job_id, source_id, clip_id, json.dumps(job_options), timestamp, timestamp),
        )
        conn.execute(
            "INSERT INTO clips(id,source_id,job_id,start,end,title,reason,rank,edit_json,status,review_status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,'ready','needs_review',?)",
            (
                clip_id, source_id, job_id, body.start, body.end, title,
                "Dibuat manual berdasarkan timestamp pengguna.", rank, json.dumps(edit), timestamp,
            ),
        )
        conn.execute("UPDATE library_assets SET last_used_at=? WHERE source_id=?", (timestamp, source_id))
    return {"id": job_id, "clip_id": clip_id, "status": "queued"}


@app.post("/api/sources/{source_id}/generate")
def generate(source_id: str, body: GenerateOptions):
    with connect() as conn:
        source = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if source is None:
            raise HTTPException(404, "Video source not found.")
    if body.provider != "local" and not body.consent:
        raise HTTPException(400, "Confirm per-job transcript sharing before using cloud AI.")
    if body.provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(400, "Set OPENAI_API_KEY in backend environment before selecting OpenAI.")
    if body.provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(400, "Set GEMINI_API_KEY in backend environment before selecting Gemini.")
    if not source["audio_codec"] and not transcript_cache_matches(dict(source), body.language):
        raise HTTPException(409, "AI Smart Clip transcription requires source audio. Use Quick Clip for silent video.")
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
                "SELECT c.id,c.source_id,c.start,c.end,c.title,c.reason,c.rank,c.status,c.review_status,CASE WHEN j.kind='batch_draft' THEN 'quick_clip' ELSE j.kind END AS origin,"
                "(c.rendered_path IS NOT NULL) AS rendered,c.created_at,s.name AS source_name "
                "FROM clips c JOIN sources s ON s.id=c.source_id JOIN jobs j ON j.id=c.job_id "
                "ORDER BY c.created_at DESC,c.rank"
            ).fetchall()
        ]


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str):
    with connect() as conn:
        clip_row = conn.execute("SELECT c.*,CASE WHEN j.kind='batch_draft' THEN 'quick_clip' ELSE j.kind END AS origin,j.options_json AS source_job_options_json FROM clips c JOIN jobs j ON j.id=c.job_id WHERE c.id=?", (clip_id,)).fetchone()
        clip = unpack(clip_row, ("edit_json",))
        if clip is None:
            raise HTTPException(404, "Clip not found.")
        original_edit_json = clip_row["edit_json"]
        source_job_options = json.loads(clip.pop("source_job_options_json") or "{}")
        raw_reference = source_job_options.get("youtube_reference")
        clip["youtube_reference"] = raw_reference if isinstance(raw_reference, dict) else None
        source_row = conn.execute("SELECT * FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
        source = dict(source_row)
        jobs = [
            {key: row[key] for key in ("id", "kind", "status", "phase", "progress", "message", "created_at", "updated_at")}
            | {"provider": json.loads(row["options_json"] or "{}").get("provider")}
            for row in conn.execute("SELECT id,kind,status,phase,progress,message,options_json,created_at,updated_at FROM jobs WHERE clip_id=? AND kind!='youtube_upload' ORDER BY created_at DESC", (clip_id,)).fetchall()
        ]
    clip["rendered"] = bool(clip.pop("rendered_path"))
    segments = json.loads(source.pop("transcript_json") or "[]")
    edit = clip["edit"]
    edit.setdefault("scene_mode", "single")
    edit.setdefault("scenes", [{
        "id": f"scene-{clip_id}",
        "source_start": clip["start"] + edit.get("trim_start", 0),
        "source_end": clip["start"] + edit.get("trim_end", clip["end"] - clip["start"]),
        "order": 0,
        "role": "body",
    }])
    if not isinstance(edit.get("scenes"), list):
        edit["scenes"] = []
    edit.setdefault("transitions", {})
    for index, scene in enumerate(edit["scenes"]):
        scene.setdefault("id", f"scene-{clip_id}-{index}")
        scene.setdefault("order", index)
        scene.setdefault("role", "body")
    edit["transitions"] = normalize_scene_transitions(edit["scenes"], edit["transitions"])
    edit.setdefault("fps", 30)
    edit.setdefault("quality", "balanced")
    edit["audio"] = {"volume": 1, "muted": False, "fade_in": 0, "fade_out": 0, "normalize": False, "target_lufs": -18, "limiter": False, **(edit.get("audio") or {})}
    edit["title_overlay"] = {"enabled": False, "text": "", "font": "Arial", "size": 48, "color": "#ffffff", "position": 18, "duration": 3, "fade_in": 0.2, "fade_out": 0.2, **(edit.get("title_overlay") or {})}
    if "subtitle_mode" not in edit:
        edit["subtitle_mode"] = "manual" if edit.get("subtitle_enabled") else "off"
    edit.setdefault("subtitle_tracks", [])
    edit.setdefault("subtitle_active_track_id", None)
    edit.setdefault("subtitle_active_translation_id", None)
    edit.setdefault("subtitle_display_mode", "original")
    edit.setdefault("subtitle_caption_mode", "sentence")
    edit.setdefault("subtitle_preset", "Minimal Clean")
    edit.setdefault("subtitle_animation", "none")
    edit.setdefault("subtitle_animation_intensity", 0.12)
    edit.setdefault("subtitle_animation_duration", 100)
    edit.setdefault("subtitle_font", "Arial")
    edit.setdefault("subtitle_outline_color", "#101010")
    edit.setdefault("subtitle_highlight_color", "#ffd700")
    edit.setdefault("subtitle_outline", 2)
    edit.setdefault("subtitle_shadow", 1)
    edit.setdefault("subtitle_background", False)
    edit.setdefault("subtitle_alignment", "bottom")
    edit.setdefault("subtitle_caption_width", 90)
    edit.setdefault("subtitle_safe_margin", 8)
    active_track = next((track for track in edit["subtitle_tracks"] if track.get("id") == edit["subtitle_active_track_id"]), None)
    if active_track:
        edit["subtitle_segments"] = active_track.get("segments", [])
        edit["subtitle_timebase"] = active_track.get("timebase", "output")
    else:
        edit["subtitle_segments"] = clip_subtitle_segments(clip, edit, segments)
    if edit["scene_mode"] == "multi" and not active_track:
        edit["subtitle_timebase"] = "source"
    elif not active_track:
        edit.setdefault("subtitle_timebase", "clip")
    source.pop("path", None)
    source.pop("sha256", None)
    source.pop("transcript_model", None)
    scenes = output_scenes(clip, edit)
    signature = composition_signature(scenes)
    fingerprint = composition_fingerprint(source_row["sha256"], signature)
    repaired_track_ids = set()
    source_tracks = {track.get("id"): track.get("segments", []) for track in edit["subtitle_tracks"]}
    source_tracks["legacy"] = edit["subtitle_segments"]
    outdated_translations = []
    stale_tracks = []
    for track in edit["subtitle_tracks"]:
        if track.get("timebase") == "output":
            if track.get("composition_fingerprint") == fingerprint:
                if track.get("composition_signature") != signature:
                    track["composition_signature"] = signature
                    repaired_track_ids.add(track["id"])
            else:
                stale_tracks.append(track["id"])
        if track.get("source_type") == "translation":
            original = source_tracks.get(track.get("source_track_id"), [])
            if translation_is_outdated(track, original):
                outdated_translations.append(track["id"])
    if repaired_track_ids:
        stored_edit = json.loads(original_edit_json)
        for track in stored_edit.get("subtitle_tracks", []):
            if track.get("id") in repaired_track_ids:
                track["composition_signature"] = signature
        with connect() as conn:
            conn.execute(
                "UPDATE clips SET edit_json=? WHERE id=? AND edit_json=?",
                (json.dumps(stored_edit, ensure_ascii=False), clip_id, original_edit_json),
            )
    return {
        "clip": clip,
        "source": source,
        "transcript": segments,
        "subtitle_stt": {
            "local": local_transcription_available(),
            "openai": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
            "gemini": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        },
        "subtitle_status": {"composition_signature": signature, "composition_fingerprint": fingerprint,
                            "stale_track_ids": stale_tracks, "outdated_translation_ids": outdated_translations},
        "jobs": jobs,
    }


def _clear_youtube_reference_for_job(conn, job_id):
    row = conn.execute("SELECT options_json FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return False
    try:
        options = json.loads(row["options_json"])
    except json.JSONDecodeError:
        return False
    if not isinstance(options, dict) or "youtube_reference" not in options:
        return False
    options.pop("youtube_reference")
    conn.execute("UPDATE jobs SET options_json=? WHERE id=?", (json.dumps(options), job_id))
    return True


@app.delete("/api/clips/{clip_id}/youtube-reference")
def clear_clip_youtube_reference(clip_id: str):
    with connect() as conn:
        row = conn.execute("SELECT job_id FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clip not found.")
        deleted = _clear_youtube_reference_for_job(conn, row["job_id"])
    return {"deleted": deleted}


@app.patch("/api/clips/{clip_id}")
def edit_clip(clip_id: str, body: ClipEdit):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clip not found.")
        if conn.execute(
            "SELECT 1 FROM youtube_publications WHERE clip_id=? AND status IN ('pending','uploading')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Cancel pending YouTube upload before editing this clip.")
        if conn.execute("SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')", (clip_id,)).fetchone():
            raise HTTPException(409, "Wait for the active render to finish or cancel it before editing.")
        if conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND kind IN ('subtitle_transcribe','subtitle_translate') "
            "AND status IN ('queued','preparing','preparing_audio','uploading','transcribing','processing_result')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Wait for the subtitle job to finish or cancel it before editing.")
        batch_item = conn.execute(
            "SELECT i.id,i.batch_id,i.status,i.job_id,b.status AS batch_status FROM video_batch_items i "
            "JOIN video_batches b ON b.id=i.batch_id WHERE i.clip_id=?",
            (clip_id,),
        ).fetchone()
        paused_pending = batch_item and batch_item["status"] == "queued" and batch_item["batch_status"] == "paused" and batch_item["job_id"] is None
        if batch_item and batch_item["status"] in {"queued", "rendering"} and not paused_pending:
            raise HTTPException(409, "This item is queued in a batch. Pause or wait before editing.")
        clip = dict(row)
        edit = json.loads(clip["edit_json"])
        original_edit = dict(edit)
        changes = body.model_dump(exclude_unset=True)
        if isinstance(changes.get("subtitle_segments"), list):
            active_id = changes.get("subtitle_active_track_id", edit.get("subtitle_active_track_id"))
            active_track = next((track for track in (changes.get("subtitle_tracks") or edit.get("subtitle_tracks") or []) if track.get("id") == active_id), None)
            previous_segments = active_track.get("segments", []) if active_track else edit.get("subtitle_segments", [])
            previous_by_id = {item.get("id"): item for item in previous_segments}
            for segment in changes["subtitle_segments"]:
                previous = previous_by_id.get(segment.get("id"))
                changed = previous and any(segment.get(key) != previous.get(key) for key in ("text", "start", "end"))
                if changed and previous.get("words") and segment.get("words") == previous.get("words"):
                    segment["word_alignment_reviewed"] = False
        source_info = conn.execute("SELECT duration,sha256 FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
        source_duration = source_info["duration"]
        if any(key in changes and changes[key] is None for key in (
            "trim_start", "trim_end", "scene_mode", "scenes", "transitions", "subtitle_mode", "subtitle_enabled",
            "subtitle_segments", "subtitle_tracks", "subtitle_timebase", "subtitle_display_mode", "subtitle_caption_mode",
            "subtitle_preset", "subtitle_animation", "subtitle_font", "subtitle_outline_color", "subtitle_highlight_color",
            "subtitle_animation_intensity", "subtitle_animation_duration",
            "subtitle_alignment", "subtitle_caption_width", "subtitle_safe_margin", "subtitle_outline", "subtitle_shadow",
            "subtitle_background", "subtitle_overrides",
            "style", "resolution", "crop_x", "crop_y", "subtitle_size", "subtitle_position", "subtitle_color", "audio",
            "title_overlay", "fps", "quality", "camera",
        )):
            raise HTTPException(422, "Scene, subtitle, audio, and title settings cannot be null.")
        defaults = {
            "audio": {"volume": 1, "muted": False, "fade_in": 0, "fade_out": 0, "normalize": False, "target_lufs": -18, "limiter": False},
            "title_overlay": {"enabled": False, "text": "", "font": "Arial", "size": 48, "color": "#ffffff", "position": 18, "duration": 3, "fade_in": 0.2, "fade_out": 0.2},
        }
        for key, values in defaults.items():
            if key in changes:
                changes[key] = {**values, **(edit.get(key) or {}), **changes[key]}
        if changes.get("subtitle_preset") and changes["subtitle_preset"] != edit.get("subtitle_preset"):
            changes.update(PRESETS[changes["subtitle_preset"]])
        color = changes.get("subtitle_color")
        if color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise HTTPException(422, "Subtitle color must be a hex RGB value.")
        for key in ("subtitle_outline_color", "subtitle_highlight_color"):
            if key in changes and not re.fullmatch(r"#[0-9a-fA-F]{6}", changes[key]):
                raise HTTPException(422, f"{key} must be a hex RGB value.")
        title_overlay = changes.get("title_overlay")
        if title_overlay is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", title_overlay["color"]):
            raise HTTPException(422, "Title color must be a hex RGB value.")
        next_edit = {**edit, **changes}
        scene_mode = next_edit.get("scene_mode", "single")
        if scene_mode == "multi" and next_edit.get("subtitle_timebase", "clip") == "clip":
            changes["subtitle_segments"] = [
                {
                    **segment,
                    "start": segment["start"] + clip["start"],
                    "end": segment["end"] + clip["start"],
                    **({"words": [
                        {**word,
                         **({"start": word["start"] + clip["start"]} if isinstance(word.get("start"), (int, float)) else {}),
                         **({"end": word["end"] + clip["start"]} if isinstance(word.get("end"), (int, float)) else {})}
                        for word in segment.get("words", [])
                    ]} if isinstance(segment.get("words"), list) else {}),
                }
                for segment in next_edit.get("subtitle_segments") or []
            ]
            changes["subtitle_timebase"] = "source"
            next_edit.update(changes)
        scenes = next_edit.get("scenes")
        ordered_scenes = sorted(scenes or [], key=lambda scene: scene["order"])
        if scenes is not None:
            scenes = [{**scene, "role": scene.get("role", "body")} for scene in scenes]
            changes["scenes"] = scenes
            next_edit["scenes"] = scenes
        if scene_mode == "multi" and not scenes:
            raise HTTPException(422, "Multi-Scene needs at least one scene.")
        output_duration = float(next_edit.get("trim_end", clip["end"] - clip["start"])) - float(next_edit.get("trim_start", 0))
        if scenes is not None:
            if not scenes or len(scenes) > MAX_SCENES:
                raise HTTPException(422, f"Scene count must be between 1 and {MAX_SCENES}.")
            if scene_mode == "single" and len(scenes) != 1:
                raise HTTPException(422, "Single Scene mode accepts exactly one scene.")
            if [scene["order"] for scene in ordered_scenes] != list(range(len(ordered_scenes))):
                raise HTTPException(422, "Scene order must be unique and contiguous from zero.")
            if len({scene["id"] for scene in scenes}) != len(scenes):
                raise HTTPException(422, "Scene IDs must be unique.")
            if sum(scene["role"] == "hook" for scene in scenes) > 1 or sum(scene["role"] == "ending" for scene in scenes) > 1:
                raise HTTPException(422, "Select at most one hook and one ending scene.")
            for scene in ordered_scenes:
                start, end = scene["source_start"], scene["source_end"]
                too_short = end - start < MIN_SCENE_SECONDS if scene_mode == "multi" else end <= start
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end > source_duration or too_short:
                    message = f"Each Multi-Scene interval must be at least {MIN_SCENE_SECONDS:.1f}s and stay within source duration." if scene_mode == "multi" else "Single Scene interval must stay within source duration."
                    raise HTTPException(422, message)
        camera_settings = next_edit.get("camera")
        if camera_settings is not None:
            try:
                camera_settings = ClipCameraSettings.model_validate(camera_settings).model_dump()
            except ValidationError as exc:
                raise HTTPException(422, f"Invalid camera configuration: {exc}") from None
            camera_scenes = ordered_scenes if scene_mode == "multi" else [{
                "id": (ordered_scenes[0]["id"] if ordered_scenes else f"scene-{clip_id}"),
                "source_start": float(clip["start"]) + float(next_edit.get("trim_start", 0)),
                "source_end": float(clip["start"]) + float(next_edit.get("trim_end", clip["end"] - clip["start"])),
            }]
            scene_ranges = {scene["id"]: scene for scene in camera_scenes}
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", scene_id) for scene_id in camera_settings["scenes"]):
                raise HTTPException(422, "Camera scene IDs must be valid stable scene IDs.")
            unknown_scenes = set(camera_settings["scenes"]) - set(scene_ranges)
            if unknown_scenes:
                raise HTTPException(422, "Camera data references a scene that no longer exists.")
            camera_fps = int(next_edit.get("fps", 30))
            keyframe_ids = set()
            for scene_id, scene_camera in camera_settings["scenes"].items():
                max_frame = math.floor((scene_ranges[scene_id]["source_end"] - scene_ranges[scene_id]["source_start"]) * camera_fps + 1e-6)
                frames = [item["frame"] for item in scene_camera["keyframes"]]
                ids = [item["id"] for item in scene_camera["keyframes"]]
                if len(frames) != len(set(frames)):
                    raise HTTPException(422, f"Camera keyframe frames must be unique in scene {scene_id}.")
                if any(frame >= max_frame for frame in frames):
                    raise HTTPException(422, f"Camera keyframe in scene {scene_id} falls outside its frame-aligned duration.")
                if any(keyframe_id in keyframe_ids for keyframe_id in ids) or len(ids) != len(set(ids)):
                    raise HTTPException(422, "Camera keyframe IDs must be unique.")
                keyframe_ids.update(ids)
                scene_camera["keyframes"].sort(key=lambda item: item["frame"])
            next_edit["camera"] = camera_settings
            if "camera" in changes:
                changes["camera"] = camera_settings
        transition_scenes = ordered_scenes if scene_mode == "multi" and scenes else scenes[:1] if scenes else []
        normalized_transitions = normalize_scene_transitions(transition_scenes, next_edit.get("transitions", {}))
        previous_scene_list = edit.get("scenes") or []
        previous_transitions = normalize_scene_transitions(previous_scene_list, edit.get("transitions", {}))
        previous_transition_timing = {}
        for key, item in previous_transitions.items():
            if item.get("type", "none") == "none":
                continue
            try:
                previous_transition_timing[key] = (float(item.get("duration", 0.25)), item.get("timing_mode", "overlap"))
            except (TypeError, ValueError):
                continue
        for key, transition in normalized_transitions.items():
            if transition.get("type", "none") == "none":
                continue
            try:
                duration = float(transition.get("duration", 0.25))
            except (TypeError, ValueError):
                continue  # validate_scene_transitions returns the canonical error below
            timing = (duration, transition.get("timing_mode", "overlap"))
            if timing != previous_transition_timing.get(key) and not (MIN_TRANSITION_SECONDS <= duration <= MAX_TRANSITION_SECONDS):
                raise HTTPException(422, f"New transition duration must be {MIN_TRANSITION_SECONDS:.1f}-{MAX_TRANSITION_SECONDS:g} seconds.")
        try:
            validate_scene_transitions(transition_scenes, normalized_transitions, int(next_edit.get("fps", 30)))
        except MediaError as exc:
            raise HTTPException(422, str(exc)) from None
        if normalized_transitions != next_edit.get("transitions", {}):
            changes["transitions"] = normalized_transitions
        next_edit["transitions"] = normalized_transitions
        output_duration = scene_output_duration(output_scenes(clip, next_edit))
        if "subtitle_tracks" in changes:
            current_signature = composition_signature(output_scenes(clip, next_edit))
            current_fingerprint = composition_fingerprint(source_info["sha256"], current_signature)
            for track in changes["subtitle_tracks"]:
                if track["source_type"] == "manual" and track["timebase"] == "output" and track.get("composition_signature") == current_signature:
                    track["composition_fingerprint"] = current_fingerprint
        overrides = changes.get("subtitle_overrides")
        if overrides is not None and any(len(str(text)) > 500 for text in overrides.values()):
            raise HTTPException(422, "Subtitle text limit is 500 characters per segment.")
        subtitle_segments = changes.get("subtitle_segments")
        if subtitle_segments is not None:
            ids = [segment["id"] for segment in subtitle_segments]
            if len(ids) != len(set(ids)):
                raise HTTPException(422, "Subtitle segment IDs must be unique.")
            timebase = changes.get("subtitle_timebase", edit.get("subtitle_timebase", "clip"))
            maximum_time = source_duration if timebase == "source" else output_duration if timebase == "output" else clip["end"] - clip["start"]
            if timebase == "output":
                active_id = changes.get("subtitle_active_track_id", edit.get("subtitle_active_track_id"))
                active_track = next((track for track in (changes.get("subtitle_tracks", edit.get("subtitle_tracks", [])) or []) if track["id"] == active_id), None)
                if active_track and active_track.get("composition_signature") != composition_signature(output_scenes(clip, next_edit)):
                    maximum_time = 24 * 60 * 60
            if any(
                not math.isfinite(segment["start"])
                or not math.isfinite(segment["end"])
                or not (0 <= segment["start"] < segment["end"] <= maximum_time)
                for segment in subtitle_segments
            ):
                raise HTTPException(422, f"Subtitle times must use {timebase} seconds and stay inside that timeline.")
            for segment in subtitle_segments:
                _validate_word_timing_draft(segment, maximum_time, timebase)
        if "subtitle_tracks" in changes:
            tracks = changes["subtitle_tracks"]
            track_ids = [track["id"] for track in tracks]
            if len(track_ids) != len(set(track_ids)):
                raise HTTPException(422, "Subtitle track IDs must be unique.")
            for track in tracks:
                segment_ids = [item["id"] for item in track["segments"]]
                if len(segment_ids) != len(set(segment_ids)):
                    raise HTTPException(422, "Segment IDs must be unique inside each subtitle track.")
                timebase = track["timebase"]
                maximum_time = source_duration if timebase == "source" else output_duration if timebase == "output" else clip["end"] - clip["start"]
                if timebase == "output" and track.get("composition_signature") != composition_signature(output_scenes(clip, next_edit)):
                    maximum_time = 24 * 60 * 60
                for segment in track["segments"]:
                    start, end = segment["start"], segment["end"]
                    if not math.isfinite(start) or not math.isfinite(end) or not (0 <= start < end <= maximum_time):
                        raise HTTPException(422, f"Subtitle track times must use {timebase} seconds and stay inside that timeline.")
                    _validate_word_timing_draft(segment, maximum_time, timebase)
            active_id = changes.get("subtitle_active_track_id", edit.get("subtitle_active_track_id"))
            if active_id is not None and active_id not in track_ids:
                raise HTTPException(422, "Active subtitle track does not exist.")
            translation_id = changes.get("subtitle_active_translation_id", edit.get("subtitle_active_translation_id"))
            translation = next((track for track in tracks if track["id"] == translation_id), None)
            if translation_id is not None and (translation is None or translation["source_type"] != "translation"):
                raise HTTPException(422, "Active translation track does not exist.")
            if translation and translation.get("source_track_id") not in {active_id, "legacy"}:
                raise HTTPException(422, "Translation track does not map to the selected original subtitle track.")
        next_style = changes.get("style")
        if next_style and next_style != edit["style"] and "subtitle_color" not in changes:
            if next_style == "Highlight" and edit["subtitle_color"].lower() == "#ffffff":
                changes["subtitle_color"] = "#ffd700"
            elif edit["style"] == "Highlight" and edit["subtitle_color"].lower() == "#ffd700":
                changes["subtitle_color"] = "#ffffff"
        edit.update(changes)
        if "subtitle_tracks" in changes:
            old_tracks = {track["id"]: track for track in original_edit.get("subtitle_tracks", [])}
            for track in edit.get("subtitle_tracks", []):
                old_track = old_tracks.get(track["id"])
                if not old_track:
                    continue
                old_segments = {segment["id"]: segment for segment in old_track.get("segments", [])}
                for segment in track.get("segments", []):
                    old = old_segments.get(segment["id"])
                    changed = old is None or (
                        segment.get("text") != old.get("text")
                        or segment.get("start") != old.get("start")
                        or segment.get("end") != old.get("end")
                        or segment.get("words") != old.get("words")
                    )
                    if changed and (segment.get("words") or (old or {}).get("words")):
                        segment["word_alignment_reviewed"] = False
        if "subtitle_segments" in changes:
            active_id = edit.get("subtitle_active_track_id")
            active_track = next((track for track in edit.get("subtitle_tracks", []) if track.get("id") == active_id), None)
            original_active_id = original_edit.get("subtitle_active_track_id")
            original_track = next((track for track in original_edit.get("subtitle_tracks", []) if track.get("id") == original_active_id), None)
            same_active_track = active_id == original_active_id
            previous_segments = (
                original_track.get("segments", []) if same_active_track and original_track
                else active_track.get("segments", []) if active_track
                else original_edit.get("subtitle_segments", []) if same_active_track
                else []
            )
            old_by_id = {item["id"]: item for item in previous_segments}
            synchronized = []
            for segment in changes["subtitle_segments"]:
                item = dict(segment)
                old = old_by_id.get(item["id"])
                segment_changed = bool(old and (item["text"] != old.get("text") or item["start"] != old.get("start") or item["end"] != old.get("end")))
                word_data_changed = item.get("words") != (old or {}).get("words")
                if segment_changed:
                    if not word_data_changed and old.get("words"):
                        item["words"] = old["words"]
                    item["original_text"] = old.get("original_text", old.get("text", ""))
                    item["edited"] = True
                if same_active_track and (word_data_changed or segment_changed) and (item.get("words") or (old or {}).get("words")):
                    item["word_alignment_reviewed"] = False
                elif old and old.get("words") and not word_data_changed:
                    item["words"] = old["words"]
                synchronized.append(item)
            if active_track:
                active_track["segments"] = synchronized
                active_track["timebase"] = edit.get("subtitle_timebase", active_track.get("timebase", "clip"))
                active_track["edited"] = True
            else:
                edit["subtitle_segments"] = synchronized
        was_subtitle_enabled = bool(original_edit.get("subtitle_enabled", original_edit.get("subtitle_mode") not in {None, "off"}))
        word_pop_activation = (
            "subtitle_caption_mode" in changes and changes["subtitle_caption_mode"] == "word_pop"
            or "subtitle_enabled" in changes and changes["subtitle_enabled"] is True and not was_subtitle_enabled
            or "subtitle_mode" in changes and changes["subtitle_mode"] != "off" and not was_subtitle_enabled
            or edit.get("subtitle_caption_mode") == "word_pop" and edit.get("subtitle_enabled") and (
                "subtitle_display_mode" in changes and changes["subtitle_display_mode"] != "original"
                or "subtitle_active_track_id" in changes and changes["subtitle_active_track_id"] != original_edit.get("subtitle_active_track_id")
                or "subtitle_active_translation_id" in changes and changes["subtitle_active_translation_id"] != original_edit.get("subtitle_active_translation_id")
            )
        )
        if edit.get("subtitle_caption_mode") == "word_pop" and word_pop_activation:
            if edit.get("subtitle_display_mode", "original") != "original":
                raise HTTPException(422, "Word Pop supports original captions only. Select Original Only before continuing.")
            active_id = edit.get("subtitle_active_track_id")
            active_track = next((track for track in edit.get("subtitle_tracks", []) if track.get("id") == active_id), None)
            word_pop_segments = active_track.get("segments", []) if active_track else edit.get("subtitle_segments", [])
            track_timebase = active_track.get("timebase", edit.get("subtitle_timebase", "clip")) if active_track else edit.get("subtitle_timebase", "clip")
            scenes = output_scenes(clip, edit)
            if track_timebase == "output":
                output_end = scenes[-1]["timeline_end"] if scenes else 0
                word_pop_segments = [item for item in word_pop_segments if item["start"] < output_end and item["end"] > 0]
            else:
                source_offset = float(clip["start"]) if track_timebase == "clip" else 0
                word_pop_segments = [item for item in word_pop_segments if source_interval_visible(
                    item["start"] + source_offset, item["end"] + source_offset, scenes,
                )]
            if not word_pop_segments or any(not valid_word_alignment(segment) for segment in word_pop_segments):
                raise HTTPException(422, "Word Pop needs reviewed, non-overlapping word timestamps for every caption. Add manual timings or use a word-timestamp provider.")
        if "subtitle_mode" in changes:
            edit["subtitle_enabled"] = edit["subtitle_mode"] != "off"
        elif "subtitle_enabled" in changes:
            edit["subtitle_mode"] = "manual" if edit["subtitle_enabled"] else "off"
        length = clip["end"] - clip["start"]
        edit.setdefault("trim_start", 0)
        edit.setdefault("trim_end", length)
        if not (0 <= edit["trim_start"] < edit["trim_end"] <= length):
            raise HTTPException(422, "Trim range must stay inside the candidate clip.")
        audio = edit.get("audio") or {}
        if float(audio.get("fade_in", 0)) + float(audio.get("fade_out", 0)) > output_duration:
            raise HTTPException(422, "Combined audio fades cannot exceed output duration.")
        title = edit.get("title_overlay") or {}
        if title.get("enabled") and (not title.get("text", "").strip() or float(title.get("duration", 0)) > output_duration):
            raise HTTPException(422, "Enabled title needs text and must fit inside output duration.")
        changed = edit != original_edit
        next_status = "needs_render" if changed and clip["rendered_path"] else clip["status"]
        review_status = "needs_review" if changed else clip["review_status"]
        reviewed_hash = None if changed else clip["reviewed_render_sha256"]
        conn.execute(
            "UPDATE clips SET edit_json=?,status=?,review_status=?,reviewed_render_sha256=? WHERE id=?",
            (json.dumps(edit), next_status, review_status, reviewed_hash, clip_id),
        )
        if changed and batch_item:
            conn.execute(
                "UPDATE video_batch_items SET custom_override=1,status=CASE WHEN status IN ('completed','failed','cancelled') THEN 'ready' ELSE status END,"
                "error=NULL,updated_at=? WHERE id=?",
                (now(), batch_item["id"]),
            )
            if batch_item["batch_status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
                conn.execute("UPDATE video_batches SET status='ready',error=NULL,updated_at=? WHERE id=?", (now(), batch_item["batch_id"]))
    return edit


@app.post("/api/clips/{clip_id}/subtitles/auto-generate")
def auto_generate_clip_subtitles(clip_id: str, body: SubtitleGenerateRequest):
    with connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clip not found.")
        _assert_batch_item_editable(conn, clip_id)
        clip = dict(row)
        source_row = conn.execute("SELECT * FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
        source = dict(source_row)
        if not source.get("audio_codec"):
            raise HTTPException(409, "Source video has no audio. Auto Generate unavailable; Manual subtitles remain available.")
        if conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND status IN ('queued','preparing','rendering')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Wait for the active clip render to finish before generating subtitles.")
        _assert_batch_item_editable(conn, clip_id)
        if conn.execute(
            "SELECT 1 FROM youtube_publications WHERE clip_id=? AND status IN ('pending','uploading')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Cancel pending YouTube upload before changing this clip.")
        original_edit_json = clip["edit_json"]
        edit = json.loads(original_edit_json)

    if body.provider == "openai":
        if not body.consent:
            raise HTTPException(400, "Confirm explicit audio sharing consent before sending the selected segment to OpenAI.")
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise HTTPException(400, "Set OPENAI_API_KEY before selecting OpenAI speech-to-text.")
    elif not local_transcription_available():
        raise HTTPException(400, "Local STT needs whisper.cpp and WHISPER_MODEL_PATH; Manual subtitles need neither.")

    length = clip["end"] - clip["start"]
    selected_scene = None
    if body.scene_id:
        selected_scene = next((scene for scene in output_scenes(clip, edit) if scene["id"] == body.scene_id), None)
        if selected_scene is None:
            raise HTTPException(422, "Selected scene no longer exists. Reload the editor and retry.")
    elif edit.get("scene_mode") == "multi":
        raise HTTPException(422, "Select a scene before generating subtitles in Multi-Scene mode.")
    if selected_scene:
        source_start, source_end = selected_scene["source_start"], selected_scene["source_end"]
        trim_start = 0.0
        selected_duration = source_end - source_start
    else:
        trim_start = edit.get("trim_start", 0)
        trim_end = edit.get("trim_end", length)
        if not (0 <= trim_start < trim_end <= length):
            raise HTTPException(422, "Trim range must stay inside the candidate clip.")
        source_start, source_end = clip["start"] + trim_start, clip["start"] + trim_end
        selected_duration = trim_end - trim_start
    try:
        audio_path = extract_subtitle_audio(_source_path(source), source_start, source_end, body.provider)
    except MediaError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        if body.provider == "local":
            generated, _, _ = transcribe(audio_path, body.language, threading.Event())
        else:
            generated = transcribe_openai(audio_path, body.language)
    except MediaError as exc:
        message = str(exc)
        if "No timestamped speech" in message:
            raise HTTPException(422, "No speech detected in the selected segment. Manual subtitles remain available.") from None
        raise HTTPException(502 if body.provider == "openai" else 503, message) from None
    finally:
        audio_path.unlink(missing_ok=True)

    generated_segments = []
    for item in generated:
        start = max(0.0, float(item["start"]))
        end = min(selected_duration, float(item["end"]))
        text = str(item.get("text") or "").strip()[:500]
        if text and start < end:
            absolute_start = min(source_end, max(source_start, round(source_start + start, 3)))
            absolute_end = min(source_end, max(source_start, round(source_start + end, 3)))
            source_timebase = bool(selected_scene) or edit.get("subtitle_timebase") == "source"
            segment_start = absolute_start if source_timebase else absolute_start - clip["start"]
            segment_end = absolute_end if source_timebase else absolute_end - clip["start"]
            if segment_start < segment_end:
                generated_segments.append({
                    "id": f"stt-{uuid.uuid4().hex}",
                    "start": segment_start,
                    "end": segment_end,
                    "text": text,
                })
                if len(generated_segments) > 500:
                    raise HTTPException(422, "Selected range produced over 500 subtitle segments. Shorten the range and retry.")
    if not generated_segments:
        raise HTTPException(422, "No speech detected in the selected segment. Manual subtitles remain available.")

    source_timebase = bool(selected_scene) or edit.get("subtitle_timebase") == "source"
    if source_timebase:
        existing = source_subtitle_segments(clip, edit, json.loads(source.get("transcript_json") or "[]"))
        if selected_scene:
            existing = [
                item for item in existing
                if not (
                    (item["id"].startswith("transcript-") or item["id"].startswith("stt-"))
                    and item["start"] < source_end and item["end"] > source_start
                )
            ]
        manual_ranges = [(item["start"], item["end"]) for item in existing if not item["id"].startswith(("transcript-", "stt-"))]
        generated_segments = [
            item for item in generated_segments
            if not any(item["start"] < end and item["end"] > start for start, end in manual_ranges)
        ]
        edit["subtitle_segments"] = existing + generated_segments
        edit["subtitle_timebase"] = "source"
    else:
        edit["subtitle_segments"] = generated_segments
        edit["subtitle_timebase"] = "clip"
    if not generated_segments:
        raise HTTPException(422, "Existing manual subtitles cover this scene; no duplicate captions were added.")
    edit["subtitle_mode"] = "auto"
    edit["subtitle_enabled"] = True
    edit["subtitle_overrides"] = {}
    edit["subtitle_active_track_id"] = None
    edit["subtitle_active_translation_id"] = None
    edit["subtitle_display_mode"] = "original"
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _assert_batch_item_editable(conn, clip_id)
        if conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND status IN ('queued','preparing','rendering')",
            (clip_id,),
        ).fetchone() or conn.execute(
            "SELECT 1 FROM youtube_publications WHERE clip_id=? AND status IN ('pending','uploading')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Clip changed state while subtitles were being generated. Retry after active work finishes.")
        changed = conn.execute(
            "UPDATE clips SET edit_json=?,status=CASE WHEN rendered_path IS NULL THEN status ELSE 'needs_render' END,"
            "review_status='needs_review',reviewed_render_sha256=NULL WHERE id=? AND edit_json=?",
            (json.dumps(edit, ensure_ascii=False), clip_id, original_edit_json),
        ).rowcount
        if not changed:
            raise HTTPException(409, "Clip edits changed during transcription. Save or reload, then try again.")
    return {"edit": edit, "provider": body.provider}


def _queue_subtitle_job(clip, kind, options, expected_edit_json):
    job_id, timestamp = uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT edit_json,source_id FROM clips WHERE id=?", (clip["id"],)).fetchone()
        if current is None:
            raise HTTPException(404, "Clip not found.")
        if current["edit_json"] != expected_edit_json:
            raise HTTPException(409, "Clip edits changed while preparing subtitle job. Reload and retry.")
        if conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')",
            (clip["id"],),
        ).fetchone():
            raise HTTPException(409, "Wait for active render before changing subtitle tracks.")
        _assert_batch_item_editable(conn, clip["id"])
        if conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND kind IN ('subtitle_transcribe','subtitle_translate') "
            "AND status IN ('queued','preparing','preparing_audio','uploading','transcribing','processing_result')",
            (clip["id"],),
        ).fetchone():
            raise HTTPException(409, "Subtitle job already queued or running for this clip.")
        if conn.execute(
            "SELECT 1 FROM youtube_publications WHERE clip_id=? AND status IN ('pending','uploading')",
            (clip["id"],),
        ).fetchone():
            raise HTTPException(409, "Cancel pending YouTube upload before changing this clip.")
        conn.execute(
            "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, current["source_id"], clip["id"], kind, "queued", "queued", None,
             "Menunggu worker subtitle lokal", json.dumps(options, ensure_ascii=False), timestamp, timestamp),
        )
    return job_id


@app.post("/api/clips/{clip_id}/subtitles/transcribe")
def queue_clip_subtitle_transcription(clip_id: str, body: SubtitleTranscriptionRequest):
    with connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clip not found.")
        clip = dict(row)
        source_row = conn.execute("SELECT * FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
        source = dict(source_row)
        original_edit_json = clip["edit_json"]
        edit = json.loads(original_edit_json)
    if not source.get("audio_codec"):
        raise HTTPException(409, "Source video has no audio. Auto Generate unavailable; Manual and Import remain available.")
    if body.provider == "local":
        if not local_transcription_available():
            raise HTTPException(400, "Local STT needs whisper.cpp and WHISPER_MODEL_PATH.")
    else:
        if not body.consent:
            raise HTTPException(400, f"Confirm explicit audio-sharing consent before uploading the composition to {body.provider}.")
        key_name = "OPENAI_API_KEY" if body.provider == "openai" else "GEMINI_API_KEY"
        if not os.environ.get(key_name, "").strip():
            raise HTTPException(400, f"Set {key_name} before selecting {body.provider} speech-to-text.")
    scenes = output_scenes(clip, edit)
    duration = scene_output_duration(scenes)
    if not math.isfinite(duration) or duration <= 0:
        raise HTTPException(422, "Current composition has no valid output duration.")
    if body.provider == "gemini" and duration > 1800:
        raise HTTPException(422, "Gemini word timestamps support audio up to 30 minutes. Shorten the composition.")
    if body.provider == "openai" and duration * 6000 > 24 * 1024 * 1024:
        raise HTTPException(422, "Estimated compressed audio exceeds OpenAI's 25 MiB limit. Shorten the composition.")
    signature = composition_signature(scenes)
    fingerprint = composition_fingerprint(source["sha256"], signature)
    cached_model = {"openai": "gpt-transcribe", "gemini": "gemini-3.5-transcribe"}.get(body.provider)
    if cached_model:
        cached = next((track for track in edit.get("subtitle_tracks", [])
                       if track.get("source_type") == "generated" and track.get("provider") == body.provider
                        and track.get("model") == cached_model and track.get("language") in {body.language, "unknown", "id-ID", "en-US"}
                        and track.get("composition_fingerprint") == fingerprint), None)
        if cached:
            return {"cached": True, "track": cached, "duration": duration}
    if len(edit.get("subtitle_tracks", [])) >= 20:
        raise HTTPException(409, "Subtitle track limit reached (20). Remove a draft before transcribing.")
    snapshot = {key: edit[key] for key in ("scene_mode", "scenes", "transitions", "trim_start", "trim_end") if key in edit}
    options = {
        "provider": body.provider, "language": body.language, "consent_at": now() if body.provider != "local" else None,
        "duration": duration, "edit_snapshot": snapshot,
        "scenes": [{key: scene[key] for key in ("id", "source_start", "source_end", "timeline_start", "transition_duration", "transition_timing_mode")} for scene in scenes],
        "composition_signature": signature, "composition_fingerprint": fingerprint,
        "track_id": f"stt-{uuid.uuid4().hex}",
    }
    job_id = _queue_subtitle_job(clip, "subtitle_transcribe", options, original_edit_json)
    return {"id": job_id, "status": "queued", "provider": body.provider, "duration": duration}


@app.post("/api/clips/{clip_id}/subtitles/translate")
def queue_clip_subtitle_translation(clip_id: str, body: SubtitleTranslationRequest):
    with connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clip not found.")
        clip = dict(row)
        original_edit_json = clip["edit_json"]
        edit = json.loads(original_edit_json)
    if not body.consent:
        raise HTTPException(400, f"Confirm explicit subtitle-text sharing consent before sending cues to {body.provider}.")
    key_name = "OPENAI_API_KEY" if body.provider == "openai" else "GEMINI_API_KEY"
    if not os.environ.get(key_name, "").strip():
        raise HTTPException(400, f"Set {key_name} before selecting translation provider.")
    source_track = next((item for item in edit.get("subtitle_tracks", []) if item.get("id") == edit.get("subtitle_active_track_id")), None)
    source_track_id = source_track.get("id") if source_track else "legacy"
    source_segments = source_track.get("segments", []) if source_track else edit.get("subtitle_segments", [])
    source_timebase = source_track.get("timebase", "clip") if source_track else edit.get("subtitle_timebase", "clip")
    if source_track and source_track.get("timebase") == "output":
        source = None
        with connect() as conn:
            source = conn.execute("SELECT sha256 FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
        current_signature = composition_signature(output_scenes(clip, edit))
        if source_track.get("composition_fingerprint") != composition_fingerprint(source["sha256"], current_signature):
            raise HTTPException(409, "Selected subtitle track is stale. Regenerate or choose another track before translating.")
    source_segments = [item for item in source_segments if str(item.get("text") or "").strip()]
    if not source_segments:
        raise HTTPException(409, "Add or generate subtitle cues before translation.")
    if len(source_segments) > 500:
        raise HTTPException(422, "Translation is limited to 500 subtitle cues.")
    source_fingerprint = subtitle_content_fingerprint(source_segments)
    for track in edit.get("subtitle_tracks", []):
        if track.get("source_type") == "translation" and track.get("provider") == body.provider and track.get("language") == body.target_language and track.get("source_track_id") == source_track_id and track.get("source_fingerprint") == source_fingerprint:
            return {"cached": True, "track": track}
    if len(edit.get("subtitle_tracks", [])) >= 20:
        raise HTTPException(409, "Subtitle track limit reached (20). Remove a draft before translating.")
    scenes = output_scenes(clip, edit)
    signature = composition_signature(scenes)
    with connect() as conn:
        source_row = conn.execute("SELECT sha256 FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
    options = {
        "provider": body.provider, "target_language": body.target_language, "consent_at": now(),
        "source_track_id": source_track_id, "source_timebase": source_timebase,
        "source_segments": source_segments, "source_fingerprint": source_fingerprint,
        "composition_signature": signature,
        "composition_fingerprint": composition_fingerprint(source_row["sha256"], signature),
        "track_id": f"tr-{uuid.uuid4().hex}",
    }
    job_id = _queue_subtitle_job(clip, "subtitle_translate", options, original_edit_json)
    return {"id": job_id, "status": "queued", "provider": body.provider}


@app.post("/api/clips/{clip_id}/subtitles/import")
def import_clip_subtitles(clip_id: str, body: SubtitleImportRequest):
    with connect() as conn:
        row = conn.execute("SELECT c.*,s.sha256 FROM clips c JOIN sources s ON s.id=c.source_id WHERE c.id=?", (clip_id,)).fetchone()
        if row is not None:
            _assert_batch_item_editable(conn, clip_id)
    if row is None:
        raise HTTPException(404, "Clip not found.")
    clip = dict(row)
    edit = json.loads(clip["edit_json"])
    scenes = output_scenes(clip, edit)
    duration = scene_output_duration(scenes)
    try:
        segments, warnings = parse_subtitle_file(body.text, body.format, duration, clamp=body.clamp)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not body.clamp and any("exceed current output duration" in item for item in warnings):
        return {"track": None, "warnings": warnings, "needs_clamp": True, "duration": duration}
    signature = composition_signature(scenes)
    track = {
        "id": f"import-{uuid.uuid4().hex}", "source_type": "imported", "provider": None,
        "language": "und", "timebase": "output", "segments": segments,
        "composition_signature": signature,
        "composition_fingerprint": composition_fingerprint(clip["sha256"], signature),
        "word_timestamps": False, "speaker_identification": False, "edited": False,
    }
    return {"track": track, "warnings": warnings, "needs_clamp": False, "duration": duration}


@app.get("/api/clips/{clip_id}/subtitles/export")
def export_clip_subtitles(clip_id: str, format: Literal["srt", "vtt"] = "srt", track_id: str | None = None, display: Literal["original", "translated", "bilingual"] = "original"):
    with connect() as conn:
        row = conn.execute("SELECT c.*,s.sha256,s.transcript_json FROM clips c JOIN sources s ON s.id=c.source_id WHERE c.id=?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Clip not found.")
    clip = dict(row)
    edit = json.loads(clip["edit_json"])
    tracks = edit.get("subtitle_tracks", [])
    selected = next((item for item in tracks if item.get("id") == track_id), None) if track_id else None
    if track_id and selected is None:
        raise HTTPException(404, "Subtitle track not found.")
    if selected:
        if selected.get("source_type") == "translation":
            edit["subtitle_active_track_id"] = selected.get("source_track_id") if selected.get("source_track_id") != "legacy" else None
            edit["subtitle_active_translation_id"] = selected["id"]
            display = "translated"
        else:
            edit["subtitle_active_track_id"] = selected["id"]
            edit["subtitle_active_translation_id"] = None
            display = "original"
    edit["subtitle_enabled"] = True
    edit["subtitle_display_mode"] = display
    try:
        segments = render_subtitle_segments(clip, edit, json.loads(clip.get("transcript_json") or "[]"), clip["sha256"])
        content = export_subtitle_file(segments, format)
    except (MediaError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from None
    if not segments:
        raise HTTPException(409, "Selected track has no timed subtitle cues to export.")
    return Response(
        content, media_type="application/x-subrip; charset=utf-8" if format == "srt" else "text/vtt; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="clip-{clip_id[:8]}.{format}"'},
    )


@app.post("/api/clips/{clip_id}/review")
def review_clip(clip_id: str, body: ClipReview):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        clip = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if clip is None:
            raise HTTPException(404, "Clip not found.")
        if conn.execute(
            "SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Wait for the active render before reviewing this clip.")
        if conn.execute(
            "SELECT 1 FROM youtube_publications WHERE clip_id=? AND status IN ('pending','uploading')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Cancel pending YouTube upload before changing review status.")
        path = _validated_final_mp4(dict(clip))
        reviewed_hash = _file_sha256(path) if body.status == "approved" else None
        conn.execute(
            "UPDATE clips SET review_status=?,reviewed_render_sha256=? WHERE id=?",
            (body.status, reviewed_hash, clip_id),
        )
    return {"id": clip_id, "review_status": body.status}


@app.post("/api/clips/{clip_id}/render")
def render_clip(clip_id: str):
    _require_storage(CLIP_DIR)
    with connect() as conn:
        clip = conn.execute("SELECT c.*,s.sha256,s.transcript_json FROM clips c JOIN sources s ON s.id=c.source_id WHERE c.id=?", (clip_id,)).fetchone()
        if clip is None:
            raise HTTPException(404, "Clip not found.")
        batch_item = conn.execute("SELECT id FROM video_batch_items WHERE clip_id=?", (clip_id,)).fetchone()
        if batch_item:
            raise HTTPException(409, "Render batch items from the Batch Creator to preserve queue order and snapshots.")
        if conn.execute("SELECT 1 FROM jobs WHERE clip_id=? AND kind='render' AND status IN ('queued','preparing','rendering')", (clip_id,)).fetchone():
            raise HTTPException(409, "A render for this clip is already queued or running.")
        if conn.execute(
            "SELECT 1 FROM youtube_publications WHERE clip_id=? AND status IN ('pending','uploading')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Cancel pending YouTube upload before rendering this clip.")
        edit = json.loads(clip["edit_json"])
        output_duration = scene_output_duration(output_scenes(dict(clip), edit))
        if output_duration > MAX_OUTPUT_SECONDS:
            raise HTTPException(422, f"Final output cannot exceed {MAX_OUTPUT_SECONDS} seconds. Shorten the timeline before rendering.")
        if edit.get("subtitle_enabled") and edit.get("subtitle_caption_mode") == "word_pop":
            try:
                render_subtitle_segments(dict(clip), edit, json.loads(clip["transcript_json"] or "[]"), clip["sha256"])
            except (MediaError, ValueError) as exc:
                raise HTTPException(409, str(exc)) from None
        conn.execute(
            "UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END,"
            "review_status='needs_review',reviewed_render_sha256=NULL WHERE id=?",
            (clip_id,),
        )
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
        if conn.execute("SELECT 1 FROM video_batch_items WHERE clip_id=?", (clip_id,)).fetchone():
            raise HTTPException(409, "Remove this clip from its batch before deleting it.")
        if conn.execute("SELECT 1 FROM jobs WHERE clip_id=? AND status IN ('queued','preparing','rendering')", (clip_id,)).fetchone():
            raise HTTPException(409, "Cancel active render before deleting this clip.")
        if conn.execute(
            "SELECT 1 FROM youtube_publications WHERE clip_id=? AND status IN ('pending','uploading')",
            (clip_id,),
        ).fetchone():
            raise HTTPException(409, "Cancel pending YouTube upload before deleting this clip.")
        rendered = row["rendered_path"]
        _clear_youtube_reference_for_job(conn, row["job_id"])
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
        jobs = [
            dict(row)
            for row in conn.execute(
                "SELECT j.id,j.source_id,j.clip_id,j.kind,j.status,j.phase,j.progress,j.message,j.created_at,j.updated_at,s.name AS source_name "
                "FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.kind NOT IN ('youtube_upload','batch_draft') ORDER BY j.created_at DESC LIMIT 30"
            ).fetchall()
        ]
        mood_jobs = [
            {**dict(row), "source_id": None, "clip_id": row["render_id"], "source_name": row["title"], "asset_type": "mood_quotes"}
            for row in conn.execute(
                "SELECT j.id,j.render_id,j.kind,j.status,j.phase,j.progress,j.message,j.created_at,j.updated_at,p.title "
                "FROM mood_jobs j JOIN mood_projects p ON p.id=j.project_id ORDER BY j.created_at DESC LIMIT 30"
            ).fetchall()
        ]
    return sorted(jobs + mood_jobs, key=lambda item: item["created_at"], reverse=True)[:30]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            mood = conn.execute("SELECT id,project_id,render_id,kind,status,phase,progress,message,created_at,updated_at FROM mood_jobs WHERE id=?", (job_id,)).fetchone()
            if mood is None:
                raise HTTPException(404, "Job not found.")
            return dict(mood)
        job = dict(row)
        usage = [dict(item) for item in conn.execute("SELECT provider,model,input_tokens,output_tokens,created_at FROM provider_usage WHERE job_id=?", (job_id,)).fetchall()]
    job.pop("options_json", None)
    job["usage"] = usage
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    with connect() as conn:
        batch_item = conn.execute(
            "SELECT 1 FROM video_batch_items i JOIN jobs j ON j.clip_id=i.clip_id WHERE j.id=? LIMIT 1",
            (job_id,),
        ).fetchone()
    if batch_item:
        raise HTTPException(409, "Cancel batch renders from their Batch Creator page.")
    if not runner.cancel(job_id):
        raise HTTPException(409, "Job is not queued or running.")
    return {"cancelled": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, body: RetryConsent):
    with connect() as conn:
        old = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if old is None:
        raise HTTPException(404, "Job not found.")
    if old["kind"] == "youtube_upload":
        raise HTTPException(409, "Retry YouTube uploads from Publishing History to reconcile safely.")
    with connect() as conn:
        if conn.execute(
            "SELECT 1 FROM video_batch_items i JOIN clips c ON c.id=i.clip_id WHERE c.id=? LIMIT 1",
            (old["clip_id"],),
        ).fetchone():
            raise HTTPException(409, "Retry this render from its Batch Creator page.")
    if old["status"] not in {"failed", "cancelled"}:
        raise HTTPException(409, "Only failed or cancelled jobs can be retried.")
    options = json.loads(old["options_json"])
    if options.get("provider") in {"openai", "gemini"}:
        if not body.consent:
            raise HTTPException(400, "Cloud retry requires fresh per-job consent.")
        options["consent_at"] = now()
    new_id = create_job(old["source_id"], old["kind"], options, old["clip_id"], resume_from=job_id)
    return {"id": new_id, "status": "queued"}


@app.get("/api/settings")
def settings():
    capabilities = _capabilities()
    return {
        "capabilities": capabilities,
        "providers": {
            "local": {"model": os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b"), "available": capabilities["ollama_connected"]},
            "openai": {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "key_configured": bool(os.environ.get("OPENAI_API_KEY"))},
            "gemini": {"model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"), "key_configured": bool(os.environ.get("GEMINI_API_KEY"))},
        },
        "subtitle_stt": {
            "local": {"ready": local_transcription_available(), "model": "whisper.cpp", "segment_timestamps": True, "word_timestamps": False, "speaker_identification": False},
            "openai": {"ready": bool(os.environ.get("OPENAI_API_KEY", "").strip()), "model": "gpt-transcribe", "segment_timestamps": False, "word_timestamps": False, "speaker_identification": False, "max_file_bytes": 25 * 1024 * 1024},
            "gemini": {"ready": bool(os.environ.get("GEMINI_API_KEY", "").strip()), "model": "gemini-3.5-transcribe", "segment_timestamps": True, "word_timestamps": True, "speaker_identification": True, "max_word_timestamp_duration_seconds": 1800},
        },
        "subtitle_presets": PRESETS,
        "assets": {"pexels_configured": bool(os.environ.get("PEXELS_API_KEY", "").strip())},
        "data_dir": str(DATA_DIR),
        "source_dir": str(SOURCE_DIR),
        "clip_dir": str(CLIP_DIR),
        "mood_dir": str(MOOD_DIR),
        "free_bytes": min(shutil.disk_usage(path).free for path in {DATA_DIR, WORK_DIR, MOOD_DIR, SOURCE_DIR, CLIP_DIR}),
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
    free = min(shutil.disk_usage(path).free for path in {DATA_DIR, WORK_DIR, MOOD_DIR, SOURCE_DIR, CLIP_DIR})
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
