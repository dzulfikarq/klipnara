"""Deterministic, local-only quote segmentation and timing helpers."""

import math
import re
import uuid


_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_CONNECTORS = {
    "agar", "although", "and", "after", "before", "because", "but", "dan", "karena", "ketika", "atau",
    "lalu", "meski", "namun", "saat", "sebelum", "setelah", "supaya", "tapi", "then", "while", "yet",
    "tetapi", "sehingga", "walaupun",
}
_DISCOURSE_OPENERS = {"terkadang", "kadang", "sesekali", "namun", "tetapi", "meski", "walau", "walaupun", "karena", "sehingga", "bahkan"}
_ALL_CONNECTORS = _CONNECTORS | _DISCOURSE_OPENERS
_ANIMATIONS = {"fade_in", "fade_out", "fade_up", "slide_up", "gentle_scale", "none"}


def word_count(text):
    return len(_WORD.findall(text or ""))


def normalized_words(text):
    return " ".join(match.group(0).casefold() for match in _WORD.finditer(text or ""))


def _split_long_phrase(phrase, max_words=11):
    words = phrase.split()
    result = []
    while len(words) > max_words:
        limit = max_words
        minimum = 3
        connector_at = lambda index: words[index].strip(".,;:!?()[]{}\"'“”‘’").casefold() in _ALL_CONNECTORS
        candidates = [
            boundary for boundary in range(minimum, limit + 1)
            if len(words) - boundary >= minimum
            and not connector_at(boundary - 1)
            and not connector_at(boundary)
        ]
        if candidates:
            punctuation = [boundary for boundary in candidates if words[boundary - 1].endswith((",", ";", ":", "—", "–"))]
            boundary = min(punctuation, key=lambda item: abs(item - limit)) if punctuation else min(candidates, key=lambda item: abs(item - limit))
        else:
            boundary = limit
        result.append(" ".join(words[:boundary]).strip())
        words = words[boundary:]
    if words:
        result.append(" ".join(words).strip())
    return [part for part in result if part]


def _semantic_parts(text, max_segments):
    source = re.sub(r"[ \t]+", " ", (text or "").strip())
    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+|\n+", source) if part.strip()]
    parts = []
    for sentence in sentences:
        clauses = [part.strip() for part in re.split(r"(?<=[,;:—–])\s+", sentence) if part.strip()]
        merged_clauses = []
        pending = []
        for clause in clauses:
            first_word = next(iter(_WORD.findall(clause)), "").casefold()
            if not merged_clauses and (word_count(clause) < 3 or first_word in _ALL_CONNECTORS):
                pending.append(clause)
                continue
            if pending:
                clause = " ".join((*pending, clause))
                pending.clear()
            if word_count(clause) < 3 and merged_clauses:
                merged_clauses[-1] = f"{merged_clauses[-1]} {clause}".strip()
            else:
                merged_clauses.append(clause)
        if pending and merged_clauses:
            merged_clauses[-1] = f"{merged_clauses[-1]} {' '.join(pending)}".strip()
        elif pending:
            merged_clauses.extend(pending)
        for clause in merged_clauses:
            parts.extend(_split_long_phrase(clause))
    if not parts:
        return []
    while len(parts) > max_segments:
        # Prefer joining the smallest adjacent pair; no word is ever cut.
        index = min(range(len(parts) - 1), key=lambda item: word_count(parts[item]) + word_count(parts[item + 1]))
        parts[index:index + 2] = [f"{parts[index]} {parts[index + 1]}".strip()]
    return parts


