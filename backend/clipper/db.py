import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import ASSET_DIR, CLIP_DIR, DATA_DIR, DB_PATH, MOOD_DIR, SOURCE_DIR, WORK_DIR


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
    for directory in (DATA_DIR, SOURCE_DIR, ASSET_DIR, WORK_DIR, CLIP_DIR, MOOD_DIR):
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
            CREATE TABLE IF NOT EXISTS library_assets (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('video','image','audio')),
                source TEXT NOT NULL DEFAULT 'local', provider_asset_id TEXT, source_url TEXT, preview_url TEXT,
                creator_name TEXT, creator_url TEXT, license_reference TEXT,
                imported_at TEXT NOT NULL, source_id TEXT UNIQUE REFERENCES sources(id) ON DELETE RESTRICT,
                title TEXT NOT NULL, path TEXT NOT NULL, mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, duration REAL, width INTEGER, height INTEGER,
                sha256 TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0,1)),
                last_used_at TEXT, artist TEXT, mood_tags_json TEXT NOT NULL DEFAULT '[]',
                license_type TEXT, license_notes TEXT, attribution_text TEXT, created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS library_assets_provider_id
                ON library_assets(source,provider_asset_id) WHERE provider_asset_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS library_assets_kind_created ON library_assets(kind,created_at DESC);
            CREATE INDEX IF NOT EXISTS library_assets_sha ON library_assets(kind,sha256);
            CREATE TABLE IF NOT EXISTS asset_provider_favorites (
                provider TEXT NOT NULL, provider_asset_id TEXT NOT NULL, source_url TEXT NOT NULL,
                preview_url TEXT, creator_name TEXT, creator_url TEXT, duration REAL NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL, orientation TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(provider,provider_asset_id)
            );
            CREATE TABLE IF NOT EXISTS asset_import_jobs (
                id TEXT PRIMARY KEY, provider_asset_id TEXT NOT NULL, video_file_id TEXT NOT NULL,
                quality TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
                progress REAL, bytes_downloaded INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER,
                message TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                asset_id TEXT REFERENCES library_assets(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS asset_import_status ON asset_import_jobs(status,created_at);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                clip_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
                progress REAL, message TEXT, options_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);
            CREATE TABLE IF NOT EXISTS youtube_import_jobs (
                id TEXT PRIMARY KEY, video_id TEXT NOT NULL, canonical_url TEXT NOT NULL,
                start_seconds REAL NOT NULL, end_seconds REAL NOT NULL,
                rights_confirmed INTEGER NOT NULL CHECK(rights_confirmed IN (0,1)),
                status TEXT NOT NULL, phase TEXT NOT NULL, progress REAL, message TEXT,
                source_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS youtube_import_status_created ON youtube_import_jobs(status,created_at);
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
                state_hash TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at REAL NOT NULL,
                account_id TEXT, purpose TEXT NOT NULL DEFAULT 'connect'
            );
            CREATE TABLE IF NOT EXISTS oauth_authorizations (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL CHECK(provider IN ('youtube','tiktok','instagram')),
                provider_subject_id TEXT, credentials_blob BLOB, granted_scopes_json TEXT NOT NULL DEFAULT '[]',
                expires_at REAL, refresh_expires_at REAL, token_status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS oauth_authorizations_provider ON oauth_authorizations(provider,token_status);
            CREATE TABLE IF NOT EXISTS youtube_accounts (
                id TEXT PRIMARY KEY, channel_id TEXT NOT NULL UNIQUE, channel_title TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('connected','expired','error','disconnected')),
                token_blob BLOB, expires_at REAL, error_message TEXT,
                channel_avatar_url TEXT, verified_at TEXT, granted_scopes_json TEXT,
                authorization_id TEXT REFERENCES oauth_authorizations(id), is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_publications (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES youtube_accounts(id),
                authorization_id TEXT REFERENCES oauth_authorizations(id), target_channel_id TEXT,
                clip_id TEXT NOT NULL, clip_title TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','uploading','processing','published','failed','cancelled')),
                title TEXT NOT NULL, description TEXT NOT NULL, tags_json TEXT NOT NULL,
                privacy_status TEXT NOT NULL, made_for_kids INTEGER NOT NULL,
                contains_synthetic_media INTEGER NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'clip', category_id TEXT NOT NULL DEFAULT '22', video_language TEXT,
                hashtags_json TEXT NOT NULL DEFAULT '[]', remote_status TEXT, publish_at TEXT, published_at TEXT,
                rendered_path TEXT NOT NULL, rendered_sha256 TEXT NOT NULL,
                file_size INTEGER NOT NULL, duration REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                uploaded_bytes INTEGER NOT NULL DEFAULT 0, upload_started INTEGER NOT NULL DEFAULT 0,
                upload_session_blob BLOB, video_id TEXT, video_url TEXT,
                attribution_json TEXT,
                job_id TEXT, attempts INTEGER NOT NULL DEFAULT 1,
                processing_checks INTEGER NOT NULL DEFAULT 0,
                reconciliation_required INTEGER NOT NULL DEFAULT 0,
                next_poll_at REAL, last_error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS youtube_publications_history ON youtube_publications(created_at DESC);
            CREATE INDEX IF NOT EXISTS youtube_publications_channel_video ON youtube_publications(account_id,status,video_id);
            CREATE UNIQUE INDEX IF NOT EXISTS youtube_publications_no_duplicate
                ON youtube_publications(account_id,rendered_sha256)
                WHERE status IN ('pending','uploading','processing','published');
            CREATE TABLE IF NOT EXISTS youtube_upload_jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'youtube_upload', status TEXT NOT NULL,
                phase TEXT NOT NULL, progress REAL, message TEXT, options_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS youtube_upload_jobs_status_created ON youtube_upload_jobs(status,created_at);
            CREATE TABLE IF NOT EXISTS youtube_analytics_cache (
                channel_id TEXT NOT NULL, query_key TEXT NOT NULL, query_json TEXT NOT NULL,
                response_json TEXT, actual_start_date TEXT, actual_end_date TEXT,
                status TEXT NOT NULL DEFAULT 'ok', fetched_at REAL, attempted_at REAL NOT NULL,
                error_code TEXT, error_message TEXT,
                PRIMARY KEY(channel_id,query_key)
            );
            CREATE INDEX IF NOT EXISTS youtube_analytics_cache_fetched ON youtube_analytics_cache(fetched_at);
            CREATE TABLE IF NOT EXISTS publishing_metadata_drafts (
                content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')),
                content_id TEXT NOT NULL, metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(content_type,content_id)
            );
            CREATE TABLE IF NOT EXISTS youtube_account_metadata_drafts (
                content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')),
                content_id TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES youtube_accounts(id) ON DELETE CASCADE,
                metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(content_type,content_id,account_id)
            );
            CREATE INDEX IF NOT EXISTS youtube_account_metadata_account ON youtube_account_metadata_drafts(account_id);
            CREATE TABLE IF NOT EXISTS publishing_metadata_templates (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, template_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS publishing_events (
                id TEXT PRIMARY KEY, content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')),
                content_id TEXT NOT NULL, publication_id TEXT REFERENCES youtube_publications(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL, message TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS publishing_events_content ON publishing_events(content_type,content_id,occurred_at DESC);
            CREATE TABLE IF NOT EXISTS platform_oauth_states (
                platform TEXT NOT NULL CHECK(platform IN ('tiktok','instagram')),
                state_hash TEXT NOT NULL, verifier_blob BLOB, created_at TEXT NOT NULL, expires_at REAL NOT NULL,
                PRIMARY KEY(platform,state_hash)
            );
            CREATE TABLE IF NOT EXISTS platform_accounts (
                id TEXT PRIMARY KEY, platform TEXT NOT NULL CHECK(platform IN ('tiktok','instagram')),
                platform_account_id TEXT NOT NULL, display_name TEXT NOT NULL, username TEXT,
                status TEXT NOT NULL CHECK(status IN ('connected','expired','error','disconnected')),
                token_blob BLOB, expires_at REAL, scopes_json TEXT NOT NULL DEFAULT '[]',
                details_json TEXT NOT NULL DEFAULT '{}', error_message TEXT,
                authorization_id TEXT REFERENCES oauth_authorizations(id), is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(platform,platform_account_id)
            );
            CREATE INDEX IF NOT EXISTS platform_accounts_status ON platform_accounts(platform,status,created_at DESC);
            CREATE TABLE IF NOT EXISTS platform_metadata_drafts (
                content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')),
                content_id TEXT NOT NULL, platform TEXT NOT NULL CHECK(platform IN ('tiktok','instagram')),
                metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(content_type,content_id,platform)
            );
            CREATE TABLE IF NOT EXISTS platform_account_metadata_drafts (
                content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')),
                content_id TEXT NOT NULL, platform TEXT NOT NULL CHECK(platform IN ('tiktok','instagram')),
                account_id TEXT NOT NULL REFERENCES platform_accounts(id) ON DELETE CASCADE,
                metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(content_type,content_id,platform,account_id)
            );
            CREATE INDEX IF NOT EXISTS platform_account_metadata_account ON platform_account_metadata_drafts(platform,account_id);
            CREATE TABLE IF NOT EXISTS platform_publications (
                id TEXT PRIMARY KEY, platform TEXT NOT NULL CHECK(platform IN ('tiktok','instagram')),
                content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')), content_id TEXT NOT NULL,
                account_id TEXT REFERENCES platform_accounts(id) ON DELETE SET NULL,
                authorization_id TEXT REFERENCES oauth_authorizations(id),
                target_account_id TEXT, media_sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL,
                upload_method TEXT NOT NULL CHECK(upload_method IN ('manual_export','inbox','direct_post','instagram_resumable')),
                status TEXT NOT NULL CHECK(status IN ('prepared_manual','queued','uploading','uploaded','processing','awaiting_manual_action','published','scheduled','failed','cancelled','needs_reconciliation')),
                remote_id TEXT, remote_url TEXT, retry_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT,
                UNIQUE(platform,content_type,content_id,media_sha256)
            );
            CREATE INDEX IF NOT EXISTS platform_publications_history ON platform_publications(created_at DESC);
            CREATE TABLE IF NOT EXISTS platform_upload_jobs (
                id TEXT PRIMARY KEY, platform TEXT NOT NULL CHECK(platform IN ('tiktok','instagram')),
                account_id TEXT NOT NULL REFERENCES platform_accounts(id), target_account_id TEXT NOT NULL,
                authorization_id TEXT REFERENCES oauth_authorizations(id), confirmed_at TEXT,
                content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')), content_id TEXT NOT NULL,
                media_sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                upload_method TEXT NOT NULL CHECK(upload_method IN ('tiktok_inbox','instagram_resumable')),
                status TEXT NOT NULL CHECK(status IN ('queued','uploading','processing','awaiting_manual_action','published','failed','cancelled','needs_reconciliation')),
                phase TEXT NOT NULL DEFAULT 'queued', progress REAL, uploaded_bytes INTEGER NOT NULL DEFAULT 0,
                upload_started INTEGER NOT NULL DEFAULT 0, remote_id TEXT, session_blob BLOB,
                provider_data_json TEXT NOT NULL DEFAULT '{}', attempts INTEGER NOT NULL DEFAULT 0,
                processing_checks INTEGER NOT NULL DEFAULT 0, next_poll_at REAL, last_error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT,
                UNIQUE(platform,account_id,content_type,content_id,media_sha256,upload_method)
            );
            CREATE INDEX IF NOT EXISTS platform_upload_jobs_queue ON platform_upload_jobs(status,created_at);
            CREATE INDEX IF NOT EXISTS platform_upload_jobs_poll ON platform_upload_jobs(status,next_poll_at);
            CREATE TABLE IF NOT EXISTS platform_upload_events (
                id TEXT PRIMARY KEY, upload_job_id TEXT NOT NULL REFERENCES platform_upload_jobs(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL, message TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS platform_upload_events_history ON platform_upload_events(upload_job_id,occurred_at DESC);
            CREATE TABLE IF NOT EXISTS platform_publishing_events (
                id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES platform_publications(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL, message TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS platform_publishing_events_history ON platform_publishing_events(publication_id,occurred_at DESC);
            CREATE TABLE IF NOT EXISTS publishing_thumbnails (
                content_type TEXT NOT NULL CHECK(content_type IN ('clip','mood_render')),
                content_id TEXT NOT NULL, path TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL, render_size INTEGER NOT NULL, render_mtime_ns INTEGER NOT NULL,
                remote_status TEXT NOT NULL DEFAULT 'local', remote_error TEXT, updated_at TEXT NOT NULL,
                PRIMARY KEY(content_type,content_id)
            );
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
                library_asset_id TEXT REFERENCES library_assets(id) ON DELETE RESTRICT,
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
            CREATE TABLE IF NOT EXISTS video_batches (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('video_clips','mood_quotes')),
                status TEXT NOT NULL CHECK(status IN ('draft','ready','queued','running','pausing','paused','completed','completed_with_errors','failed','cancelled')),
                source_id TEXT REFERENCES sources(id) ON DELETE RESTRICT,
                mood_source_project_id TEXT,
                shared_json TEXT NOT NULL DEFAULT '{}', error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS video_batches_updated ON video_batches(updated_at DESC);
            CREATE TABLE IF NOT EXISTS video_batch_items (
                id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES video_batches(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, name TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','ready','queued','rendering','completed','failed','cancelled','skipped')),
                clip_id TEXT, mood_project_id TEXT, job_id TEXT,
                custom_override INTEGER NOT NULL DEFAULT 0 CHECK(custom_override IN (0,1)),
                snapshot_json TEXT, fingerprint TEXT, error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(batch_id,position)
            );
            CREATE INDEX IF NOT EXISTS video_batch_items_order ON video_batch_items(batch_id,position);
            CREATE INDEX IF NOT EXISTS video_batch_items_job ON video_batch_items(job_id);
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
        if "transcript_config" not in columns:
            conn.execute("ALTER TABLE sources ADD COLUMN transcript_config TEXT")
        mood_asset_columns = {row["name"] for row in conn.execute("PRAGMA table_info(mood_assets)")}
        if "library_asset_id" not in mood_asset_columns:
            conn.execute("ALTER TABLE mood_assets ADD COLUMN library_asset_id TEXT REFERENCES library_assets(id) ON DELETE RESTRICT")
        account_columns = {row["name"] for row in conn.execute("PRAGMA table_info(youtube_accounts)")}
        for name, declaration in (
            ("channel_avatar_url", "TEXT"), ("verified_at", "TEXT"), ("granted_scopes_json", "TEXT"),
            ("authorization_id", "TEXT REFERENCES oauth_authorizations(id)"),
            ("is_default", "INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1))"),
        ):
            if name not in account_columns:
                conn.execute(f"ALTER TABLE youtube_accounts ADD COLUMN {name} {declaration}")
        platform_account_columns = {row["name"] for row in conn.execute("PRAGMA table_info(platform_accounts)")}
        for name, declaration in (
            ("authorization_id", "TEXT REFERENCES oauth_authorizations(id)"),
            ("is_default", "INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1))"),
        ):
            if name not in platform_account_columns:
                conn.execute(f"ALTER TABLE platform_accounts ADD COLUMN {name} {declaration}")
        publication_columns = {row["name"] for row in conn.execute("PRAGMA table_info(youtube_publications)")}
        for name, declaration in (
            ("authorization_id", "TEXT REFERENCES oauth_authorizations(id)"),
            ("target_channel_id", "TEXT"),
        ):
            if name not in publication_columns:
                conn.execute(f"ALTER TABLE youtube_publications ADD COLUMN {name} {declaration}")
        social_publication_columns = {row["name"] for row in conn.execute("PRAGMA table_info(platform_publications)")}
        if "authorization_id" not in social_publication_columns:
            conn.execute("ALTER TABLE platform_publications ADD COLUMN authorization_id TEXT REFERENCES oauth_authorizations(id)")
        platform_upload_columns = {row["name"] for row in conn.execute("PRAGMA table_info(platform_upload_jobs)")}
        for name, declaration in (
            ("authorization_id", "TEXT REFERENCES oauth_authorizations(id)"), ("confirmed_at", "TEXT"),
        ):
            if name not in platform_upload_columns:
                conn.execute(f"ALTER TABLE platform_upload_jobs ADD COLUMN {name} {declaration}")
        for provider, table, external_key, scope_key in (
            ("youtube", "youtube_accounts", "channel_id", "granted_scopes_json"),
            ("tiktok", "platform_accounts", "platform_account_id", "scopes_json"),
            ("instagram", "platform_accounts", "platform_account_id", "scopes_json"),
        ):
            provider_filter = " AND platform=?" if table == "platform_accounts" else ""
            query = f"SELECT id,{external_key},token_blob,{scope_key},expires_at,created_at,updated_at FROM {table} WHERE authorization_id IS NULL AND token_blob IS NOT NULL{provider_filter}"
            accounts = conn.execute(query, (provider,) if provider_filter else ()).fetchall()
            for account in accounts:
                authorization_id = f"legacy-{provider}-{account['id']}"
                conn.execute(
                    "INSERT OR IGNORE INTO oauth_authorizations(id,provider,credentials_blob,granted_scopes_json,expires_at,token_status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'active',?,?)",
                    (authorization_id, provider, account["token_blob"], account[scope_key] or "[]",
                     account["expires_at"], account["created_at"], account["updated_at"]),
                )
                conn.execute(f"UPDATE {table} SET authorization_id=? WHERE id=? AND authorization_id IS NULL",
                             (authorization_id, account["id"]))
        conn.execute(
            "UPDATE youtube_publications SET authorization_id=(SELECT authorization_id FROM youtube_accounts WHERE id=youtube_publications.account_id),"
            "target_channel_id=(SELECT channel_id FROM youtube_accounts WHERE id=youtube_publications.account_id) "
            "WHERE account_id IS NOT NULL AND (authorization_id IS NULL OR target_channel_id IS NULL)"
        )
        conn.execute(
            "UPDATE platform_upload_jobs SET authorization_id=(SELECT authorization_id FROM platform_accounts WHERE id=platform_upload_jobs.account_id) "
            "WHERE account_id IS NOT NULL AND authorization_id IS NULL"
        )
        conn.execute(
            "UPDATE platform_publications SET authorization_id=(SELECT authorization_id FROM platform_accounts WHERE id=platform_publications.account_id) "
            "WHERE account_id IS NOT NULL AND authorization_id IS NULL"
        )
        for table, provider_column in (("youtube_accounts", None), ("platform_accounts", "platform")):
            providers = [None] if provider_column is None else ["tiktok", "instagram"]
            for provider in providers:
                clause = "" if provider_column is None else f" AND {provider_column}=?"
                params = () if provider is None else (provider,)
                conn.execute(f"UPDATE {table} SET is_default=0 WHERE status!='connected' AND is_default=1{clause}", params)
                defaults = conn.execute(
                    f"SELECT id FROM {table} WHERE status='connected' AND is_default=1{clause} ORDER BY created_at,id",
                    params,
                ).fetchall()
                if len(defaults) > 1:
                    keep = defaults[0]["id"]
                    conn.execute(f"UPDATE {table} SET is_default=0 WHERE status='connected' AND is_default=1 AND id!=?{clause}",
                                 (keep, *params))
                if not defaults:
                    first = conn.execute(
                        f"SELECT id FROM {table} WHERE status='connected'{clause} ORDER BY created_at,id LIMIT 1",
                        params,
                    ).fetchone()
                    if first:
                        conn.execute(f"UPDATE {table} SET is_default=1 WHERE id=?", (first["id"],))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS youtube_accounts_one_default ON youtube_accounts(is_default) WHERE is_default=1")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS platform_accounts_one_default ON platform_accounts(platform) WHERE is_default=1")
        oauth_state_columns = {row["name"] for row in conn.execute("PRAGMA table_info(youtube_oauth_states)")}
        for name, declaration in (("account_id", "TEXT"), ("purpose", "TEXT NOT NULL DEFAULT 'connect'")):
            if name not in oauth_state_columns:
                conn.execute(f"ALTER TABLE youtube_oauth_states ADD COLUMN {name} {declaration}")
        publication_columns = {row["name"] for row in conn.execute("PRAGMA table_info(youtube_publications)")}
        publication_additions = (
            ("content_type", "TEXT NOT NULL DEFAULT 'clip'"),
            ("category_id", "TEXT NOT NULL DEFAULT '22'"),
            ("video_language", "TEXT"),
            ("hashtags_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("remote_status", "TEXT"),
            ("publish_at", "TEXT"),
            ("published_at", "TEXT"),
            ("attribution_json", "TEXT"),
        )
        for name, declaration in publication_additions:
            if name not in publication_columns:
                conn.execute(f"ALTER TABLE youtube_publications ADD COLUMN {name} {declaration}")
        thumbnail_columns = {row["name"] for row in conn.execute("PRAGMA table_info(publishing_thumbnails)")}
        if "remote_error" not in thumbnail_columns:
            conn.execute("ALTER TABLE publishing_thumbnails ADD COLUMN remote_error TEXT")
        platform_upload_columns = {row["name"] for row in conn.execute("PRAGMA table_info(platform_upload_jobs)")}
        if "file_size" not in platform_upload_columns:
            conn.execute("ALTER TABLE platform_upload_jobs ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "UPDATE platform_upload_jobs SET status='needs_reconciliation',"
            "phase=CASE WHEN phase='publishing' THEN 'publish_reconciliation' ELSE 'interrupted' END,progress=NULL,"
            "last_error='Backend stopped during transfer. No automatic retry was attempted; inspect provider state first.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status='uploading'"
        )
        conn.execute(
            "INSERT OR IGNORE INTO library_assets(id,kind,source,imported_at,source_id,title,path,mime_type,"
            "size_bytes,duration,width,height,sha256,created_at) "
            "SELECT id,'video','local',created_at,id,name,path,"
            "CASE WHEN lower(path) LIKE '%.mov' THEN 'video/quicktime' ELSE 'video/mp4' END,"
            "size_bytes,duration,width,height,sha256,created_at FROM sources"
        )
        interrupted_asset_imports = [row["id"] for row in conn.execute(
            "SELECT id FROM asset_import_jobs WHERE status IN ('queued','downloading','probing')"
        ).fetchall()]
        interrupted_subtitle_transcriptions = [row["id"] for row in conn.execute(
            "SELECT id FROM jobs WHERE kind='subtitle_transcribe' AND status IN ('preparing','preparing_audio','uploading','transcribing','processing_result')"
        ).fetchall()]
        conn.execute(
            "UPDATE asset_import_jobs SET status='failed',phase='interrupted',progress=NULL,"
            "message='Backend stopped during import. Retry is available.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('queued','downloading','probing')"
        )
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
            "message='Worker stopped before job finished. Retry is available; cloud retry requires fresh consent.' "
            "WHERE status IN ('preparing','preparing_audio','uploading','transcribing','processing_result','analyzing','rendering')"
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
        conn.execute(
            "UPDATE youtube_upload_jobs SET status='failed',phase='interrupted',progress=NULL,"
            "message='Worker stopped. Retry will reconcile resumable upload before sending more bytes.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('preparing','uploading')"
        )
        conn.execute(
            "UPDATE youtube_publications SET status='failed',last_error='Worker stopped before upload began. Retry is safe.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status='pending' AND job_id IN (SELECT id FROM youtube_upload_jobs WHERE status='failed')"
        )
        interrupted_youtube_imports = [row["id"] for row in conn.execute(
            "SELECT id FROM youtube_import_jobs WHERE status IN ('preparing','importing','processing')"
        ).fetchall()]
        conn.execute(
            "UPDATE youtube_import_jobs SET status='failed',phase='interrupted',progress=NULL,"
            "message='Backend stopped during import. Retry is available.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('preparing','importing','processing')"
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
        conn.execute(
            "UPDATE mood_renders SET status='cancelled',updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','rendering') "
            "AND job_id IN (SELECT id FROM mood_jobs WHERE status='cancelled')"
        )
        conn.execute(
            "UPDATE video_batch_items SET status='completed',error=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE job_id IN (SELECT j.id FROM jobs j JOIN clips c ON c.id=j.clip_id "
            "WHERE j.status='completed' AND c.status='completed' AND c.rendered_path IS NOT NULL)"
        )
        conn.execute(
            "UPDATE video_batch_items SET status='completed',error=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE job_id IN (SELECT j.id FROM mood_jobs j JOIN mood_renders r ON r.id=j.render_id "
            "WHERE j.status='completed' AND r.status='completed' AND r.path IS NOT NULL)"
        )
        conn.execute(
            "UPDATE video_batch_items SET status='failed',error='Render stopped before batch state was saved. Retry this item or resume batch.',"
            "updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','rendering') AND job_id IN ("
            "SELECT id FROM jobs WHERE status='failed' UNION ALL SELECT id FROM mood_jobs WHERE status='failed')"
        )
        conn.execute(
            "UPDATE video_batch_items SET status='cancelled',error='Render cancelled before batch state was saved.',"
            "updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','rendering') AND job_id IN ("
            "SELECT id FROM jobs WHERE status='cancelled' UNION ALL SELECT id FROM mood_jobs WHERE status='cancelled')"
        )
        conn.execute(
            "UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END "
            "WHERE status='rendering' AND job_id IN (SELECT id FROM jobs WHERE status IN ('failed','cancelled'))"
        )
        conn.execute(
            "UPDATE jobs SET status='cancelled',phase='cancelled',message='Batch paused after backend restart; resume to continue.',"
            "updated_at=CURRENT_TIMESTAMP WHERE status='queued' AND kind='render' AND id IN ("
            "SELECT job_id FROM video_batch_items WHERE status='queued' AND job_id IS NOT NULL)"
        )
        conn.execute(
            "UPDATE mood_jobs SET status='cancelled',phase='cancelled',message='Batch paused after backend restart; resume to continue.',"
            "updated_at=CURRENT_TIMESTAMP WHERE status='queued' AND kind='mood_render' AND id IN ("
            "SELECT job_id FROM video_batch_items WHERE status='queued' AND job_id IS NOT NULL)"
        )
        conn.execute(
            "UPDATE mood_renders SET status='cancelled',updated_at=CURRENT_TIMESTAMP WHERE job_id IN ("
            "SELECT id FROM mood_jobs WHERE status='cancelled' AND message='Batch paused after backend restart; resume to continue.')"
        )
        conn.execute(
            "UPDATE video_batch_items SET job_id=NULL WHERE status='queued' AND job_id IN ("
            "SELECT id FROM jobs WHERE status='cancelled' AND message='Batch paused after backend restart; resume to continue.' UNION ALL "
            "SELECT id FROM mood_jobs WHERE status='cancelled' AND message='Batch paused after backend restart; resume to continue.')"
        )
        conn.execute(
            "UPDATE video_batches SET status='paused',error='Render interrupted by backend restart. Resume or retry failed items.',"
            "updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running','pausing') AND EXISTS ("
            "SELECT 1 FROM video_batch_items i WHERE i.batch_id=video_batches.id AND i.status='failed')"
        )
        conn.execute(
            "UPDATE video_batches SET status='completed_with_errors',error='One or more items did not complete.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('queued','running','pausing') AND NOT EXISTS ("
            "SELECT 1 FROM video_batch_items i WHERE i.batch_id=video_batches.id AND i.status IN ('draft','ready','queued','rendering')) "
            "AND EXISTS (SELECT 1 FROM video_batch_items i WHERE i.batch_id=video_batches.id AND i.status IN ('failed','cancelled','skipped'))"
        )
        conn.execute(
            "UPDATE video_batches SET status='completed',error=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('queued','running','pausing') AND NOT EXISTS ("
            "SELECT 1 FROM video_batch_items i WHERE i.batch_id=video_batches.id AND i.status!='completed')"
        )
        conn.execute(
            "UPDATE video_batches SET status='paused',error='Backend restarted. Resume batch to continue.',updated_at=CURRENT_TIMESTAMP "
            "WHERE status IN ('queued','running','pausing')"
        )
    for render_id in interrupted_mood_renders:
        (CLIP_DIR / f"mood-{render_id}.mp4").unlink(missing_ok=True)
        for suffix in (".ass", ".ppm", ".log"):
            (WORK_DIR / f"mood-{render_id}{suffix}").unlink(missing_ok=True)
    for job_id in interrupted_subtitle_transcriptions:
        for suffix in (".wav", ".m4a"):
            (WORK_DIR / f"{job_id}{suffix}").unlink(missing_ok=True)
    for import_id in interrupted_youtube_imports:
        temp_dir = SOURCE_DIR / f".youtube-import-{import_id}"
        if temp_dir.parent.resolve() == SOURCE_DIR.resolve() and temp_dir.name == f".youtube-import-{import_id}":
            shutil.rmtree(temp_dir, ignore_errors=True)
        with connect() as conn:
            source = conn.execute("SELECT 1 FROM sources WHERE id=?", (import_id,)).fetchone()
        if source is None:
            orphan = SOURCE_DIR / f"{import_id}.mp4"
            if orphan.parent.resolve() == SOURCE_DIR.resolve() and orphan.name == f"{import_id}.mp4":
                orphan.unlink(missing_ok=True)
    for import_id in interrupted_asset_imports:
        temp_dir = SOURCE_DIR / f".pexels-import-{import_id}"
        orphan = SOURCE_DIR / f"{import_id}.mp4"
        with connect() as conn:
            source = conn.execute("SELECT 1 FROM sources WHERE id=?", (import_id,)).fetchone()
        if source is None:
            try:
                if (temp_dir / "video.part").samefile(orphan):
                    orphan.unlink(missing_ok=True)
            except OSError:
                pass
        if temp_dir.parent.resolve() == SOURCE_DIR.resolve() and temp_dir.name == f".pexels-import-{import_id}":
            shutil.rmtree(temp_dir, ignore_errors=True)


def unpack(row, json_fields=()):
    if row is None:
        return None
    value = dict(row)
    for field in json_fields:
        if value.get(field):
            value[field.removesuffix("_json")] = json.loads(value.pop(field))
    return value
