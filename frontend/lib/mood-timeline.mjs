/** @typedef {"fade_in"|"fade_out"|"fade_up"|"slide_up"|"gentle_scale"|"none"} SegmentAnimation */
/** @typedef {{id: string, text: string, start: number, end: number, animation: SegmentAnimation, animation_duration: number}} TimelineSegment */
/** @typedef {"move"|"resize-start"|"resize-end"} TimingMode */

export const MIN_SEGMENT_SECONDS = 0.5;
const MIN_MUSIC_SPAN_SECONDS = 0.05;
const CONNECTORS = new Set(["agar", "although", "and", "atau", "after", "before", "because", "but", "dan", "karena", "ketika", "lalu", "meski", "meskipun", "namun", "saat", "sebelum", "setelah", "supaya", "tapi", "tetapi", "sehingga", "walaupun", "walau", "bila", "jika", "hingga", "sambil", "seperti", "seolah", "ketimbang", "daripada", "while", "yet", "then", "yang"]);
const OPENERS = new Set(["terkadang", "kadang", "sesekali", "namun", "tetapi", "meski", "walau", "walaupun", "karena", "sehingga", "bahkan"]);
const WORD = /[\p{L}\p{N}]+/gu;
const round = (value) => Math.round(value * 1000) / 1000;
const words = (text) => (text.match(WORD) || []).map((word) => word.toLocaleLowerCase());
const makeId = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

/** @param {number} clientX @param {number} left @param {number} pixelsPerSecond @param {number} duration */
export function timeAtPosition(clientX, left, pixelsPerSecond, duration) {
  if (![clientX, left, pixelsPerSecond, duration].every(Number.isFinite) || pixelsPerSecond <= 0) return 0;
  return round(Math.max(0, Math.min(duration, (clientX - left) / pixelsPerSecond)));
}

/** @param {number} value @param {number[]} boundaries @param {number} [tolerance] */
export function snapTimelineTime(value, boundaries, tolerance = 0.12) {
  const nearest = boundaries.filter(Number.isFinite).reduce((best, point) =>
    Math.abs(point - value) < Math.abs(best - value) ? point : best, value);
  return round(Math.abs(nearest - value) <= tolerance ? nearest : value);
}

/** Change only selected segment. Neighbors never ripple; invalid moves clamp to free gap. */
/** @param {TimelineSegment[]} segments @param {string} id @param {TimingMode} mode @param {number} delta @param {number} duration @param {{start: number, end: number}} [origin] @param {boolean} [snap] */
export function updateSegmentTiming(segments, id, mode, delta, duration, origin, snap = true) {
  const index = segments.findIndex((item) => item.id === id);
  if (index < 0 || !Number.isFinite(delta)) return { segments, blocked: true };
  const current = segments[index];
  const start0 = origin?.start ?? current.start;
  const end0 = origin?.end ?? current.end;
  const previous = segments[index - 1];
  const next = segments[index + 1];
  const minSpan = mode === "move" ? end0 - start0 : MIN_SEGMENT_SECONDS;
  const boundaries = [0, duration, ...segments.filter((item) => item.id !== id).flatMap((item) => [item.start, item.end])];
  const target = (value) => snap ? snapTimelineTime(value, boundaries) : round(value);
  let start = start0;
  let end = end0;
  let clamped = false;

  if (mode === "move") {
    const low = previous?.end ?? 0;
    const high = (next?.start ?? duration) - minSpan;
    if (high < low) return { segments, blocked: true };
    const desired = target(start0 + delta);
    start = Math.max(low, Math.min(high, desired));
    clamped = start !== desired;
    end = start + minSpan;
  } else if (mode === "resize-start") {
    const low = previous?.end ?? 0;
    const high = end0 - minSpan;
    if (high < low) return { segments, blocked: true };
    const desired = target(start0 + delta);
    start = Math.max(low, Math.min(high, desired));
    clamped = start !== desired;
  } else if (mode === "resize-end") {
    const low = start0 + minSpan;
    const high = next?.start ?? duration;
    if (high < low) return { segments, blocked: true };
    const desired = target(end0 + delta);
    end = Math.max(low, Math.min(high, desired));
    clamped = end !== desired;
  } else {
    return { segments, blocked: true };
  }

  start = round(start);
  end = round(end);
  if (start < 0 || end <= start || end > duration || previous && start < previous.end || next && end > next.start) {
    return { segments, blocked: true };
  }
  const updated = segments.map((item) => item.id === id ? { ...item, start, end, animation_duration: Math.min(item.animation_duration, (end - start) / 2) } : item);
  return { segments: updated, blocked: false, clamped, changed: start !== current.start || end !== current.end };
}

