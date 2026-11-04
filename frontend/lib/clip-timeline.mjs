export const MIN_SCENE_SECONDS = 0.5;
export const MAX_SCENES = 12;
export const MAX_HISTORY = 40;
export const MIN_TRANSITION_SECONDS = 0.1;
export const MAX_TRANSITION_SECONDS = 2;
export const TRANSITION_TYPES = [
  "none", "crossfade", "dip_to_black", "zoom_blur",
  "wipeleft", "wiperight", "wipeup", "wipedown",
  "slideleft", "slideright", "slideup", "slidedown",
  "smoothleft", "smoothright", "smoothup", "smoothdown",
  "circleopen", "circleclose", "dissolve", "pixelize", "radial", "fadewhite",
];
export const TRANSITION_TIMING_MODES = ["insert_slot", "overlap"];

const round = (value) => Math.round(value * 1000) / 1000;
const makeId = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
export const transitionKey = (fromId, toId) => `${fromId}>${toId}`;

export function formatTimeInput(value) {
  if (!Number.isFinite(value)) return "";
  const [mantissa, exponent = "0"] = String(Math.abs(value)).toLowerCase().split("e");
  const [whole, fraction = ""] = mantissa.split(".");
  const digits = whole + fraction;
  const decimal = whole.length + Number(exponent);
  const integer = decimal <= 0 ? "0" : digits.slice(0, decimal) + "0".repeat(Math.max(0, decimal - digits.length));
  const decimals = (decimal <= 0 ? "0".repeat(-decimal) + digits : digits.slice(decimal)).slice(0, 3).replace(/0+$/, "");
  return `${value < 0 ? "-" : ""}${integer}${decimals ? `.${decimals}` : ""}`;
}

export function sceneTransition(scenes, index, transitions = {}) {
  const ordered = [...scenes].sort((a, b) => a.order - b.order);
  const from = ordered[index], to = ordered[index + 1];
  return from && to
    ? transitions[transitionKey(from.id, to.id)] || { type: "none", duration: 0.5, timing_mode: "insert_slot", smooth_audio: false }
    : { type: "none", duration: 0.5, timing_mode: "insert_slot", smooth_audio: false };
}

export function transitionMode(transition) {
  return transition?.timing_mode === "insert_slot" ? "insert_slot" : "overlap";
}

export function transitionFrameCount(duration, fps = 30) {
  if (!Number.isFinite(duration) || ![30, 60].includes(fps)) return 0;
  return duration > 0 ? Math.max(1, Math.round(duration * fps)) : 0;
}

export function quantizeTransitionDuration(duration, fps = 30) {
  const frames = transitionFrameCount(duration, fps);
  return frames > 0 ? frames / fps : 0;
}

function transitionFrameCounts(scenes, transitions, fps) {
  const ordered = [...scenes].sort((a, b) => a.order - b.order);
  const boundaries = ordered.slice(0, -1).map((from, index) => transitions?.[transitionKey(from.id, ordered[index + 1].id)]
    || { type: "none", duration: 0.5, timing_mode: "insert_slot", smooth_audio: false });
  const modes = boundaries.map(transitionMode);
  const frames = boundaries.map((transition) => transition.type === "none" ? 0 : transitionFrameCount(transition.duration, fps));
  const overlapFrames = ordered.map((_, index) => (index > 0 && modes[index - 1] === "overlap" ? frames[index - 1] : 0)
    + (index < frames.length && modes[index] === "overlap" ? frames[index] : 0));
  const sceneFrames = ordered.map((scene) => Math.floor((scene.source_end - scene.source_start) * fps + 1e-6));
  while (true) {
    const overflowing = overlapFrames.findIndex((count, index) => count > sceneFrames[index]);
    if (overflowing < 0) break;
    let excess = overlapFrames[overflowing] - sceneFrames[overflowing];
    let reduced = false;
    for (const candidate of [overflowing, overflowing - 1]) {
      if (candidate < 0 || candidate >= frames.length || frames[candidate] <= 0 || modes[candidate] !== "overlap") continue;
      const reduction = Math.min(excess, frames[candidate]);
      frames[candidate] -= reduction;
      overlapFrames[overflowing] -= reduction;
      overlapFrames[candidate === overflowing ? candidate + 1 : candidate] -= reduction;
      excess -= reduction;
      reduced = true;
      if (!excess) break;
    }
    if (!reduced) break;
  }
  return frames;
}

