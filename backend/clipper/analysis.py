import json
import re
from collections import deque
from copy import deepcopy


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

RANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "reason": {"type": "string"}},
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ranking"],
    "additionalProperties": False,
}


def transcript_chunks(segments, window=180, overlap=25):
    """Split near sentence endings, with bounded timestamp overlap."""
    if not segments:
        return []
    chunks, cursor = [], 0
    while cursor < len(segments):
        target = float(segments[cursor]["start"]) + window
        upper = cursor
        while upper + 1 < len(segments) and float(segments[upper + 1]["start"]) < target:
            upper += 1
        sentence_ends = [index for index in range(cursor, upper + 1) if _sentence_end(segments[index]["text"])]
        end_index = sentence_ends[-1] if sentence_ends else upper
        chunks.append(segments[cursor:end_index + 1])
        if end_index >= len(segments) - 1:
            break
        cutoff = float(segments[end_index]["end"]) - overlap
        starts = [
            index for index in range(cursor + 1, end_index + 1)
            if float(segments[index]["start"]) >= cutoff and _sentence_end(segments[index - 1]["text"])
        ]
        next_cursor = starts[0] if starts else next(
            (index for index in range(cursor + 1, len(segments)) if float(segments[index]["start"]) >= cutoff),
            end_index + 1,
        )
        cursor = next_cursor if next_cursor > cursor else end_index + 1
    return chunks


def candidate_schema(limit):
    schema = deepcopy(SCHEMA)
    schema["properties"]["clips"]["maxItems"] = limit
    return schema


def ranking_schema(limit):
    schema = deepcopy(RANK_SCHEMA)
    schema["properties"]["ranking"]["maxItems"] = limit
    return schema


def _sentence_end(text):
    return str(text).rstrip().endswith((".", "!", "?", "。", "！", "？"))


def split_oversized_chunk(chunk, overlap=25):
    """Split at a measured segment boundary; prefer punctuation near temporal midpoint."""
    if len(chunk) < 2:
        return None
    midpoint = (float(chunk[0]["start"]) + float(chunk[-1]["end"])) / 2
    boundaries = [index for index in range(1, len(chunk)) if _sentence_end(chunk[index - 1]["text"])]
    split = min(boundaries, key=lambda index: abs(float(chunk[index]["start"]) - midpoint)) if boundaries else len(chunk) // 2
    if not 0 < split < len(chunk):
        return None
    cutoff = float(chunk[split]["start"]) - overlap
    overlap_starts = [index for index in range(1, split + 1) if float(chunk[index]["start"]) >= cutoff and _sentence_end(chunk[index - 1]["text"])]
    right_start = overlap_starts[0] if overlap_starts else next(
        (index for index in range(1, split + 1) if float(chunk[index]["start"]) >= cutoff), split
    )
    left, right = chunk[:split], chunk[right_start:]
    return (left, right) if left and right and len(left) < len(chunk) and len(right) < len(chunk) else None


def token_bounded_chunks(chunks, count_tokens, maximum):
    """Split chunks until measured prompt size fits; preserve ordered overlap."""
    pending, bounded = deque(chunks), []
    while pending:
        chunk = pending.popleft()
        if count_tokens(chunk) <= maximum:
            bounded.append(chunk)
            continue
        split = split_oversized_chunk(chunk)
        if split is None:
            raise ValueError("A transcript segment exceeds Ollama context and cannot be split safely.")
        pending.extendleft(reversed(split))
    return bounded


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
        "Select up to the requested number of engaging, self-contained clips. Prefer a hook, useful "
        "insight or conclusion. Preserve context and sentence boundaries. Use concise titles and one-sentence "
        "reasons under 120 characters. Use only transcript timestamps; return best-first JSON, no invented "
        "times or viral claims.\n"
        f"Language: {language}. Source duration: {duration:.1f}s. Clip length: {minimum}-{maximum}s. "
        f"Return up to {limit}.\n"
        + "\n".join(lines)
    )


def rank_prompt(candidates, segments, limit, language, excerpt_limit=120):
    rows = []
    for index, candidate in enumerate(candidates):
        excerpt = " ".join(
            item["text"] for item in segments
            if float(item["end"]) > candidate["start"] and float(item["start"]) < candidate["end"]
        )
        rows.append(
            f"[{index}] {candidate['start']:.1f}-{candidate['end']:.1f}s | {candidate['title'][:80]} | "
            f"{candidate['reason'][:160]} | {excerpt[:excerpt_limit]}"
        )
    return (
        f"Rank these transcript-only clip candidates best-first. Choose up to {limit}. "
        f"Prefer a strong opening, complete context, useful information and a natural ending. "
        f"Language: {language}. Return only JSON with candidate IDs and short ranking reasons.\n"
        + "\n".join(rows)
    )


def parse_ranking(raw, candidates, limit):
    try:
        response = json.loads(raw) if isinstance(raw, str) else raw
        ranking = response["ranking"]
        if not isinstance(ranking, list):
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("AI response must contain a JSON object with a ranking array.") from exc
    ranked, seen = [], set()
    for item in ranking:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            continue
        index = item["id"]
        if index in seen or not 0 <= index < len(candidates):
            continue
        seen.add(index)
        candidate = dict(candidates[index])
        if isinstance(item.get("reason"), str) and item["reason"].strip():
            candidate["reason"] = item["reason"][:500]
        ranked.append(candidate)
        if len(ranked) == limit:
            break
    if not ranked:
        raise ValueError("Global AI ranking returned no known candidate IDs.")
    return ranked


def normalize_for_provider(raw):
    # Strip common markdown wrappers; schema validation still happens downstream.
    return re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(), flags=re.I)