function splitText(text) {
  const tokens = text.trim().split(/\s+/u);
  if (tokens.length < 4) return null;
  const connector = (token) => words(token)[0] && (CONNECTORS.has(words(token)[0]) || OPENERS.has(words(token)[0]));
  const candidates = [];
  for (let boundary = 2; boundary <= tokens.length - 2; boundary++) {
    if (connector(tokens[boundary - 1]) || connector(tokens[boundary])) continue;
    const ending = tokens[boundary - 1];
    const punctuationBias = /[.!?…]$/u.test(ending) ? -2 : /[,;:—–]$/u.test(ending) ? -1 : 0;
    candidates.push({ boundary, score: Math.abs(boundary - tokens.length / 2) + punctuationBias });
  }
  if (!candidates.length) return null;
  const boundary = candidates.sort((a, b) => a.score - b.score)[0].boundary;
  return [tokens.slice(0, boundary).join(" "), tokens.slice(boundary).join(" ")];
}

/** @param {TimelineSegment[]} segments @param {string} id @param {number} duration @returns {TimelineSegment[] | null} */
export function splitSegment(segments, id, duration) {
  const index = segments.findIndex((item) => item.id === id);
  if (index < 0) return null;
  const segment = segments[index];
  const span = segment.end - segment.start;
  const parts = splitText(segment.text);
  if (!parts || span < MIN_SEGMENT_SECONDS * 2) return null;
  const ratio = words(parts[0]).length / Math.max(1, words(segment.text).length);
  const splitAt = round(segment.start + Math.max(MIN_SEGMENT_SECONDS, Math.min(span - MIN_SEGMENT_SECONDS, span * ratio)));
  if (splitAt <= segment.start || splitAt >= segment.end || segment.end > duration) return null;
  const left = { ...segment, text: parts[0], end: splitAt, animation_duration: Math.min(segment.animation_duration, (splitAt - segment.start) / 2) };
  const right = { ...segment, id: makeId(), text: parts[1], start: splitAt, animation_duration: Math.min(segment.animation_duration, (segment.end - splitAt) / 2) };
  return [...segments.slice(0, index), left, right, ...segments.slice(index + 1)];
}

/** @param {TimelineSegment[]} segments @param {string} id @param {-1|1} direction @returns {TimelineSegment[] | null} */
export function mergeSegment(segments, id, direction) {
  const index = segments.findIndex((item) => item.id === id);
  const neighborIndex = index + direction;
  if (index < 0 || neighborIndex < 0 || neighborIndex >= segments.length || ![-1, 1].includes(direction)) return null;
  const firstIndex = Math.min(index, neighborIndex);
  const first = segments[firstIndex];
  const second = segments[firstIndex + 1];
  const merged = {
    ...first,
    text: `${first.text.trim()} ${second.text.trim()}`.trim(),
    start: Math.min(first.start, second.start),
    end: Math.max(first.end, second.end),
  };
  merged.animation_duration = Math.min(merged.animation_duration, (merged.end - merged.start) / 2);
  return [...segments.slice(0, firstIndex), merged, ...segments.slice(firstIndex + 2)];
}

