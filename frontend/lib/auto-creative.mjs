import { cameraFrameCount, cameraStateAtFrame, clampCameraState } from "./camera.mjs";
import { maxSceneTransitionDuration, quantizeTransitionDuration, transitionKey } from "./clip-timeline.mjs";

export const AUTO_CREATIVE_PRESETS = {
  cinematic_survival: {
    name: "Cinematic Survival",
    brightness: -0.02, contrast: 1.08, saturation: 0.94, temperature: -2,
    zoom: 1.05, transition: 0.35, targetLufs: -18,
  },
  outdoor_cooking: {
    name: "Outdoor Cooking",
    brightness: 0.02, contrast: 1.03, saturation: 1.08, temperature: 3,
    zoom: 1.07, transition: 0.25, targetLufs: -19,
  },
  viral_fast_cut: {
    name: "Viral Fast Cut",
    brightness: 0, contrast: 1.12, saturation: 1.12, temperature: 0,
    zoom: 1.1, transition: 0.15, targetLufs: -16,
  },
};

const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));
const round = (value) => Math.round(value * 1000) / 1000;

export function createAutoCreativeEdit(edit, scenes, presetId, intensity = 100) {
  const preset = AUTO_CREATIVE_PRESETS[presetId];
  if (!preset) throw new RangeError("Unknown Auto Creative preset.");
  const strength = clamp(Number.isFinite(intensity) ? intensity : 100, 0, 100) / 100;
  const fps = [30, 60].includes(edit.fps) ? edit.fps : 30;
  const ordered = [...scenes].sort((left, right) => left.order - right.order);
  const grade = edit.color_grade || { brightness: 0, contrast: 1, saturation: 1, temperature: 0 };
  const camera = edit.camera || { enabled: false, interpolation: "smooth", scenes: {} };
  const cameraScenes = { ...camera.scenes };

  if (strength) {
    for (const scene of ordered) {
      const sceneId = scene.camera_id || scene.id;
      const frameCount = cameraFrameCount(scene.source_end - scene.source_start, fps);
      const lastFrame = Math.max(0, frameCount - 1);
      const existing = cameraScenes[sceneId]?.keyframes || [];
      const fallback = { x: edit.crop_x ?? 50, y: edit.crop_y ?? 50, zoom: 1 };
      const firstState = clampCameraState(cameraStateAtFrame(existing, 0, camera.interpolation || "smooth", fallback));
      const lastState = clampCameraState(cameraStateAtFrame(existing, lastFrame, camera.interpolation || "smooth", fallback));
      const zoomDelta = (preset.zoom - 1) * strength;
      const keyframes = existing.map((keyframe) => ({
        ...keyframe,
        zoom: keyframe.frame <= lastFrame
          ? round(clamp(keyframe.zoom + zoomDelta * (lastFrame ? keyframe.frame / lastFrame : 0), 1, 2))
          : keyframe.zoom,
      }));
      const upsert = (frame, state) => {
        const previous = keyframes.find((keyframe) => keyframe.frame === frame);
        const keyframe = {
          id: previous?.id || `auto-${sceneId.slice(0, 40)}-${frame}`,
          frame,
          x: state.x,
          y: state.y,
          zoom: round(state.zoom),
        };
        const index = keyframes.findIndex((item) => item.frame === frame);
        if (index < 0) keyframes.push(keyframe);
        else keyframes[index] = keyframe;
      };
      upsert(0, firstState);
      upsert(lastFrame, { ...lastState, zoom: clamp(lastState.zoom + zoomDelta, 1, 2) });
      cameraScenes[sceneId] = { ...cameraScenes[sceneId], keyframes: keyframes.sort((left, right) => left.frame - right.frame) };
    }
  }

  const transitions = { ...(edit.transitions || {}) };
  if (strength && edit.scene_mode === "multi") {
    for (let index = 0; index < ordered.length - 1; index += 1) {
      const key = transitionKey(ordered[index].id, ordered[index + 1].id);
      const adjacentTransitions = { ...transitions };
      delete adjacentTransitions[key];
      const maximum = maxSceneTransitionDuration(ordered, index, adjacentTransitions, fps, "overlap");
      if (maximum < 0.1) continue;
      const duration = Math.min(maximum, quantizeTransitionDuration(Math.min(maximum, Math.max(0.1, preset.transition * strength)), fps));
      if (duration >= 0.1) transitions[key] = { type: "crossfade", duration, timing_mode: "overlap", smooth_audio: true };
    }
  }

  return {
    ...edit,
    color_grade: {
      brightness: round(grade.brightness + (preset.brightness - grade.brightness) * strength),
      contrast: round(grade.contrast + (preset.contrast - grade.contrast) * strength),
      saturation: round(grade.saturation + (preset.saturation - grade.saturation) * strength),
      temperature: round(grade.temperature + (preset.temperature - grade.temperature) * strength),
    },
    camera: strength ? { ...camera, enabled: true, interpolation: "smooth", scenes: cameraScenes } : edit.camera,
    transitions,
    audio: { ...edit.audio, normalize: true, limiter: true, target_lufs: preset.targetLufs },
  };
}

export function colorGradeMatrix(grade = {}) {
  const brightness = 1 + clamp(Number.isFinite(grade.brightness) ? grade.brightness : 0, -0.1, 0.1);
  const contrast = clamp(Number.isFinite(grade.contrast) ? grade.contrast : 1, 0.8, 1.25);
  const saturation = clamp(Number.isFinite(grade.saturation) ? grade.saturation : 1, 0, 1.5);
  const temperature = clamp(Number.isFinite(grade.temperature) ? grade.temperature : 0, -10, 10);
  const luma = [0.213, 0.715, 0.072];
  const saturationMatrix = luma.map((_, row) => luma.map((weight, column) => (row === column ? saturation : 0) + weight * (1 - saturation)));
  const tint = Math.abs(temperature) * 0.008 * Math.sign(temperature);
  const gains = [1 + tint, 1, 1 - tint];
  const scale = brightness * contrast;
  const offset = 0.5 * (1 - contrast);
  return {
    matrix: saturationMatrix.map((row, index) => row.map((value) => value * scale * gains[index])),
    offset: gains.map((gain) => offset * gain),
  };
}
