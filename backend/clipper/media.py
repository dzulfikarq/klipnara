import hashlib
import http.client
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import ssl
import subprocess
import textwrap
import urllib.parse
import urllib.error
import urllib.request
import uuid
from fractions import Fraction
from pathlib import Path

from .config import CLIP_DIR, MAX_UPLOAD_BYTES, SOURCE_DIR, WORK_DIR
from .subtitles import composition_fingerprint, composition_signature, gemini_word_annotations, group_word_segments, subtitle_content_fingerprint, transcript_text, valid_word_alignment


class MediaError(RuntimeError):
    pass


MIN_SCENE_SECONDS = 0.5
MAX_SCENES = 12
MAX_MULTI_SCENE_SECONDS = 180


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
    try:
        frame_rate = float(Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"))
    except (ValueError, ZeroDivisionError, TypeError):
        frame_rate = None
    try:
        audio_sample_rate = int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None
        audio_channels = int(audio["channels"]) if audio and audio.get("channels") else None
    except (TypeError, ValueError):
        audio_sample_rate, audio_channels = None, None
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": video["codec_name"],
        "frame_rate": frame_rate,
        "audio_codec": audio.get("codec_name") if audio else None,
        "audio_sample_rate": audio_sample_rate,
        "audio_channels": audio_channels,
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
        host = parsed.hostname.lower().rstrip(".")
        if any(host == domain or host.endswith("." + domain) for domain in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
            raise MediaError("YouTube URLs are preview references, not media-file links. Choose an MP4/MOV source file you may process.")
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
    selected_language = {"auto": "auto", "indonesia": "id", "english": "en"}.get(language)
    command.extend(["-l", selected_language or "auto"])
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


def local_transcription_available():
    model = os.environ.get("WHISPER_MODEL_PATH", "")
    if not model or not Path(model).is_file():
        return False
    try:
        executable("whisper-cli", "WHISPER_CPP_PATH")
        return True
    except MediaError:
        return False


def extract_subtitle_audio(source, start, end, provider):
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise MediaError("Selected subtitle audio range is invalid.")
    if provider == "openai" and (end - start) * 6000 > 24 * 1024 * 1024:
        raise MediaError("Selected segment is too long for OpenAI's 25 MiB upload limit. Shorten it or use local STT.")
    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    work_id = uuid.uuid4().hex
    suffix = ".wav" if provider == "local" else ".m4a"
    target = WORK_DIR / f"subtitle-audio-{work_id}{suffix}"
    audio_filter = ["-af", "loudnorm=I=-20:TP=-1.5:LRA=11"] if provider == "local" else []
    audio_codec = ["-c:a", "pcm_s16le", "-f", "wav"] if provider == "local" else ["-c:a", "aac", "-b:a", "48k", "-f", "ipod"]
    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}",
        "-i", str(source), "-t", f"{end - start:.3f}", "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
        *audio_filter, *audio_codec, str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
    except FileNotFoundError:
        raise MediaError("FFmpeg executable was not found.") from None
    except subprocess.TimeoutExpired:
        target.unlink(missing_ok=True)
        raise MediaError("Selected audio extraction timed out.") from None
    if result.returncode or not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise MediaError("Could not extract audio from the selected clip segment. Check source audio and FFmpeg codecs.")
    if provider == "openai" and target.stat().st_size > 25 * 1024 * 1024:
        target.unlink(missing_ok=True)
        raise MediaError("Selected audio exceeds OpenAI's 25 MiB transcription upload limit. Shorten the clip or use local STT.")
    return target


def transcribe_openai(path, language):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MediaError("Set OPENAI_API_KEY before selecting OpenAI speech-to-text.")
    audio = Path(path).read_bytes()
    if not audio or len(audio) > 25 * 1024 * 1024:
        raise MediaError("Selected audio is empty or exceeds OpenAI's 25 MiB transcription upload limit.")
    boundary = f"klipnara-{uuid.uuid4().hex}"
    fields = {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities[]": "segment",
    }
    language_code = {"indonesia": "id", "english": "en"}.get(language)
    if language_code:
        fields["language"] = language_code
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    filename = Path(path).name
    body.extend(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    body.extend(audio)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=bytes(body),
        headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MediaError(f"OpenAI speech-to-text request failed (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise MediaError("OpenAI speech-to-text request failed. Check network access and provider availability.") from None
    segments = []
    for item in payload.get("segments", []):
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        if text and math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
            segments.append({"start": start, "end": end, "text": text})
    return segments


def transcribe_openai_current(path, language):
    """Use current recommended OpenAI model; it returns transcript text, not timestamps."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MediaError("Set OPENAI_API_KEY before selecting OpenAI speech-to-text.")
    audio = Path(path).read_bytes()
    if not audio or len(audio) > 25 * 1024 * 1024:
        raise MediaError("Selected audio is empty or exceeds OpenAI's 25 MiB transcription upload limit.")
    boundary = f"klipnara-{uuid.uuid4().hex}"
    fields = {"model": "gpt-transcribe", "response_format": "json"}
    language_code = {"indonesia": "id", "english": "en"}.get(language)
    if language_code:
        fields["language"] = language_code
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    body.extend(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"composition.m4a\"\r\n"
        "Content-Type: audio/mp4\r\n\r\n".encode()
    )
    body.extend(audio)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions", data=bytes(body),
        headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=int(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "180"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = "rate limit/quota" if exc.code == 429 else "authentication/configuration" if exc.code in {401, 403} else f"HTTP {exc.code}"
        raise MediaError(f"OpenAI transcription failed ({detail}); no automatic retry or provider fallback.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise MediaError("OpenAI transcription failed. Check network access, timeout, and provider availability.") from None
    text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
    if not text:
        raise MediaError("OpenAI returned no transcript text.")
    return {"text": text, "language": payload.get("language", "unknown"), "segments": [], "words": [], "model": "gpt-transcribe"}


def transcribe_gemini(path, language, duration, cancel, progress=lambda *_: None):
    """Upload one temporary composition file, request verbatim word timing, then delete provider file."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise MediaError("Set GEMINI_API_KEY before selecting Gemini speech-to-text.")
    if duration > 1800:
        raise MediaError("Gemini word timestamps support audio up to 30 minutes. Shorten the composition.")
    payload_size = Path(path).stat().st_size
    if payload_size <= 0 or payload_size > 25 * 1024 * 1024:
        raise MediaError("Selected audio is empty or exceeds Gemini upload limit. Shorten the composition.")
    timeout = int(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "180"))
    upload_name = upload_uri = None
    progress("uploading", "Mengunggah audio komposisi ke Gemini Files API")
    try:
        init = urllib.request.Request(
            "https://generativelanguage.googleapis.com/upload/v1beta/files",
            data=json.dumps({"file": {"display_name": f"klipnara-{uuid.uuid4().hex[:12]}.m4a"}}).encode(),
            headers={
                "x-goog-api-key": key, "Content-Type": "application/json",
                "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(payload_size),
                "X-Goog-Upload-Header-Content-Type": "audio/m4a",
            },
        )
        with urllib.request.urlopen(init, timeout=timeout) as response:
            upload_url = response.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            raise MediaError("Gemini Files API did not return an upload URL.")
        if cancel.is_set():
            raise MediaError("Job cancelled.")
        upload = urllib.request.Request(
            upload_url, data=Path(path).read_bytes(),
            headers={"Content-Length": str(payload_size), "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"},
        )
        with urllib.request.urlopen(upload, timeout=timeout) as response:
            file_response = json.loads(response.read().decode("utf-8"))
        file_data = file_response.get("file", {})
        upload_name, upload_uri = file_data.get("name"), file_data.get("uri")
        if not upload_name or not upload_uri:
            raise MediaError("Gemini Files API returned malformed file metadata.")
        if cancel.is_set():
            raise MediaError("Job cancelled.")
        progress("transcribing", "Gemini memproses audio · word timestamps aktif")
        language_code = {"indonesia": "id-ID", "english": "en-US"}.get(language)
        transcription_config = {"mode": {"type": "verbatim", "timestamp_granularities": ["word"], "diarization_mode": "speaker"}}
        if language_code:
            transcription_config["language_codes"] = [language_code]
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=json.dumps({
                "model": "gemini-3.5-transcribe",
                "input": [{"type": "audio", "uri": upload_uri, "mime_type": "audio/m4a"}],
                "generation_config": {"transcription_config": transcription_config},
            }).encode(),
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            interaction = json.loads(response.read().decode("utf-8"))
        if interaction.get("status") != "completed":
            raise MediaError(f"Gemini transcription did not complete (status: {interaction.get('status', 'unknown')}).")
        text = transcript_text(interaction)
        words = gemini_word_annotations(interaction, duration)
        segments = group_word_segments(words)
        if not text and not segments:
            raise MediaError("Gemini returned no speech transcript. Check source audio.")
        return {"text": text, "language": language_code or "unknown", "segments": segments, "words": words, "model": "gemini-3.5-transcribe"}
    except urllib.error.HTTPError as exc:
        detail = "rate limit/quota" if exc.code == 429 else "authentication/model access" if exc.code in {401, 403} else f"HTTP {exc.code}"
        raise MediaError(f"Gemini transcription failed ({detail}); no automatic retry or provider fallback.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise MediaError(f"Gemini transcription failed ({type(exc).__name__}); check network and provider availability.") from None
    finally:
        if upload_name:
            delete = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{urllib.parse.quote(upload_name, safe='/')}",
                headers={"x-goog-api-key": key}, method="DELETE",
            )
            try:
                with urllib.request.urlopen(delete, timeout=min(timeout, 30)):
                    pass
            except (urllib.error.URLError, TimeoutError, OSError):
                # Provider expires uploaded files automatically after 48 hours.
                pass


def extract_composition_audio(source, clip, edit, output, cancel, progress=lambda *_: None, *, local=False):
    scenes = output_scenes(clip, edit)
    duration = sum(scene["duration"] for scene in scenes)
    if not scenes or not math.isfinite(duration) or duration <= 0:
        raise MediaError("Clip needs at least one valid scene for subtitle transcription.")
    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    args, graph, labels = [ffmpeg, "-hide_banner", "-nostdin", "-y"], [], []
    for index, scene in enumerate(scenes):
        span = scene["duration"]
        args.extend(["-ss", f"{scene['source_start']:.3f}", "-t", f"{span:.3f}", "-i", str(source)])
        graph.append(
            f"[{index}:a:0]atrim=duration={span:.3f},asetpts=PTS-STARTPTS,"
            f"loudnorm=I=-20:TP=-1.5:LRA=11,aresample=16000,"
            f"aformat=sample_fmts=fltp:channel_layouts=mono[a{index}]"
        )
        labels.append(f"[a{index}]")
    graph.append(f"{''.join(labels)}concat=n={len(scenes)}:v=0:a=1[aout]")
    codec = ["-c:a", "pcm_s16le", "-f", "wav"] if local else ["-c:a", "aac", "-b:a", "48k", "-f", "ipod"]
    args.extend(["-filter_complex", ";".join(graph), "-map", "[aout]", "-vn", *codec, "-ar", "16000", "-ac", "1", str(output)])
    progress("preparing_audio", "FFmpeg mengekstrak dan menyambung audio sesuai urutan komposisi")
    try:
        _run(args, cancel)
    except MediaError:
        Path(output).unlink(missing_ok=True)
        raise
    if not Path(output).is_file() or Path(output).stat().st_size == 0:
        Path(output).unlink(missing_ok=True)
        raise MediaError("FFmpeg produced no composition audio.")
    return duration


def output_scenes(clip, edit):
    """Return ordered source ranges with derived, contiguous output timestamps."""
    stored = edit.get("scenes")
    if edit.get("scene_mode", "single") == "multi" and isinstance(stored, list) and stored:
        scenes = sorted(stored, key=lambda item: item.get("order", 0))
        scenes = [{**item, "id": item.get("id") or f"scene-{clip['id']}-{index}"} for index, item in enumerate(scenes)]
    else:
        start = float(clip["start"]) + float(edit.get("trim_start", 0))
        end = float(clip["start"]) + float(edit.get("trim_end", clip["end"] - clip["start"]))
        scenes = [{"id": f"scene-{clip['id']}", "source_start": start, "source_end": end, "order": 0, "role": "body"}]
    cursor, result = 0.0, []
    for scene in scenes:
        start, end = float(scene["source_start"]), float(scene["source_end"])
        duration = end - start
        result.append({
            **scene,
            "source_start": start,
            "source_end": end,
            "duration": duration,
            "timeline_start": cursor,
            "timeline_end": cursor + duration,
        })
        cursor += duration
    return result


def source_subtitle_segments(clip, edit, transcript):
    """Normalize stored/legacy captions to source seconds, filling uncovered transcript ranges."""
    clip_start = float(clip["start"])
    source_timebase = edit.get("subtitle_timebase") == "source"
    transcript = transcript or []
    overrides = edit.get("subtitle_overrides") or {}
    scenes = output_scenes(clip, edit)
    stored = edit.get("subtitle_segments")
    segments, represented, manual_ranges = [], set(), []
    if isinstance(stored, list):
        for item in stored:
            start, end = float(item["start"]), float(item["end"])
            if not source_timebase:
                start, end = start + clip_start, end + clip_start
            text = str(item.get("text") or "").strip()
            if text and start < end:
                segment = {key: value for key, value in item.items() if key in {"id", "start", "end", "text", "words", "word_alignment_reviewed", "speaker_id", "edited", "original_text"}}
                segment.update({"id": item["id"], "start": start, "end": end, "text": text})
                if isinstance(item.get("words"), list):
                    segment["words"] = []
                    for word in item["words"]:
                        if not isinstance(word, dict):
                            continue
                        mapped_word = dict(word)
                        for key in ("start", "end"):
                            if isinstance(word.get(key), (int, float)) and not source_timebase:
                                mapped_word[key] = float(word[key]) + clip_start
                        segment["words"].append(mapped_word)
                segments.append(segment)
                if str(item["id"]).startswith("transcript-"):
                    try:
                        represented.add(int(str(item["id"])[11:]))
                    except ValueError:
                        pass
                else:
                    manual_ranges.append((start, end))

    if edit.get("scene_mode") == "multi":
        for index, item in enumerate(transcript):
            if index in represented:
                continue
            try:
                start, end = float(item.get("start", 0)), float(item.get("end", 0))
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(start) and math.isfinite(end) and start < end):
                continue
            if not any(start < scene["source_end"] and end > scene["source_start"] for scene in scenes):
                continue
            if any(start < manual_end and end > manual_start for manual_start, manual_end in manual_ranges):
                continue
            text = str(overrides.get(str(index), item.get("text", ""))).strip()
            if text:
                segments.append({"id": f"transcript-{index}", "start": start, "end": end, "text": text})
    elif not isinstance(stored, list):
        clip_end = float(clip["end"])
        for index, item in enumerate(transcript):
            start = max(clip_start, float(item.get("start", 0)))
            end = min(clip_end, float(item.get("end", 0)))
            text = str(overrides.get(str(index), item.get("text", ""))).strip()
            if start < end and text:
                segments.append({"id": f"transcript-{index}", "start": start, "end": end, "text": text})
    return sorted(segments[:500], key=lambda item: (item["start"], item["end"], item["id"]))


def clip_subtitle_segments(clip, edit, transcript):
    active_id = edit.get("subtitle_active_track_id")
    active_track = next((track for track in edit.get("subtitle_tracks", []) if track.get("id") == active_id), None)
    if active_track:
        return active_track.get("segments", [])
    segments = source_subtitle_segments(clip, edit, transcript)
    if edit.get("scene_mode") == "multi" or edit.get("subtitle_timebase") in {"source", "output"}:
        return segments
    return [
        {**segment, "start": segment["start"] - float(clip["start"]), "end": segment["end"] - float(clip["start"])}
        for segment in segments
    ]


def map_scene_subtitles(clip, edit, transcript):
    source_segments = source_subtitle_segments(clip, edit, transcript)
    mapped, scenes = [], output_scenes(clip, edit)
    for scene in scenes:
        for segment in source_segments:
            start = max(scene["source_start"], segment["start"])
            end = min(scene["source_end"], segment["end"])
            if start < end:
                item = {
                    "id": f"{scene['id']}-{segment['id']}",
                    "segment_id": segment["id"],
                    "start": scene["timeline_start"] + start - scene["source_start"],
                    "end": scene["timeline_start"] + end - scene["source_start"],
                    "text": segment["text"],
                }
                for key in ("speaker_id", "edited", "original_text"):
                    if key in segment:
                        item[key] = segment[key]
                if "word_alignment_reviewed" in segment:
                    item["word_alignment_reviewed"] = segment["word_alignment_reviewed"]
                if isinstance(segment.get("words"), list):
                    item["words"] = []
                    for word in segment["words"]:
                        if not isinstance(word.get("start"), (int, float)) or not isinstance(word.get("end"), (int, float)):
                            item["words"].append(dict(word))
                            continue
                        if word["end"] <= scene["source_start"] or word["start"] >= scene["source_end"]:
                            continue
                        source_word_start = max(scene["source_start"], word["start"])
                        source_word_end = min(scene["source_end"], word["end"])
                        item["words"].append({
                            **word,
                            "start": scene["timeline_start"] + source_word_start - scene["source_start"],
                            "end": scene["timeline_start"] + source_word_end - scene["source_start"],
                            "source_start": source_word_start,
                            "source_end": source_word_end,
                        })
                mapped.append(item)
    return mapped


def render_subtitle_segments(clip, edit, transcript, source_sha256):
    if not edit.get("subtitle_enabled", False):
        return []
    tracks = edit.get("subtitle_tracks") or []
    active = next((track for track in tracks if track.get("id") == edit.get("subtitle_active_track_id")), None)
    scenes = output_scenes(clip, edit)
    signature = composition_signature(scenes)
    caption_mode = edit.get("subtitle_caption_mode", "sentence")
    if caption_mode == "word_pop":
        if edit.get("subtitle_display_mode", "original") != "original":
            raise MediaError("Word Pop supports original captions only. Select Original Only before rendering.")
        alignment_segments = active.get("segments", []) if active else source_subtitle_segments(clip, edit, transcript)
        if active:
            active_timebase = active.get("timebase", "source")
            total_output = scenes[-1]["timeline_end"] if scenes else 0
            alignment_segments = [item for item in alignment_segments if (
                float(item["start"]) < total_output and float(item["end"]) > 0
                if active_timebase == "output"
                else any(
                    float(item["end"]) + (float(clip["start"]) if active_timebase == "clip" else 0) > scene["source_start"]
                    and float(item["start"]) + (float(clip["start"]) if active_timebase == "clip" else 0) < scene["source_end"]
                    for scene in scenes
                )
            )]
        else:
            alignment_segments = [item for item in alignment_segments if any(item["end"] > scene["source_start"] and item["start"] < scene["source_end"] for scene in scenes)]
        if not alignment_segments or any(not valid_word_alignment(item) for item in alignment_segments):
            raise MediaError("Word Pop needs reviewed, non-overlapping word timestamps for every caption. Add manual timings or use a word-timestamp provider.")
    if active:
        if active.get("timebase") == "output":
            if active.get("composition_signature") != signature or active.get("composition_fingerprint") != composition_fingerprint(source_sha256, signature):
                raise MediaError("Selected output-time subtitle track is stale after scene edits. Remap or regenerate before render.")
            segments = [dict(item, segment_id=item["id"]) for item in active.get("segments", [])]
        else:
            track_edit = {**edit, "subtitle_segments": active.get("segments", []), "subtitle_timebase": active.get("timebase", "source")}
            segments = map_scene_subtitles(clip, track_edit, transcript)
    else:
        segments = map_scene_subtitles(clip, edit, transcript)

    display_mode = edit.get("subtitle_display_mode", "original")
    translation = next((track for track in tracks if track.get("id") == edit.get("subtitle_active_translation_id")), None)
    if translation and ((active and translation.get("source_track_id") == active.get("id")) or (not active and translation.get("source_track_id") == "legacy")):
        source_segments = active.get("segments", []) if active else edit.get("subtitle_segments", [])
        current_fingerprint = subtitle_content_fingerprint(source_segments)
    else:
        source_segments = edit.get("subtitle_segments") or []
        current_fingerprint = subtitle_content_fingerprint(source_segments)
    if translation and translation.get("source_fingerprint") == current_fingerprint:
        translations = {item.get("source_segment_id"): item.get("text", "") for item in translation.get("segments", [])}
        for item in segments:
            translated = translations.get(item.get("segment_id"))
            if translated:
                if display_mode == "translated":
                    item["text"] = translated
                elif display_mode == "bilingual":
                    item["translated_text"] = translated
                item["words"] = []
    elif display_mode in {"translated", "bilingual"}:
        raise MediaError("Selected translation is missing or outdated. Choose Original Only or translate the current subtitle track again.")
    for item in segments:
        item.setdefault("translated_text", None)
    return segments


def transcript_cache_matches(source, language):
    if not source.get("transcript_json") or source.get("transcript_config") != transcription_config_key(language):
        return False
    cached = source.get("transcript_model") or ""
    parts = cached.split("|")
    if len(parts) < 2:
        return True
    configured_model = os.environ.get("WHISPER_MODEL_PATH")
    if not configured_model or Path(configured_model).resolve() != Path(parts[1]).resolve():
        return not configured_model and source.get("transcript_config") == transcription_config_key(language)
    binary = os.environ.get("WHISPER_CPP_PATH", "whisper-cli")
    binary = shutil.which(binary) or (str(Path(binary).resolve()) if Path(binary).is_file() else None)
    if not binary or Path(binary).resolve() != Path(parts[0]).resolve() or len(parts) < 6:
        return True
    try:
        return cached == _transcription_model_id(binary, configured_model)
    except OSError:
        return True


def transcription_config_key(language):
    decode = "auto-detect-v1" if language == "auto" else language
    return f"{decode}|loudnorm-i20-tp15-lra11-v1"


def _transcription_model_id(binary, model):
    binary_path, model_path = Path(binary).resolve(), Path(model).resolve()
    binary_stat, model_stat = binary_path.stat(), model_path.stat()
    return "|".join(map(str, (
        binary_path, model_path, binary_stat.st_size, binary_stat.st_mtime_ns,
        model_stat.st_size, model_stat.st_mtime_ns,
    )))


def transcription_model_id():
    binary = executable("whisper-cli", "WHISPER_CPP_PATH")
    model = os.environ.get("WHISPER_MODEL_PATH", "")
    if not model or not Path(model).is_file():
        raise MediaError("Set WHISPER_MODEL_PATH to a downloaded multilingual whisper.cpp model.")
    return _transcription_model_id(binary, model)


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


def _video_encoder(ffmpeg, resolution, quality):
    crf = {"smaller": 28, "balanced": 23, "high": 19}[quality]
    if resolution == "1080":
        try:
            encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            encoders = ""
        if "h264_amf" in encoders:
            bitrate = {"smaller": 2500, "balanced": 4000, "high": 6500}[quality]
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak",
                    "-b:v", f"{bitrate}k", "-maxrate", f"{bitrate * 3 // 2}k", "-bufsize", f"{bitrate * 2}k"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]