export function validateSceneTransitions(scenes, transitions = {}, fps = 30) {
  const ordered = [...scenes].sort((a, b) => a.order - b.order);
  const overlapSeconds = ordered.map(() => 0);
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const transition = sceneTransition(ordered, index, transitions);
    if (!TRANSITION_TYPES.includes(transition.type)) return "Tipe transisi tidak valid.";
    if (transition.timing_mode != null && !TRANSITION_TIMING_MODES.includes(transition.timing_mode)) return "Mode waktu transisi tidak valid.";
    if (transition.type === "none") {
      if (transition.smooth_audio) return "Smooth Audio Transition memerlukan transisi visual.";
      continue;
    }
    const frames = transitionFrameCount(transition.duration, fps);
    if (!frames || !Number.isFinite(transition.duration)) {
      return "Durasi transisi harus angka positif dan selaras dengan frame.";
    }
    if (transition.type === "zoom_blur" && transitionMode(transition) === "insert_slot") {
      return "Zoom Blur lama hanya dapat dipakai dalam mode Overlap; renderer memakai Crossfade.";
    }
    if (transitionMode(transition) === "overlap") {
      const duration = transition.duration;
      const fromDuration = ordered[index].source_end - ordered[index].source_start;
      const toDuration = ordered[index + 1].source_end - ordered[index + 1].source_start;
      if (duration > Math.min(fromDuration, toDuration) + 0.001) {
        return "Overlap harus muat pada rentang frame kedua scene.";
      }
      overlapSeconds[index] += duration;
      overlapSeconds[index + 1] += duration;
    }
  }
  if (overlapSeconds.some((duration, index) => duration > ordered[index].source_end - ordered[index].source_start + 0.001)) {
    return "Total overlap masuk dan keluar tidak boleh melebihi durasi scene.";
  }
  const overlapFrames = transitionFrameCounts(ordered, transitions, fps);
  return overlapFrames.some((frames, index) => frames > 0 && frames > Math.floor((ordered[index].source_end - ordered[index].source_start) * fps + 1e-6))
    ? "Total overlap masuk dan keluar tidak boleh melebihi durasi scene."
    : "";
}

export function maxSceneTransitionDuration(scenes, index, transitions = {}, fps = 30, timingMode) {
  const ordered = [...scenes].sort((a, b) => a.order - b.order);
  const from = ordered[index], to = ordered[index + 1];
  if (!from || !to) return 0;
  const candidateMode = timingMode || transitionMode(sceneTransition(ordered, index, transitions));
  const existingFrames = transitionFrameCounts(ordered, transitions, fps);
  let maximumFrames = Math.floor(MAX_TRANSITION_SECONDS * fps);
  if (candidateMode === "overlap") {
    maximumFrames = Math.min(maximumFrames,
      Math.floor((from.source_end - from.source_start) * fps + 1e-6),
      Math.floor((to.source_end - to.source_start) * fps + 1e-6));
    if (index > 0) {
      const incoming = sceneTransition(ordered, index - 1, transitions);
      if (incoming.type !== "none" && transitionMode(incoming) === "overlap") maximumFrames -= existingFrames[index - 1];
    }
    if (index + 2 < ordered.length) {
      const outgoing = sceneTransition(ordered, index + 1, transitions);
      if (outgoing.type !== "none" && transitionMode(outgoing) === "overlap") maximumFrames = Math.min(maximumFrames,
        Math.floor((to.source_end - to.source_start) * fps + 1e-6) - existingFrames[index + 1]);
    }
  }
  return Math.max(0, maximumFrames) / fps;
}

export function reconcileSceneTransitions(previousScenes, nextScenes, transitions = {}, fps = 30) {
  const previous = [...previousScenes].sort((a, b) => a.order - b.order);
  const next = [...nextScenes].sort((a, b) => a.order - b.order);
  const previousIds = new Set(previous.map((scene) => scene.id));
  const valid = new Set(next.slice(0, -1).map((scene, index) => transitionKey(scene.id, next[index + 1].id)));
  const reconciled = {};
  for (const [key, value] of Object.entries(transitions || {})) if (valid.has(key)) reconciled[key] = value;

  for (let index = 0; index < previous.length - 1; index += 1) {
    const from = previous[index], to = previous[index + 1];
    const transition = transitions?.[transitionKey(from.id, to.id)];
    if (!transition || valid.has(transitionKey(from.id, to.id))) continue;
    const toIndex = next.findIndex((scene) => scene.id === to.id);
    const continuation = toIndex > 0 ? next[toIndex - 1] : null;
    if (continuation && !previousIds.has(continuation.id)
      && Math.abs(continuation.source_end - from.source_end) <= 0.001
      && continuation.source_start > from.source_start + 0.001) {
      reconciled[transitionKey(continuation.id, to.id)] = transition;
    }
  }

  for (const [key, transition] of Object.entries(reconciled)) {
    const index = next.findIndex((scene, position) => position < next.length - 1 && transitionKey(scene.id, next[position + 1].id) === key);
    if (index < 0 || !TRANSITION_TYPES.includes(transition.type) || !TRANSITION_TIMING_MODES.includes(transitionMode(transition))) { delete reconciled[key]; continue; }
    if (transition.type !== "none" && (!Number.isFinite(transition.duration) || transition.duration <= 0)) delete reconciled[key];
  }
  while (validateSceneTransitions(next, reconciled, fps)) {
    const invalid = Object.keys(reconciled).at(-1);
    if (!invalid) break;
    delete reconciled[invalid];
  }
  return reconciled;
}

