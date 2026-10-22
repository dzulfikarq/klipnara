import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .analysis import parse_and_validate, prompt_for, transcript_chunks
from .config import CLIP_DIR, WORK_DIR
from .db import connect
from .media import MediaError, executable, render, transcribe
from .providers import ProviderError, analyze


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job(source_id, kind, options, clip_id=None):
    job_id, timestamp = uuid.uuid4().hex, now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id,source_id,clip_id,kind,status,phase,progress,message,options_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, source_id, clip_id, kind, "queued", "queued", None, "Menunggu giliran", json.dumps(options), timestamp, timestamp),
        )
    return job_id


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
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
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
        if job["kind"] == "render":
            self._render_job(job, source, options, cancel)
            return
        if source["transcript_json"] and source["transcript_config"] == options["language"]:
            segments = json.loads(source["transcript_json"])
            language = source["transcript_language"] or "unknown"
        else:
            update_job(job["id"], status="preparing", phase="preparing", message="Ekstrak audio sumber")
            audio = WORK_DIR / f"{job['id']}.wav"
            ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
            from .media import _run

            _run([ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", source["path"], "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)], cancel)
            update_job(job["id"], status="transcribing", phase="transcribing", message="Transkripsi lokal · whisper.cpp")
            segments, language, model_id = transcribe(audio, options["language"], cancel)
            with connect() as conn:
                conn.execute(
                    "UPDATE sources SET transcript_json=?,transcript_model=?,transcript_language=?,transcript_config=? WHERE id=?",
                    (json.dumps(segments, ensure_ascii=False), model_id, language, options["language"], source["id"]),
                )
            audio.unlink(missing_ok=True)
        if cancel.is_set():
            raise MediaError("Job cancelled.")
        update_job(job["id"], status="analyzing", phase="analyzing", message=f"Menganalisis transkrip · {options['provider']}")
        chunks = transcript_chunks(segments)
        collected = []
        per_chunk = max(1, (options["count"] + len(chunks) - 1) // max(1, len(chunks)))
        for chunk in chunks:
            if cancel.is_set():
                raise MediaError("Job cancelled.")
            prompt = prompt_for(chunk, source["duration"], *options["clip_range"], per_chunk, options["language"])
            raw, model, usage = analyze(options["provider"], prompt)
            input_tokens = (usage or {}).get("prompt_tokens") or (usage or {}).get("promptTokenCount")
            output_tokens = (usage or {}).get("completion_tokens") or (usage or {}).get("candidatesTokenCount")
            with connect() as conn:
                conn.execute(
                    "INSERT INTO provider_usage(job_id,provider,model,input_tokens,output_tokens,created_at) VALUES(?,?,?,?,?,?)",
                    (job["id"], options["provider"], model, input_tokens, output_tokens, now()),
                )
            chunk_start, chunk_end = float(chunk[0]["start"]), float(chunk[-1]["end"])
            collected.append(
                parse_and_validate(
                    raw,
                    duration=source["duration"],
                    minimum=options["clip_range"][0],
                    maximum=options["clip_range"][1],
                    limit=per_chunk,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                    segments=chunk,
                )
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
            conn.execute("UPDATE clips SET rendered_path=?,status='completed' WHERE id=?", (str(output), clip["id"]))
        if old and old != str(output):
            Path(old).unlink(missing_ok=True)
        update_job(job["id"], status="completed", phase="completed", progress=1, message="MP4 siap diunduh")


runner = JobRunner()
