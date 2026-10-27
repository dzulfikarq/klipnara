import hashlib
import json
import math
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import CLIP_DIR, DATA_DIR, LEGACY_SOURCE_DIR, MIN_FREE_BYTES, MOOD_DIR, SOURCE_DIR, WORK_DIR
from .db import connect
from .jobs import now, runner


router = APIRouter(prefix="/api")
MAX_BATCH_ITEMS = 10


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class NamedModel(StrictModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Name must be nonblank and contain no control characters.")
        return value


class ClipSettings(StrictModel):
    resolution: Literal["720", "1080"] = "720"
    fps: Literal[30, 60] = 30
    quality: Literal["smaller", "balanced", "high"] = "balanced"
    subtitle_enabled: bool = False


class ClipItemSpec(NamedModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class CreateClipBatch(NamedModel):
    source_id: str = Field(min_length=1, max_length=64)
    shared_settings: ClipSettings = Field(default_factory=ClipSettings)
    items: list[ClipItemSpec] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)


class MoodItemSpec(NamedModel):
    quote: dict


class CreateMoodBatch(NamedModel):
    items: list[MoodItemSpec] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)


class AddBatchItem(NamedModel):
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    quote: dict | None = None


class BatchPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    shared_settings: ClipSettings | None = None
    apply_to_pending: bool = False

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if value is None:
            raise ValueError("Name cannot be null.")
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Name must be nonblank and contain no control characters.")
        return value


class BatchOrder(StrictModel):
    item_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _managed_source(row):
    path = Path(row["path"]).resolve()
    if path.parent not in {SOURCE_DIR.resolve(), LEGACY_SOURCE_DIR.resolve()} or not path.is_file():
        raise HTTPException(404, "Source file missing or outside managed storage.")
    return path


def _clip_edit(clip_id, start, end, settings):
    return {
        "trim_start": 0, "trim_end": end - start, "scene_mode": "single",
        "scenes": [{"id": f"scene-{clip_id}", "source_start": start, "source_end": end, "order": 0, "role": "body"}],
        "subtitle_enabled": settings["subtitle_enabled"], "subtitle_mode": "off", "subtitle_segments": [],
        "subtitle_timebase": "clip", "subtitle_tracks": [], "subtitle_active_track_id": None,
        "subtitle_active_translation_id": None, "subtitle_display_mode": "original", "subtitle_caption_mode": "sentence",
        "subtitle_preset": "Minimal Clean", "subtitle_animation": "none", "subtitle_font": "Arial",
        "subtitle_outline_color": "#101010", "subtitle_highlight_color": "#ffd700", "subtitle_outline": 2,
        "subtitle_shadow": 1, "subtitle_background": False, "subtitle_alignment": "bottom",
        "subtitle_caption_width": 90, "subtitle_safe_margin": 8, "subtitle_overrides": {},
        "style": "Clean", "resolution": settings["resolution"], "fps": settings["fps"],
        "quality": settings["quality"], "crop_x": 50, "crop_y": 50,
        "subtitle_size": 48, "subtitle_position": 82, "subtitle_color": "#ffffff",
        "audio": {"volume": 1, "muted": False, "fade_in": 0, "fade_out": 0, "normalize": False, "target_lufs": -18, "limiter": False},
        "title_overlay": {"enabled": False, "text": "", "font": "Arial", "size": 48, "color": "#ffffff", "position": 18, "duration": 3, "fade_in": 0.2, "fade_out": 0.2},
    }


def _insert_clip_item(conn, batch, spec, position):
    source = conn.execute("SELECT * FROM sources WHERE id=?", (batch["source_id"],)).fetchone()
    if source is None:
        raise HTTPException(404, "Video source not found.")
    _managed_source(source)
    start, end = float(spec.start), float(spec.end)
    if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= source["duration"]:
        raise HTTPException(422, "Each clip range must satisfy 0 ≤ start < end ≤ source duration.")
    settings = json.loads(batch["shared_json"])
    item_id, clip_id, draft_job_id, timestamp = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex, now()
    edit = _clip_edit(clip_id, start, end, settings)
    conn.execute(
        "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
        "VALUES(?,?,?,'batch_draft','draft','draft',NULL,'Batch clip draft',?,?,?)",
        (draft_job_id, source["id"], clip_id, _json({"edit": edit}), timestamp, timestamp),
    )
    conn.execute(
        "INSERT INTO clips(id,source_id,job_id,start,end,title,reason,rank,edit_json,status,review_status,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,'ready','needs_review',?)",
        (clip_id, source["id"], draft_job_id, start, end, spec.name.strip(), "Batch clip; timestamp dipilih pengguna.", position + 1, _json(edit), timestamp),
    )
    conn.execute(
        "INSERT INTO video_batch_items(id,batch_id,position,name,status,clip_id,created_at,updated_at) VALUES(?,?,?,?,'ready',?,?,?)",
        (item_id, batch["id"], position, spec.name.strip(), clip_id, timestamp, timestamp),
    )
    return item_id


