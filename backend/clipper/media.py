import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import textwrap
import urllib.parse
import uuid
from pathlib import Path

from .config import CLIP_DIR, MAX_UPLOAD_BYTES, SOURCE_DIR, WORK_DIR


class MediaError(RuntimeError):
    pass


def executable(name, override):
    value = os.environ.get(override, name)
    found = shutil.which(value)
    if not found and Path(value).is_file():
        found = str(Path(value).resolve())
    if not found:
        raise MediaError(f"{name} is required. Install it and add it to PATH, or set {override}.")
    return found


def probe(path):
    ffprobe = executable("ffprobe", "FFPROBE_PATH")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        raise MediaError("ffprobe could not read this video. Check that file is not damaged.") from None
    format_names = set(data.get("format", {}).get("format_name", "").split(","))
    if not format_names.intersection({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}):
        raise MediaError("Only valid MP4 and MOV video files are supported.")
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video or not video.get("codec_name"):
        raise MediaError("Video stream or codec could not be detected.")
    try:
        duration = float(data.get("format", {}).get("duration") or video.get("duration"))
        width, height = int(video["width"]), int(video["height"])
    except (TypeError, ValueError, KeyError):
        raise MediaError("Video duration or dimensions are missing.") from None
    if duration <= 0 or duration > 4 * 60 * 60 or min(width, height) < 1:
        raise MediaError("Video must be between 1 second and 4 hours long.")
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if audio is None:
        raise MediaError("Video has no audio stream to transcribe.")
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": video["codec_name"],
        "audio_codec": audio.get("codec_name") if audio else None,
    }


