import hashlib
import json
import logging
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .analysis import candidate_schema, parse_and_validate, parse_ranking, prompt_for, rank_prompt, ranking_schema, token_bounded_chunks, transcript_chunks
from .config import CLIP_DIR, SOURCE_DIR, WORK_DIR
from .db import connect
from .media import (
    MAX_OUTPUT_SECONDS, MediaError, executable, extract_composition_audio, map_scene_subtitles, output_scenes, render,
    render_subtitle_segments, scene_output_duration, transcribe, transcribe_gemini, transcribe_openai_current,
    transcript_cache_matches, transcription_config_key,
)
from .mood_renderer import render_mood_video
from .providers import PromptTooLargeError, ProviderError, analyze, count_prompt_tokens, local_limits, model_for
from .subtitles import TRANSLATION_SCHEMA, subtitle_content_fingerprint, validate_translation


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job(source_id, kind, options, clip_id=None, resume_from=None):
    job_id, timestamp = uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, source_id, clip_id, kind, "queued", "queued", None, "Menunggu giliran", json.dumps(options), timestamp, timestamp),
        )
        conn.execute("UPDATE library_assets SET last_used_at=? WHERE source_id=?", (timestamp, source_id))
        if resume_from:
            conn.execute(
                "INSERT INTO analysis_chunks(job_id,chunk_index,cache_key,input_tokens,candidates_json,created_at) "
                "SELECT ?,chunk_index,cache_key,input_tokens,candidates_json,created_at FROM analysis_chunks WHERE job_id=?",
                (job_id, resume_from),
            )
    return job_id


def _save_usage(conn, job_id, provider, model, usage):
    usage = usage or {}
    input_tokens = usage.get("prompt_tokens", usage.get("promptTokenCount"))
    output_tokens = usage.get("completion_tokens", usage.get("candidatesTokenCount"))
    conn.execute(
        "INSERT INTO provider_usage(job_id,provider,model,input_tokens,output_tokens,created_at) VALUES(?,?,?,?,?,?)",
        (job_id, provider, model, input_tokens, output_tokens, now()),
    )


