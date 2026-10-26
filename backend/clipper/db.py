import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import CLIP_DIR, DATA_DIR, DB_PATH, MOOD_DIR, SOURCE_DIR, WORK_DIR


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    for directory in (DATA_DIR, SOURCE_DIR, WORK_DIR, CLIP_DIR, MOOD_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL, duration REAL NOT NULL, width INTEGER NOT NULL,
                height INTEGER NOT NULL, video_codec TEXT NOT NULL, audio_codec TEXT,
                sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                transcript_json TEXT, transcript_model TEXT, transcript_language TEXT, transcript_config TEXT
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                clip_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
                progress REAL, message TEXT, options_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);
            CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                start REAL NOT NULL, end REAL NOT NULL, title TEXT NOT NULL, reason TEXT NOT NULL,
                rank INTEGER NOT NULL, edit_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready',
                review_status TEXT NOT NULL DEFAULT 'needs_review',
                reviewed_render_sha256 TEXT,
                rendered_path TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS clips_source_rank ON clips(source_id, rank);
            CREATE TABLE IF NOT EXISTS provider_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                provider TEXT NOT NULL, model TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analysis_chunks (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL, cache_key TEXT NOT NULL,
                input_tokens INTEGER NOT NULL, candidates_json TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(job_id, chunk_index)
            );
            CREATE TABLE IF NOT EXISTS youtube_oauth_states (
                state_hash TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_accounts (
                id TEXT PRIMARY KEY, channel_id TEXT NOT NULL UNIQUE, channel_title TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('connected','expired','error','disconnected')),
                token_blob BLOB, expires_at REAL, error_message TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_publications (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES youtube_accounts(id),
                clip_id TEXT NOT NULL, clip_title TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','uploading','processing','published','failed','cancelled')),
                title TEXT NOT NULL, description TEXT NOT NULL, tags_json TEXT NOT NULL,
                privacy_status TEXT NOT NULL, made_for_kids INTEGER NOT NULL,
                contains_synthetic_media INTEGER NOT NULL,
                rendered_path TEXT NOT NULL, rendered_sha256 TEXT NOT NULL,
                file_size INTEGER NOT NULL, duration REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                uploaded_bytes INTEGER NOT NULL DEFAULT 0, upload_started INTEGER NOT NULL DEFAULT 0,
                upload_session_blob BLOB, video_id TEXT, video_url TEXT,
                job_id TEXT, attempts INTEGER NOT NULL DEFAULT 1,
                processing_checks INTEGER NOT NULL DEFAULT 0,
                reconciliation_required INTEGER NOT NULL DEFAULT 0,
                next_poll_at REAL, last_error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS youtube_publications_history ON youtube_publications(created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS youtube_publications_no_duplicate
                ON youtube_publications(account_id,rendered_sha256)
                WHERE status IN ('pending','uploading','processing','published');
            CREATE TABLE IF NOT EXISTS mood_projects (
                id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'Mood Quotes',
                category_id TEXT, subcategory_id TEXT, custom_topic TEXT NOT NULL DEFAULT '',
                tone TEXT NOT NULL DEFAULT 'natural', perspective TEXT NOT NULL DEFAULT 'netral',
                length TEXT NOT NULL DEFAULT 'short', language TEXT NOT NULL DEFAULT 'indonesia',
                provider TEXT NOT NULL DEFAULT 'gemini',
                selected_quote_json TEXT, composition_json TEXT NOT NULL,
                current_generation_id TEXT, current_render_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mood_generations (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES mood_projects(id) ON DELETE CASCADE,
                provider TEXT NOT NULL, model TEXT NOT NULL, request_json TEXT NOT NULL, quotes_json TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS mood_generations_project ON mood_generations(project_id,created_at DESC);
            CREATE TABLE IF NOT EXISTS mood_favorites (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES mood_projects(id) ON DELETE CASCADE,
                generation_id TEXT REFERENCES mood_generations(id) ON DELETE SET NULL,
                quote_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS mood_favorites_project ON mood_favorites(project_id,created_at DESC);
            CREATE TABLE IF NOT EXISTS mood_assets (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES mood_projects(id) ON DELETE CASCADE,
                source_id TEXT REFERENCES sources(id) ON DELETE RESTRICT,
                kind TEXT NOT NULL CHECK(kind IN ('background_image','background_video','music')),
                name TEXT NOT NULL, path TEXT NOT NULL, mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, duration REAL, width INTEGER, height INTEGER,
                has_audio INTEGER NOT NULL DEFAULT 0, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS mood_assets_project ON mood_assets(project_id,created_at DESC);
            CREATE TABLE IF NOT EXISTS mood_jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES mood_projects(id) ON DELETE CASCADE,
                render_id TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'mood_render',
                status TEXT NOT NULL, phase TEXT NOT NULL, progress REAL, message TEXT,
                options_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS mood_jobs_status_created ON mood_jobs(status,created_at);
            CREATE TABLE IF NOT EXISTS mood_renders (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES mood_projects(id) ON DELETE CASCADE,
                job_id TEXT NOT NULL REFERENCES mood_jobs(id) ON DELETE CASCADE,
                path TEXT, status TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'needs_review',
                reviewed_render_sha256 TEXT, composition_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS mood_renders_project ON mood_renders(project_id,created_at DESC);
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
        if "transcript_config" not in columns:
            conn.execute("ALTER TABLE sources ADD COLUMN transcript_config TEXT")
        clip_columns = {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}
        if "review_status" not in clip_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN review_status TEXT NOT NULL DEFAULT 'needs_review'")
        if "reviewed_render_sha256" not in clip_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN reviewed_render_sha256 TEXT")
        conn.execute(
            "UPDATE clips SET review_status='needs_review' WHERE review_status='approved' AND reviewed_render_sha256 IS NULL"
        )
        conn.execute(
            "UPDATE jobs SET status='failed', phase='interrupted', progress=NULL, "
            "message='Worker stopped before job finished. Retry to resume from saved transcript.' "
            "WHERE status IN ('preparing','transcribing','analyzing','rendering')"
        )
        conn.execute(
            "UPDATE youtube_publications SET status='processing',next_poll_at=0,last_error=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE status='uploading' AND video_id IS NOT NULL"
        )
        conn.execute(
            "UPDATE youtube_publications SET status='failed',last_error='Worker stopped. Retry will reconcile resumable upload before sending more bytes.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status='uploading' AND video_id IS NULL"
        )
        conn.execute(
            "UPDATE youtube_publications SET status='failed',last_error='Worker stopped before upload began. Retry is safe.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE kind='youtube_upload' AND status='failed')"
        )
        interrupted_mood_renders = [row["id"] for row in conn.execute(
            "SELECT r.id FROM mood_renders r JOIN mood_jobs j ON j.id=r.job_id "
            "WHERE j.status IN ('preparing','rendering') AND r.path IS NULL"
        ).fetchall()]
        conn.execute(
            "UPDATE mood_jobs SET status='completed',phase='completed',progress=1,message='Render selesai sebelum worker berhenti.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('preparing','rendering') AND render_id IN (SELECT id FROM mood_renders WHERE status='completed' AND path IS NOT NULL)"
        )
        conn.execute(
            "UPDATE mood_jobs SET status='failed',phase='interrupted',progress=NULL,message='Worker berhenti saat render. Retry untuk melanjutkan draft.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('preparing','rendering')"
        )
        conn.execute(
            "UPDATE mood_renders SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','rendering') "
            "AND job_id IN (SELECT id FROM mood_jobs WHERE status='failed')"
        )
    for render_id in interrupted_mood_renders:
        (CLIP_DIR / f"mood-{render_id}.mp4").unlink(missing_ok=True)
        for suffix in (".ass", ".ppm", ".log"):
            (WORK_DIR / f"mood-{render_id}{suffix}").unlink(missing_ok=True)


def unpack(row, json_fields=()):
    if row is None:
        return None
    value = dict(row)
    for field in json_fields:
        if value.get(field):
            value[field.removesuffix("_json")] = json.loads(value.pop(field))
    return value
