export const MIN_SCENE_SECONDS = 0.5;
export const MAX_SCENES = 12;
export const MAX_HISTORY = 40;

const round = (value) => Math.round(value * 1000) / 1000;
const makeId = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

/** Source timestamps stay fixed when scenes move; output time is cumulative order. */
export function sceneTimeline(scenes) {
  let cursor = 0;
  return [...scenes].sort((a, b) => a.order - b.order).map((scene) => {
    const duration = scene.source_end - scene.source_start;
    const item = { ...scene, duration, timeline_start: cursor, timeline_end: cursor + duration };
    cursor += duration;
    return item;
  });
}

export function reorderScene(scenes, id, targetId) {
  const next = [...scenes].sort((a, b) => a.order - b.order);
  const from = next.findIndex((scene) => scene.id === id);
  const to = next.findIndex((scene) => scene.id === targetId);
  if (from < 0 || to < 0 || from === to) return scenes;
  const [scene] = next.splice(from, 1);
  next.splice(to, 0, scene);
  return next.map((item, order) => ({ ...item, order }));
}

export function updateSceneRange(scenes, id, sourceStart, sourceEnd, sourceDuration) {
  const current = scenes.find((scene) => scene.id === id);
  if (!current || ![sourceStart, sourceEnd, sourceDuration].every(Number.isFinite)
    || sourceStart < 0 || sourceEnd > sourceDuration || sourceEnd - sourceStart < MIN_SCENE_SECONDS) return null;
  return scenes.map((scene) => scene.id === id ? { ...scene, source_start: round(sourceStart), source_end: round(sourceEnd) } : scene);
}

export function splitScene(scenes, id, sourceTime) {
  if (scenes.length >= MAX_SCENES) return null;
  const ordered = [...scenes].sort((a, b) => a.order - b.order);
  const index = ordered.findIndex((scene) => scene.id === id);
  if (index < 0) return null;
  const scene = ordered[index];
  if (!Number.isFinite(sourceTime) || sourceTime - scene.source_start < MIN_SCENE_SECONDS || scene.source_end - sourceTime < MIN_SCENE_SECONDS) return null;
  const left = { ...scene, source_end: round(sourceTime), role: scene.role === "ending" ? "body" : scene.role };
  const right = { ...scene, id: makeId(), source_start: round(sourceTime), role: scene.role === "hook" ? "body" : scene.role };
  return [...ordered.slice(0, index), left, right, ...ordered.slice(index + 1)].map((item, order) => ({ ...item, order }));
}

export function duplicateScene(scenes, id) {
  const ordered = [...scenes].sort((a, b) => a.order - b.order);
  const index = ordered.findIndex((scene) => scene.id === id);
  if (index < 0 || scenes.length >= MAX_SCENES) return null;
  const copy = { ...ordered[index], id: makeId(), role: "body" };
  return [...ordered.slice(0, index + 1), copy, ...ordered.slice(index + 1)].map((item, order) => ({ ...item, order }));
}

export function deleteScene(scenes, id) {
  if (scenes.length <= 1 || !scenes.some((scene) => scene.id === id)) return null;
  return [...scenes].sort((a, b) => a.order - b.order).filter((scene) => scene.id !== id).map((item, order) => ({ ...item, order }));
}

/** Remove output-time interval; every remaining source fragment ripples left. */
export function deleteOutputRange(scenes, rangeStart, rangeEnd) {
  const ordered = sceneTimeline(scenes);
  const total = ordered.at(-1)?.timeline_end || 0;
  if (!Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd) || rangeStart < 0 || rangeEnd > total || rangeEnd - rangeStart < 0.001) return null;
  const next = [];
  for (const scene of ordered) {
    const cutStart = Math.max(rangeStart, scene.timeline_start);
    const cutEnd = Math.min(rangeEnd, scene.timeline_end);
    if (cutStart >= cutEnd) {
      next.push({ ...scene });
      continue;
    }
    const leftEnd = scene.source_start + cutStart - scene.timeline_start;
    const rightStart = scene.source_start + cutEnd - scene.timeline_start;
    const leftDuration = leftEnd - scene.source_start;
    const rightDuration = scene.source_end - rightStart;
    if (leftDuration >= MIN_SCENE_SECONDS) {
      next.push({ ...scene, source_end: round(leftEnd), role: scene.role === "ending" ? "body" : scene.role });
    } else if (leftDuration > 0.001) return null;
    if (rightDuration >= MIN_SCENE_SECONDS) {
      next.push({ ...scene, id: leftDuration >= MIN_SCENE_SECONDS ? makeId() : scene.id, source_start: round(rightStart), role: scene.role === "hook" ? "body" : scene.role });
    } else if (rightDuration > 0.001) return null;
  }
  if (!next.length || next.length > MAX_SCENES) return null;
  return next.map((scene, order) => ({ ...scene, order }));
}

export function pushEditHistory(history, current) {
  return { undo: [...history.undo, current].slice(-MAX_HISTORY), redo: [] };
}

export function undoEditHistory(history, current) {
  const previous = history.undo.at(-1);
  return previous ? {
    edit: previous,
    history: { undo: history.undo.slice(0, -1), redo: [...history.redo, current].slice(-MAX_HISTORY) },
  } : null;
}

export function redoEditHistory(history, current) {
  const next = history.redo.at(-1);
  return next ? {
    edit: next,
    history: { undo: [...history.undo, current].slice(-MAX_HISTORY), redo: history.redo.slice(0, -1) },
  } : null;
}

/** Clip source-timed captions at each cut; repeated source ranges intentionally repeat captions. */
export function mapSubtitlesToScenes(scenes, subtitles) {
  const ordered = sceneTimeline(scenes);
  return ordered.flatMap((scene) => subtitles.flatMap((subtitle) => {
    const start = Math.max(scene.source_start, subtitle.start);
    const end = Math.min(scene.source_end, subtitle.end);
    if (start >= end || !subtitle.text?.trim()) return [];
    return [{
      id: `${scene.id}-${subtitle.id}`,
      text: subtitle.text,
      output_start: scene.timeline_start + start - scene.source_start,
      output_end: scene.timeline_start + end - scene.source_start,
      source_start: start,
      source_end: end,
    }];
  }));
}

export function outputToSource(scenes, outputTime) {
  const timeline = sceneTimeline(scenes);
  if (!timeline.length || !Number.isFinite(outputTime)) return null;
  const time = Math.max(0, Math.min(timeline.at(-1).timeline_end, outputTime));
  const scene = timeline.find((item) => time < item.timeline_end) || timeline.at(-1);
  return { sceneId: scene.id, sourceTime: Math.min(scene.source_end, scene.source_start + Math.max(0, time - scene.timeline_start)) };
}

export function sourceToOutput(scenes, sourceTime) {
  if (!Number.isFinite(sourceTime)) return [];
  return sceneTimeline(scenes)
    .filter((scene) => sourceTime >= scene.source_start && sourceTime < scene.source_end)
    .map((scene) => ({ sceneId: scene.id, outputTime: scene.timeline_start + sourceTime - scene.source_start }));
}