def _mood_quote_composition(quote, composition):
    from .mood_studio import _model_composition
    from .mood_text import automatic_segments

    comp = _model_composition(composition)
    comp["text"]["text"] = quote["text"]
    if comp["text_mode"] == "sequential":
        comp["text"]["start"], comp["text"]["end"] = 0, comp["duration"]
        comp["segments"] = automatic_segments(
            quote["text"], comp["duration"], preferred=quote["segments"],
            animation=comp["visual"]["segment_animation"],
        )
        comp["segments_source"] = "auto"
    else:
        comp["text"]["end"] = min(comp["duration"], max(comp["text"]["start"] + 0.1, comp["text"]["end"]))
    return _model_composition(comp)


def _insert_mood_item(conn, batch, spec, position, source_project=None, source_project_id=None, preserve_composition=False):
    from .mood_studio import _model_composition, _safe_asset, _valid_quote

    source_project_id = source_project_id or batch["mood_source_project_id"]
    source = source_project or conn.execute("SELECT * FROM mood_projects WHERE id=?", (source_project_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "Mood Quotes draft not found.")
    quote = _valid_quote(spec.quote)
    if preserve_composition:
        composition = _model_composition(json.loads(source["composition_json"]))
        text = composition["text"]["text"].strip()
        if text:
            quote["text"] = text
            quote["segments"] = (
                [{"text": segment["text"], "order": index} for index, segment in enumerate(composition["segments"], 1)]
                if composition["text_mode"] == "sequential" else [{"text": text, "order": 1}]
            )
            quote = _valid_quote(quote)
    else:
        composition = _mood_quote_composition(quote, json.loads(source["composition_json"]))
    referenced = {
        asset_id for asset_id in (
            composition["background"].get("asset_id"), composition["music"].get("asset_id")
        ) if asset_id
    }
    assets = []
    if referenced:
        marks = ",".join("?" for _ in referenced)
        assets = conn.execute(
            f"SELECT * FROM mood_assets WHERE project_id=? AND id IN ({marks})",
            [source_project_id, *referenced],
        ).fetchall()
        if len(assets) != len(referenced):
            raise HTTPException(409, "Selected Mood asset is missing. Re-select asset before batching.")
    mapping = {}
    for row in assets:
        item = dict(row)
        if not (item.get("source_id") or item.get("library_asset_id")):
            raise HTTPException(409, "Batch needs shared Asset Library media; re-link project-owned legacy assets first.")
        _safe_asset(item)
        mapping[row["id"]] = uuid.uuid4().hex
    for section in ("background", "music"):
        asset_id = composition[section].get("asset_id")
        if asset_id:
            composition[section]["asset_id"] = mapping[asset_id]

    project_id, timestamp = uuid.uuid4().hex, now()
    title = f"{batch['name']} · {position + 1:02d} · {spec.name.strip()}"[:120]
    conn.execute(
        "INSERT INTO mood_projects(id,title,category_id,subcategory_id,custom_topic,tone,perspective,length,language,provider,selected_quote_json,composition_json,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, title, source["category_id"], source["subcategory_id"], source["custom_topic"], source["tone"],
         source["perspective"], source["length"], source["language"], source["provider"], _json(quote),
         _json(composition), timestamp, timestamp),
    )
    for row in assets:
        conn.execute(
            "INSERT INTO mood_assets(id,project_id,source_id,library_asset_id,kind,name,path,mime_type,size_bytes,duration,width,height,has_audio,sha256,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mapping[row["id"]], project_id, row["source_id"], row["library_asset_id"], row["kind"], row["name"],
             row["path"], row["mime_type"], row["size_bytes"], row["duration"], row["width"], row["height"],
             row["has_audio"], row["sha256"], timestamp),
        )
    item_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO video_batch_items(id,batch_id,position,name,status,mood_project_id,created_at,updated_at) VALUES(?,?,?,?,'ready',?,?,?)",
        (item_id, batch["id"], position, spec.name.strip(), project_id, timestamp, timestamp),
    )
    return item_id


def _storage_ok():
    roots = {DATA_DIR, SOURCE_DIR, WORK_DIR, MOOD_DIR, CLIP_DIR}
    return min(shutil.disk_usage(root).free for root in roots) >= MIN_FREE_BYTES


def _safe_item_error(exc):
    message = str(exc).splitlines()[0][:500]
    return message or "Item could not be queued."


