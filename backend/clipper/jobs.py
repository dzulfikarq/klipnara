import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .analysis import candidate_schema, parse_and_validate, parse_ranking, prompt_for, rank_prompt, ranking_schema, token_bounded_chunks, transcript_chunks
from .config import CLIP_DIR, WORK_DIR
from .db import connect
from .media import MediaError, executable, render, transcribe, transcript_cache_matches, transcription_config_key
from .providers import PromptTooLargeError, ProviderError, analyze, count_prompt_tokens, local_limits, model_for


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
            if not row:
                return False
            if row["kind"] == "youtube_upload":
                return False
            if row["status"] == "queued":
                update_job(job_id, status="cancelled", phase="cancelled", message="Dibatalkan pengguna.")
            elif row["status"] in {"preparing", "transcribing", "analyzing", "rendering"}:
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
                    "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
                ).fetchone()
            if row is None:
                if self._active_lock.acquire(blocking=False):
                    try:
                        from .youtube import next_due_publication, poll_publication

                        publication_id = next_due_publication()
                        if publication_id:
                            poll_publication(publication_id)
                    except Exception:
                        logging.getLogger("klipnara").exception("YouTube processing poll failed")
                    finally:
                        self._active_lock.release()
                time.sleep(0.5)
                continue
            if not self._active_lock.acquire(blocking=False):
                time.sleep(0.2)
                continue
            job = dict(row)
            with connect() as conn:
                claimed = conn.execute(
                    "UPDATE jobs SET status='preparing',phase='preparing',message='Memulai proses',updated_at=? "
                    "WHERE id=? AND status='queued'",
                    (now(), job["id"]),
                ).rowcount
            if not claimed:
                self._active_lock.release()
                continue
            cancel = threading.Event()
            self._cancel[job["id"]] = cancel
            try:
                self._process(job, cancel)
            except (MediaError, ProviderError, ValueError) as exc:
                if cancel.is_set() or str(exc) == "Job cancelled.":
                    update_job(job["id"], status="cancelled", phase="cancelled", progress=None, message="Dibatalkan pengguna.")
                    if job["clip_id"]:
                        with connect() as conn:
                            conn.execute("UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END WHERE id=? AND status='rendering'", (job["clip_id"],))
                else:
                    update_job(job["id"], status="failed", phase="failed", progress=None, message=str(exc))
                    if job["clip_id"]:
                        with connect() as conn:
                            conn.execute("UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END WHERE id=? AND status='rendering'", (job["clip_id"],))
            except Exception:
                logging.getLogger("klipnara").exception("Unexpected failure in local job %s", job["id"])
                update_job(job["id"], status="failed", phase="failed", progress=None, message="Proses gagal. Periksa konfigurasi dan log backend.")
                if job["clip_id"]:
                    with connect() as conn:
                        conn.execute("UPDATE clips SET status=CASE WHEN rendered_path IS NULL THEN 'ready' ELSE 'needs_render' END WHERE id=? AND status='rendering'", (job["clip_id"],))
            finally:
                (WORK_DIR / f"{job['id']}.wav").unlink(missing_ok=True)
                (WORK_DIR / f"{job['id']}.ass").unlink(missing_ok=True)
                self._cancel.pop(job["id"], None)
                self._active_lock.release()

    def _process(self, job, cancel):
        options = json.loads(job["options_json"])
        with connect() as conn:
            source = dict(conn.execute("SELECT * FROM sources WHERE id=?", (job["source_id"],)).fetchone())
        if job["kind"] == "youtube_upload":
            from .youtube import run_upload

            def upload_progress(sent, total):
                update_job(
                    job["id"], phase="uploading", progress=(sent / total if total else 0),
                    message=f"YouTube upload · {sent:,}/{total:,} bytes confirmed",
                )

            run_upload(json.loads(job["options_json"])["publication_id"], cancel, upload_progress)
            update_job(job["id"], status="completed", phase="completed", progress=1, message="Video diterima YouTube; menunggu processing")
            return
        if job["kind"] == "render":
            self._render_job(job, source, options, cancel)
            return
        if transcript_cache_matches(source, options["language"]):
            segments = json.loads(source["transcript_json"])
            language = source["transcript_language"] or "unknown"
        else:
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
        segments = json.loads(source["transcript_json"] or "[]")
        with connect() as conn:
            conn.execute("UPDATE clips SET status='rendering' WHERE id=?", (clip["id"],))
        output = render(
            source["path"], clip, options["edit"], segments, job["id"], cancel,
            lambda value: update_job(job["id"], status="rendering", phase="rendering", progress=value, message="Render FFmpeg · progress encoder nyata"),
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


runner = JobRunner()