def _audio_filters(edit, duration):
    audio = edit.get("audio") or {}
    filters = []
    volume = 0 if audio.get("muted", False) else float(audio.get("volume", 1))
    if volume != 1:
        filters.append(f"volume={volume:.3f}")
    if audio.get("normalize", False) and volume:
        filters.append(f"loudnorm=I={float(audio.get('target_lufs', -18)):.1f}:TP=-1.5:LRA=11")
    if audio.get("limiter", False) and volume:
        filters.append("alimiter=limit=0.95")
    fade_in = min(float(audio.get("fade_in", 0)), duration)
    fade_out = min(float(audio.get("fade_out", 0)), duration)
    if fade_in:
        filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out:
        filters.append(f"afade=t=out:st={max(0, duration - fade_out):.3f}:d={fade_out:.3f}")
    return filters


def render(source, clip, edit, segments, job_id, cancel, progress, has_audio=True):
    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    resolution = edit.get("resolution", "720")
    width, height = (1080, 1920) if resolution == "1080" else (720, 1280)
    fps = int(edit.get("fps", 30))
    quality = edit.get("quality", "balanced")
    scenes = output_scenes(clip, edit)
    duration = sum(scene["duration"] for scene in scenes)
    if not scenes or not math.isfinite(duration) or duration <= 0:
        raise MediaError("Clip needs at least one valid scene.")
    video_encoder = _video_encoder(ffmpeg, resolution, quality)
    target = CLIP_DIR / f"{clip['id']}-{job_id}.mp4"
    crop_x, crop_y = float(edit.get("crop_x", 50)), float(edit.get("crop_y", 50))
    audio_filters = _audio_filters(edit, duration)
    overlay = edit.get("title_overlay") or {}
    use_ass = bool(edit.get("subtitle_enabled", False) or overlay.get("enabled", False) and overlay.get("text", "").strip())
    subtitle = WORK_DIR / f"{job_id}.ass"
    if use_ass:
        _write_ass(subtitle, segments if edit.get("subtitle_enabled", False) else [], 0, duration, edit, height, clip_relative=True, title_overlay=overlay)
    multi_scene = edit.get("scene_mode") == "multi"
    input_args = [ffmpeg, "-hide_banner", "-nostdin", "-y"]
    filter_args = []
    output_maps = []
    if multi_scene:
        graph = []
        video_labels, audio_labels = [], []
        for index, scene in enumerate(scenes):
            scene_duration = scene["duration"]
            input_args.extend(["-ss", f"{scene['source_start']:.3f}", "-t", f"{scene_duration:.3f}", "-i", str(source)])
            graph.append(
                f"[{index}:v:0]trim=duration={scene_duration:.3f},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(in_w-out_w)*{crop_x / 100:.4f}:(in_h-out_h)*{crop_y / 100:.4f},"
                f"setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration=1,"
                f"trim=duration={scene_duration:.3f},setpts=PTS-STARTPTS,format=yuv420p,settb=AVTB[v{index}]"
            )
            video_labels.append(f"[v{index}]")
            if has_audio and not (edit.get("audio") or {}).get("muted", False):
                graph.append(
                    f"[{index}:a:0]atrim=duration={scene_duration:.3f},asetpts=PTS-STARTPTS,"
                    f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"apad,atrim=duration={scene_duration:.3f}[a{index}]"
                )
            else:
                graph.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=duration={scene_duration:.3f},"
                    f"asetpts=PTS-STARTPTS[a{index}]"
                )
            audio_labels.append(f"[a{index}]")
        graph.append(f"{''.join(video_labels)}{''.join(audio_labels)}concat=n={len(scenes)}:v=1:a=1[vcat][acat]")
        if audio_filters:
            graph.append(f"[acat]{','.join(audio_filters)}[aout]")
            output_maps.extend(["-map", "[aout]"])
        else:
            output_maps.extend(["-map", "[acat]"])
        if use_ass:
            graph.append(f"[vcat]ass='{_ass_escape(subtitle)}'[vout]")
            output_maps.extend(["-map", "[vout]"])
        else:
            output_maps.extend(["-map", "[vcat]"])
        filter_args = ["-filter_complex", ";".join(graph)]
    else:
        scene = scenes[0]
        scene_duration = scene["duration"]
        input_args.extend(["-ss", f"{scene['source_start']:.3f}", "-i", str(source)])
        if not has_audio:
            input_args.extend(["-f", "lavfi", "-t", f"{scene_duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
            output_maps.extend(["-map", "1:a:0"])
        else:
            output_maps.extend(["-map", "0:a?"])
        filters = [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}:(in_w-out_w)*{crop_x / 100:.4f}:(in_h-out_h)*{crop_y / 100:.4f}",
            "setsar=1", f"fps={fps}",
        ]
        if use_ass:
            filters.append(f"ass='{_ass_escape(subtitle)}'")
        output_maps.extend(["-map", "0:v:0", "-vf", ",".join(filters)])
        if audio_filters:
            output_maps.extend(["-af", ",".join(audio_filters)])
    command = [
        *input_args, *filter_args, "-t", f"{duration:.3f}", *output_maps,
        *video_encoder, "-r", str(fps), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        "-map_metadata", "-1", "-progress", "pipe:1", "-stats_period", "0.5", "-nostats", str(target),
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
        subtitle.unlink(missing_ok=True)
        if not succeeded:
            target.unlink(missing_ok=True)
    if cancel.is_set():
        target.unlink(missing_ok=True)
        raise MediaError("Job cancelled.")
    if not target.is_file() or target.stat().st_size <= 0:
        target.unlink(missing_ok=True)
        raise MediaError("FFmpeg completed without a non-empty MP4 output.")
    metadata = probe(target)
    if metadata["video_codec"] != "h264" or metadata["audio_codec"] != "aac":
        target.unlink(missing_ok=True)
        raise MediaError("Rendered MP4 must contain H.264 video and AAC audio.")
    if (metadata["width"], metadata["height"]) != (width, height) or abs(metadata["duration"] - duration) > 0.3:
        target.unlink(missing_ok=True)
        raise MediaError("Rendered MP4 duration or resolution does not match selected scenes.")
    return target


def _write_ass(path, segments, start, end, edit, height, clip_relative=False, title_overlay=None):
    caption_mode = edit.get("subtitle_caption_mode", "sentence")
    presets = {
        "Clean": (0, "&H00FFFFFF", 2, 1),
        "Bold": (-1, "&H00FFFFFF", 4, 1),
        "Highlight": (0, "&H0000D7FF", 4, 1),
    }
    bold, color, outline, border_style = presets.get(edit["style"], presets["Clean"])
    text_color = edit.get("subtitle_color", "#ffffff")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text_color):
        red, green, blue = text_color[1:3], text_color[3:5], text_color[5:7]
        color = f"&H00{blue}{green}{red}".upper()
    size = min(240 if caption_mode == "word_pop" else 120, max(20, int(edit["subtitle_size"] * height / 1280)))
    margin_v = int((100 - edit["subtitle_position"]) / 100 * (height - size))
    font = edit.get("subtitle_font", "Arial")
    outline_color = edit.get("subtitle_outline_color", "#101010")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", outline_color):
        red, green, blue = outline_color[1:3], outline_color[3:5], outline_color[5:7]
        outline_color = f"&H00{blue}{green}{red}".upper()
    else:
        outline_color = "&H00101010"
    outline = max(0, min(8, float(edit.get("subtitle_outline", outline))))
    shadow = max(0, min(4, float(edit.get("subtitle_shadow", 1))))
    if caption_mode == "word_pop":
        outline *= height / 1280
        shadow *= height / 1280
    if edit.get("subtitle_background", False):
        border_style = 3
    alignment = {"top": 8, "center": 5, "bottom": 2}.get(edit.get("subtitle_alignment", "bottom"), 2)
    back_color = "&H80000000"
    title_overlay = title_overlay or {}
    title_style = ""
    if title_overlay.get("enabled") and title_overlay.get("text", "").strip():
        title_color_hex = title_overlay.get("color", "#ffffff")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", title_color_hex):
            red, green, blue = title_color_hex[1:3], title_color_hex[3:5], title_color_hex[5:7]
            title_color = f"&H00{blue}{green}{red}".upper()
        else:
            title_color = "&H00FFFFFF"
        title_size = min(120, max(20, int(title_overlay.get("size", 48) * height / 1280)))
        title_style = f"Style: Title,{title_overlay.get('font', 'Arial')},{title_size},{title_color},&H000000FF,&H00101010,&H80000000,-1,0,1,3,1,5,90,90,0,1\n"
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n" % (height * 9 // 16, height)
        + "WrapStyle: 2\nScaledBorderAndShadow: yes\n[V4+ Styles]\n"
        + "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + f"Style: Default,{font},{size},{color},&H000000FF,{outline_color},{back_color},{bold},0,{border_style},{outline:g},{shadow:g},{alignment},{round(height * 9 / 16 * edit.get('subtitle_safe_margin', 8) / 100)},{round(height * 9 / 16 * edit.get('subtitle_safe_margin', 8) / 100)},{margin_v},1\n"
        + title_style
        + "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    animation = edit.get("subtitle_animation", "none")
    animation_tags = ""
    if animation == "fade":
        animation_tags = "{\\fad(120,120)}"
    elif animation in {"pop", "scale"}:
        animation_tags = "{\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)}"
    highlight_color = edit.get("subtitle_highlight_color", "#ffd700")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", highlight_color):
        red, green, blue = highlight_color[1:3], highlight_color[3:5], highlight_color[5:7]
        highlight_color = f"&H00{blue}{green}{red}".upper()
    else:
        highlight_color = "&H0000D7FF"

    def clean(value):
        return str(value).replace("\\", "／").replace("{", "｛").replace("}", "｝").replace("\r", " ").replace("\n", " ").strip()

    def line_text(value):
        width = max(12, round(28 * 48 / edit["subtitle_size"] * float(edit.get("subtitle_caption_width", 100)) / 100))
        return "\\N".join(
            "\\N".join(textwrap.wrap(clean(line), width=width, break_long_words=False))
            for line in str(value).split("\\N")
        )

    def word_text(words):
        result = ""
        for word in words:
            token = clean(word.get("text", ""))
            if result and token and not re.match(r"^[,.;:!?%)\]}]", token):
                result += " "
            result += token
        return result.strip()

    def add_event(event_start, event_end, text, layer=0, tags=None):
        if event_end <= event_start or not text.strip():
            return
        events.append(
            f"Dialogue: {layer},{_ass_time(max(0, event_start))},{_ass_time(min(end - start, event_end))},"
            f"Default,,0,0,0,,{animation_tags if tags is None else tags}{text}\n"
        )

    if caption_mode == "word_pop":
        word_events = sorted((
            (word["start"], word["end"], str(word.get("text", "")).strip(), word.get("id"), word.get("source_start"), word.get("source_end"))
            for segment in segments
            for word in segment.get("words", [])
            if isinstance(word.get("start"), (int, float)) and isinstance(word.get("end"), (int, float)) and str(word.get("text", "")).strip()
        ), key=lambda item: (item[0], item[1], item[2]))
        merged_words = []
        for word_event in word_events:
            previous = merged_words[-1] if merged_words else None
            same_source_word = (
                previous and word_event[3] is not None and word_event[3] == previous[3]
                and isinstance(previous[5], (int, float)) and isinstance(word_event[4], (int, float))
                and abs(word_event[4] - previous[5]) <= 0.005
                and abs(word_event[0] - previous[1]) <= 0.005
                and word_event[2] == previous[2]
            )
            if same_source_word:
                merged_words[-1] = (*previous[:1], word_event[1], *previous[2:5], word_event[5])
            else:
                merged_words.append(word_event)
        word_events = merged_words
        frame_width = height * 9 // 16
        safe_margin = min(20, max(0, float(edit.get("subtitle_safe_margin", 8))))
        position = min(min(90, 100 - safe_margin), max(max(10, safe_margin), float(edit.get("subtitle_position", 70))))
        x, y = frame_width // 2, round(height * position / 100)
        max_width_percent = min(float(edit.get("subtitle_caption_width", 85)), 100 - 2 * safe_margin)
        max_word_width = max(1, frame_width * max_width_percent / 100)
        intensity = min(0.2, max(0.05, float(edit.get("subtitle_animation_intensity", 0.12))))
        configured_ms = min(250, max(50, int(edit.get("subtitle_animation_duration", 100))))
        for index, (word_start, word_end, word, _word_id, _source_word_start, _source_word_end) in enumerate(word_events):
            event_start = max(0, word_start - start)
            next_start = word_events[index + 1][0] - start if index + 1 < len(word_events) else end - start
            event_end = min(end - start, word_end - start, next_start)
            duration = event_end - event_start
            if duration <= 0:
                continue
            glyph_units = sum(1.0 if ord(char) > 0x2E80 else 0.58 for char in word)
            desired_size = max_word_width / max(1, glyph_units * 0.62)
            fitted_size = max(12, min(size, int(desired_size)))
            horizontal_scale = min(100, max(1, round(desired_size / fitted_size * 100)))
            animation = edit.get("subtitle_animation", "pop")
            animation_ms = min(configured_ms, max(1, round(duration * 350)))
            animation_tags = f"\\an5\\pos({x},{y})\\fs{fitted_size}"
            if horizontal_scale < 100:
                animation_tags += f"\\fscx{horizontal_scale}"
            if duration >= 0.18 and animation == "pop":
                initial_scale = round(100 * (1 - intensity))
                overshoot_scale = round(100 + intensity * 35)
                settle_ms = max(1, round(animation_ms * 0.72))
                animation_tags += (
                    f"\\fscx{round(horizontal_scale * initial_scale / 100)}\\fscy{initial_scale}"
                    f"\\t(0,{settle_ms},1.2,\\fscx{round(horizontal_scale * overshoot_scale / 100)}\\fscy{overshoot_scale})"
                    f"\\t({settle_ms},{animation_ms},\\fscx{horizontal_scale}\\fscy100)"
                )
            elif duration >= 0.18 and animation == "scale":
                initial_scale = round(100 * (1 - intensity))
                animation_tags += f"\\fscx{round(horizontal_scale * initial_scale / 100)}\\fscy{initial_scale}\\t(0,{animation_ms},1.1,\\fscx{horizontal_scale}\\fscy100)"
            elif duration >= 0.18 and animation == "fade":
                animation_tags += f"\\fad({animation_ms},40)"
            if round(max(0, event_end) * 100) <= round(max(0, event_start) * 100):
                raise MediaError("Word Pop timing is shorter than ASS 10 ms timestamp precision. Widen or recheck word timing.")
            add_event(event_start, event_end, clean(word), tags="{" + animation_tags + "}")

    for index, segment in enumerate(segments) if caption_mode != "word_pop" else []:
        segment_start = segment["start"]
        segment_end = segment["end"]
        if segment_end <= start or segment_start >= end:
            continue
        text = segment["text"] if clip_relative else edit["subtitle_overrides"].get(str(index), segment["text"])
        event_start = segment_start - start
        event_end = segment_end - start
        words = [word for word in segment.get("words", []) if word.get("end", 0) > segment_start and word.get("start", 0) < segment_end]
        translated = segment.get("translated_text")
        if caption_mode == "word" and words:
            for word in words:
                add_event(word["start"] - start, word["end"] - start, line_text(word.get("text", "")))
            continue
        if caption_mode == "phrase" and words:
            for phrase in group_word_segments(words):
                phrase_text = phrase["text"] + (f"\\N{clean(translated)}" if translated else "")
                add_event(phrase["start"] - start, phrase["end"] - start, line_text(phrase_text))
            continue
        if caption_mode == "karaoke" and words:
            tokens = [clean(word.get("text", "")) for word in words]
            for word_index, word in enumerate(words):
                parts = []
                for token_index, token in enumerate(tokens):
                    if token_index:
                        parts.append(" ")
                    parts.append(f"{{\\c{highlight_color}&}}{token}{{\\c{color}&}}" if token_index == word_index else token)
                full_text = "".join(parts) + (f"\\N{clean(translated)}" if translated else "")
                last = word_index == len(words) - 1
                next_start = words[word_index + 1]["start"] if not last else segment_end
                add_event(max(event_start, word["start"] - start), min(event_end, next_start - start), line_text(full_text))
            continue
        full_text = clean(text) + (f"\\N{clean(translated)}" if translated else "")
        add_event(event_start, event_end, line_text(full_text))
    if title_overlay.get("enabled") and title_overlay.get("text", "").strip():
        title_duration = min(end - start, float(title_overlay.get("duration", 3)))
        fade_in = min(float(title_overlay.get("fade_in", 0.2)), title_duration / 2)
        fade_out = min(float(title_overlay.get("fade_out", 0.2)), title_duration - fade_in)
        position = min(90, max(10, float(title_overlay.get("position", 18))))
        x, y = height * 9 // 32, round(height * position / 100)
        text = str(title_overlay["text"]).replace("\\", "／").replace("{", "｛").replace("}", "｝").replace("\r", " ").replace("\n", " ")
        wrap_width = max(12, round(30 * 48 / max(20, int(title_overlay.get("size", 48)))))
        text = "\\N".join(textwrap.wrap(text, width=wrap_width, break_long_words=False))
        tags = f"{{\\pos({x},{y})\\fad({round(fade_in * 1000)},{round(fade_out * 1000)})}}"
        events.append(f"Dialogue: 1,0:00:00.00,{_ass_time(title_duration)},Title,,0,0,0,,{tags}{text}\n")
    path.write_text(header + "".join(events), encoding="utf-8-sig")