/** @param {TimelineSegment[]} segments @param {string} id @param {number} duration @returns {TimelineSegment[] | null} */
export function duplicateSegment(segments, id, duration) {
  const index = segments.findIndex((item) => item.id === id);
  if (index < 0) return null;
  const source = segments[index];
  const span = source.end - source.start;
  const next = segments[index + 1];
  const afterEnd = next?.start ?? duration;
  if (afterEnd - source.end >= MIN_SEGMENT_SECONDS) {
    const end = Math.min(afterEnd, source.end + span);
    const copy = { ...source, id: makeId(), start: source.end, end, animation_duration: Math.min(source.animation_duration, (end - source.end) / 2) };
    return [...segments.slice(0, index + 1), copy, ...segments.slice(index + 1)];
  }
  const previous = segments[index - 1];
  const beforeStart = previous?.end ?? 0;
  if (source.start - beforeStart >= MIN_SEGMENT_SECONDS) {
    const start = Math.max(beforeStart, source.start - span);
    const copy = { ...source, id: makeId(), start, end: source.start, animation_duration: Math.min(source.animation_duration, (source.start - start) / 2) };
    return [...segments.slice(0, index), copy, ...segments.slice(index)];
  }
  return null;
}

/** @param {TimelineSegment[]} segments @param {number} duration @returns {TimelineSegment[] | null} */
export function resetSegmentTimings(segments, duration) {
  if (!segments.length || !Number.isFinite(duration) || duration < segments.length * MIN_SEGMENT_SECONDS) return null;
  const weights = segments.map((item) => Math.max(1, words(item.text).length / 2.8 + Math.min(1, (item.text.match(/[,;:.!?…]/gu) || []).length * 0.12)));
  const weightTotal = weights.reduce((sum, item) => sum + item, 0);
  const extra = duration - segments.length * MIN_SEGMENT_SECONDS;
  let cursor = 0;
  return segments.map((item, index) => {
    const start = round(cursor);
    const end = index === segments.length - 1 ? duration : round(cursor + MIN_SEGMENT_SECONDS + extra * weights[index] / weightTotal);
    cursor = end;
    return { ...item, start, end, animation_duration: Math.min(item.animation_duration, (end - start) / 2) };
  });
}