def _queue_mood(conn, item, batch):
    from .mood_studio import _check_project_assets, _model_composition, _validate_music_timing

    project = conn.execute("SELECT * FROM mood_projects WHERE id=?", (item["mood_project_id"],)).fetchone()
    if project is None:
        raise HTTPException(404, "Mood Quotes item draft was deleted.")
    quote = json.loads(project["selected_quote_json"] or "null")
    if not quote:
        raise HTTPException(409, "Choose a quote for every Mood batch item.")
    composition = _model_composition(json.loads(project["composition_json"]))
    quote["text"] = composition["text"]["text"].strip()
    if composition["text_mode"] == "sequential":
        quote["segments"] = [{"text": segment["text"], "order": index} for index, segment in enumerate(composition["segments"], 1)]
    elif not quote["text"]:
        raise HTTPException(422, "Quote text is empty.")
    assets = _check_project_assets(project["id"], composition)
    music = composition["music"]
    if music.get("asset_id"):
        _validate_music_timing(composition, assets[music["asset_id"]])
    asset_hashes = sorted((asset["id"], asset["sha256"]) for asset in assets.values())
    snapshot = {"quote": quote, "composition": composition, "asset_hashes": asset_hashes}
    fingerprint = _digest(snapshot)
    timestamp, job_id, render_id = now(), uuid.uuid4().hex, uuid.uuid4().hex
    options = {"quote": quote, "composition": composition}
    conn.execute(
        "INSERT INTO mood_jobs(id,project_id,render_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
        "VALUES(?,?,?,'mood_render','queued','queued',NULL,'Batch Mood render queued',?,?,?)",
        (job_id, project["id"], render_id, _json(options), timestamp, timestamp),
    )
    conn.execute(
        "INSERT INTO mood_renders(id,project_id,job_id,path,status,review_status,composition_json,created_at,updated_at) "
        "VALUES(?,?,?,NULL,'queued','needs_review',?,?,?)",
        (render_id, project["id"], job_id, _json(composition), timestamp, timestamp),
    )
    conn.execute(
        "UPDATE video_batch_items SET job_id=?,snapshot_json=?,fingerprint=?,updated_at=? WHERE id=?",
        (job_id, _json(snapshot), fingerprint, timestamp, item["id"]),
    )


def _queue_clip(conn, item, batch):
    from .subtitles import composition_signature

    clip = conn.execute("SELECT * FROM clips WHERE id=?", (item["clip_id"],)).fetchone()
    if clip is None:
        raise HTTPException(404, "Batch clip item was deleted.")
    source = conn.execute("SELECT * FROM sources WHERE id=?", (clip["source_id"],)).fetchone()
    if source is None:
        raise HTTPException(404, "Video source was deleted.")
    _managed_source(source)
    edit = json.loads(clip["edit_json"])
    if edit.get("subtitle_enabled") and edit.get("subtitle_timebase") == "output":
        from .media import output_scenes
        scenes = output_scenes(dict(clip), edit)
        signature = composition_signature(scenes)
        active_id = edit.get("subtitle_active_track_id")
        active = next((track for track in edit.get("subtitle_tracks", []) if track.get("id") == active_id), None)
        if active and active.get("composition_signature") != signature:
            raise HTTPException(409, "Selected output-time subtitle track is stale. Refresh it in Clip Editor.")
    fingerprint = _digest({"source_sha256": source["sha256"], "edit": edit})
    snapshot = {"source_sha256": source["sha256"], "edit": edit}
    job_id, timestamp = uuid.uuid4().hex, now()
    conn.execute(
        "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
        "VALUES(?,?,?,'render','queued','queued',NULL,'Batch clip render queued',?,?,?)",
        (job_id, source["id"], clip["id"], _json({"edit": edit, "batch_item_id": item["id"]}), timestamp, timestamp),
    )
    conn.execute(
        "UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END,review_status='needs_review',reviewed_render_sha256=NULL WHERE id=?",
        (clip["id"],),
    )
    conn.execute(
        "UPDATE video_batch_items SET job_id=?,snapshot_json=?,fingerprint=?,updated_at=? WHERE id=?",
        (job_id, _json(snapshot), fingerprint, timestamp, item["id"]),
    )


def _finish_batch(conn, batch_id):
    rows = conn.execute("SELECT status FROM video_batch_items WHERE batch_id=?", (batch_id,)).fetchall()
    statuses = [row["status"] for row in rows]
    if not statuses or any(status in {"draft", "ready", "queued", "rendering"} for status in statuses):
        return
    failed = any(status in {"failed", "cancelled", "skipped"} for status in statuses)
    conn.execute(
        "UPDATE video_batches SET status=?,error=?,updated_at=? WHERE id=?",
        ("completed_with_errors" if failed else "completed", "One or more items did not complete." if failed else None, now(), batch_id),
    )


