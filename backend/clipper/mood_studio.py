import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import CLIP_DIR, DATA_DIR, LEGACY_CLIP_DIR, LEGACY_SOURCE_DIR, MIN_FREE_BYTES, MOOD_DIR, SOURCE_DIR, WORK_DIR
from .db import connect
from .jobs import now
from .media import MediaError, executable, probe
from .mood_renderer import validate_quote_layout
from .mood_text import automatic_segments
from .mood_quotes import (
    FONTS, LANGUAGES, LENGTHS, MOOD_CATEGORIES, MOOD_TEMPLATES, MUSIC_MOODS,
    PERSPECTIVES, STYLES, category_selection, generate_quotes,
)
from .mood_visuals import MoodVisualSettings, VISUAL_PRESETS
from .providers import ProviderError, model_for


router = APIRouter(prefix="/api")
DEFAULT_COMPOSITION = {
    "resolution": "720", "fps": 30, "duration": 10,
    "background": {"kind": "gradient", "asset_id": None, "color": "#1b332c", "color2": "#568b70", "video_start": 0, "loop": True, "mute_audio": True, "audio_volume": 0.2},
    "music": {"asset_id": None, "offset": 0, "trim_start": 0, "trim_end": 30, "volume": 0.25, "fade_in": 1, "fade_out": 1, "loop": True, "muted": False},
    "text": {"text": "", "font": "Georgia", "font_size": 50, "color": "#ffffff", "alignment": "center", "x": 50, "y": 52,
             "font_weight": 600, "line_spacing": 1.25, "shadow": True, "outline": False, "opacity": 100, "start": 0, "end": 10,
             "animation_in": "fade", "animation_out": "fade", "animation_duration": 0.8, "gradient_opacity": 18, "auto_contrast": False},
    "visual": MoodVisualSettings().model_dump(mode="json"),
    "text_mode": "sequential", "segments": [], "segments_source": "auto",
}
_ACTIVE = {"queued", "preparing", "rendering"}
_IMAGE_EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_VIDEO_EXTENSIONS = {".mp4": "video/mp4", ".mov": "video/quicktime"}
_AUDIO_EXTENSIONS = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}
_MAX_ASSET_BYTES = {"background_image": 25 * 1024**2, "background_video": 512 * 1024**2, "music": 100 * 1024**2}
# ponytail: single-user workstation, one shared lock bounds thumbnail CPU; per-asset locks if parallel previews become a real need.
_THUMBNAIL_LOCK = threading.Lock()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MoodBackground(StrictModel):
    kind: Literal["solid", "gradient", "image", "video"] = "gradient"
    asset_id: str | None = Field(default=None, max_length=64)
    color: str = Field(default="#1b332c", pattern=r"^#[0-9a-fA-F]{6}$")
    color2: str = Field(default="#568b70", pattern=r"^#[0-9a-fA-F]{6}$")
    video_start: float = Field(default=0, ge=0, le=14400)
    loop: bool = True
    mute_audio: bool = True
    audio_volume: float = Field(default=0.2, ge=0, le=1)


class MoodMusic(StrictModel):
    asset_id: str | None = Field(default=None, max_length=64)
    offset: float = Field(default=0, ge=0, le=40)
    trim_start: float = Field(default=0, ge=0, le=14400)
    trim_end: float = Field(default=30, gt=0, le=14400)
    volume: float = Field(default=0.25, ge=0, le=1)
    fade_in: float = Field(default=1, ge=0, le=40)
    fade_out: float = Field(default=1, ge=0, le=40)
    loop: bool = True
    muted: bool = False


class MoodText(StrictModel):
    text: str = Field(default="", max_length=500)
    font: str = Field(default="Georgia", max_length=40)
    font_size: int = Field(default=50, ge=20, le=120)
    font_weight: int = Field(default=600, ge=400, le=800)
    color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    alignment: Literal["left", "center", "right"] = "center"
    x: int = Field(default=50, ge=0, le=100)
    y: int = Field(default=52, ge=0, le=100)
    line_spacing: float = Field(default=1.25, ge=0.8, le=2.2)
    shadow: bool = True
    outline: bool = False
    opacity: int = Field(default=100, ge=10, le=100)
    start: float = Field(default=0, ge=0, le=40)
    end: float = Field(default=10, gt=0, le=40)
    animation_in: Literal["none", "fade", "slide_up", "slide_down", "typewriter", "zoom"] = "fade"
    animation_out: Literal["none", "fade"] = "fade"
    animation_duration: float = Field(default=0.8, ge=0.1, le=5)
    gradient_opacity: int = Field(default=0, ge=0, le=80)
    auto_contrast: bool = False

    @field_validator("text")
    @classmethod
    def no_control_characters(cls, value):
        if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in value):
            raise ValueError("Teks mengandung karakter kontrol yang tidak didukung.")
        return value


class MoodTextSegment(StrictModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=64)
    text: str = Field(default="", max_length=500)
    start: float = Field(ge=0, le=40)
    end: float = Field(gt=0, le=40)
    animation: Literal["fade_in", "fade_out", "fade_up", "slide_up", "gentle_scale", "none"] = "fade_up"
    animation_duration: float = Field(default=0.45, ge=0.1, le=2)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value):
        if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in value):
            raise ValueError("Teks segmen mengandung karakter kontrol yang tidak didukung.")
        return value.strip()


