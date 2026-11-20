import assert from "node:assert/strict";
import test from "node:test";
import { AUTO_CREATIVE_PRESETS, colorGradeMatrix, createAutoCreativeEdit } from "./auto-creative.mjs";

const baseEdit = {
  scene_mode: "multi", fps: 30, crop_x: 50, crop_y: 50,
  color_grade: { brightness: 0, contrast: 1, saturation: 1, temperature: 0 },
  camera: { enabled: false, interpolation: "linear", scenes: {} },
  transitions: {},
  audio: { volume: 1, muted: false, fade_in: 0, fade_out: 0, normalize: false, target_lufs: -18, limiter: false },
};
const scenes = [
  { id: "scene-a", source_start: 1, source_end: 5, order: 0 },
  { id: "scene-b", source_start: 10, source_end: 14, order: 1 },
];

test("all Auto Creative presets stay bounded and configure grade, motion, transitions, and audio", () => {
  for (const [id, preset] of Object.entries(AUTO_CREATIVE_PRESETS)) {
    const edit = createAutoCreativeEdit(baseEdit, scenes, id);
    assert.ok(edit.color_grade.brightness >= -0.08 && edit.color_grade.brightness <= 0.08);
    assert.ok(edit.color_grade.contrast >= 0.9 && edit.color_grade.contrast <= 1.2);
    assert.ok(edit.color_grade.saturation >= 0.9 && edit.color_grade.saturation <= 1.2);
    assert.ok(edit.color_grade.temperature >= -10 && edit.color_grade.temperature <= 10);
    assert.equal(edit.camera.enabled, true);
    assert.equal(edit.camera.interpolation, "smooth");
    assert.equal(edit.camera.scenes["scene-a"].keyframes.at(-1).zoom, preset.zoom);
    assert.deepEqual(Object.values(edit.transitions).map(({ type, timing_mode, smooth_audio }) => [type, timing_mode, smooth_audio]), [
      ["crossfade", "overlap", true],
    ]);
    assert.equal(edit.audio.normalize, true);
    assert.equal(edit.audio.limiter, true);
    assert.equal(edit.audio.target_lufs, preset.targetLufs);
  }
  assert.equal(baseEdit.camera.enabled, false, "input draft stays immutable");
});

test("Auto Creative intensity scales visual changes and single-scene edit adds no transition", () => {
  const existingTransition = { "scene-a>scene-b": { type: "dip_to_black", duration: 0.3, timing_mode: "insert_slot", smooth_audio: false } };
  const low = createAutoCreativeEdit({ ...baseEdit, transitions: existingTransition }, scenes, "viral_fast_cut", 0);
  assert.deepEqual(low.color_grade, baseEdit.color_grade);
  assert.deepEqual(low.transitions, existingTransition);
  assert.deepEqual(low.camera, baseEdit.camera);
  const single = createAutoCreativeEdit({ ...baseEdit, scene_mode: "single" }, scenes.slice(0, 1), "outdoor_cooking", 50);
  assert.deepEqual(single.transitions, {});
  assert.equal(single.camera.scenes["scene-a"].keyframes.at(-1).zoom, 1.035);
});

test("color grade matrix is identity by default and remains finite at safe bounds", () => {
  assert.deepEqual(colorGradeMatrix(), {
    matrix: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], offset: [0, 0, 0],
  });
  const bounded = colorGradeMatrix({ brightness: 9, contrast: 9, saturation: -4, temperature: -50 });
  assert.ok([...bounded.matrix.flat(), ...bounded.offset].every(Number.isFinite));
  assert.ok(bounded.matrix.flat().every((value) => Math.abs(value) <= 2));
  const grayscale = colorGradeMatrix({ saturation: 0 }).matrix;
  assert.deepEqual(grayscale[0], grayscale[1]);
  assert.deepEqual(grayscale[1], grayscale[2]);
});

test("Auto zoom adds gentle zoom without flattening manual framing keyframes", () => {
  const edit = {
    ...baseEdit,
    camera: { enabled: true, interpolation: "smooth", scenes: { "scene-a": { keyframes: [
      { id: "start", frame: 0, x: 50, y: 50, zoom: 1 },
      { id: "track", frame: 60, x: 75, y: 35, zoom: 1.2 },
      { id: "end", frame: 119, x: 90, y: 20, zoom: 1.4 },
    ] } } },
  };
  const result = createAutoCreativeEdit(edit, scenes, "cinematic_survival");
  assert.deepEqual(result.camera.scenes["scene-a"].keyframes.map(({ frame, x, y }) => [frame, x, y]), [
    [0, 50, 50], [60, 75, 35], [119, 90, 20],
  ]);
  assert.equal(result.camera.scenes["scene-a"].keyframes.at(-1).zoom, 1.45);
  assert.equal(edit.camera.scenes["scene-a"].keyframes.at(-1).zoom, 1.4);
});