def _schedule_next(conn, batch_id):
    batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
    if batch is None or batch["status"] not in {"queued", "running"}:
        return
    if conn.execute("SELECT 1 FROM video_batch_items WHERE batch_id=? AND status IN ('queued','rendering') AND job_id IS NOT NULL", (batch_id,)).fetchone():
        return
    while True:
        item = conn.execute(
            "SELECT * FROM video_batch_items WHERE batch_id=? AND status='queued' AND job_id IS NULL ORDER BY position LIMIT 1",
            (batch_id,),
        ).fetchone()
        if item is None:
            _finish_batch(conn, batch_id)
            return
        if not _storage_ok():
            conn.execute(
                "UPDATE video_batches SET status='paused',error='Low disk space. Free at least 1 GiB, then resume batch.',updated_at=? WHERE id=?",
                (now(), batch_id),
            )
            return
        try:
            if batch["type"] == "video_clips":
                _queue_clip(conn, item, batch)
            else:
                _queue_mood(conn, item, batch)
            conn.execute("UPDATE video_batches SET updated_at=?,error=NULL WHERE id=?", (now(), batch_id))
            return
        except HTTPException as exc:
            conn.execute(
                "UPDATE video_batch_items SET status='failed',error=?,updated_at=? WHERE id=?",
                (_safe_item_error(exc.detail), now(), item["id"]),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            conn.execute(
                "UPDATE video_batch_items SET status='failed',error=?,updated_at=? WHERE id=?",
                (_safe_item_error(exc), now(), item["id"]),
            )


def batch_job_started(job_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        item = conn.execute("SELECT * FROM video_batch_items WHERE job_id=?", (job_id,)).fetchone()
        if item is None or item["status"] not in {"queued", "rendering"}:
            return
        batch = conn.execute("SELECT status FROM video_batches WHERE id=?", (item["batch_id"],)).fetchone()
        conn.execute("UPDATE video_batch_items SET status='rendering',updated_at=? WHERE id=?", (now(), item["id"]))
        if batch and batch["status"] == "queued":
            conn.execute("UPDATE video_batches SET status='running',updated_at=? WHERE id=?", (now(), item["batch_id"]))


def batch_job_finished(job_id):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        item = conn.execute("SELECT * FROM video_batch_items WHERE job_id=?", (job_id,)).fetchone()
        if item is None:
            return
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (item["batch_id"],)).fetchone()
        if batch is None:
            return
        job = conn.execute("SELECT status,message FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            job = conn.execute("SELECT status,message FROM mood_jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            status, message = "failed", "Render job record missing."
        else:
            status, message = job["status"], job["message"]
        if status == "completed":
            item_status = "completed"
            error = None
        elif status == "cancelled":
            item_status = "cancelled"
            error = "Render cancelled."
        elif status == "failed":
            item_status = "failed"
            error = _safe_item_error(message or "Render failed.")
        else:
            return
        conn.execute(
            "UPDATE video_batch_items SET status=?,error=?,updated_at=? WHERE id=?",
            (item_status, error, now(), item["id"]),
        )
        if batch["status"] == "cancelled":
            return
        if batch["status"] == "pausing":
            pending = conn.execute(
                "SELECT 1 FROM video_batch_items WHERE batch_id=? AND status='queued' AND job_id IS NULL LIMIT 1",
                (batch["id"],),
            ).fetchone()
            if pending:
                conn.execute("UPDATE video_batches SET status='paused',updated_at=? WHERE id=?", (now(), batch["id"]))
            else:
                _finish_batch(conn, batch["id"])
            return
        if batch["status"] == "paused":
            return
        _schedule_next(conn, batch["id"])


def _batch_public(batch_id):
    with connect() as conn:
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        items = conn.execute("SELECT * FROM video_batch_items WHERE batch_id=? ORDER BY position", (batch_id,)).fetchall()
        output = []
        for row in items:
            item = dict(row)
            public = {key: item[key] for key in (
                "id", "position", "name", "status", "custom_override", "error", "retry_count", "fingerprint", "created_at", "updated_at"
            )}
            public["custom_override"] = bool(public["custom_override"])
            public["job"] = None
            if item["job_id"]:
                job = conn.execute("SELECT id,status,phase,progress,message FROM jobs WHERE id=?", (item["job_id"],)).fetchone()
                if job is None:
                    job = conn.execute("SELECT id,status,phase,progress,message FROM mood_jobs WHERE id=?", (item["job_id"],)).fetchone()
                public["job"] = dict(job) if job else None
            if item["clip_id"]:
                clip = conn.execute("SELECT id,title,start,end,status,review_status,rendered_path FROM clips WHERE id=?", (item["clip_id"],)).fetchone()
                if clip:
                    public.update({"clip_id": clip["id"], "editor_url": f"/clips/{clip['id']}?batch={batch_id}",
                                   "output_url": f"/api/clips/{clip['id']}/file" if clip["rendered_path"] else None,
                                   "download_url": f"/api/clips/{clip['id']}/download" if clip["rendered_path"] else None,
                                   "review_status": clip["review_status"], "rendered": bool(clip["rendered_path"]),
                                   "start": clip["start"], "end": clip["end"], "clip_status": clip["status"]})
            if item["mood_project_id"]:
                project = conn.execute("SELECT title FROM mood_projects WHERE id=?", (item["mood_project_id"],)).fetchone()
                render = conn.execute(
                    "SELECT id,status,review_status,path FROM mood_renders WHERE project_id=? AND path IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                    (item["mood_project_id"],),
                ).fetchone()
                public.update({"mood_project_id": item["mood_project_id"],
                               "editor_url": f"/mood?id={item['mood_project_id']}&batch={batch_id}"})
                if project:
                    public["project_title"] = project["title"]
                if render:
                    public.update({"render_id": render["id"], "render_status": render["status"],
                                   "review_status": render["review_status"],
                                   "output_url": f"/api/mood-renders/{render['id']}/file" if render["path"] else None,
                                   "download_url": f"/api/mood-renders/{render['id']}/download" if render["path"] else None,
                                   "rendered": bool(render["path"])})
            output.append(public)
        statuses = [item["status"] for item in output]
    completed = statuses.count("completed")
    return {
        "id": batch["id"], "name": batch["name"], "type": batch["type"], "status": batch["status"],
        "source_id": batch["source_id"], "mood_source_project_id": batch["mood_source_project_id"],
        "shared_settings": json.loads(batch["shared_json"]), "error": batch["error"],
        "total": len(output), "completed_count": completed,
        "failed_count": statuses.count("failed"), "pending_count": statuses.count("draft") + statuses.count("ready") + statuses.count("queued"),
        "progress": completed / len(output) if output else 0,
        "items": output, "created_at": batch["created_at"], "updated_at": batch["updated_at"],
    }


def _load_batch(batch_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Batch not found.")
    return dict(row)


@router.post("/batches/clips")
def create_clip_batch(body: CreateClipBatch):
    batch_id, timestamp = uuid.uuid4().hex, now()
    settings = body.shared_settings.model_dump()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = conn.execute("SELECT * FROM sources WHERE id=?", (body.source_id,)).fetchone()
        if source is None:
            raise HTTPException(404, "Video source not found.")
        _managed_source(source)
        conn.execute(
            "INSERT INTO video_batches(id,name,type,status,source_id,shared_json,created_at,updated_at) VALUES(?,?,'video_clips','draft',?,?,?,?)",
            (batch_id, body.name.strip(), body.source_id, _json(settings), timestamp, timestamp),
        )
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        for position, spec in enumerate(body.items):
            _insert_clip_item(conn, batch, spec, position)
    return _batch_public(batch_id)


@router.post("/mood-projects/{project_id}/batches")
def create_mood_batch(project_id: str, body: CreateMoodBatch):
    batch_id, timestamp = uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = conn.execute("SELECT * FROM mood_projects WHERE id=?", (project_id,)).fetchone()
        if source is None:
            raise HTTPException(404, "Mood Quotes draft not found.")
        conn.execute(
            "INSERT INTO video_batches(id,name,type,status,mood_source_project_id,shared_json,created_at,updated_at) VALUES(?,?,'mood_quotes','draft',?,'{}',?,?)",
            (batch_id, body.name.strip(), project_id, timestamp, timestamp),
        )
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        for position, spec in enumerate(body.items):
            _insert_mood_item(conn, batch, spec, position, source)
    return _batch_public(batch_id)


@router.get("/batches")
def list_batches():
    with connect() as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM video_batches ORDER BY updated_at DESC LIMIT 200").fetchall()]
    return [_batch_public(batch_id) for batch_id in ids]


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str):
    return _batch_public(batch_id)


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT status FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] in {"queued", "running", "pausing"}:
            raise HTTPException(409, "Pause or cancel batch before removing its queue record.")
        active = conn.execute(
            "SELECT 1 FROM video_batch_items i WHERE i.batch_id=? AND ("
            "i.job_id IN (SELECT id FROM jobs WHERE status IN ('queued','preparing','rendering')) OR "
            "i.job_id IN (SELECT id FROM mood_jobs WHERE status IN ('queued','preparing','rendering'))) LIMIT 1",
            (batch_id,),
        ).fetchone()
        if active:
            raise HTTPException(409, "Wait for batch render jobs to stop before removing queue record.")
        conn.execute("DELETE FROM video_batches WHERE id=?", (batch_id,))
    return {"deleted": True, "outputs_preserved": True}


@router.patch("/batches/{batch_id}")
def update_batch(batch_id: str, body: BatchPatch):
    changes = body.model_dump(exclude_unset=True)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] in {"queued", "running", "pausing"}:
            raise HTTPException(409, "Pause batch before changing shared settings.")
        if "name" in changes:
            conn.execute("UPDATE video_batches SET name=?,updated_at=? WHERE id=?", (changes["name"].strip(), now(), batch_id))
        if changes.get("shared_settings") is not None:
            if batch["type"] != "video_clips":
                raise HTTPException(422, "Clip export settings apply only to Video Clips batches.")
            if batch["status"] not in {"draft", "ready", "paused"}:
                raise HTTPException(409, "Shared settings can change only before start or while batch is paused.")
            settings = changes["shared_settings"]
            conn.execute("UPDATE video_batches SET shared_json=?,updated_at=? WHERE id=?", (_json(settings), now(), batch_id))
            if changes.get("apply_to_pending"):
                for item in conn.execute(
                    "SELECT * FROM video_batch_items WHERE batch_id=? AND custom_override=0 AND "
                    "(status IN ('ready','draft') OR (status='queued' AND job_id IS NULL))",
                    (batch_id,),
                ).fetchall():
                    clip = conn.execute("SELECT * FROM clips WHERE id=?", (item["clip_id"],)).fetchone()
                    if clip:
                        edit = json.loads(clip["edit_json"])
                        edit.update(settings)
                        conn.execute("UPDATE clips SET edit_json=? WHERE id=?", (_json(edit), clip["id"]))
    return _batch_public(batch_id)