class MoodComposition(StrictModel):
    resolution: Literal["720", "1080"] = "720"
    fps: Literal[30] = 30
    duration: float = Field(default=10, ge=5, le=40)
    background: MoodBackground = Field(default_factory=MoodBackground)
    music: MoodMusic = Field(default_factory=MoodMusic)
    text: MoodText = Field(default_factory=MoodText)
    visual: MoodVisualSettings = Field(default_factory=MoodVisualSettings)
    text_mode: Literal["single", "sequential"] = "single"
    segments: list[MoodTextSegment] = Field(default_factory=list, max_length=8)
    segments_source: Literal["auto", "manual", "legacy"] = "legacy"

    @model_validator(mode="after")
    def valid_timing(self):
        if self.text_mode == "single" and (self.text.start >= self.text.end or self.text.end > self.duration):
            raise ValueError("Waktu tampil teks harus berada di dalam durasi video.")
        if self.music.offset >= self.duration:
            raise ValueError("Posisi mulai musik harus berada di dalam durasi video.")
        if self.music.trim_end <= self.music.trim_start:
            raise ValueError("Trim akhir musik harus setelah trim awal.")
        if self.music.asset_id and self.music.fade_in + self.music.fade_out > self.duration - self.music.offset + 0.001:
            raise ValueError("Total fade musik melebihi durasi musik yang tersedia di komposisi.")
        if self.text_mode == "sequential":
            if len({segment.id for segment in self.segments}) != len(self.segments):
                raise ValueError("ID segmen sequential harus unik.")
            previous_end = 0.0
            for index, segment in enumerate(self.segments, 1):
                span = segment.end - segment.start
                if segment.start >= segment.end or segment.end > self.duration:
                    raise ValueError(f"Timing segmen {index} harus berada di dalam durasi video.")
                if segment.start < previous_end - 0.01:
                    raise ValueError("Segmen sequential tidak boleh overlap.")
                if segment.animation_duration > span:
                    raise ValueError(f"Animasi segmen {index} lebih panjang dari waktu tampilnya.")
                previous_end = segment.end
        return self


class MoodProjectCreate(StrictModel):
    title: str = Field(default="Mood Quotes", min_length=1, max_length=120)


class MoodProjectPatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    category_id: str | None = Field(default=None, max_length=80)
    subcategory_id: str | None = Field(default=None, max_length=80)
    custom_topic: str | None = Field(default=None, max_length=200)
    tone: str | None = Field(default=None, max_length=40)
    perspective: str | None = Field(default=None, max_length=40)
    length: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=40)
    provider: Literal["gemini", "openai"] | None = None
    selected_quote: dict | None = None
    composition: MoodComposition | None = None


class MoodGenerateRequest(StrictModel):
    provider: Literal["gemini", "openai"] = "gemini"
    consent: bool = False


class MoodFavoriteRequest(StrictModel):
    quote: dict
    generation_id: str | None = Field(default=None, max_length=64)


class MoodSourceRequest(StrictModel):
    source_id: str = Field(min_length=1, max_length=64)


class MoodReviewRequest(StrictModel):
    status: Literal["approved", "needs_revision"]


class _Usage:  # Keeps provider token usage optional and untrusted.
    @staticmethod
    def integer(value):
        return value if type(value) is int and value >= 0 else None


