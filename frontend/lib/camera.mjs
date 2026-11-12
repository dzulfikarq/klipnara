export const DEFAULT_CAMERA = { enabled: false, interpolation: "smooth", scenes: {} };

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const roundFrame = (value) => Math.round(value);
const newKeyframeId = () => `camera-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;

export function cameraFrameCount(duration, fps) {
  return Math.max(1, Math.floor(duration * fps + 1e-6));
}

export function cameraFrameAtTime(localTime, fps, frameCount = Infinity) {
  return clamp(roundFrame(Math.max(0, localTime) * fps), 0, Math.max(0, frameCount - 1));
}

export function cameraStateAtFrame(keyframes = [], frame = 0, interpolation = "smooth", fallback = { x: 50, y: 50, zoom: 1 }) {
  const ordered = [...keyframes].sort((a, b) => a.frame - b.frame);
  if (!ordered.length) return { ...fallback };
  if (frame <= ordered[0].frame) return { x: ordered[0].x, y: ordered[0].y, zoom: ordered[0].zoom };
  for (let index = 1; index < ordered.length; index += 1) {
    const to = ordered[index];
    if (frame > to.frame) continue;
    const from = ordered[index - 1];
    if (frame === to.frame) return { x: to.x, y: to.y, zoom: to.zoom };
    if (interpolation === "hold") return { x: from.x, y: from.y, zoom: from.zoom };
    let amount = (frame - from.frame) / (to.frame - from.frame);
    if (interpolation === "smooth") amount = amount * amount * (3 - 2 * amount);
    return Object.fromEntries(["x", "y", "zoom"].map((key) => [key, from[key] + (to[key] - from[key]) * amount]));
  }
  const last = ordered.at(-1);
  return { x: last.x, y: last.y, zoom: last.zoom };
}

export function clampCameraState(state) {
  const zoom = clamp(Number.isFinite(state.zoom) ? state.zoom : 1, 1, 2);
  return {
    x: clamp(Number.isFinite(state.x) ? state.x : 50, 0, 100),
    y: clamp(Number.isFinite(state.y) ? state.y : 50, 0, 100),
    zoom,
  };
}

// ponytail: x/y are alignment percentages over remaining crop room; this makes every crop stay inside source bounds.
export function cameraCropRect(state, sourceWidth, sourceHeight, outputWidth = 720, outputHeight = 1280) {
  const camera = clampCameraState(state);
  const width = Math.min(1, outputWidth / outputHeight / (sourceWidth / sourceHeight)) / camera.zoom;
  const height = Math.min(1, (sourceWidth / sourceHeight) / (outputWidth / outputHeight)) / camera.zoom;
  return { left: (1 - width) * camera.x / 100, top: (1 - height) * camera.y / 100, width, height, camera };
}

export function upsertCameraKeyframe(camera, sceneId, frame, value) {
  const current = camera || DEFAULT_CAMERA;
  const scene = current.scenes?.[sceneId] || { keyframes: [] };
  const existing = scene.keyframes.find((item) => item.frame === frame);
  const keyframe = { id: existing?.id || newKeyframeId(), frame, x: value.x, y: value.y, zoom: value.zoom };
  return {
    ...current,
    enabled: true,
    scenes: { ...current.scenes, [sceneId]: { ...scene, keyframes: [...scene.keyframes.filter((item) => item.frame !== frame), keyframe].sort((a, b) => a.frame - b.frame) } },
  };
}

export function deleteCameraKeyframe(camera, sceneId, keyframeId) {
  const current = camera || DEFAULT_CAMERA;
  const scene = current.scenes?.[sceneId];
  if (!scene) return current;
  return {
    ...current,
    scenes: { ...current.scenes, [sceneId]: { ...scene, keyframes: scene.keyframes.filter((item) => item.id !== keyframeId) } },
  };
}

export function remapCameraScenes(camera, previousScenes, nextScenes, fps, sourceIds = {}, previousFps = fps) {
  if (!camera) return camera;
  const previous = [...previousScenes].sort((a, b) => a.order - b.order);
  const next = [...nextScenes].sort((a, b) => a.order - b.order);
  const mappedScenes = {};
  for (const scene of next) {
    const sourceId = sourceIds[scene.id];
    const oldScene = previous.find((item) => item.id === sourceId)
      || previous.find((item) => item.id === scene.id)
      || previous.filter((item) => item.source_start <= scene.source_start + 1e-6 && item.source_end >= scene.source_end - 1e-6)
        .sort((a, b) => (a.source_end - a.source_start) - (b.source_end - b.source_start) || Math.abs(a.order - scene.order) - Math.abs(b.order - scene.order))[0];
    const config = oldScene && camera.scenes?.[oldScene.id];
    if (!config) continue;
    if (!config.keyframes?.length) { mappedScenes[scene.id] = { ...config, keyframes: [] }; continue; }
    const copyKeyframe = (item) => ({ ...item, ...(oldScene.id === scene.id ? {} : { id: newKeyframeId() }) });
    if (previousFps === fps && Math.abs(scene.source_start - oldScene.source_start) < 1e-6
      && Math.abs(scene.source_end - oldScene.source_end) < 1e-6) {
      mappedScenes[scene.id] = { ...config, keyframes: config.keyframes.map(copyKeyframe) };
      continue;
    }
    const oldCount = cameraFrameCount(oldScene.source_end - oldScene.source_start, previousFps);
    const nextCount = cameraFrameCount(scene.source_end - scene.source_start, fps);
    const offset = scene.source_start - oldScene.source_start;
    const mapped = new Map();
    for (const item of config.keyframes) {
      const frame = roundFrame((item.frame / previousFps - offset) * fps);
      if (frame >= 0 && frame < nextCount) mapped.set(frame, { ...copyKeyframe(item), frame });
    }
    const keyframes = [...mapped.values()];
    const fallback = { x: 50, y: 50, zoom: 1 };
    const boundary = (frame) => cameraStateAtFrame(config.keyframes, clamp(offset * previousFps + frame * previousFps / fps, 0, oldCount - 1), camera.interpolation, fallback);
    const addBoundary = (frame, state) => {
      if (!keyframes.some((item) => item.frame === frame)) keyframes.push({ id: newKeyframeId(), frame, ...state });
    };
    addBoundary(0, boundary(0));
    if (nextCount > 1) addBoundary(nextCount - 1, boundary(nextCount - 1));
    mappedScenes[scene.id] = { ...config, keyframes: keyframes.sort((a, b) => a.frame - b.frame) };
  }
  return { ...camera, scenes: mappedScenes };
}