def _public_addresses(host):
    try:
        ip = ipaddress.ip_address(host)
        addresses = [ip]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            ]
        except socket.gaierror:
            raise MediaError("Video URL host could not be resolved.") from None
    if not addresses or any(not address.is_global for address in addresses):
        raise MediaError("Private or local network addresses are blocked for URL import.")
    return str(addresses[0])


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def download_url(url, max_bytes=MAX_UPLOAD_BYTES):
    current = url
    for redirect in range(4):
        try:
            parsed = urllib.parse.urlsplit(current)
            port = parsed.port
        except ValueError:
            raise MediaError("Video URL is malformed.") from None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or port not in (None, 443)
            or parsed.fragment
        ):
            raise MediaError("Use a direct HTTPS media-file URL on port 443; private hosts are blocked.")
        address = _public_addresses(parsed.hostname)
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        connection = _PinnedHTTPSConnection(parsed.hostname, address, timeout=20)
        path_out = None
        try:
            connection.request("GET", path, headers={"User-Agent": "Klipnara/1.0", "Accept": "video/mp4,video/quicktime,application/octet-stream"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirect == 3:
                    raise MediaError("Video URL redirected too many times.")
                current = urllib.parse.urljoin(current, location)
                continue
            if response.status != 200:
                raise MediaError(f"Video URL returned HTTP {response.status}.")
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
            if content_type and content_type not in {"application/octet-stream"} and not content_type.startswith("video/"):
                raise MediaError("URL did not return a video file. Use a direct MP4/MOV file URL.")
            length = response.getheader("Content-Length")
            if length and int(length) > max_bytes:
                raise MediaError("Video exceeds the 2 GiB import limit.")
            file_id = uuid.uuid4().hex
            path_out = SOURCE_DIR / f"{file_id}.mp4"
            digest, size = hashlib.sha256(), 0
            with path_out.open("xb") as output:
                while block := response.read(1024 * 1024):
                    if shutil.disk_usage(SOURCE_DIR).free < 1024**3 + len(block):
                        raise MediaError("Keep at least 1 GiB free for processing temporary files.")
                    size += len(block)
                    if size > max_bytes:
                        raise MediaError("Video exceeds the 2 GiB import limit.")
                    digest.update(block)
                    output.write(block)
            return path_out, file_id, size, digest.hexdigest()
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError) as exc:
            if path_out:
                path_out.unlink(missing_ok=True)
            raise MediaError(f"Could not securely download video ({type(exc).__name__}).") from None
        except MediaError:
            if path_out:
                path_out.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
    raise MediaError("Video URL redirected too many times.")


def save_upload(stream, suffix):
    if suffix.lower() not in {".mp4", ".mov"}:
        raise MediaError("Choose an MP4 or MOV file.")
    source_id = uuid.uuid4().hex
    path = SOURCE_DIR / f"{source_id}{suffix.lower()}"
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as output:
            while block := stream.read(1024 * 1024):
                if shutil.disk_usage(SOURCE_DIR).free < 1024**3 + len(block):
                    raise MediaError("Keep at least 1 GiB free for processing temporary files.")
                size += len(block)
                if size > MAX_UPLOAD_BYTES:
                    raise MediaError("Video exceeds the 2 GiB upload limit.")
                digest.update(block)
                output.write(block)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise MediaError("Uploaded video is empty.")
    return path, source_id, size, digest.hexdigest()


def transcribe(path, language, cancel):
    model_id = transcription_model_id()
    binary = executable("whisper-cli", "WHISPER_CPP_PATH")
    model = os.environ.get("WHISPER_MODEL_PATH", "")
    work_id = uuid.uuid4().hex
    output_base = WORK_DIR / f"transcript-{work_id}"
    command = [binary, "-m", model, "-f", str(path), "-oj", "-of", str(output_base)]
    selected_language = {"indonesia": "id", "english": "en"}.get(language)
    if selected_language:
        command.extend(["-l", selected_language])
    output_json = Path(f"{output_base}.json")
    try:
        _run(command, cancel)
        payload = json.loads(output_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise MediaError("whisper.cpp finished without a valid JSON transcript.") from None
    finally:
        output_json.unlink(missing_ok=True)
    segments = []
    for item in payload.get("transcription", []):
        text = (item.get("text") or "").strip()
        offsets = item.get("offsets", {})
        start, end = offsets.get("from"), offsets.get("to")
        if start is None or end is None:
            continue
        start, end = float(start) / 1000, float(end) / 1000
        if text and 0 <= start < end:
            segments.append({"start": start, "end": end, "text": text})
    if not segments:
        raise MediaError("No timestamped speech found. Check source audio and whisper.cpp model.")
    detected = payload.get("result", {}).get("language") or payload.get("language") or "unknown"
    return segments, detected, model_id


def transcription_model_id():
    binary = executable("whisper-cli", "WHISPER_CPP_PATH")
    model = os.environ.get("WHISPER_MODEL_PATH", "")
    if not model or not Path(model).is_file():
        raise MediaError("Set WHISPER_MODEL_PATH to a downloaded whisper.cpp multilingual base model.")
    return f"{binary}|{Path(model).resolve()}"


def _run(command, cancel):
    error_log = WORK_DIR / f"ffmpeg-{uuid.uuid4().hex}.log"
    try:
        with error_log.open("wb") as stderr:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr)
            try:
                while process.poll() is None:
                    if cancel.is_set():
                        process.terminate()
                        process.wait(timeout=10)
                        raise MediaError("Job cancelled.")
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        continue
                if process.returncode:
                    stderr.flush()
                    size = stderr.seek(0, os.SEEK_END)
                    stderr.seek(max(0, size - 3000))
                    detail = stderr.read().decode(errors="replace").strip()
                    raise MediaError(detail[-1800:] or "Media processing failed. Check required codecs and model.")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
    except FileNotFoundError:
        raise MediaError(f"Required program not found: {command[0]}.") from None
    except subprocess.TimeoutExpired:
        raise MediaError("Media process did not stop cleanly after cancellation.") from None
    finally:
        error_log.unlink(missing_ok=True)


def _ass_time(seconds):
    centiseconds = max(0, round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"


def _ass_escape(path):
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def render(source, clip, edit, segments, job_id, cancel, progress):
    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    if edit["resolution"] == "1080":
        width, height = 1080, 1920
    else:
        width, height = 720, 1280
    start = clip["start"] + edit["trim_start"]
    end = clip["start"] + edit["trim_end"]
    duration = end - start
    target = CLIP_DIR / f"{clip['id']}-{job_id}.mp4"
    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}:(in_w-out_w)*{edit['crop_x'] / 100:.4f}:(in_h-out_h)*{edit['crop_y'] / 100:.4f}",
        "setsar=1",
    ]
    if edit["subtitle_enabled"]:
        subtitle = WORK_DIR / f"{job_id}.ass"
        _write_ass(subtitle, segments, start, end, edit, height)
        filters.append(f"ass='{_ass_escape(subtitle)}'")
    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", str(source),
        "-t", f"{duration:.3f}", "-map", "0:v:0", "-map", "0:a?", "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-progress", "pipe:1",
        "-stats_period", "0.5", "-nostats", str(target),
    ]
    error_log = WORK_DIR / f"render-{job_id}.log"
    process = None
    succeeded = False
    try:
        with error_log.open("wb") as stderr:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)
            for line in process.stdout:
                if cancel.is_set():
                    process.terminate()
                    process.wait(timeout=10)
                    raise MediaError("Job cancelled.")
                if line.startswith("out_time_us="):
                    try:
                        fraction = int(line.split("=", 1)[1]) / 1_000_000 / duration
                        progress(min(0.99, max(0.01, fraction)))
                    except (ValueError, ZeroDivisionError):
                        pass
            process.wait()
            if process.returncode:
                stderr.flush()
                size = stderr.seek(0, os.SEEK_END)
                stderr.seek(max(0, size - 3000))
                detail = stderr.read().decode(errors="replace").strip()
                raise MediaError(detail[-1800:] or "FFmpeg render failed. Check that libx264 and libass are enabled.")
            succeeded = True
    except FileNotFoundError:
        raise MediaError("FFmpeg executable was not found.") from None
    except subprocess.TimeoutExpired:
        raise MediaError("FFmpeg did not stop cleanly after cancellation.") from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if process is not None and process.stdout:
            process.stdout.close()
        error_log.unlink(missing_ok=True)
        (WORK_DIR / f"{job_id}.ass").unlink(missing_ok=True)
        if not succeeded:
            target.unlink(missing_ok=True)
    if cancel.is_set():
        target.unlink(missing_ok=True)
        raise MediaError("Job cancelled.")
    return target


