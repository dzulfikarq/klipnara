import hashlib
import json
import math
import re
import uuid


TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

PRESETS = {
    "Minimal Clean": {"style": "Clean", "subtitle_color": "#ffffff", "subtitle_outline": 2, "subtitle_shadow": 1, "subtitle_background": False},
    "Bold Viral": {"style": "Bold", "subtitle_color": "#ffffff", "subtitle_outline": 4, "subtitle_shadow": 1, "subtitle_background": False},
    "Karaoke Highlight": {"style": "Highlight", "subtitle_color": "#ffffff", "subtitle_outline": 3, "subtitle_shadow": 1, "subtitle_background": False},
    "Cinematic": {"style": "Clean", "subtitle_color": "#f4e7ca", "subtitle_outline": 2, "subtitle_shadow": 2, "subtitle_background": False, "subtitle_position": 72},
    "Podcast Caption": {"style": "Bold", "subtitle_color": "#ffffff", "subtitle_outline": 3, "subtitle_shadow": 1, "subtitle_background": True},
    "Yellow Pop": {"style": "Highlight", "subtitle_color": "#ffd700", "subtitle_outline": 4, "subtitle_shadow": 1, "subtitle_background": False},
    "Soft Purple": {"style": "Clean", "subtitle_color": "#eadbff", "subtitle_outline": 2, "subtitle_shadow": 2, "subtitle_background": False},
    "Classic White": {"style": "Clean", "subtitle_color": "#ffffff", "subtitle_outline": 2, "subtitle_shadow": 0, "subtitle_background": False},
    "Word Pop": {"style": "Bold", "subtitle_font": "Arial", "subtitle_size": 58, "subtitle_color": "#FFDF36", "subtitle_outline_color": "#000000", "subtitle_outline": 4, "subtitle_shadow": 1, "subtitle_background": False, "subtitle_alignment": "center", "subtitle_position": 70, "subtitle_caption_width": 85, "subtitle_animation": "pop", "subtitle_animation_intensity": 0.12, "subtitle_animation_duration": 100},
}


def stable_fingerprint(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def composition_signature(scenes):
    has_transitions = any(float(scene.get("transition_duration", 0) or 0) > 0 for scene in scenes)
    has_frame_adjusted_scenes = any(
        abs(float(scene.get("duration", float(scene["source_end"]) - float(scene["source_start"]))) - (float(scene["source_end"]) - float(scene["source_start"]))) > 1e-6
        for scene in scenes
    )
    return "|".join(
        f"{scene['id']}:{float(scene['source_start']):.3f}:{float(scene['source_end']):.3f}"
        f"@{float(scene.get('timeline_start', 0)):.3f}:{scene.get('transition_timing_mode', scene.get('transition_to_next', {}).get('timing_mode', 'overlap'))}"
        f":{float(scene.get('transition_duration', 0) or 0):.6f}" if has_transitions or has_frame_adjusted_scenes else
        f"{scene['id']}:{float(scene['source_start']):.3f}:{float(scene['source_end']):.3f}"
        for scene in scenes
    )


def composition_fingerprint(source_sha256, signature):
    return stable_fingerprint([source_sha256, signature])


def subtitle_content_fingerprint(segments):
    normalized = [
        {"id": item.get("id"), "start": round(float(item["start"]), 3), "end": round(float(item["end"]), 3), "text": item.get("text", "")}
        for item in segments
    ]
    return stable_fingerprint(sorted(normalized, key=lambda item: (item["start"], item["end"], str(item["id"]))))


def translation_is_outdated(track, source_segments):
    return track.get("source_fingerprint") != subtitle_content_fingerprint(source_segments)


def _cue_text(words):
    result = ""
    for item in words:
        token = str(item["text"]).strip()
        if not token:
            continue
        if result and not re.match(r"^[,.;:!?%)\]}]", token) and result[-1] not in "([{“‘¿¡":
            result += " "
        result += token
    return result.strip()


def valid_word_alignment(segment):
    """Require reviewed, one-to-one text/timing alignment; gaps between words are valid."""
    if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
        return False
    words = segment.get("words")
    if segment.get("word_alignment_reviewed") is not True or not isinstance(words, list) or not words:
        return False
    if any(not isinstance(word, dict) or not isinstance(word.get("text"), str) for word in words):
        return False
    normalized = " ".join(str(segment.get("text", "")).split())
    if _cue_text(words) != normalized:
        return False
    try:
        raw_start, raw_end = segment["start"], segment["end"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (raw_start, raw_end)):
            return False
        start, end = float(raw_start), float(raw_end)
        if start >= end:
            return False
        previous_end = start
        for word in words:
            raw_start, raw_end = word.get("start"), word.get("end")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (raw_start, raw_end)):
                return False
            word_start, word_end = float(raw_start), float(raw_end)
            if not word["text"].strip() or not (start <= word_start < word_end <= end):
                return False
            if word_start < previous_end:
                return False
            previous_end = word_end
    except (KeyError, OverflowError, TypeError, ValueError):
        return False
    return True


def group_word_segments(words, max_words=7):
    groups, current = [], []
    for word in words:
        current.append(word)
        if re.search(r"[.!?]$", str(word.get("text", ""))) or len(current) >= max_words:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return [
        {
            "id": f"seg-{uuid.uuid4().hex}",
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": _cue_text(group),
            "words": group,
            "word_alignment_reviewed": True,
            "edited": False,
        }
        for group in groups
        if group and group[0]["start"] < group[-1]["end"] and _cue_text(group)
    ]


