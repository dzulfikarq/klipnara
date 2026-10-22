import json
import re


SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["start", "end", "title", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def transcript_chunks(segments, window=180, overlap=90):
    """Split long transcripts on segment boundaries; keep a short timestamped overlap."""
    if not segments:
        return []
    chunks, chunk, start = [], [], float(segments[0]["start"])
    end = start + window
    for segment in segments:
        if chunk and float(segment["start"]) >= end:
            chunks.append(chunk)
            cutoff = end - overlap
            chunk = [item for item in chunk if float(item["end"]) > cutoff]
            start = float(chunk[0]["start"]) if chunk else float(segment["start"])
            end = start + window
        chunk.append(segment)
    if chunk:
        chunks.append(chunk)
    return chunks


def parse_and_validate(raw, *, duration, minimum, maximum, limit, chunk_start=0, chunk_end=None, segments=None):
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
        candidates = result["clips"]
        if not isinstance(candidates, list):
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("AI response must contain a JSON object with a clips array.") from exc

    if chunk_end is None:
        chunk_end = duration
    valid = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        title, reason = item.get("title"), item.get("reason")
        if not isinstance(title, str) or not isinstance(reason, str):
            continue
        if segments and 0 < end - start < minimum:
            start, end, expanded = expand_to_speech_boundaries(
                start, end, segments, minimum, maximum, chunk_start, min(duration, chunk_end)
            )
            if expanded:
                reason = f"{reason} Timing expanded to complete nearby speech."
        if not (chunk_start <= start < end <= min(duration, chunk_end) and minimum <= end - start <= maximum):
            continue
        valid.append({"start": start, "end": end, "title": title[:120], "reason": reason[:500]})

    deduped = []
    for item in valid:
        if any(
            min(item["end"], other["end"]) - max(item["start"], other["start"])
            > 0.5 * min(item["end"] - item["start"], other["end"] - other["start"])
            for other in deduped
        ):
            continue
        deduped.append(item)
    return deduped[:limit]


def expand_to_speech_boundaries(start, end, segments, minimum, maximum, chunk_start, chunk_end):
    """Ponytail: pad short model picks with neighboring timestamped segments; no invented timings."""
    if not segments:
        return start, end, False
    start_index = min(range(len(segments)), key=lambda index: abs(float(segments[index]["start"]) - start))
    end_index = min(range(len(segments)), key=lambda index: abs(float(segments[index]["end"]) - end))
    if start_index > end_index:
        return start, end, False
    start, end = float(segments[start_index]["start"]), float(segments[end_index]["end"])
    if end - start >= minimum:
        return start, end, False
    original = (start, end)
    while end - start < minimum:
        if end_index + 1 < len(segments):
            candidate_end = float(segments[end_index + 1]["end"])
            if candidate_end <= chunk_end and candidate_end - start <= maximum:
                end_index += 1
                end = candidate_end
                continue
        if start_index > 0:
            candidate_start = float(segments[start_index - 1]["start"])
            if candidate_start >= chunk_start and end - candidate_start <= maximum:
                start_index -= 1
                start = candidate_start
                continue
        return original[0], original[1], False
    return start, end, True


def prompt_for(segments, duration, minimum, maximum, limit, language):
    lines = [f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in segments]
    return (
        "Choose and rank self-contained, engaging short-video moments from this timestamped transcript. "
        "Prefer a clear hook, useful insight or punchline; keep complete context and sentence "
        "boundaries. Copy timestamps from the transcript, never invent them. Return only JSON "
        "matching the required schema. Scores are not viral predictions.\n"
        f"Language: {language}. Source duration: {duration:.2f}s. "
        f"Clip duration: {minimum}-{maximum}s. Return up to {limit} clips.\n"
        + "\n".join(lines)
    )


def normalize_for_provider(raw):
    # Strip common markdown wrappers; schema validation still happens downstream.
    return re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(), flags=re.I)