def _cache_key(provider, model, schema, prompt):
    payload = json.dumps([2, provider, model, schema, prompt], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def update_job(job_id, *, status=None, phase=None, progress=..., message=None):
    fields, values = [], []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if phase is not None:
        fields.append("phase=?")
        values.append(phase)
    if progress is not ...:
        fields.append("progress=?")
        values.append(progress)
    if message is not None:
        fields.append("message=?")
        values.append(message[:2000])
    fields.append("updated_at=?")
    values.extend([now(), job_id])
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {','.join(fields)} WHERE id=?", values)


def update_mood_job(job_id, *, status=None, phase=None, progress=..., message=None):
    fields, values = [], []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if phase is not None:
        fields.append("phase=?")
        values.append(phase)
    if progress is not ...:
        fields.append("progress=?")
        values.append(progress)
    if message is not None:
        fields.append("message=?")
        values.append(message[:2000])
    fields.append("updated_at=?")
    values.extend([now(), job_id])
    with connect() as conn:
        conn.execute(f"UPDATE mood_jobs SET {','.join(fields)} WHERE id=?", values)


def update_youtube_import(job_id, *, status=None, phase=None, progress=..., message=None, source_id=None):
    fields, values = [], []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if phase is not None:
        fields.append("phase=?")
        values.append(phase)
    if progress is not ...:
        fields.append("progress=?")
        values.append(progress)
    if message is not None:
        fields.append("message=?")
        values.append(message[:2000])
    if source_id is not None:
        fields.append("source_id=?")
        values.append(source_id)
    fields.append("updated_at=?")
    values.extend([now(), job_id])
    with connect() as conn:
        conn.execute(f"UPDATE youtube_import_jobs SET {','.join(fields)} WHERE id=?", values)


def update_youtube_upload(job_id, *, status=None, phase=None, progress=..., message=None):
    fields, values = [], []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if phase is not None:
        fields.append("phase=?")
        values.append(phase)
    if progress is not ...:
        fields.append("progress=?")
        values.append(progress)
    if message is not None:
        fields.append("message=?")
        values.append(message[:2000])
    fields.append("updated_at=?")
    values.extend([now(), job_id])
    with connect() as conn:
        conn.execute(f"UPDATE youtube_upload_jobs SET {','.join(fields)} WHERE id=?", values)


class JobRunner:
    def __init__(self):
        self._thread = None
        self._active_lock = threading.Lock()
        self._cancel = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="clipper-worker")
        self._thread.start()

    def cancel(self, job_id):
        with connect() as conn:
            row = conn.execute("SELECT status,kind FROM jobs WHERE id=?", (job_id,)).fetchone()
            queue = "clip"
            if not row:
                row = conn.execute("SELECT status,kind FROM mood_jobs WHERE id=?", (job_id,)).fetchone()
                queue = "mood"
            if not row:
                row = conn.execute("SELECT status,'youtube_import' AS kind FROM youtube_import_jobs WHERE id=?", (job_id,)).fetchone()
                queue = "youtube_import"
            if not row:
                row = conn.execute("SELECT status,'youtube_upload' AS kind FROM youtube_upload_jobs WHERE id=?", (job_id,)).fetchone()
                queue = "youtube_upload"
            if not row:
                row = conn.execute("SELECT status,phase,'platform_upload' AS kind FROM platform_upload_jobs WHERE id=?", (job_id,)).fetchone()
                queue = "platform_upload"
            if not row:
                return False
            if row["kind"] == "youtube_upload":
                return False
            if queue == "platform_upload":
                if row["status"] == "queued":
                    changed = conn.execute(
                        "UPDATE platform_upload_jobs SET status='cancelled',phase='cancelled',next_poll_at=NULL,"
                        "last_error='Cancelled before transfer started.',updated_at=? WHERE id=? AND status='queued'",
                        (now(), job_id),
                    ).rowcount
                    if changed:
                        conn.execute(
                            "INSERT INTO platform_upload_events(id,upload_job_id,event_type,message,details_json,occurred_at) VALUES(?,?,?,?,?,?)",
                            (uuid.uuid4().hex, job_id, "cancelled", "Cancelled before provider transfer started.", "{}", now()),
                        )
                        return True
                    row = conn.execute("SELECT status,phase FROM platform_upload_jobs WHERE id=?", (job_id,)).fetchone()
                    if row and row["status"] == "uploading" and row["phase"] != "publishing":
                        event = self._cancel.get(job_id)
                        if event:
                            event.set()
                            return True
                elif row["status"] == "uploading":
                    if row["phase"] == "publishing":
                        return False
                    event = self._cancel.get(job_id)
                    if event:
                        event.set()
                        return True
                return False
            if row["status"] == "queued":
                if queue == "youtube_import":
                    changed = conn.execute(
                        "UPDATE youtube_import_jobs SET status='cancelled',phase='cancelled',"
                        "message='Dibatalkan pengguna.',updated_at=? WHERE id=? AND status='queued'",
                        (now(), job_id),
                    ).rowcount
                    if not changed:
                        event = self._cancel.get(job_id)
                        if not event:
                            return False
                        event.set()
                elif queue == "youtube_upload":
                    changed = conn.execute(
                        "UPDATE youtube_upload_jobs SET status='cancelled',phase='cancelled',"
                        "message='Upload dibatalkan sebelum dimulai.',updated_at=? WHERE id=? AND status='queued'",
                        (now(), job_id),
                    ).rowcount
                    if not changed:
                        event = self._cancel.get(job_id)
                        if not event:
                            return False
                        event.set()
                else:
                    updater = update_mood_job if queue == "mood" else update_job
                    updater(job_id, status="cancelled", phase="cancelled", message="Dibatalkan pengguna.")
                if queue == "mood":
                    conn.execute("UPDATE mood_renders SET status='cancelled',updated_at=? WHERE job_id=?", (now(), job_id))
            elif row["status"] in {"preparing", "importing", "processing", "preparing_audio", "uploading", "transcribing", "processing_result", "analyzing", "rendering"}:
                event = self._cancel.get(job_id)
                if event:
                    event.set()
                else:
                    return False
            else:
                return False
        return True

    def _run(self):
        while True:
            with connect() as conn:
                row = conn.execute(
                    "SELECT id,kind,created_at,'clip' AS queue FROM jobs WHERE status='queued' "
                    "UNION ALL SELECT id,kind,created_at,'mood' AS queue FROM mood_jobs WHERE status='queued' "
                    "UNION ALL SELECT id,'youtube_import' AS kind,created_at,'youtube_import' AS queue FROM youtube_import_jobs WHERE status='queued' "
                    "UNION ALL SELECT id,kind,created_at,'youtube_upload' AS queue FROM youtube_upload_jobs WHERE status='queued' "
                    "UNION ALL SELECT id,'platform_upload' AS kind,created_at,'platform_upload' AS queue FROM platform_upload_jobs WHERE status='queued' "
                    "ORDER BY created_at LIMIT 1"
                ).fetchone()
            if row is None:
                if self._active_lock.acquire(blocking=False):
                    try:
                        from .platform_publishing import next_due_platform_upload, poll_platform_upload
                        from .youtube import next_due_publication, poll_publication

                        platform_job_id = next_due_platform_upload()
                        if platform_job_id:
                            poll_platform_upload(platform_job_id)
                        else:
                            publication_id = next_due_publication()
                            if publication_id:
                                poll_publication(publication_id)
                    except Exception:
                        logging.getLogger("klipnara").exception("Platform status poll failed")
                    finally:
                        self._active_lock.release()
                time.sleep(0.5)
                continue
            if not self._active_lock.acquire(blocking=False):
                time.sleep(0.2)
                continue
            job = dict(row)
            cancel = threading.Event()
            self._cancel[job["id"]] = cancel
            with connect() as conn:
                if job["queue"] == "mood":
                    claimed = conn.execute(
                        "UPDATE mood_jobs SET status='preparing',phase='preparing',message='Menyiapkan Mood Quotes',updated_at=? "
                        "WHERE id=? AND status='queued'", (now(), job["id"]),
                    ).rowcount
                elif job["queue"] == "youtube_import":
                    claimed = conn.execute(
                        "UPDATE youtube_import_jobs SET status='preparing',phase='preparing',message='Menyiapkan impor segmen',updated_at=? "
                        "WHERE id=? AND status='queued'", (now(), job["id"]),
                    ).rowcount
                elif job["queue"] == "youtube_upload":
                    claimed = conn.execute(
                        "UPDATE youtube_upload_jobs SET status='preparing',phase='preparing',message='Menyiapkan upload YouTube',updated_at=? "
                        "WHERE id=? AND status='queued'", (now(), job["id"]),
                    ).rowcount
                elif job["queue"] == "platform_upload":
                    claimed = conn.execute(
                        "UPDATE platform_upload_jobs SET status='uploading',phase=CASE WHEN phase='queued' THEN 'preparing' ELSE phase END,"
                        "updated_at=? WHERE id=? AND status='queued'", (now(), job["id"]),
                    ).rowcount
                else:
                    claimed = conn.execute(
                        "UPDATE jobs SET status='preparing',phase='preparing',message='Memulai proses',updated_at=? "
                        "WHERE id=? AND status='queued'", (now(), job["id"]),
                    ).rowcount
            if not claimed:
                self._cancel.pop(job["id"], None)
                self._active_lock.release()
                continue
            with connect() as conn:
                table = {"mood": "mood_jobs", "youtube_import": "youtube_import_jobs", "youtube_upload": "youtube_upload_jobs", "platform_upload": "platform_upload_jobs", "clip": "jobs"}[job["queue"]]
                record = conn.execute(f"SELECT * FROM {table} WHERE id=?", (job["id"],)).fetchone()
            queue = job["queue"]
            job = dict(record)
            job["queue"] = queue
            try:
                from .batch_studio import batch_job_started

                batch_job_started(job["id"])
            except Exception:
                logging.getLogger("klipnara").exception("Could not mark batch item started: %s", job["id"])
            try:
                if job["queue"] == "mood":
                    self._process_mood(job, cancel)
                elif job["queue"] == "youtube_import":
                    self._process_youtube_import(job, cancel)
                elif job["queue"] == "platform_upload":
                    self._process_platform_upload(job, cancel)
                else:
                    self._process(job, cancel)
            except (MediaError, ProviderError, ValueError) as exc:
                if job["queue"] == "platform_upload":
                    from .platform_publishing import fail_platform_upload

                    fail_platform_upload(job["id"], exc, cancelled=cancel.is_set())
                elif cancel.is_set() or str(exc) == "Job cancelled.":
                    updater = {"clip": update_job, "mood": update_mood_job, "youtube_import": update_youtube_import, "youtube_upload": update_youtube_upload}[job["queue"]]
                    updater(job["id"], status="cancelled", phase="cancelled", progress=None, message="Dibatalkan pengguna.")
                    if job["queue"] == "mood":
                        with connect() as conn:
                            conn.execute("UPDATE mood_renders SET status='cancelled',updated_at=? WHERE job_id=?", (now(), job["id"]))
                    elif job.get("clip_id"):
                        with connect() as conn:
                            conn.execute("UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END WHERE id=? AND status='rendering'", (job["clip_id"],))
                else:
                    updater = {"clip": update_job, "mood": update_mood_job, "youtube_import": update_youtube_import, "youtube_upload": update_youtube_upload}[job["queue"]]
                    updater(job["id"], status="failed", phase="failed", progress=None, message=str(exc))
                    if job["queue"] == "mood":
                        with connect() as conn:
                            conn.execute("UPDATE mood_renders SET status='failed',updated_at=? WHERE job_id=?", (now(), job["id"]))
                    elif job.get("clip_id"):
                        with connect() as conn:
                            conn.execute("UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END WHERE id=? AND status='rendering'", (job["clip_id"],))
            except Exception:
                logging.getLogger("klipnara").exception("Unexpected failure in local job %s", job["id"])
                if job["queue"] == "platform_upload":
                    from .platform_publishing import fail_platform_upload

                    fail_platform_upload(job["id"], "Platform transfer failed. Check backend log and reconcile provider state.")
                else:
                    updater = {"clip": update_job, "mood": update_mood_job, "youtube_import": update_youtube_import, "youtube_upload": update_youtube_upload}[job["queue"]]
                    updater(job["id"], status="failed", phase="failed", progress=None, message="Proses gagal. Periksa konfigurasi dan log backend.")
                    if job["queue"] == "mood":
                        with connect() as conn:
                            conn.execute("UPDATE mood_renders SET status='failed',updated_at=? WHERE job_id=?", (now(), job["id"]))
                    elif job.get("clip_id"):
                        with connect() as conn:
                            conn.execute("UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END WHERE id=? AND status='rendering'", (job["clip_id"],))
            finally:
                try:
                    from .batch_studio import batch_job_finished

                    batch_job_finished(job["id"])
                except Exception:
                    logging.getLogger("klipnara").exception("Could not advance batch after job: %s", job["id"])
                for suffix in (".wav", ".m4a"):
                    (WORK_DIR / f"{job['id']}{suffix}").unlink(missing_ok=True)
                (WORK_DIR / f"{job['id']}.ass").unlink(missing_ok=True)
                self._cancel.pop(job["id"], None)
                self._active_lock.release()

    def _process_youtube_import(self, job, cancel):
        from .asset_library import register_source_asset
        from .youtube_import import cleanup_temp, download_segment

        temp_dir = None
        source_id = job["id"]
        final_path = SOURCE_DIR / f"{source_id}.mp4"
        if final_path.exists():
            raise MediaError("File tujuan impor sudah ada; job dihentikan tanpa menimpa source.")

        def progress(value):
            update_youtube_import(
                job["id"], status="importing", phase="importing", progress=value,
                message="Mengimpor segmen yang dipilih dengan adapter lokal",
            )

        try:
            update_youtube_import(job["id"], phase="preparing", progress=0, message="Memvalidasi URL, izin, dan adapter lokal")
            path, metadata, size, digest, temp_dir = download_segment(
                job["id"], job["canonical_url"], job["video_id"], job["start_seconds"], job["end_seconds"],
                bool(job["rights_confirmed"]), cancel, progress,
            )
            if cancel.is_set():
                raise MediaError("Impor dibatalkan pengguna.")
            update_youtube_import(job["id"], status="processing", phase="processing", progress=0.97, message="Memvalidasi dan menyimpan source lokal")
            try:
                os.link(path, final_path)
            except FileExistsError:
                raise MediaError("File tujuan impor sudah ada; source existing tidak ditimpa.") from None
            except OSError as exc:
                raise MediaError(f"Tidak dapat menyimpan source impor ({type(exc).__name__}).") from None
            timestamp = now()
            try:
                path.unlink()
                with connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    if cancel.is_set():
                        raise MediaError("Impor dibatalkan pengguna.")
                    conn.execute(
                        "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            source_id,
                            f"YouTube segment {job['video_id']} {job['start_seconds']:.0f}-{job['end_seconds']:.0f}.mp4",
                            str(final_path.resolve()), size, metadata["duration"], metadata["width"], metadata["height"],
                            metadata["video_codec"], metadata["audio_codec"], digest, timestamp,
                        ),
                    )
                    register_source_asset(conn, {
                        "id": source_id,
                        "name": f"YouTube segment {job['video_id']} {job['start_seconds']:.0f}-{job['end_seconds']:.0f}.mp4",
                        "path": str(final_path.resolve()), "size_bytes": size, "duration": metadata["duration"],
                        "width": metadata["width"], "height": metadata["height"], "sha256": digest,
                        "created_at": timestamp,
                    })
                    conn.execute(
                        "UPDATE youtube_import_jobs SET source_id=?,status='ready',phase='ready',progress=1,"
                        "message='Segmen lokal siap untuk Quick Clip',updated_at=? WHERE id=?",
                        (source_id, timestamp, job["id"]),
                    )
            except Exception:
                final_path.unlink(missing_ok=True)
                raise
        finally:
            if temp_dir:
                cleanup_temp(temp_dir)

    def _process_mood(self, job, cancel):
        from .mood_studio import _check_project_assets

        options = json.loads(job["options_json"])
        composition, quote = options["composition"], options["quote"]
        assets = _check_project_assets(job["project_id"], composition)
        with connect() as conn:
            conn.execute("UPDATE mood_renders SET status='rendering',updated_at=? WHERE id=?", (now(), job["render_id"]))
        update_mood_job(job["id"], status="rendering", phase="rendering", progress=0, message="FFmpeg membuat video Mood Quotes")
        output = render_mood_video(
            render_id=job["render_id"], quote=quote, composition=composition, assets=assets, cancel=cancel,
            progress=lambda value: update_mood_job(job["id"], progress=value, message="FFmpeg merender video Mood Quotes"),
        )
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE mood_renders SET path=?,status='completed',review_status='needs_review',reviewed_render_sha256=NULL,updated_at=? WHERE id=?",
                         (str(output), now(), job["render_id"]))
            project = conn.execute("SELECT composition_json,selected_quote_json FROM mood_projects WHERE id=?", (job["project_id"],)).fetchone()
            if project and json.loads(project["composition_json"]) == composition and json.loads(project["selected_quote_json"] or "null") == quote:
                conn.execute("UPDATE mood_projects SET current_render_id=?,updated_at=? WHERE id=?", (job["render_id"], now(), job["project_id"]))
        update_mood_job(job["id"], status="completed", phase="completed", progress=1, message="Mood Quotes MP4 siap untuk review")

    def _process_platform_upload(self, job, cancel):
        from .platform_publishing import run_platform_upload, update_platform_upload

        def progress(sent, total):
            update_platform_upload(job["id"], status="uploading", progress=(sent / total if total else 0))

        run_platform_upload(job["id"], cancel, progress)

    def _process(self, job, cancel):
        options = json.loads(job["options_json"])
        if job["kind"] == "youtube_upload":
            from .youtube import run_upload

            update = update_youtube_upload if job.get("queue") == "youtube_upload" else update_job

            def upload_progress(sent, total):
                update(
                    job["id"], phase="uploading", progress=(sent / total if total else 0),
                    message=f"YouTube upload · {sent:,}/{total:,} bytes confirmed",
                )

            run_upload(json.loads(job["options_json"])["publication_id"], cancel, upload_progress)
            update(job["id"], status="completed", phase="completed", progress=1, message="Upload selesai; status remote diperiksa")
            return
        with connect() as conn:
            source = dict(conn.execute("SELECT * FROM sources WHERE id=?", (job["source_id"],)).fetchone())
        if job["kind"] == "subtitle_transcribe":
            self._process_subtitle_transcription(job, source, options, cancel)
            return
        if job["kind"] == "subtitle_translate":
            self._process_subtitle_translation(job, options, cancel)
            return
        if job["kind"] in {"render", "quick_clip"}:
            self._render_job(job, source, options, cancel)
            return
        if transcript_cache_matches(source, options["language"]):
            segments = json.loads(source["transcript_json"])
            language = source["transcript_language"] or "unknown"
        else:
            if not source.get("audio_codec"):
                raise MediaError("AI Smart Clip transcription requires source audio. Use Quick Clip for silent video.")
            update_job(job["id"], status="preparing", phase="preparing", message="Ekstrak audio sumber")
            audio = WORK_DIR / f"{job['id']}.wav"
            ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
            from .media import _run

            _run([
                ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", source["path"], "-vn",
                "-af", "loudnorm=I=-20:TP=-1.5:LRA=11", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(audio),
            ], cancel)
            update_job(job["id"], status="transcribing", phase="transcribing", message="Transkripsi lokal · whisper.cpp")
            segments, language, model_id = transcribe(audio, options["language"], cancel)
            with connect() as conn:
                conn.execute(
                    "UPDATE sources SET transcript_json=?,transcript_model=?,transcript_language=?,transcript_config=? WHERE id=?",
                    (json.dumps(segments, ensure_ascii=False), model_id, language, transcription_config_key(options["language"]), source["id"]),
                )
            audio.unlink(missing_ok=True)
        if cancel.is_set():
            raise MediaError("Job cancelled.")
        update_job(job["id"], status="analyzing", phase="analyzing", progress=0, message=f"Menganalisis transkrip · {options['provider']}")
        chunks = transcript_chunks(segments)
        measured_tokens = {}
        if options["provider"] == "local":
            _, _, token_budget = local_limits()
            update_job(job["id"], progress=0.01, message="Mengukur token Ollama sebelum inferensi")

            def measure_chunk(chunk):
                if cancel.is_set():
                    raise MediaError("Job cancelled.")
                prompt = prompt_for(chunk, source["duration"], *options["clip_range"], options["count"], options["language"])
                try:
                    tokens, model, usage = count_prompt_tokens(prompt, candidate_schema(options["count"]))
                except PromptTooLargeError:
                    return token_budget + 1
                if cancel.is_set():
                    raise MediaError("Job cancelled.")
                measured_tokens[prompt] = tokens
                with connect() as conn:
                    _save_usage(conn, job["id"], options["provider"], model, usage)
                return tokens

            chunks = token_bounded_chunks(chunks, measure_chunk, token_budget)
        collected = []
        per_chunk = max(1, (options["count"] + len(chunks) - 1) // max(1, len(chunks)))
        for chunk_index, chunk in enumerate(chunks):
            if cancel.is_set():
                raise MediaError("Job cancelled.")
            prompt = prompt_for(chunk, source["duration"], *options["clip_range"], per_chunk, options["language"])
            chunk_schema = candidate_schema(per_chunk)
            cached_key = _cache_key(options["provider"], model_for(options["provider"]), chunk_schema, prompt)
            with connect() as conn:
                cached = conn.execute(
                    "SELECT cache_key,input_tokens,candidates_json FROM analysis_chunks WHERE job_id=? AND chunk_index=?",
                    (job["id"], chunk_index),
                ).fetchone()
            input_tokens = measured_tokens.get(prompt)
            if cached and cached["cache_key"] == cached_key:
                chunk_candidates = json.loads(cached["candidates_json"])
                input_tokens = cached["input_tokens"]
                collected.append(chunk_candidates)
                update_job(
                    job["id"], progress=0.05 + 0.8 * (chunk_index + 1) / max(1, len(chunks)),
                    message=f"Bagian {chunk_index + 1}/{len(chunks)} dipulihkan · {input_tokens} token",
                )
                continue
            update_job(
                job["id"], progress=0.05 + 0.8 * chunk_index / max(1, len(chunks)),
                message=f"Menganalisis bagian {chunk_index + 1}/{len(chunks)}"
                + (f" · {input_tokens} token" if input_tokens is not None else ""),
            )
            raw, model, usage = analyze(options["provider"], prompt, chunk_schema)
            input_tokens = (usage or {}).get("prompt_tokens", (usage or {}).get("promptTokenCount")) or input_tokens
            with connect() as conn:
                _save_usage(conn, job["id"], options["provider"], model, usage)
            chunk_start, chunk_end = float(chunk[0]["start"]), float(chunk[-1]["end"])
            chunk_candidates = parse_and_validate(
                raw,
                duration=source["duration"],
                minimum=options["clip_range"][0],
                maximum=options["clip_range"][1],
                limit=per_chunk,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                segments=chunk,
            )
            collected.append(chunk_candidates)
            with connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO analysis_chunks(job_id,chunk_index,cache_key,input_tokens,candidates_json,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (job["id"], chunk_index, _cache_key(options["provider"], model, chunk_schema, prompt), input_tokens or 0,
                     json.dumps(chunk_candidates, ensure_ascii=False), now()),
                )
            update_job(
                job["id"], progress=0.05 + 0.8 * (chunk_index + 1) / max(1, len(chunks)),
                message=f"Bagian {chunk_index + 1}/{len(chunks)} selesai · {input_tokens or 0} token",
            )
        # Merge each chunk's model-ranked list by rank, not by timestamp.
        collected = [
            candidates_by_chunk[rank]
            for rank in range(max((len(items) for items in collected), default=0))
            for candidates_by_chunk in collected
            if rank < len(candidates_by_chunk)
        ]
        candidates = parse_and_validate(
            {"clips": collected},
            duration=source["duration"],
            minimum=options["clip_range"][0],
            maximum=options["clip_range"][1],
            limit=options["count"],
        )
        if not candidates:
            raise ValueError("Tidak ada kandidat valid. Coba materi lain, model lebih baik, atau rentang durasi lebih pendek.")
        update_job(job["id"], progress=0.9, message="Memeringkat kandidat terbaik secara global")
        ranking_prompt = rank_prompt(candidates, segments, options["count"], options["language"])
        rank_schema = ranking_schema(options["count"])
        if options["provider"] == "local":
            for excerpt_limit in (120, 40, 0):
                ranking_prompt = rank_prompt(candidates, segments, options["count"], options["language"], excerpt_limit)
                try:
                    ranking_tokens, model, usage = count_prompt_tokens(ranking_prompt, rank_schema)
                except PromptTooLargeError:
                    continue
                with connect() as conn:
                    _save_usage(conn, job["id"], options["provider"], model, usage)
                if ranking_tokens <= token_budget:
                    break
            else:
                raise ValueError("Global ranking prompt exceeds the configured Ollama context budget.")
        ranking_raw, model, usage = analyze(options["provider"], ranking_prompt, rank_schema, "clip_ranking")
        with connect() as conn:
            _save_usage(conn, job["id"], options["provider"], model, usage)
        candidates = parse_ranking(ranking_raw, candidates, options["count"])
        timestamp = now()
        with connect() as conn:
            for rank, candidate in enumerate(candidates, 1):
                conn.execute(
                    "INSERT INTO clips(id,source_id,job_id,start,end,title,reason,rank,edit_json,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'ready',?)",
                    (
                        uuid.uuid4().hex, source["id"], job["id"], candidate["start"], candidate["end"],
                        candidate["title"], candidate["reason"], rank,
                        json.dumps({
                            "trim_start": 0,
                            "trim_end": candidate["end"] - candidate["start"],
                            "subtitle_enabled": options["subtitle_enabled"],
                            "style": options["style"],
                            "resolution": options["resolution"],
                            "crop_x": 50,
                            "crop_y": 50,
                            "subtitle_size": 48,
                            "subtitle_position": 82,
                            "subtitle_color": "#ffd700" if options["style"] == "Highlight" else "#ffffff",
                            "subtitle_overrides": {},
                        }),
                        timestamp,
                    ),
                )
        update_job(job["id"], status="ready_for_review", phase="ready_for_review", progress=None, message=f"{len(candidates)} kandidat siap ditinjau")

    def _render_job(self, job, source, options, cancel):
        with connect() as conn:
            clip = dict(conn.execute("SELECT * FROM clips WHERE id=?", (job["clip_id"],)).fetchone())
        if job["kind"] == "render" and scene_output_duration(output_scenes(clip, options["edit"])) > MAX_OUTPUT_SECONDS:
            raise MediaError(f"Final output cannot exceed {MAX_OUTPUT_SECONDS} seconds. Shorten the timeline before rendering.")
        segments = render_subtitle_segments(
            clip, options["edit"], json.loads(source["transcript_json"] or "[]"), source["sha256"],
        )
        with connect() as conn:
            conn.execute("UPDATE clips SET status='rendering' WHERE id=?", (clip["id"],))
        output = render(
            source["path"], clip, options["edit"], segments, job["id"], cancel,
            lambda value: update_job(job["id"], status="rendering", phase="rendering", progress=value, message="Render FFmpeg · progress encoder nyata"),
            has_audio=bool(source.get("audio_codec")),
        )
        with connect() as conn:
            old = conn.execute("SELECT rendered_path FROM clips WHERE id=?", (clip["id"],)).fetchone()["rendered_path"]
            conn.execute(
                "UPDATE clips SET rendered_path=?,status='completed',review_status='needs_review',reviewed_render_sha256=NULL WHERE id=?",
                (str(output), clip["id"]),
            )
        if old and old != str(output):
            Path(old).unlink(missing_ok=True)
        update_job(job["id"], status="completed", phase="completed", progress=1, message="MP4 siap diunduh")

    def _process_subtitle_transcription(self, job, source, options, cancel):
        with connect() as conn:
            clip_row = conn.execute("SELECT * FROM clips WHERE id=?", (job["clip_id"],)).fetchone()
        if clip_row is None:
            raise MediaError("Clip was deleted before subtitle transcription started.")
        clip, edit = dict(clip_row), options["edit_snapshot"]
        provider = options["provider"]
        audio = WORK_DIR / f"{job['id']}{'.wav' if provider == 'local' else '.m4a'}"

        def progress(phase, message):
            if cancel.is_set():
                raise MediaError("Job cancelled.")
            update_job(job["id"], status=phase, phase=phase, progress=None, message=message)

        try:
            duration = extract_composition_audio(
                source["path"], clip, edit, audio, cancel, progress, local=provider == "local",
            )
            if cancel.is_set():
                raise MediaError("Job cancelled.")
            if provider == "local":
                progress("transcribing", "Transkripsi lokal · whisper.cpp")
                raw_segments, language, model = transcribe(audio, options["language"], cancel)
                segments = []
                for item in raw_segments:
                    text = str(item.get("text") or "").strip()
                    try:
                        start, end = max(0.0, float(item["start"])), min(duration, float(item["end"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not text or not math.isfinite(start) or not math.isfinite(end) or start >= end:
                        continue
                    if len(text) > 500:
                        raise MediaError("A local transcript segment exceeds 500 characters. Shorten composition or edit transcript manually.")
                    segments.append({"id": f"seg-{uuid.uuid4().hex}", "start": round(start, 3), "end": round(end, 3),
                                     "text": text, "original_text": text, "edited": False})
                if not segments:
                    raise MediaError("No timed speech was detected in this composition.")
                transcript = " ".join(item["text"] for item in segments)
            elif provider == "openai":
                progress("transcribing", "OpenAI gpt-transcribe · text-only, no timestamp alignment")
                result = transcribe_openai_current(audio, options["language"])
                segments, language, model, transcript = [], result.get("language", "unknown"), result["model"], result["text"]
            else:
                result = transcribe_gemini(audio, options["language"], duration, cancel, progress)
                segments, language, model, transcript = result["segments"], result["language"], result["model"], result["text"]
        finally:
            audio.unlink(missing_ok=True)
        if cancel.is_set():
            raise MediaError("Job cancelled.")
        if len(segments) > 500:
            raise MediaError("Transcription produced over 500 subtitle cues. Shorten composition and retry.")
        signature = options["composition_signature"]
        track = {
            "id": options["track_id"], "source_type": "generated", "provider": provider,
            "model": model, "language": language or "unknown", "timebase": "output",
            "segments": segments, "transcript_text": transcript[:100000],
            "composition_signature": signature,
            "composition_fingerprint": options["composition_fingerprint"],
            "word_timestamps": any(item.get("words") for item in segments),
            "speaker_identification": any(item.get("speaker_id") or any(word.get("speaker_id") for word in item.get("words", [])) for item in segments),
            "edited": False,
        }
        update_job(job["id"], status="processing_result", phase="processing_result", progress=None, message="Menyimpan transkrip untuk review; subtitle lama tidak diganti")
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT edit_json FROM clips WHERE id=?", (clip["id"],)).fetchone()
            if row is None:
                raise MediaError("Clip was deleted before transcript could be saved.")
            current = json.loads(row["edit_json"])
            tracks = current.setdefault("subtitle_tracks", [])
            tracks = [item for item in tracks if item.get("id") != track["id"]]
            if len(tracks) >= 20:
                raise MediaError("Subtitle track limit reached (20). Remove a draft, then retry.")
            tracks.append(track)
            current["subtitle_tracks"] = tracks
            conn.execute("UPDATE clips SET edit_json=? WHERE id=?", (json.dumps(current, ensure_ascii=False), clip["id"]))
        update_job(job["id"], status="completed", phase="completed", progress=1, message="Transkrip siap ditinjau; pilih Gunakan untuk mengaktifkan")

    def _process_subtitle_translation(self, job, options, cancel):
        source_segments = options["source_segments"]
        provider, target = options["provider"], options["target_language"]
        translated = []
        batch_size = 40
        batches = [source_segments[index:index + batch_size] for index in range(0, len(source_segments), batch_size)]
        for index, batch in enumerate(batches):
            if cancel.is_set():
                raise MediaError("Job cancelled.")
            prompt = (
                f"Translate subtitle cues to {target}. Preserve meaning and context; use natural language; do not add information; "
                "retain proper nouns and technical terms where appropriate; keep mobile-readable length. Return exactly one translated "
                "text for every input id, in the same order. Do not add, remove, merge, or split cues. Do not return timestamps.\n"
                + json.dumps({"segments": [{"id": item["id"], "text": item["text"]} for item in batch]}, ensure_ascii=False)
            )
            update_job(job["id"], status="transcribing", phase="transcribing", progress=None,
                       message=f"Menerjemahkan batch {index + 1}/{len(batches)} · {provider}")
            raw, model, usage = analyze(provider, prompt, TRANSLATION_SCHEMA, "subtitle_translation")
            outputs = validate_translation(raw, batch)
            translated.extend(outputs)
            with connect() as conn:
                _save_usage(conn, job["id"], provider, model, usage)
            if cancel.is_set():
                raise MediaError("Job cancelled.")
            update_job(job["id"], status="processing_result", phase="processing_result",
                       progress=(index + 1) / max(1, len(batches)), message=f"Batch terjemahan {index + 1}/{len(batches)} selesai")
        if not translated:
            raise MediaError("No subtitle cues available to translate.")
        source_by_id = {item["id"]: item for item in source_segments}
        track = {
            "id": options["track_id"], "source_type": "translation", "provider": provider,
            "model": model, "language": target, "timebase": options["source_timebase"],
            "source_track_id": options["source_track_id"], "source_fingerprint": options["source_fingerprint"],
            "composition_signature": options.get("composition_signature"),
            "composition_fingerprint": options.get("composition_fingerprint"),
            "segments": [
                {"id": f"tr-{uuid.uuid4().hex}", "source_segment_id": item["id"],
                 "start": source_by_id[item["id"]]["start"], "end": source_by_id[item["id"]]["end"],
                 "text": item["text"], "edited": False}
                for item in translated
            ],
            "edited": False,
        }
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT edit_json FROM clips WHERE id=?", (job["clip_id"],)).fetchone()
            if row is None:
                raise MediaError("Clip was deleted before translation could be saved.")
            current = json.loads(row["edit_json"])
            tracks = current.setdefault("subtitle_tracks", [])
            tracks = [item for item in tracks if item.get("id") != track["id"]]
            if len(tracks) >= 20:
                raise MediaError("Subtitle track limit reached (20). Remove a draft, then retry.")
            tracks.append(track)
            current["subtitle_tracks"] = tracks
            conn.execute("UPDATE clips SET edit_json=? WHERE id=?", (json.dumps(current, ensure_ascii=False), job["clip_id"]))
        update_job(job["id"], status="completed", phase="completed", progress=1, message="Terjemahan tersimpan sebagai track terpisah; tinjau sebelum digunakan")


runner = JobRunner()