def _seconds(value):
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(value or ""))
    return float(match.group(1)) if match else None


def gemini_word_annotations(payload, duration):
    words = []
    for step in payload.get("steps", []) if isinstance(payload, dict) else []:
        for content in step.get("content", []) if isinstance(step, dict) else []:
            for item in content.get("annotations", []) if isinstance(content, dict) else []:
                if item.get("type") != "word_info":
                    continue
                start, end = _seconds(item.get("start_offset")), _seconds(item.get("end_offset"))
                text = str(item.get("text") or "").strip()
                if text and start is not None and end is not None and 0 <= start < end <= duration + 0.25:
                    word = {"id": f"word-{uuid.uuid4().hex}", "text": text, "start": round(start, 3), "end": round(min(end, duration), 3)}
                    speaker = item.get("speaker_id", item.get("speaker"))
                    if speaker:
                        word["speaker_id"] = str(speaker)[:64]
                    words.append(word)
    words.sort(key=lambda item: (item["start"], item["end"]))
    return words


def transcript_text(payload):
    steps = payload.get("steps", []) if isinstance(payload, dict) else []
    return "\n".join(
        str(content.get("text", "")).strip()
        for step in steps if isinstance(step, dict)
        for content in step.get("content", []) if isinstance(content, dict) and content.get("type") == "text"
        if str(content.get("text", "")).strip()
    ).strip()


def _timestamp(value, *, vtt=False):
    value = value.strip()
    if vtt:
        match = re.fullmatch(r"(?:(\d{2,}):)?([0-5]?\d):([0-5]\d)\.(\d{3})", value)
        if not match:
            short = re.fullmatch(r"([0-5]?\d):([0-5]\d)\.(\d{3})", value)
            if not short:
                raise ValueError("Invalid subtitle timestamp.")
            minutes, seconds, millis = short.groups()
            return int(minutes) * 60 + int(seconds) + int(millis) / 1000
    else:
        match = re.fullmatch(r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})", value)
        if not match:
            raise ValueError("Invalid subtitle timestamp.")
    hours, minutes, seconds, millis = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_subtitle_file(text, fmt, duration, *, clamp=False):
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 2 * 1024 * 1024 or "\x00" in text:
        raise ValueError("Subtitle file is empty, too large, or contains invalid text.")
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"srt", "vtt"}:
        raise ValueError("Only SRT and VTT subtitle files are supported.")
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if fmt == "vtt" and not text.startswith("WEBVTT"):
        raise ValueError("VTT file must start with WEBVTT.")
    blocks = re.split(r"\n\s*\n", text)
    result, warnings = [], []
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if not lines or fmt == "vtt" and (lines[0].startswith("WEBVTT") or lines[0].startswith(("NOTE", "STYLE", "REGION"))):
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None or timing_index + 1 >= len(lines):
            raise ValueError("Malformed subtitle cue: missing timing or text.")
        timing = lines[timing_index].split("-->")
        if len(timing) != 2:
            raise ValueError("Malformed subtitle cue timing.")
        start = _timestamp(timing[0], vtt=fmt == "vtt")
        end_field = timing[1].split()[0]
        end = _timestamp(end_field, vtt=fmt == "vtt")
        cue_text = " ".join(lines[timing_index + 1:]).strip()
        cue_text = re.sub(r"<[^>]*>", "", cue_text).strip()
        if start >= end or not cue_text or len(cue_text) > 500:
            raise ValueError("Subtitle cue needs valid positive timing and 1–500 text characters.")
        if end > duration or start >= duration:
            warnings.append("One or more cues exceed current output duration.")
            if not clamp:
                continue
            start, end = min(start, duration), min(end, duration)
        if start < end:
            result.append({"id": f"import-{uuid.uuid4().hex}", "start": round(start, 3), "end": round(end, 3), "text": cue_text, "edited": False})
        if len(result) > 500:
            raise ValueError("Subtitle import is limited to 500 cues.")
    result.sort(key=lambda item: (item["start"], item["end"]))
    if not result:
        if warnings and not clamp:
            return [], list(dict.fromkeys(warnings))
        raise ValueError("Subtitle file contains no valid cues within output duration.")
    if any(right["start"] < left["end"] for left, right in zip(result, result[1:])):
        warnings.append("Cues overlap; review timing before render.")
    return result, list(dict.fromkeys(warnings))


def _format_time(seconds, fmt):
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole, milliseconds = divmod(milliseconds, 1000)
    stamp = f"{hours:02}:{minutes:02}:{whole:02}"
    return stamp + ("," if fmt == "srt" else ".") + f"{milliseconds:03}"


def export_subtitle_file(segments, fmt):
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"srt", "vtt"}:
        raise ValueError("Only SRT and VTT subtitle files are supported.")
    blocks = []
    for index, item in enumerate(segments, 1):
        text = str(item.get("text") or "").replace("\r", "").strip()
        if not text:
            continue
        timing = f"{_format_time(item['start'], fmt)} --> {_format_time(item['end'], fmt)}"
        blocks.append(f"{index}\n{timing}\n{text}" if fmt == "srt" else f"{timing}\n{text}")
    return ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n\n".join(blocks) + ("\n" if blocks else "")


def validate_translation(raw, source_segments):
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        translated = payload["segments"]
        expected = [item["id"] for item in source_segments]
        actual = [item.get("id") for item in translated]
        if actual != expected or any(not isinstance(item.get("text"), str) or not item["text"].strip() or len(item["text"]) > 500 for item in translated):
            raise ValueError
        return translated
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ValueError("Translation response IDs or text did not match source cues.") from None