/** @param {string} text @param {number} duration @param {SegmentAnimation} [animation] @param {{text: string}[]} [preferred] @returns {TimelineSegment[]} */
export function semanticSegments(text, duration, animation = "fade_up", preferred = []) {
  const clean = (text || "").trim().replace(/[\t ]+/gu, " ");
  if (!clean || !Number.isFinite(duration) || duration <= 0) return [];
  const maxParts = Math.max(1, Math.min(8, Math.floor(duration / 1.4)));
  const normalized = (value) => words(value).join(" ");
  const validPreferred = preferred.length > 0 && preferred.length <= maxParts
    && preferred.every((item) => item.text?.trim() && words(item.text).length <= 18)
    && normalized(preferred.map((item) => item.text).join(" ")) === normalized(clean)
    && (preferred.length === 1 || preferred.every((item, index) => {
      const first = words(item.text)[0];
      const last = words(item.text).at(-1);
      return words(item.text).length >= 2 && (index === 0 || !CONNECTORS.has(first) && !OPENERS.has(first))
        && (index === preferred.length - 1 || !CONNECTORS.has(last) && !OPENERS.has(last));
    }));
  let parts = validPreferred ? preferred.map((item) => item.text.trim()) : [];
  if (!parts.length) {
    const sentences = clean.split(/(?<=[.!?…])\s+|\n+/u).filter(Boolean);
    const clauses = [];
    let pending = "";
    for (const sentence of sentences) {
      const count = words(sentence).length;
      const startsWithConnector = CONNECTORS.has(words(sentence)[0]) || OPENERS.has(words(sentence)[0]);
      if (count < 3 || startsWithConnector) pending = `${pending} ${sentence}`.trim();
      else {
        clauses.push(`${pending} ${sentence}`.trim());
        pending = "";
      }
    }
    if (pending) {
      if (clauses.length) clauses[clauses.length - 1] += ` ${pending}`;
      else clauses.push(pending);
    }
    parts = clauses.flatMap((sentence) => {
      const count = words(sentence).length;
      if (count <= 11) return [sentence];
      const pieces = sentence.split(/(?<=[,;:—–])\s+/u).filter(Boolean);
      if (pieces.length < 2) return splitLongPhrase(sentence);
      const grouped = [];
      let current = "";
      for (const piece of pieces) {
        const startsWithConnector = CONNECTORS.has(words(piece)[0]) || OPENERS.has(words(piece)[0]);
        if (current && words(current).length >= 9 && !startsWithConnector) {
          grouped.push(...splitLongPhrase(current));
          current = piece;
        } else current = `${current} ${piece}`.trim();
      }
      if (current) grouped.push(...splitLongPhrase(current));
      return grouped;
    });
  }
  while (parts.length > maxParts) {
    let smallest = 0;
    for (let index = 1; index < parts.length - 1; index++) {
      if (words(parts[index]).length + words(parts[index + 1]).length < words(parts[smallest]).length + words(parts[smallest + 1]).length) smallest = index;
    }
    parts.splice(smallest, 2, `${parts[smallest]} ${parts[smallest + 1]}`.trim());
  }
  const weights = parts.map((part) => Math.max(1, words(part).length / 2.8 + Math.min(1, (part.match(/[,;:.!?…]/gu) || []).length * 0.12)));
  const total = weights.reduce((sum, item) => sum + item, 0);
  const extra = duration - parts.length * MIN_SEGMENT_SECONDS;
  let cursor = 0;
  return parts.map((part, index) => {
    const start = round(cursor);
    const end = index === parts.length - 1 ? duration : round(cursor + MIN_SEGMENT_SECONDS + Math.max(0, extra) * weights[index] / total);
    cursor = end;
    return { id: makeId(), text: part, start, end, animation, animation_duration: round(Math.min(0.45, (end - start) / 2)) };
  });
}

function splitLongPhrase(phrase, maxWords = 11) {
  const tokens = phrase.split(/\s+/u).filter(Boolean);
  const result = [];
  while (tokens.length > maxWords) {
    const limit = Math.min(maxWords, tokens.length - 3);
    const candidates = [];
    for (let boundary = 3; boundary <= limit; boundary++) {
      const before = words(tokens[boundary - 1]).at(-1);
      const after = words(tokens[boundary])[0];
      if (!CONNECTORS.has(before) && !OPENERS.has(before) && !CONNECTORS.has(after) && !OPENERS.has(after)) {
        const punctuationBias = /[,;:—–]$/u.test(tokens[boundary - 1]) ? -1 : 0;
        candidates.push({ boundary, score: Math.abs(boundary - 11) + punctuationBias });
      }
    }
    if (!candidates.length) break;
    const boundary = candidates.sort((a, b) => a.score - b.score)[0].boundary;
    result.push(tokens.splice(0, boundary).join(" "));
  }
  if (tokens.length) result.push(tokens.join(" "));
  return result;
}

/** @param {{asset_id: string|null, offset: number, trim_start: number, trim_end: number, loop: boolean}|null} music @param {number} duration @param {number|null} assetDuration */
export function musicPlaybackSpan(music, duration, assetDuration) {
  if (!music?.asset_id || !Number.isFinite(duration) || !Number.isFinite(music.offset)) return 0;
  const remaining = Math.max(0, duration - music.offset);
  const sourceSpan = Math.max(0, music.trim_end - music.trim_start);
  const boundedSourceSpan = assetDuration === null ? sourceSpan : Math.min(sourceSpan, Math.max(0, assetDuration - music.trim_start));
  if (boundedSourceSpan < MIN_MUSIC_SPAN_SECONDS) return 0;
  return Math.max(0, music.loop ? remaining : Math.min(remaining, boundedSourceSpan));
}