def _valid_preferred_segments(text, preferred):
    if not isinstance(preferred, list) or not 1 <= len(preferred) <= 8:
        return False
    if any(not isinstance(item, dict) or not isinstance(item.get("text"), str) for item in preferred):
        return False
    parts = [item["text"].strip() for item in preferred]
    if not (len(parts) == len(preferred) and all(parts) and all(word_count(part) <= 18 for part in parts)
            and normalized_words(" ".join(parts)) == normalized_words(text)):
        return False
    if len(parts) > 1 and word_count(text) > 1:
        if any(word_count(part) < 2 for part in parts):
            return False
        words = [list(_WORD.finditer(part)) for part in parts]
        starts_with_connector = any(
            matches and matches[0].group(0).casefold() in _ALL_CONNECTORS
            for matches in words[1:]
        )
        ends_with_connector = any(
            matches and matches[-1].group(0).casefold() in _ALL_CONNECTORS
            for matches in words[:-1]
        )
        if starts_with_connector or ends_with_connector:
            return False
    return True


def automatic_segments(text, duration, *, preferred=None, animation="fade_up", animation_duration=0.45):
    """Build stable-in-draft timed segment records without network/AI calls."""
    clean_text = (text or "").strip()
    if not clean_text:
        return []
    if not math.isfinite(float(duration)) or duration <= 0:
        raise ValueError("Durasi segmentasi harus lebih besar dari nol.")
    max_segments = max(1, min(8, int(float(duration) // 1.4)))
    parts = (
        [item["text"].strip() for item in preferred]
        if isinstance(preferred, list) and len(preferred) <= max_segments and _valid_preferred_segments(clean_text, preferred)
        else _semantic_parts(clean_text, max_segments)
    )
    if not parts:
        parts = [clean_text]

    # Longer phrases receive more room; punctuation adds a small reading pause.
    weights = [max(1.0, word_count(part) / 2.8 + min(1.0, len(re.findall(r"[,;:.!?…]", part)) * 0.12)) for part in parts]
    total_weight = sum(weights)
    minimum_span = 0.2
    available = float(duration) - minimum_span * len(parts)
    cursor = 0.0
    output = []
    for index, (part, weight) in enumerate(zip(parts, weights)):
        start = round(cursor, 3)
        end = float(duration) if index == len(parts) - 1 else round(cursor + minimum_span + available * weight / total_weight, 3)
        span = max(0.001, end - start)
        output.append({
            "id": uuid.uuid4().hex,
            "text": part,
            "start": start,
            "end": end,
            "animation": animation if animation in _ANIMATIONS else "fade_up",
            "animation_duration": round(min(max(0.1, animation_duration), span / 2), 3),
        })
        cursor = end
    return output


def sequence_warnings(segments, duration):
    """Return actionable warnings; timing gaps/short reading times are not hidden."""
    warnings = []
    if not segments:
        return ["Belum ada teks berurutan untuk ditampilkan."]
    previous_end = 0.0
    required_reading_time = 0.0
    for index, segment in enumerate(segments):
        text = str(segment.get("text", "")).strip()
        start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
        span = max(0.0, end - start)
        words = word_count(text)
        required_reading_time += max(1.2, words / 2.8 + 0.35) + min(float(segment.get("animation_duration", 0)), span / 2) * 0.35
        if not text:
            warnings.append(f"Segmen {index + 1} masih kosong.")
        if start > previous_end + 0.05:
            warnings.append(f"Ada jeda {start - previous_end:.1f} dtk sebelum segmen {index + 1}.")
        if start < previous_end - 0.01:
            warnings.append(f"Segmen {index + 1} overlap dengan segmen sebelumnya.")
        if span > 0 and words / span > 3.2:
            warnings.append(f"Segmen {index + 1} mungkin terlalu cepat dibaca; pecah frasa atau tambah durasi.")
        if words > 18:
            warnings.append(f"Segmen {index + 1} panjang; pertimbangkan segmentasi ulang untuk mencegah teks mengecil.")
        previous_end = max(previous_end, end)
    if previous_end < float(duration) - 0.05:
        warnings.append(f"Ada jeda {float(duration) - previous_end:.1f} dtk setelah segmen terakhir.")
    if required_reading_time > float(duration) + 0.05:
        warnings.append(f"Durasi {float(duration):.1f} dtk mungkin terlalu singkat; perkiraan waktu baca dan transisi {required_reading_time:.1f} dtk.")
    return warnings