/** Pair-keyed transitions shift composition time; source timestamps remain non-destructive. */
export function sceneTimeline(scenes, transitions = {}, fps = 30) {
  const rate = [30, 60].includes(fps) ? fps : 30;
  const ticksPerSecond = rate * 1_000_000;
  const ticksPerFrame = 1_000_000;
  let cursorTicks = 0;
  const ordered = [...scenes].sort((a, b) => a.order - b.order);
  const frameCounts = transitionFrameCounts(ordered, transitions, rate);
  return ordered.map((scene, index) => {
    const sourceFrames = Math.max(1, Math.floor((scene.source_end - scene.source_start) * rate + 1e-6));
    const durationTicks = sourceFrames * ticksPerFrame;
    const duration = durationTicks / ticksPerSecond;
    const timelineStartTicks = cursorTicks;
    const timelineEndTicks = timelineStartTicks + durationTicks;
    const outgoing = sceneTransition(ordered, index, transitions);
    const frames = outgoing.type === "none" ? 0 : frameCounts[index];
    const transitionTicks = frames * ticksPerFrame;
    const transitionDuration = frames / rate;
    const mode = transitionMode(outgoing);
    const transitionStartTicks = mode === "overlap" ? timelineEndTicks - transitionTicks : timelineEndTicks;
    const item = {
      ...scene,
      duration,
      timeline_start: timelineStartTicks / ticksPerSecond,
      timeline_end: timelineEndTicks / ticksPerSecond,
      transition_to_next: outgoing,
      transition_duration: transitionDuration,
      transition_frames: frames,
      transition_timing_mode: mode,
      transition_start: transitionStartTicks / ticksPerSecond,
      transition_end: (transitionStartTicks + transitionTicks) / ticksPerSecond,
    };
    cursorTicks = mode === "insert_slot" ? timelineEndTicks + transitionTicks : timelineEndTicks - transitionTicks;
    return item;
  });
}

export function compositionSignature(scenes, transitions = {}, fps = 30) {
  const timeline = sceneTimeline(scenes, transitions, fps);
  const hasTransitions = timeline.some((scene) => scene.transition_duration > 0);
  const hasFrameAdjustedScenes = timeline.some((scene) => Math.abs(scene.duration - (scene.source_end - scene.source_start)) > 1e-6);
  return timeline.map((scene) => `${scene.id}:${scene.source_start.toFixed(3)}:${scene.source_end.toFixed(3)}${hasTransitions || hasFrameAdjustedScenes
    ? `@${scene.timeline_start.toFixed(3)}:${scene.transition_timing_mode}:${scene.transition_duration.toFixed(6)}` : ""}`).join("|");
}

export function sceneSourceOwnership(timeline, index) {
  const scene = timeline[index];
  if (!scene) return null;
  const incoming = index ? timeline[index - 1] : null;
  const incomingOverlap = incoming?.transition_timing_mode === "overlap" ? incoming.transition_duration || 0 : 0;
  const outgoingOverlap = scene.transition_timing_mode === "overlap" ? scene.transition_duration || 0 : 0;
  const renderedEnd = Math.min(scene.source_end, scene.source_start + scene.duration);
  return { start: scene.source_start + incomingOverlap / 2, end: renderedEnd - outgoingOverlap / 2 };
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
export function deleteOutputRangeEdit(scenes, rangeStart, rangeEnd, transitions = {}, fps = 30) {
  const ordered = sceneTimeline(scenes, transitions, fps);
  const total = ordered.at(-1)?.timeline_end || 0;
  if (!Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd) || rangeStart < 0 || rangeEnd > total || rangeEnd - rangeStart < 1 / fps) return null;
  const nextTransitions = { ...transitions };
  for (const [index, scene] of ordered.slice(0, -1).entries()) {
    if (scene.transition_to_next.type === "none" || scene.transition_timing_mode !== "insert_slot") continue;
    const removed = Math.max(0, Math.min(rangeEnd, scene.transition_end) - Math.max(rangeStart, scene.transition_start));
    if (!removed) continue;
    const remainingFrames = scene.transition_frames - Math.round(removed * fps);
    const key = transitionKey(scene.id, ordered[index + 1].id);
    if (remainingFrames <= 0 || remainingFrames < Math.ceil(MIN_TRANSITION_SECONDS * fps)) delete nextTransitions[key];
    else nextTransitions[key] = { ...scene.transition_to_next, duration: remainingFrames / fps };
  }
  const next = [];
  for (let index = 0; index < ordered.length; index += 1) {
    const scene = ordered[index];
    const ownership = sceneSourceOwnership(ordered, index);
    const ownedStart = scene.timeline_start + ownership.start - scene.source_start;
    const ownedEnd = scene.timeline_start + ownership.end - scene.source_start;
    const cutStart = Math.max(rangeStart, ownedStart);
    const cutEnd = Math.min(rangeEnd, ownedEnd);
    if (cutStart >= cutEnd) {
      next.push({ ...scene });
      continue;
    }
    const leftEnd = scene.source_start + cutStart - scene.timeline_start;
    const rightStart = scene.source_start + cutEnd - scene.timeline_start;
    const leftDuration = leftEnd - scene.source_start;
    const renderedEnd = Math.min(scene.source_end, scene.source_start + scene.duration);
    const rightDuration = renderedEnd - rightStart;
    if (leftDuration >= MIN_SCENE_SECONDS) {
      next.push({ ...scene, source_end: round(leftEnd), role: scene.role === "ending" ? "body" : scene.role });
    } else if (leftDuration > 0.001) return null;
    if (rightDuration >= MIN_SCENE_SECONDS) {
      next.push({ ...scene, id: leftDuration >= MIN_SCENE_SECONDS ? makeId() : scene.id, source_start: round(rightStart), source_end: round(renderedEnd), role: scene.role === "hook" ? "body" : scene.role });
    } else if (rightDuration > 0.001) return null;
  }
  if (!next.length || next.length > MAX_SCENES) return null;
  const result = next.map((scene, order) => ({ ...scene, order }));
  return { scenes: result, transitions: reconcileSceneTransitions(scenes, result, nextTransitions, fps) };
}