@router.post("/batches/{batch_id}/start")
def start_batch(batch_id: str):
    if not _storage_ok():
        raise HTTPException(507, "Keep at least 1 GiB free for temporary processing and render output.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] in {"queued", "running"}:
            return _batch_public(batch_id)
        if batch["status"] not in {"draft", "ready"}:
            raise HTTPException(409, "Resume paused batches or retry failed items.")
        if not conn.execute("SELECT 1 FROM video_batch_items WHERE batch_id=? AND status IN ('ready','draft')", (batch_id,)).fetchone():
            raise HTTPException(409, "Batch has no ready items.")
        conn.execute("UPDATE video_batch_items SET status='queued',error=NULL,updated_at=? WHERE batch_id=? AND status IN ('ready','draft')", (now(), batch_id))
        conn.execute("UPDATE video_batches SET status='queued',error=NULL,updated_at=? WHERE id=?", (now(), batch_id))
        _schedule_next(conn, batch_id)
    return _batch_public(batch_id)


@router.post("/batches/{batch_id}/pause")
def pause_batch(batch_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] == "paused":
            return _batch_public(batch_id)
        if batch["status"] not in {"queued", "running"}:
            raise HTTPException(409, "Only queued or running batches can be paused.")
        active = conn.execute("SELECT * FROM video_batch_items WHERE batch_id=? AND job_id IS NOT NULL AND status IN ('queued','rendering') LIMIT 1", (batch_id,)).fetchone()
        if active:
            job = conn.execute("SELECT status FROM jobs WHERE id=?", (active["job_id"],)).fetchone()
            queue = "jobs"
            if job is None:
                job = conn.execute("SELECT status FROM mood_jobs WHERE id=?", (active["job_id"],)).fetchone()
                queue = "mood_jobs"
            if job and job["status"] == "queued":
                conn.execute(f"UPDATE {queue} SET status='cancelled',phase='cancelled',message='Held by batch pause',updated_at=? WHERE id=? AND status='queued'", (now(), active["job_id"]))
                if queue == "mood_jobs":
                    conn.execute("UPDATE mood_renders SET status='cancelled',updated_at=? WHERE job_id=?", (now(), active["job_id"]))
                conn.execute("UPDATE video_batch_items SET job_id=NULL,status='queued',updated_at=? WHERE id=?", (now(), active["id"]))
                conn.execute("UPDATE video_batches SET status='paused',updated_at=? WHERE id=?", (now(), batch_id))
            else:
                conn.execute("UPDATE video_batches SET status='pausing',updated_at=? WHERE id=?", (now(), batch_id))
        else:
            conn.execute("UPDATE video_batches SET status='paused',updated_at=? WHERE id=?", (now(), batch_id))
    return _batch_public(batch_id)


@router.post("/batches/{batch_id}/resume")
def resume_batch(batch_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] != "paused":
            raise HTTPException(409, "Only paused batches can resume.")
        if not conn.execute("SELECT 1 FROM video_batch_items WHERE batch_id=? AND status='queued'", (batch_id,)).fetchone():
            raise HTTPException(409, "No pending items. Retry failed items first.")
        conn.execute("UPDATE video_batches SET status='queued',error=NULL,updated_at=? WHERE id=?", (now(), batch_id))
        _schedule_next(conn, batch_id)
    return _batch_public(batch_id)


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str):
    jobs = []
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
            raise HTTPException(409, "Batch is already terminal.")
        rows = conn.execute("SELECT * FROM video_batch_items WHERE batch_id=? AND job_id IS NOT NULL AND status IN ('queued','rendering')", (batch_id,)).fetchall()
        jobs = [row["job_id"] for row in rows]
        conn.execute("UPDATE video_batch_items SET status='cancelled',error='Cancelled by user.',updated_at=? WHERE batch_id=? AND status IN ('draft','ready','queued')", (now(), batch_id))
        conn.execute("UPDATE video_batches SET status='cancelled',error='Cancelled by user.',updated_at=? WHERE id=?", (now(), batch_id))
    for job_id in jobs:
        runner.cancel(job_id)
    return _batch_public(batch_id)