def _project_row(project_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM mood_projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Mood Quotes draft tidak ditemukan.")
    return dict(row)


def _project_asset_dir(project_id):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(404, "Mood Quotes draft tidak ditemukan.")
    path = MOOD_DIR / project_id / "assets"
    path.mkdir(parents=True, exist_ok=True)
    if path.resolve().parent != (MOOD_DIR / project_id).resolve():
        raise HTTPException(400, "Lokasi aset draft tidak valid.")
    return path.resolve()


def _safe_asset(row):
    path = Path(row["path"]).resolve()
    if row.get("source_id"):
        if path.parent not in {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()} or not path.is_file():
            raise HTTPException(404, "Video Source Library tidak ditemukan.")
        return path
    asset_dir = _project_asset_dir(row["project_id"])
    if path.parent != asset_dir or not path.is_file():
        raise HTTPException(404, "File aset lokal tidak ditemukan.")
    return path


def _asset_public(row):
    item = dict(row)
    item.pop("path", None)
    item.pop("sha256", None)
    item["has_audio"] = bool(item["has_audio"])
    item["url"] = f"/api/mood-assets/{item['id']}/file"
    return item


def _render_public(row):
    item = dict(row)
    has_file = bool(item.pop("path", None))
    item.pop("composition_json", None)
    item.pop("reviewed_render_sha256", None)
    if has_file:
        item["url"] = f"/api/mood-renders/{item['id']}/file"
        item["download_url"] = f"/api/mood-renders/{item['id']}/download"
    return item


def _detail(project_id, *, full=True):
    with connect() as conn:
        row = conn.execute("SELECT * FROM mood_projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Mood Quotes draft tidak ditemukan.")
        project = dict(row)
        current = conn.execute("SELECT * FROM mood_renders WHERE id=?", (project["current_render_id"],)).fetchone() if project["current_render_id"] else None
        assets = conn.execute("SELECT * FROM mood_assets WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
        latest_job = conn.execute("SELECT id,status,phase,progress,message FROM mood_jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
        result = {
            "project": {
                "id": project["id"], "title": project["title"], "category_id": project["category_id"],
                "subcategory_id": project["subcategory_id"], "custom_topic": project["custom_topic"],
                "tone": project["tone"], "perspective": project["perspective"], "length": project["length"],
                "language": project["language"], "provider": project["provider"],
                "selected_quote": json.loads(project["selected_quote_json"]) if project["selected_quote_json"] else None,
                "composition": json.loads(project["composition_json"]), "created_at": project["created_at"], "updated_at": project["updated_at"],
                "current_render": _render_public(dict(current)) if current else None,
                "latest_job": dict(latest_job) if latest_job else None,
            },
            "assets": [_asset_public(dict(item)) for item in assets],
        }
        if full:
            generations = conn.execute("SELECT * FROM mood_generations WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
            favorites = conn.execute("SELECT * FROM mood_favorites WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
            renders = conn.execute("SELECT * FROM mood_renders WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,)).fetchall()
            result["quotes"] = json.loads(generations[0]["quotes_json"]) if generations and generations[0]["id"] == project["current_generation_id"] else []
            if project["current_generation_id"]:
                current_generation = next((item for item in generations if item["id"] == project["current_generation_id"]), None)
                result["quotes"] = json.loads(current_generation["quotes_json"]) if current_generation else []
            result["generations"] = [{"id": item["id"], "provider": item["provider"], "model": item["model"], "created_at": item["created_at"], "quotes": json.loads(item["quotes_json"])} for item in generations]
            result["favorites"] = [{"id": item["id"], "generation_id": item["generation_id"], "quote": json.loads(item["quote_json"]), "created_at": item["created_at"]} for item in favorites]
            result["renders"] = [_render_public(dict(item)) for item in renders]
        return result


def _valid_quote(quote):
    if not isinstance(quote, dict):
        raise HTTPException(422, "Pilih quote yang valid.")
    title, text = quote.get("title"), quote.get("text")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80 or not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        raise HTTPException(422, "Judul quote harus 1–80 karakter dan teks 1–500 karakter.")
    visual_keywords = quote.get("visual_keywords")
    if not isinstance(visual_keywords, list) or not 2 <= len(visual_keywords) <= 5 or any(not isinstance(item, str) or not item.strip() or len(item) > 40 for item in visual_keywords) or quote.get("music_mood") not in MUSIC_MOODS:
        raise HTTPException(422, "Metadata quote tidak valid.")
    segments = quote.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 8:
        raise HTTPException(422, "Quote harus memiliki 1–8 segmen valid.")
    normalized_text = " ".join(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))
    clean_segments = []
    for order, segment in enumerate(segments, 1):
        if not isinstance(segment, dict) or set(segment) != {"text", "order"} or type(segment["order"]) is not int or segment["order"] != order or not isinstance(segment["text"], str) or not segment["text"].strip():
            raise HTTPException(422, "Urutan segmen quote tidak valid.")
        clean_segments.append({"text": segment["text"].strip(), "order": order})
    if " ".join(re.findall(r"\w+", " ".join(item["text"] for item in clean_segments).casefold(), flags=re.UNICODE)) != normalized_text:
        raise HTTPException(422, "Segmen quote tidak cocok dengan teks final.")
    return {
        "id": str(quote.get("id") or uuid.uuid4().hex)[:64], "title": title.strip(), "text": text.strip(),
        "segments": clean_segments, "mood": str(quote.get("mood") or "")[:80],
        "tone": str(quote.get("tone") or "")[:40], "visual_keywords": [item.strip() for item in visual_keywords],
        "music_mood": quote["music_mood"],
    }


def _validate_category_fields(values):
    category_id, subcategory_id = values.get("category_id"), values.get("subcategory_id")
    if category_id and subcategory_id:
        try:
            category_selection(category_id, subcategory_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    elif category_id or subcategory_id:
        raise HTTPException(422, "Kategori dan subkategori harus dipilih bersama.")
    for key, rows in (("tone", STYLES), ("perspective", PERSPECTIVES), ("length", LENGTHS), ("language", LANGUAGES)):
        if key in values and values[key] is not None and values[key] not in {item["id"] for item in rows}:
            raise HTTPException(422, f"Pilihan {key} tidak dikenal.")


def _model_composition(value):
    try:
        raw = value.model_dump(mode="json") if isinstance(value, MoodComposition) else dict(value)
        legacy_shape = "text_mode" not in raw
        comp = value if isinstance(value, MoodComposition) else MoodComposition.model_validate(value)
    except Exception as exc:
        raise HTTPException(422, f"Konfigurasi video tidak valid: {str(exc).splitlines()[0]}") from None
    if legacy_shape:
        comp.text_mode = "single"
        comp.segments_source = "legacy"
    if comp.text.font not in FONTS:
        raise HTTPException(422, "Font tidak tersedia pada daftar font sistem.")
    if comp.text_mode == "sequential" and not comp.segments and comp.text.text.strip():
        comp.segments = [MoodTextSegment.model_validate(item) for item in automatic_segments(
            comp.text.text, comp.duration, animation=comp.visual.segment_animation,
        )]
    if comp.text_mode == "sequential" and comp.segments:
        final_text = " ".join(segment.text for segment in comp.segments)
        if len(final_text) > 500:
            raise HTTPException(422, "Gabungan teks segmen melebihi 500 karakter.")
        comp.text.text = final_text
        comp.text.start = min(segment.start for segment in comp.segments)
        comp.text.end = max(segment.end for segment in comp.segments)
    return comp.model_dump(mode="json")


def _check_project_assets(project_id, composition):
    background, music = composition["background"], composition["music"]
    requirements = []
    if background["kind"] in {"image", "video"}:
        requirements.append((background.get("asset_id"), "background_image" if background["kind"] == "image" else "background_video"))
    if music.get("asset_id"):
        requirements.append((music["asset_id"], "music"))
    assets = {}
    with connect() as conn:
        for asset_id, kind in requirements:
            row = conn.execute("SELECT * FROM mood_assets WHERE id=? AND project_id=? AND kind=?", (asset_id, project_id, kind)).fetchone()
            if row is None:
                raise HTTPException(422, "Pilih aset background/audio yang tersedia di draft ini.")
            item = dict(row)
            path = _safe_asset(item)
            if kind == "background_video" and background["video_start"] >= item["duration"]:
                raise HTTPException(422, "Waktu awal background video melebihi durasi file.")
            if kind == "music":
                if music["trim_start"] >= item["duration"] or music["trim_end"] <= music["trim_start"]:
                    raise HTTPException(422, "Rentang trim musik tidak valid.")
                music["trim_end"] = min(music["trim_end"], item["duration"])
                if music["trim_end"] <= music["trim_start"]:
                    raise HTTPException(422, "Trim musik harus menyisakan audio.")
            item["path"] = str(path)
            assets[item["id"]] = item
    if background["kind"] in {"solid", "gradient"}:
        background["asset_id"] = None
    return assets


def _validate_music_timing(composition, asset):
    music = composition["music"]
    if not music.get("asset_id"):
        return
    offset = float(music.get("offset", 0))
    available = max(0.0, composition["duration"] - offset)
    source_span = max(0.0, music["trim_end"] - music["trim_start"])
    source_remaining = max(0.0, asset["duration"] - music["trim_start"])
    if min(source_span, source_remaining) < 0.05:
        raise HTTPException(422, "Trim musik harus menyisakan sedikitnya 0,05 detik audio.")
    play_duration = available if music["loop"] else min(available, source_span, source_remaining)
    if play_duration < 0.05:
        raise HTTPException(422, "Posisi mulai/trim musik tidak menyisakan audio di durasi komposisi.")
    if music["fade_in"] + music["fade_out"] > play_duration + 0.001:
        raise HTTPException(422, "Gabungan fade-in dan fade-out melebihi durasi musik yang terdengar.")


def _probe_asset(path, kind):
    try:
        result = subprocess.run(
            [executable("ffprobe", "FFPROBE_PATH"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raise HTTPException(400, "ffprobe tidak dapat membaca aset. Pastikan format dan file valid.") from None
    streams = payload.get("streams", [])
    if kind == "music":
        stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
        if not stream:
            raise HTTPException(400, "File musik tidak memiliki audio yang dapat dibaca.")
        try:
            duration = float(payload.get("format", {}).get("duration") or stream.get("duration") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Durasi audio tidak valid.") from None
        if not math.isfinite(duration) or duration <= 0 or duration > 4 * 60 * 60:
            raise HTTPException(400, "Durasi musik tidak valid atau melebihi 4 jam.")
        return {"duration": duration, "width": None, "height": None, "has_audio": True}
    stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not stream:
        raise HTTPException(400, "Aset gambar/video tidak memiliki stream visual yang valid.")
    try:
        width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Dimensi aset visual tidak valid.") from None
    if min(width, height) < 1 or max(width, height) > 12000 or width * height > 40_000_000:
        raise HTTPException(400, "Dimensi aset visual tidak didukung.")
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if kind == "background_image":
        return {"duration": None, "width": width, "height": height, "has_audio": False}
    try:
        duration = float(payload.get("format", {}).get("duration") or stream.get("duration") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Durasi background video tidak valid.") from None
    if not math.isfinite(duration) or duration <= 0 or duration > 4 * 60 * 60:
        raise HTTPException(400, "Durasi background video tidak valid atau melebihi 4 jam.")
    return {"duration": duration, "width": width, "height": height, "has_audio": bool(audio)}


@router.get("/mood-quotes/categories")
def mood_quote_categories():
    return {
        "categories": MOOD_CATEGORIES, "styles": STYLES, "perspectives": PERSPECTIVES,
        "lengths": LENGTHS, "languages": LANGUAGES, "music_moods": MUSIC_MOODS,
        "fonts": FONTS, "templates": MOOD_TEMPLATES,
        "visual_presets": [preset.model_dump(mode="json") for preset in VISUAL_PRESETS],
        "providers": {
            "gemini": {"configured": bool(os.environ.get("GEMINI_API_KEY")), "model": model_for("gemini")},
            "openai": {"configured": bool(os.environ.get("OPENAI_API_KEY")), "model": model_for("openai")},
            "default": _default_quote_provider(),
        },
        "consent_data": "Kategori, subkategori, topik kustom, gaya, sudut pandang, target durasi, bahasa, serta instruksi pembuatan quote dikirim ke provider pilihan. Aset video/gambar/audio dan API key tidak dikirim.",
    }


@router.get("/mood-projects")
def list_mood_projects():
    with connect() as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM mood_projects ORDER BY updated_at DESC LIMIT 200").fetchall()]
    return [_detail(project_id, full=False)["project"] for project_id in ids]


@router.post("/mood-projects")
def create_mood_project(body: MoodProjectCreate):
    project_id, timestamp = uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO mood_projects(id,title,category_id,subcategory_id,custom_topic,tone,perspective,length,language,provider,composition_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, body.title.strip(), "bahagia-positif", "kebahagiaan-sederhana", "", "natural", "netral", "short", "indonesia", _default_quote_provider(),
             json.dumps(DEFAULT_COMPOSITION), timestamp, timestamp),
        )
    return _detail(project_id)


@router.get("/mood-projects/{project_id}")
def get_mood_project(project_id: str):
    return _detail(project_id)


@router.patch("/mood-projects/{project_id}")
def update_mood_project(project_id: str, body: MoodProjectPatch):
    updates = body.model_dump(exclude_unset=True)
    if "selected_quote" in updates:
        quote = _valid_quote(updates["selected_quote"]) if updates["selected_quote"] is not None else None
        updates["selected_quote_json"] = json.dumps(quote, ensure_ascii=False) if quote else None
        updates.pop("selected_quote")
    if "composition" in updates:
        updates["composition_json"] = json.dumps(_model_composition(updates.pop("composition")), ensure_ascii=False)
    mapping = {
        "title": "title", "category_id": "category_id", "subcategory_id": "subcategory_id", "custom_topic": "custom_topic",
        "tone": "tone", "perspective": "perspective", "length": "length", "language": "language", "provider": "provider",
        "selected_quote_json": "selected_quote_json", "composition_json": "composition_json",
    }
    values, fields = [], []
    for key, column in mapping.items():
        if key in updates:
            value = updates[key]
            if key == "title":
                value = value.strip()
                if not value:
                    raise HTTPException(422, "Nama draft wajib diisi.")
            if key == "custom_topic":
                value = value.strip()
            fields.append(f"{column}=?")
            values.append(value)
    if fields:
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project = conn.execute("SELECT * FROM mood_projects WHERE id=?", (project_id,)).fetchone()
            if project is None:
                raise HTTPException(404, "Mood Quotes draft tidak ditemukan.")
            if conn.execute("SELECT 1 FROM mood_jobs WHERE project_id=? AND status IN ('queued','preparing','rendering')", (project_id,)).fetchone():
                raise HTTPException(409, "Simpan perubahan setelah render aktif selesai atau dibatalkan.")
            next_fields = {key: project[key] for key in ("category_id", "subcategory_id", "tone", "perspective", "length", "language")}
            next_fields.update({key: value for key, value in updates.items() if key in next_fields})
            _validate_category_fields(next_fields)
            render_changed = (
                updates.get("composition_json", project["composition_json"]) != project["composition_json"]
                or updates.get("selected_quote_json", project["selected_quote_json"]) != project["selected_quote_json"]
            )
            conn.execute(f"UPDATE mood_projects SET {','.join(fields)},updated_at=? WHERE id=?", [*values, now(), project_id])
            if render_changed:
                conn.execute("UPDATE mood_renders SET status='needs_render',review_status='needs_review',reviewed_render_sha256=NULL WHERE id=? AND status='completed'", (project["current_render_id"],))
    return _detail(project_id)


@router.post("/mood-projects/{project_id}/generate")
def generate_mood_project_quotes(project_id: str, body: MoodGenerateRequest):
    project = _project_row(project_id)
    if not body.consent:
        raise HTTPException(400, "Persetujuan cloud eksplisit diperlukan untuk setiap permintaan quote.")
    key = "GEMINI_API_KEY" if body.provider == "gemini" else "OPENAI_API_KEY"
    if not os.environ.get(key):
        raise HTTPException(503, f"{key} belum dikonfigurasi di backend; tidak ada provider fallback otomatis.")
    if not project["category_id"] or not project["subcategory_id"]:
        raise HTTPException(422, "Pilih kategori dan subkategori sebelum generate.")
    try:
        quotes, model, usage, topic = generate_quotes(
            category_id=project["category_id"], subcategory_id=project["subcategory_id"],
            custom_topic=project["custom_topic"], tone_id=project["tone"], perspective_id=project["perspective"],
            length_id=project["length"], language_id=project["language"], provider=body.provider,
        )
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from None
    generation_id, timestamp = uuid.uuid4().hex, now()
    request_snapshot = {
        "category_id": project["category_id"], "subcategory_id": project["subcategory_id"], "custom_topic": topic,
        "tone": project["tone"], "perspective": project["perspective"], "length": project["length"],
        "language": project["language"], "provider": body.provider, "consent_at": timestamp,
    }
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO mood_generations(id,project_id,provider,model,request_json,quotes_json,input_tokens,output_tokens,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (generation_id, project_id, body.provider, model, json.dumps(request_snapshot, ensure_ascii=False), json.dumps(quotes, ensure_ascii=False),
             _Usage.integer(usage.get("prompt_tokens", usage.get("promptTokenCount"))),
             _Usage.integer(usage.get("completion_tokens", usage.get("candidatesTokenCount"))), timestamp),
        )
        conn.execute("UPDATE mood_projects SET current_generation_id=?,provider=?,updated_at=? WHERE id=?", (generation_id, body.provider, timestamp, project_id))
    return {"id": generation_id, "provider": body.provider, "model": model, "quotes": quotes, "usage": usage, "created_at": timestamp}


@router.get("/mood-projects/{project_id}/generations")
def mood_project_generations(project_id: str):
    _project_row(project_id)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mood_generations WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    return [{"id": row["id"], "provider": row["provider"], "model": row["model"], "created_at": row["created_at"], "quotes": json.loads(row["quotes_json"])} for row in rows]


@router.post("/mood-projects/{project_id}/favorites")
def save_mood_favorite(project_id: str, body: MoodFavoriteRequest):
    _project_row(project_id)
    quote = _valid_quote(body.quote)
    with connect() as conn:
        if body.generation_id and not conn.execute("SELECT 1 FROM mood_generations WHERE id=? AND project_id=?", (body.generation_id, project_id)).fetchone():
            raise HTTPException(404, "Riwayat generate quote tidak ditemukan.")
        for row in conn.execute("SELECT id,quote_json FROM mood_favorites WHERE project_id=?", (project_id,)).fetchall():
            if json.loads(row["quote_json"]).get("text", "").casefold() == quote["text"].casefold():
                return {"id": row["id"], "quote": quote, "saved": True}
        favorite_id = uuid.uuid4().hex
        conn.execute("INSERT INTO mood_favorites(id,project_id,generation_id,quote_json,created_at) VALUES(?,?,?,?,?)",
                     (favorite_id, project_id, body.generation_id, json.dumps(quote, ensure_ascii=False), now()))
    return {"id": favorite_id, "quote": quote, "saved": True}


@router.delete("/mood-projects/{project_id}/favorites/{favorite_id}")
def delete_mood_favorite(project_id: str, favorite_id: str):
    with connect() as conn:
        if not conn.execute("DELETE FROM mood_favorites WHERE id=? AND project_id=?", (favorite_id, project_id)).rowcount:
            raise HTTPException(404, "Quote favorit tidak ditemukan.")
    return {"deleted": True}


@router.post("/mood-projects/{project_id}/assets")
def upload_mood_asset(project_id: str, kind: Literal["background_image", "background_video", "music"] = Form(...), file: UploadFile = File(...)):
    _project_row(project_id)
    suffix = Path((file.filename or "").replace("\\", "/")).suffix.lower()
    allowed = _IMAGE_EXTENSIONS if kind == "background_image" else _VIDEO_EXTENSIONS if kind == "background_video" else _AUDIO_EXTENSIONS
    if suffix not in allowed:
        extensions = ", ".join(allowed)
        raise HTTPException(415, f"Format {kind} tidak didukung. Gunakan {extensions}.")
    asset_id, timestamp = uuid.uuid4().hex, now()
    asset_dir = _project_asset_dir(project_id)
    path = asset_dir / f"{asset_id}{suffix}"
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as output:
            while block := file.file.read(1024 * 1024):
                size += len(block)
                if size > _MAX_ASSET_BYTES[kind]:
                    raise HTTPException(413, "Aset melebihi batas ukuran untuk jenis file ini.")
                if min(shutil.disk_usage(folder).free for folder in {DATA_DIR, MOOD_DIR, WORK_DIR, CLIP_DIR}) < MIN_FREE_BYTES + len(block):
                    raise HTTPException(507, "Sisakan minimal 1 GiB ruang kosong untuk file sementara dan render.")
                digest.update(block)
                output.write(block)
        if not size:
            raise HTTPException(400, "File yang diunggah kosong.")
        metadata = _probe_asset(path, kind)
        with connect() as conn:
            conn.execute(
                "INSERT INTO mood_assets(id,project_id,kind,name,path,mime_type,size_bytes,duration,width,height,has_audio,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, project_id, kind, Path((file.filename or "asset").replace("\\", "/")).name[:120], str(path.resolve()),
                 allowed[suffix], size, metadata["duration"], metadata["width"], metadata["height"], int(metadata["has_audio"]), digest.hexdigest(), timestamp),
            )
            conn.execute("UPDATE mood_projects SET updated_at=? WHERE id=?", (timestamp, project_id))
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise
    with connect() as conn:
        row = conn.execute("SELECT * FROM mood_assets WHERE id=?", (asset_id,)).fetchone()
    return _asset_public(dict(row))


@router.get("/mood-assets/{asset_id}/file")
def mood_asset_file(asset_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM mood_assets WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Aset Mood Quotes tidak ditemukan.")
    return FileResponse(_safe_asset(dict(row)), media_type=row["mime_type"], filename=row["name"], content_disposition_type="inline")


@router.get("/mood-assets/{asset_id}/thumbnail")
def mood_asset_thumbnail(asset_id: str, time: float = Query(default=0, ge=0, le=14400)):
    with connect() as conn:
        row = conn.execute("SELECT * FROM mood_assets WHERE id=?", (asset_id,)).fetchone()
    if row is None or row["kind"] != "background_video":
        raise HTTPException(404, "Background video Mood Quotes tidak ditemukan.")
    asset = dict(row)
    if not math.isfinite(time) or time >= asset["duration"]:
        raise HTTPException(422, "Waktu preview melebihi durasi background video.")
    source = _safe_asset(asset)
    project_root = (MOOD_DIR / asset["project_id"]).resolve()
    preview_dir = project_root / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    if preview_dir.resolve().parent != project_root:
        raise HTTPException(400, "Lokasi cache preview tidak valid.")
    tenth_second = round(time * 10)
    preview = preview_dir / f"{asset_id}-{tenth_second}.jpg"
    with _THUMBNAIL_LOCK:
        if not preview.is_file():
            temporary = preview_dir / f"{asset_id}-{tenth_second}-{uuid.uuid4().hex}.jpg"
            try:
                subprocess.run(
                    [executable("ffmpeg", "FFMPEG_PATH"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                     "-ss", f"{time:.3f}", "-i", str(source), "-frames:v", "1",
                     "-vf", "scale=720:1280:force_original_aspect_ratio=decrease", "-threads", "1", "-q:v", "4", str(temporary)],
                    capture_output=True, timeout=25, check=True,
                )
                if not temporary.is_file() or temporary.stat().st_size == 0:
                    raise MediaError("Empty thumbnail")
                os.replace(temporary, preview)
            except (OSError, subprocess.SubprocessError, MediaError):
                temporary.unlink(missing_ok=True)
                raise HTTPException(422, "FFmpeg tidak dapat mengekstrak frame preview. Periksa background video.") from None
            cached = sorted(preview_dir.glob(f"{asset_id}-*.jpg"), key=lambda item: item.stat().st_mtime, reverse=True)
            for stale in cached[16:]:
                stale.unlink(missing_ok=True)
    return FileResponse(preview, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/mood-projects/{project_id}/source-assets")
def attach_source_asset(project_id: str, body: MoodSourceRequest):
    _project_row(project_id)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = conn.execute("SELECT * FROM sources WHERE id=?", (body.source_id,)).fetchone()
        if source is None:
            raise HTTPException(404, "Video Source Library tidak ditemukan.")
        existing = conn.execute("SELECT * FROM mood_assets WHERE project_id=? AND source_id=?", (project_id, body.source_id)).fetchone()
        if existing:
            return _asset_public(dict(existing))
        source = dict(source)
        path = Path(source["path"]).resolve()
        if path.parent not in {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()} or not path.is_file():
            raise HTTPException(404, "File Source Library tidak ditemukan.")
        asset_id, timestamp = uuid.uuid4().hex, now()
        mime = "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"
        conn.execute(
            "INSERT INTO mood_assets(id,project_id,source_id,kind,name,path,mime_type,size_bytes,duration,width,height,has_audio,sha256,created_at) "
            "VALUES(?,?,?,'background_video',?,?,?,?,?,?,?,?,?,?)",
            (asset_id, project_id, body.source_id, source["name"], str(path), mime, source["size_bytes"], source["duration"],
             source["width"], source["height"], int(bool(source["audio_codec"])), source["sha256"], timestamp),
        )
        conn.execute("UPDATE mood_projects SET updated_at=? WHERE id=?", (timestamp, project_id))
        row = conn.execute("SELECT * FROM mood_assets WHERE id=?", (asset_id,)).fetchone()
    return _asset_public(dict(row))


@router.delete("/mood-projects/{project_id}/assets/{asset_id}")
def delete_mood_asset(project_id: str, asset_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project = conn.execute("SELECT * FROM mood_projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(404, "Mood Quotes draft tidak ditemukan.")
        row = conn.execute("SELECT * FROM mood_assets WHERE id=? AND project_id=?", (asset_id, project_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Aset Mood Quotes tidak ditemukan.")
        if conn.execute("SELECT 1 FROM mood_jobs WHERE project_id=? AND status IN ('queued','preparing','rendering')", (project_id,)).fetchone():
            raise HTTPException(409, "Tunggu atau batalkan render aktif sebelum menghapus aset.")
        composition = json.loads(project["composition_json"])
        if asset_id in {composition["background"].get("asset_id"), composition["music"].get("asset_id")}:
            raise HTTPException(409, "Ganti aset yang dipakai komposisi draft sebelum menghapus file ini.")
        path = _safe_asset(dict(row))
        conn.execute("DELETE FROM mood_assets WHERE id=?", (asset_id,))
        conn.execute("UPDATE mood_projects SET updated_at=? WHERE id=?", (now(), project_id))
    if not row["source_id"]:
        path.unlink(missing_ok=True)
    return {"deleted": True}


@router.get("/mood-projects/{project_id}/renders")
def list_mood_renders(project_id: str):
    _project_row(project_id)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mood_renders WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    return [_render_public(dict(row)) for row in rows]


@router.post("/mood-projects/{project_id}/render")
def queue_mood_render(project_id: str, composition: MoodComposition):
    _project_row(project_id)
    comp = _model_composition(composition)
    if not comp["text"]["text"].strip():
        raise HTTPException(422, "Isi teks quote sebelum render.")
    if comp["text_mode"] == "sequential" and any(not item["text"].strip() for item in comp["segments"]):
        raise HTTPException(422, "Lengkapi atau hapus segmen kosong sebelum render.")
    try:
        dimensions = (720, 1280) if comp["resolution"] == "720" else (1080, 1920)
        layout_texts = [item["text"] for item in comp["segments"]] if comp["text_mode"] == "sequential" else [comp["text"]["text"]]
        if not layout_texts:
            raise ValueError("Belum ada segmen teks untuk dirender.")
        for item in layout_texts:
            validate_quote_layout(item, comp, *dimensions)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    _require_mood_storage()
    timestamp, job_id, render_id = now(), uuid.uuid4().hex, uuid.uuid4().hex
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project = conn.execute("SELECT * FROM mood_projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(404, "Mood Quotes draft tidak ditemukan.")
        quote = json.loads(project["selected_quote_json"]) if project["selected_quote_json"] else None
        if not quote:
            raise HTTPException(409, "Pilih quote sebelum membuat video.")
        final_text = comp["text"]["text"].strip()
        if comp["text_mode"] == "sequential":
            segments = [{"text": item["text"], "order": index} for index, item in enumerate(comp["segments"], 1)]
        else:
            segments = quote["segments"] if quote["text"] == final_text else [{"text": final_text, "order": 1}]
        quote = {**quote, "text": final_text, "segments": segments}
        if conn.execute("SELECT 1 FROM mood_jobs WHERE project_id=? AND status IN ('queued','preparing','rendering')", (project_id,)).fetchone():
            raise HTTPException(409, "Render Mood Quotes lain masih berjalan.")
        assets = _check_project_assets(project_id, comp)
        if comp["music"].get("asset_id"):
            music_asset = assets[comp["music"]["asset_id"]]
            if comp["music"]["trim_start"] >= music_asset["duration"]:
                raise HTTPException(422, "Trim awal musik berada di luar durasi file.")
            comp["music"]["trim_end"] = min(comp["music"]["trim_end"], music_asset["duration"])
            if comp["music"]["trim_end"] <= comp["music"]["trim_start"]:
                raise HTTPException(422, "Trim musik tidak menyisakan rentang audio yang valid.")
            _validate_music_timing(comp, music_asset)
        bg_asset = assets.get(comp["background"].get("asset_id"))
        if bg_asset and bg_asset["kind"] == "background_video" and comp["background"]["video_start"] >= bg_asset["duration"]:
            raise HTTPException(422, "Segmen background video berada di luar durasi file.")
        options = {"quote": quote, "composition": comp}
        conn.execute("UPDATE mood_projects SET composition_json=?,selected_quote_json=?,updated_at=? WHERE id=?",
                     (json.dumps(comp, ensure_ascii=False), json.dumps(quote, ensure_ascii=False), timestamp, project_id))
        conn.execute("UPDATE mood_renders SET status='needs_render',review_status='needs_review',reviewed_render_sha256=NULL WHERE id=? AND status='completed'", (project["current_render_id"],))
        conn.execute(
            "INSERT INTO mood_jobs(id,project_id,render_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,?,?,'mood_render','queued','queued',NULL,'Menunggu render Mood Quotes',?,?,?)",
            (job_id, project_id, render_id, json.dumps(options, ensure_ascii=False), timestamp, timestamp),
        )
        conn.execute(
            "INSERT INTO mood_renders(id,project_id,job_id,path,status,review_status,composition_json,created_at,updated_at) "
            "VALUES(?,?,?,NULL,'queued','needs_review',?,?,?)",
            (render_id, project_id, job_id, json.dumps(comp, ensure_ascii=False), timestamp, timestamp),
        )
    return {"id": job_id, "render_id": render_id, "status": "queued"}


def _require_mood_storage():
    for directory in (MOOD_DIR, WORK_DIR, CLIP_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if min(shutil.disk_usage(folder).free for folder in {DATA_DIR, MOOD_DIR, WORK_DIR, CLIP_DIR}) < MIN_FREE_BYTES:
        raise HTTPException(507, "Sisakan minimal 1 GiB ruang kosong untuk file sementara dan render.")


def _default_quote_provider():
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "openai" if os.environ.get("OPENAI_API_KEY") else "gemini"


@router.get("/mood-jobs/{job_id}")
def get_mood_job(job_id: str):
    with connect() as conn:
        row = conn.execute("SELECT id,project_id,render_id,kind,status,phase,progress,message,created_at,updated_at FROM mood_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Mood Quotes render job tidak ditemukan.")
    return dict(row)


@router.post("/mood-jobs/{job_id}/cancel")
def cancel_mood_job(job_id: str):
    from .jobs import runner
    if not runner.cancel(job_id):
        raise HTTPException(409, "Mood Quotes job tidak sedang menunggu atau berjalan.")
    return {"cancelled": True}


@router.post("/mood-jobs/{job_id}/retry")
def retry_mood_job(job_id: str):
    with connect() as conn:
        old = conn.execute("SELECT * FROM mood_jobs WHERE id=?", (job_id,)).fetchone()
    if old is None:
        raise HTTPException(404, "Mood Quotes render job tidak ditemukan.")
    if old["status"] not in {"failed", "cancelled"}:
        raise HTTPException(409, "Hanya render gagal/dibatalkan yang bisa di-retry.")
    options = json.loads(old["options_json"])
    options["composition"].setdefault("music", {}).setdefault("offset", 0)
    options["composition"].setdefault("music", {}).setdefault("muted", False)
    retry_assets = _check_project_assets(old["project_id"], options["composition"])
    music = options["composition"]["music"]
    if music.get("asset_id"):
        _validate_music_timing(options["composition"], retry_assets[music["asset_id"]])
    timestamp, new_job, render_id = now(), uuid.uuid4().hex, uuid.uuid4().hex
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM mood_jobs WHERE project_id=? AND status IN ('queued','preparing','rendering')", (old["project_id"],)).fetchone():
            raise HTTPException(409, "Render Mood Quotes lain masih berjalan.")
        conn.execute(
            "INSERT INTO mood_jobs(id,project_id,render_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,?,?,'mood_render','queued','queued',NULL,'Retry render Mood Quotes',?,?,?)",
            (new_job, old["project_id"], render_id, json.dumps(options, ensure_ascii=False), timestamp, timestamp),
        )
        conn.execute(
            "INSERT INTO mood_renders(id,project_id,job_id,path,status,review_status,composition_json,created_at,updated_at) "
            "VALUES(?,?,?,NULL,'queued','needs_review',?,?,?)",
            (render_id, old["project_id"], new_job, json.dumps(options["composition"], ensure_ascii=False), timestamp, timestamp),
        )
    return {"id": new_job, "render_id": render_id, "status": "queued"}


def _safe_render_path(row):
    path = Path(row["path"]).resolve()
    if path.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or not path.is_file() or path.suffix.lower() != ".mp4":
        raise HTTPException(404, "Mood Quotes MP4 tidak ditemukan.")
    return path


def _managed_render_path(row):
    path = Path(row["path"]).resolve()
    if path.parent not in {CLIP_DIR.resolve(), LEGACY_CLIP_DIR.resolve()} or path.suffix.lower() != ".mp4":
        raise HTTPException(500, "Lokasi Mood Quotes render di luar folder terkelola.")
    return path


def _validate_mood_mp4(row):
    if row["status"] != "completed" or not row["path"]:
        raise HTTPException(409, "Render Mood Quotes belum selesai.")
    try:
        path = _safe_render_path(row)
        metadata = probe(path)
        if path.stat().st_size <= 0 or metadata["video_codec"] != "h264" or metadata["audio_codec"] != "aac":
            raise MediaError("invalid output")
    except (HTTPException, MediaError, OSError):
        raise HTTPException(409, "Render MP4 hilang atau codec tidak valid; render ulang sebelum review.") from None
    return path


@router.post("/mood-renders/{render_id}/review")
def review_mood_render(render_id: str, body: MoodReviewRequest):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM mood_renders WHERE id=?", (render_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Mood Quotes render tidak ditemukan.")
        if conn.execute("SELECT 1 FROM mood_jobs WHERE render_id=? AND status IN ('queued','preparing','rendering')", (render_id,)).fetchone():
            raise HTTPException(409, "Tunggu render sebelum memberi keputusan review.")
        path = _validate_mood_mp4(dict(row))
        digest = None
        if body.status == "approved":
            sha = hashlib.sha256()
            with path.open("rb") as media:
                for block in iter(lambda: media.read(1024 * 1024), b""):
                    sha.update(block)
            digest = sha.hexdigest()
        conn.execute("UPDATE mood_renders SET review_status=?,reviewed_render_sha256=?,updated_at=? WHERE id=?",
                     (body.status, digest, now(), render_id))
    return {"id": render_id, "review_status": body.status}


@router.get("/mood-renders/{render_id}/file")
def mood_render_file(render_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM mood_renders WHERE id=?", (render_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Mood Quotes render tidak ditemukan.")
    return FileResponse(_safe_render_path(dict(row)), media_type="video/mp4", content_disposition_type="inline")


@router.get("/mood-renders/{render_id}/download")
def download_mood_render(render_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM mood_renders WHERE id=?", (render_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Mood Quotes render tidak ditemukan.")
    return FileResponse(_safe_render_path(dict(row)), media_type="video/mp4", filename=f"mood-quotes-{render_id[:8]}.mp4")


@router.delete("/mood-projects/{project_id}")
def delete_mood_project(project_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM mood_projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(404, "Mood Quotes draft tidak ditemukan.")
        if conn.execute("SELECT 1 FROM mood_jobs WHERE project_id=? AND status IN ('queued','preparing','rendering')", (project_id,)).fetchone():
            raise HTTPException(409, "Batalkan atau tunggu render aktif sebelum menghapus draft.")
        assets = conn.execute("SELECT * FROM mood_assets WHERE project_id=?", (project_id,)).fetchall()
        renders = conn.execute("SELECT * FROM mood_renders WHERE project_id=?", (project_id,)).fetchall()
        safe_assets = [( _safe_asset(dict(row)), bool(row["source_id"])) for row in assets]
        safe_renders = [_managed_render_path(dict(row)) for row in renders if row["path"]]
        conn.execute("DELETE FROM mood_projects WHERE id=?", (project_id,))
    for path, is_source_asset in safe_assets:
        if not is_source_asset:
            path.unlink(missing_ok=True)
    for path in safe_renders:
        path.unlink(missing_ok=True)
    project_dir = (MOOD_DIR / project_id).resolve()
    if project_dir.parent == MOOD_DIR.resolve() and project_dir.exists():
        shutil.rmtree(project_dir)
    return {"deleted": True}