export function deleteOutputRange(scenes, rangeStart, rangeEnd, transitions = {}, fps = 30) {
  return deleteOutputRangeEdit(scenes, rangeStart, rangeEnd, transitions, fps)?.scenes || null;
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
export function mapSubtitlesToScenes(scenes, subtitles, transitions = {}, fps = 30) {
  const ordered = sceneTimeline(scenes, transitions, fps);
  return ordered.flatMap((scene, index) => {
    const ownership = sceneSourceOwnership(ordered, index);
    return subtitles.flatMap((subtitle) => {
      const start = Math.max(ownership.start, subtitle.start);
      const end = Math.min(ownership.end, subtitle.end);
      if (start >= end || !subtitle.text?.trim()) return [];
      return [{
        id: `${scene.id}-${subtitle.id}`,
        text: subtitle.text,
        output_start: scene.timeline_start + start - scene.source_start,
        output_end: scene.timeline_start + end - scene.source_start,
        source_start: start,
        source_end: end,
      }];
    });
  });
}

export function outputToSource(scenes, outputTime, transitions = {}, fps = 30) {
  const timeline = sceneTimeline(scenes, transitions, fps);
  if (!timeline.length || !Number.isFinite(outputTime)) return null;
  const time = Math.max(0, Math.min(timeline.at(-1).timeline_end, outputTime));
  for (let index = 0; index < timeline.length - 1; index += 1) {
    const from = timeline[index], to = timeline[index + 1], duration = from.transition_duration;
    const start = from.transition_start;
    const end = from.transition_end;
    if (duration > 0 && time >= start && time < end) {
      const progress = Math.max(0, Math.min(1, (time - start) / duration));
      const inserted = from.transition_timing_mode === "insert_slot";
      const fromSourceTime = inserted ? Math.max(from.source_start, from.source_start + from.duration - 1 / fps) : from.source_start + time - from.timeline_start;
      const toSourceTime = inserted ? to.source_start : to.source_start + time - to.timeline_start;
      return {
      sceneId: from.id,
      sourceTime: fromSourceTime,
      transition: {
        type: from.transition_to_next.type,
        timing_mode: from.transition_timing_mode,
        smooth_audio: Boolean(from.transition_to_next.smooth_audio),
        fromSceneId: from.id,
        toSceneId: to.id,
        fromSourceTime,
        toSourceTime,
        start,
        end,
        duration,
        progress,
      },
      };
    }
  }
  const scene = timeline.find((item) => time < item.timeline_end) || timeline.at(-1);
  return { sceneId: scene.id, sourceTime: Math.min(scene.source_start + scene.duration, scene.source_start + Math.max(0, time - scene.timeline_start)) };
}

export function sourceToOutput(scenes, sourceTime, transitions = {}, fps = 30) {
  if (!Number.isFinite(sourceTime)) return [];
  return sceneTimeline(scenes, transitions, fps)
    .filter((scene) => sourceTime >= scene.source_start && sourceTime < Math.min(scene.source_end, scene.source_start + scene.duration))
    .map((scene) => ({ sceneId: scene.id, outputTime: scene.timeline_start + sourceTime - scene.source_start }));
}