def _write_ass(path, segments, start, end, edit, height):
    presets = {
        "Clean": (0, "&H00FFFFFF", 2, 1),
        "Bold": (-1, "&H00FFFFFF", 4, 1),
        "Highlight": (0, "&H0000D7FF", 4, 1),
    }
    bold, color, outline, border_style = presets.get(edit["style"], presets["Clean"])
    if re.fullmatch(r"#[0-9a-fA-F]{6}", edit["subtitle_color"]):
        red, green, blue = edit["subtitle_color"][1:3], edit["subtitle_color"][3:5], edit["subtitle_color"][5:7]
        color = f"&H00{blue}{green}{red}".upper()
    size = min(120, max(20, int(edit["subtitle_size"] * height / 1280)))
    margin_v = int((100 - edit["subtitle_position"]) / 100 * (height - size))
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n" % (height * 9 // 16, height)
        + "WrapStyle: 2\nScaledBorderAndShadow: yes\n[V4+ Styles]\n"
        + "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + f"Style: Default,Arial,{size},{color},&H000000FF,&H00101010,&H80000000,{bold},0,{border_style},{outline},0,2,{60 * height // 1280},{60 * height // 1280},{margin_v},1\n"
        + "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for index, segment in enumerate(segments):
        if segment["end"] <= start or segment["start"] >= end:
            continue
        text = edit["subtitle_overrides"].get(str(index), segment["text"])
        text = str(text).replace("\\", "／").replace("{", "｛").replace("}", "｝")
        wrap_width = max(12, round(28 * 48 / edit["subtitle_size"]))
        text = "\\N".join(textwrap.wrap(text, width=wrap_width, break_long_words=False))
        if not text:
            continue
        events.append(
            f"Dialogue: 0,{_ass_time(max(0, segment['start'] - start))},"
            f"{_ass_time(min(end - start, segment['end'] - start))},Default,,0,0,0,,{text}\n"
        )
    path.write_text(header + "".join(events), encoding="utf-8-sig")