def _retry_items(batch_id, item_ids=None):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] in {"queued", "running", "pausing"}:
            raise HTTPException(409, "Pause batch before retrying items.")
        if item_ids is None:
            rows = conn.execute("SELECT * FROM video_batch_items WHERE batch_id=? AND status IN ('failed','cancelled')", (batch_id,)).fetchall()
        else:
            rows = [conn.execute("SELECT * FROM video_batch_items WHERE batch_id=? AND id=?", (batch_id, item_id)).fetchone() for item_id in item_ids]
            if any(row is None or row["status"] not in {"failed", "cancelled"} for row in rows):
                raise HTTPException(409, "Selected item is not retryable.")
        if not rows:
            raise HTTPException(409, "No retryable items.")
        for row in rows:
            conn.execute(
                "UPDATE video_batch_items SET status='queued',job_id=NULL,error=NULL,retry_count=retry_count+1,updated_at=? WHERE id=?",
                (now(), row["id"]),
            )
        conn.execute("UPDATE video_batches SET status='queued',error=NULL,updated_at=? WHERE id=?", (now(), batch_id))
        _schedule_next(conn, batch_id)
    return _batch_public(batch_id)


@router.post("/batches/{batch_id}/retry-failed")
def retry_failed_items(batch_id: str):
    return _retry_items(batch_id)


