import hashlib
import math
import os
import queue
import shutil
import signal
import subprocess
import threading
from pathlib import Path

from .config import MAX_UPLOAD_BYTES, MIN_FREE_BYTES, SOURCE_DIR
from .media import MediaError, executable, probe
from .youtube_clip import parse_youtube_url

_MAX_IMPORT_SECONDS = 4 * 60 * 60
_MAX_TIMESTAMP_SECONDS = 9_007_199_254_740_991
_PROGRESS_PREFIX = "KLIPNARA_PROGRESS:"


def _enabled():
    return os.environ.get("YOUTUBE_IMPORT_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def capabilities():
    if not _enabled():
        return {
            "available": False,
            "reason": "Impor otomatis nonaktif. Admin harus mengaktifkan adapter lokal secara eksplisit.",
            "notice": "yt-dlp bukan metode resmi YouTube dan pengunduhan mungkin dibatasi ketentuan platform. Gunakan hanya bila pengambilan dan penggunaan konten diizinkan.",
        }
    try:
        executable("yt-dlp", "YT_DLP_PATH")
        executable("ffmpeg", "FFMPEG_PATH")
        executable("ffprobe", "FFPROBE_PATH")
    except MediaError as exc:
        return {"available": False, "reason": str(exc), "notice": None}
    return {
        "available": True,
        "reason": None,
        "notice": "Adapter lokal opsional, bukan fitur resmi YouTube. Gunakan hanya untuk konten yang boleh diambil dan diproses; proteksi akses tidak dilewati.",
    }


def _time_arg(seconds):
    whole = int(seconds)
    millis = round((seconds - whole) * 1000)
    if millis == 1000:
        whole += 1
        millis = 0
    hours, remainder = divmod(whole, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def validate_import(url, video_id, start, end, rights_confirmed):
    if not rights_confirmed:
        raise MediaError("Konfirmasi izin pengambilan dan penggunaan konten diperlukan.")
    try:
        reference = parse_youtube_url(url)
    except ValueError as exc:
        raise MediaError(str(exc)) from None
    if reference["canonical_url"] != url or reference["video_id"] != video_id:
        raise MediaError("URL sumber harus kanonis dan cocok dengan video ID yang divalidasi.")
    if not all(math.isfinite(value) for value in (start, end)) or start < 0 or end <= start:
        raise MediaError("Timestamp impor harus memenuhi 0 ≤ Start < End.")
    if max(start, end) > _MAX_TIMESTAMP_SECONDS:
        raise MediaError("Timestamp impor terlalu besar untuk direpresentasikan dengan aman.")
    if end - start > _MAX_IMPORT_SECONDS:
        raise MediaError("Durasi segmen otomatis dibatasi sampai 4 jam. Pilih interval lebih pendek atau gunakan sumber lokal.")
    return reference


def build_command(binary, ffmpeg, output_template, canonical_url, start, end):
    section = f"*{_time_arg(start)}-{_time_arg(end)}"
    return [
        binary,
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--no-colors",
        "--newline",
        "--progress-template",
        f"download:{_PROGRESS_PREFIX}%(progress.downloaded_bytes)s|%(progress.total_bytes_estimate)s",
        "--socket-timeout", "15",
        "--retries", "1",
        "--fragment-retries", "1",
        "--max-filesize", str(MAX_UPLOAD_BYTES),
        "--format", "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "--ffmpeg-location", ffmpeg,
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
        "--output", output_template,
        "--",
        canonical_url,
    ]


def _terminate(process):
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, ValueError, subprocess.SubprocessError):
        if process.poll() is None:
            process.kill()
            process.wait()


def _run_downloader(command, temp_dir, cancel, progress):
    lines = queue.Queue()
    last_lines = []
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError:
        raise MediaError("yt-dlp executable tidak ditemukan. Periksa YT_DLP_PATH.") from None
    except OSError as exc:
        raise MediaError(f"yt-dlp gagal dijalankan ({type(exc).__name__}).") from None

    def read_output():
        try:
            for line in process.stdout:
                lines.put(line.rstrip())
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True, name="youtube-import-output")
    reader.start()
    finished = False
    try:
        while True:
            if cancel.is_set():
                _terminate(process)
                raise MediaError("Impor dibatalkan pengguna.")
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                last_lines.append(line)
                del last_lines[:-12]
                if line.startswith(_PROGRESS_PREFIX):
                    try:
                        downloaded, estimated = map(int, line.removeprefix(_PROGRESS_PREFIX).split("|", 1))
                        progress(min(0.95, downloaded / estimated) if estimated > 0 else None)
                    except (ValueError, TypeError):
                        pass
            size = sum(path.stat().st_size for path in temp_dir.iterdir() if path.is_file())
            if size > MAX_UPLOAD_BYTES:
                _terminate(process)
                limit_gib = MAX_UPLOAD_BYTES / 1024**3
                raise MediaError(f"Segmen melebihi batas impor yang dikonfigurasi ({limit_gib:g} GiB).")
            if shutil.disk_usage(SOURCE_DIR).free < MIN_FREE_BYTES:
                _terminate(process)
                raise MediaError("Ruang disk tidak cukup. Sisakan minimal 1 GiB untuk pemrosesan.")
        process.wait(timeout=5)
        finished = True
    except subprocess.TimeoutExpired:
        _terminate(process)
        raise MediaError("yt-dlp tidak berhenti setelah proses selesai.") from None
    finally:
        if process.poll() is None:
            _terminate(process)
        reader.join(timeout=2)
        if process.stdout and not reader.is_alive():
            process.stdout.close()

    if cancel.is_set():
        raise MediaError("Impor dibatalkan pengguna.")
    if not finished or process.returncode:
        output = "\n".join(last_lines).lower()
        if any(term in output for term in (
            "private video", "sign in", "members-only", "members only", "login required",
            "age-restricted", "age verification", "not available in your country", "video unavailable",
        )):
            raise MediaError("Video tidak dapat diambil secara anonim atau dibatasi platform. Gunakan Source Library/upload yang diizinkan; Klipnara tidak memakai cookies atau melewati pembatasan.")
        if "429" in output or "too many requests" in output:
            raise MediaError("Platform membatasi permintaan sementara. Tunggu lalu coba lagi, atau gunakan Source Library/upload yang diizinkan.")
        if "403" in output or "forbidden" in output:
            raise MediaError("Platform menolak akses ke media ini. Klipnara tidak mencoba melewati pembatasan; gunakan Source Library/upload yang diizinkan.")
        if "requested format is not available" in output or "no video formats found" in output:
            raise MediaError("Format video tidak didukung untuk impor segmen. Gunakan Source Library/upload MP4/MOV yang diizinkan.")
        raise MediaError("yt-dlp gagal mengambil segmen. Video mungkin tidak tersedia untuk adapter ini; coba lagi atau gunakan sumber lokal.")


