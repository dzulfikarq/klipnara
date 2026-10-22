import json
import sqlite3
from contextlib import contextmanager

from .config import CLIP_DIR, DATA_DIR, DB_PATH, SOURCE_DIR, WORK_DIR


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
    for directory in (DATA_DIR, SOURCE_DIR, WORK_DIR, CLIP_DIR):
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
                rendered_path TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS clips_source_rank ON clips(source_id, rank);
            CREATE TABLE IF NOT EXISTS provider_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                provider TEXT NOT NULL, model TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, created_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
        if "transcript_config" not in columns:
            conn.execute("ALTER TABLE sources ADD COLUMN transcript_config TEXT")
        conn.execute(
            "UPDATE jobs SET status='failed', phase='interrupted', progress=NULL, "
            "message='Worker stopped before job finished. Retry to resume from saved transcript.' "
            "WHERE status IN ('preparing','transcribing','analyzing','rendering')"
        )


def unpack(row, json_fields=()):
    if row is None:
        return None
    value = dict(row)
    for field in json_fields:
        if value.get(field):
            value[field.removesuffix("_json")] = json.loads(value.pop(field))
    return value