@router.post("/batches/{batch_id}/items/{item_id}/retry")
def retry_batch_item(batch_id: str, item_id: str):
    return _retry_items(batch_id, [item_id])


@router.post("/batches/{batch_id}/items")
def add_batch_item(batch_id: str, body: AddBatchItem):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        if batch["status"] not in {"draft", "ready", "paused"}:
            raise HTTPException(409, "Items can only be added before start or while batch is paused.")
        count = conn.execute("SELECT count(*) FROM video_batch_items WHERE batch_id=?", (batch_id,)).fetchone()[0]
        if count >= MAX_BATCH_ITEMS:
            raise HTTPException(422, f"A batch can contain at most {MAX_BATCH_ITEMS} items.")
        position = count
        if batch["type"] == "video_clips":
            if body.start is None or body.end is None or body.quote is not None:
                raise HTTPException(422, "Video Clips item needs start/end and no quote.")
            item_id = _insert_clip_item(conn, batch, ClipItemSpec(name=body.name, start=body.start, end=body.end), position)
        else:
            if body.quote is None or body.start is not None or body.end is not None:
                raise HTTPException(422, "Mood Quotes item needs one quote.")
            item_id = _insert_mood_item(conn, batch, MoodItemSpec(name=body.name, quote=body.quote), position)
        if batch["status"] == "paused":
            conn.execute("UPDATE video_batch_items SET status='queued' WHERE id=?", (item_id,))
        conn.execute("UPDATE video_batches SET updated_at=? WHERE id=?", (now(), batch_id))
    return _batch_public(batch_id)