def download_segment(job_id, canonical_url, video_id, start, end, rights_confirmed, cancel, progress):
    validate_import(canonical_url, video_id, start, end, rights_confirmed)
    capability = capabilities()
    if not capability["available"]:
        raise MediaError(capability["reason"] or "Adapter impor otomatis tidak tersedia.")
    if cancel.is_set():
        raise MediaError("Impor dibatalkan pengguna.")

    temp_dir = SOURCE_DIR / f".youtube-import-{job_id}"
    try:
        temp_dir.mkdir(exist_ok=False)
    except FileExistsError:
        raise MediaError("Direktori sementara impor sudah dipakai job lain.") from None
    except OSError:
        raise MediaError("Direktori sumber tidak dapat menyiapkan impor sementara.") from None

    try:
        if shutil.disk_usage(SOURCE_DIR).free < MIN_FREE_BYTES:
            raise MediaError("Ruang disk tidak cukup. Sisakan minimal 1 GiB untuk pemrosesan.")
        binary = executable("yt-dlp", "YT_DLP_PATH")
        ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
        output_template = str(temp_dir / "segment.%(ext)s")
        command = build_command(binary, ffmpeg, output_template, canonical_url, start, end)
        progress(None)
        _run_downloader(command, temp_dir, cancel, progress)
        files = [path for path in temp_dir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"]
        if len(files) != 1:
            raise MediaError("Adapter tidak menghasilkan tepat satu file MP4. Gunakan sumber lokal atau format lain.")
        path = files[0]
        size = path.stat().st_size
        if not size:
            raise MediaError("Adapter menghasilkan segmen kosong.")
        if size > MAX_UPLOAD_BYTES:
            limit_gib = MAX_UPLOAD_BYTES / 1024**3
            raise MediaError(f"Segmen melebihi batas impor yang dikonfigurasi ({limit_gib:g} GiB).")
        metadata = probe(path)
        requested = end - start
        if abs(metadata["duration"] - requested) > max(2.0, requested * 0.05):
            raise MediaError("Durasi segmen hasil impor berbeda jauh dari timestamp pilihan. Gunakan file lokal agar dapat memeriksa sumber.")
        digest = hashlib.sha256()
        with path.open("rb") as media:
            for chunk in iter(lambda: media.read(1024 * 1024), b""):
                if cancel.is_set():
                    raise MediaError("Impor dibatalkan pengguna.")
                digest.update(chunk)
        progress(0.99)
        return path, metadata, size, digest.hexdigest(), temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def cleanup_temp(path):
    temp_dir = Path(path).resolve()
    if temp_dir.parent == SOURCE_DIR.resolve() and temp_dir.name.startswith(".youtube-import-"):
        shutil.rmtree(temp_dir, ignore_errors=True)