@router.post("/batches/{batch_id}/items/{item_id}/duplicate")
def duplicate_batch_item(batch_id: str, item_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        item = conn.execute("SELECT * FROM video_batch_items WHERE batch_id=? AND id=?", (batch_id, item_id)).fetchone()
        if batch is None or item is None:
            raise HTTPException(404, "Batch item not found.")
        if batch["status"] not in {"draft", "ready"} or item["status"] not in {"ready", "draft"}:
            raise HTTPException(409, "Only pending items in an unstarted batch can be duplicated.")
        count = conn.execute("SELECT count(*) FROM video_batch_items WHERE batch_id=?", (batch_id,)).fetchone()[0]
        if count >= MAX_BATCH_ITEMS:
            raise HTTPException(422, f"A batch can contain at most {MAX_BATCH_ITEMS} items.")
        name = f"{item['name']} copy"[:120]
        if batch["type"] == "video_clips":
            clip = conn.execute("SELECT * FROM clips WHERE id=?", (item["clip_id"],)).fetchone()
            spec = ClipItemSpec(name=name, start=clip["start"], end=clip["end"])
            new_id = _insert_clip_item(conn, batch, spec, count)
            new_item = conn.execute("SELECT clip_id FROM video_batch_items WHERE id=?", (new_id,)).fetchone()
            edit = json.loads(clip["edit_json"])
            edit["scenes"] = [dict(scene, id=f"scene-{new_item['clip_id']}-{index}") for index, scene in enumerate(edit.get("scenes", []))]
            source_job = conn.execute("SELECT job_id FROM clips WHERE id=?", (new_item["clip_id"],)).fetchone()
            conn.execute("UPDATE clips SET edit_json=? WHERE id=?", (_json(edit), new_item["clip_id"]))
            conn.execute("UPDATE jobs SET options_json=? WHERE id=?", (_json({"edit": edit}), source_job["job_id"]))
            conn.execute("UPDATE video_batch_items SET custom_override=? WHERE id=?", (item["custom_override"], new_id))
        else:
            project = conn.execute("SELECT * FROM mood_projects WHERE id=?", (item["mood_project_id"],)).fetchone()
            quote = json.loads(project["selected_quote_json"] or "null")
            if not quote:
                raise HTTPException(409, "Mood Quotes item has no selected quote to duplicate.")
            new_id = _insert_mood_item(
                conn, batch, MoodItemSpec(name=name, quote=quote), count,
                source_project=project, source_project_id=item["mood_project_id"], preserve_composition=True,
            )
            conn.execute("UPDATE video_batch_items SET custom_override=? WHERE id=?", (item["custom_override"], new_id))
        conn.execute("UPDATE video_batches SET updated_at=? WHERE id=?", (now(), batch_id))
    return _batch_public(batch_id)


@router.patch("/batches/{batch_id}/items/order")
def reorder_batch_items(batch_id: str, body: BatchOrder):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT status FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        rows = conn.execute("SELECT id,status,job_id,position FROM video_batch_items WHERE batch_id=? ORDER BY position", (batch_id,)).fetchall()
        ids = [row["id"] for row in rows]
        if batch["status"] in {"draft", "ready"}:
            movable = set(ids)
        elif batch["status"] in {"queued", "running", "paused"}:
            movable = {row["id"] for row in rows if row["status"] == "queued" and row["job_id"] is None}
            locked = {row["position"]: row["id"] for row in rows if row["id"] not in movable}
            if any(body.item_ids[position] != item_id for position, item_id in locked.items()):
                raise HTTPException(409, "Active and completed items cannot move; reorder pending items only.")
        else:
            raise HTTPException(409, "Completed batch order is locked.")
        if set(body.item_ids) != set(ids) or len(body.item_ids) != len(ids) or {item_id for item_id in body.item_ids if item_id in movable} != movable:
            raise HTTPException(409, "Reorder requires every batch item exactly once.")
        for position, item_id in enumerate(body.item_ids):
            conn.execute("UPDATE video_batch_items SET position=? WHERE id=?", (-position - 1, item_id))
        for position, item_id in enumerate(body.item_ids):
            conn.execute("UPDATE video_batch_items SET position=?,updated_at=? WHERE id=?", (position, now(), item_id))
        conn.execute("UPDATE video_batches SET updated_at=? WHERE id=?", (now(), batch_id))
    return _batch_public(batch_id)


@router.delete("/batches/{batch_id}/items/{item_id}")
def remove_batch_item(batch_id: str, item_id: str):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM video_batches WHERE id=?", (batch_id,)).fetchone()
        item = conn.execute("SELECT * FROM video_batch_items WHERE batch_id=? AND id=?", (batch_id, item_id)).fetchone()
        if batch is None or item is None:
            raise HTTPException(404, "Batch item not found.")
        removable = batch["status"] in {"draft", "ready"} and item["status"] in {"ready", "draft"}
        removable = removable or batch["status"] in {"queued", "running", "paused"} and item["status"] == "queued" and item["job_id"] is None
        if not removable:
            raise HTTPException(409, "Only unclaimed pending items can be removed.")
        if item["clip_id"]:
            clip = conn.execute("SELECT rendered_path FROM clips WHERE id=?", (item["clip_id"],)).fetchone()
            if clip and clip["rendered_path"]:
                raise HTTPException(409, "Keep rendered output. Remove is limited to items without a saved MP4.")
            conn.execute("DELETE FROM clips WHERE id=?", (item["clip_id"],))
            conn.execute("DELETE FROM jobs WHERE clip_id=?", (item["clip_id"],))
        if item["mood_project_id"]:
            if conn.execute("SELECT 1 FROM mood_renders WHERE project_id=? AND path IS NOT NULL LIMIT 1", (item["mood_project_id"],)).fetchone():
                raise HTTPException(409, "Keep rendered output. Remove is limited to items without a saved MP4.")
            conn.execute("DELETE FROM mood_projects WHERE id=?", (item["mood_project_id"],))
        conn.execute("DELETE FROM video_batch_items WHERE id=?", (item_id,))
        conn.execute(
            "UPDATE video_batch_items SET position=-position-1 WHERE batch_id=? AND position>?",
            (batch_id, item["position"]),
        )
        conn.execute(
            "UPDATE video_batch_items SET position=-position-2 WHERE batch_id=? AND position<?",
            (batch_id, -item["position"] - 1),
        )
        remaining = conn.execute("SELECT count(*) FROM video_batch_items WHERE batch_id=?", (batch_id,)).fetchone()[0]
        if not remaining:
            conn.execute("UPDATE video_batches SET status='cancelled',error='No items remain.',updated_at=? WHERE id=?", (now(), batch_id))
        else:
            conn.execute("UPDATE video_batches SET updated_at=? WHERE id=?", (now(), batch_id))
    return _batch_public(batch_id)
