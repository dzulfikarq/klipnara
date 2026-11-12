import assert from "node:assert/strict";
import test from "node:test";
import { cameraCropRect, cameraFrameAtTime, cameraStateAtFrame, clampCameraState, deleteCameraKeyframe, remapCameraScenes, upsertCameraKeyframe } from "./camera.mjs";
import { deleteOutputRangeEdit, deleteScene, duplicateScene, reorderScene, splitScene, updateSceneRange } from "./clip-timeline.mjs";

const keys = [
  { id: "a", frame: 0, x: 50, y: 50, zoom: 1 },
  { id: "b", frame: 120, x: 75, y: 60, zoom: 1.5 },
];

test("camera keyframes interpolate hold, linear, and smooth without overshoot", () => {
  assert.deepEqual(cameraStateAtFrame(keys, 60, "hold"), { x: 50, y: 50, zoom: 1 });
  assert.deepEqual(cameraStateAtFrame(keys, 60, "linear"), { x: 62.5, y: 55, zoom: 1.25 });
  assert.deepEqual(cameraStateAtFrame(keys, 60, "smooth"), { x: 62.5, y: 55, zoom: 1.25 });
  assert.ok(cameraStateAtFrame(keys, 30, "smooth").x < cameraStateAtFrame(keys, 30, "linear").x);
  assert.deepEqual(cameraStateAtFrame(keys, 120, "hold"), { x: 75, y: 60, zoom: 1.5 });
  assert.equal(cameraFrameAtTime(4.001, 30), 120);
});

test("camera clamps to source bounds and crop rectangle never exposes bars", () => {
  const clamped = clampCameraState({ x: 0, y: 100, zoom: 1 });
  assert.equal(clamped.x, 0);
  assert.equal(clamped.y, 100);
  const rect = cameraCropRect({ x: 100, y: 100, zoom: 2 }, 1920, 1080);
  assert.ok(rect.left >= 0 && rect.top >= 0);
  assert.ok(rect.left + rect.width <= 1 && rect.top + rect.height <= 1);
  const legacyCenter = cameraCropRect({ x: 50, y: 50, zoom: 1 }, 1920, 1080);
  assert.equal(legacyCenter.left, (1 - legacyCenter.width) / 2);
  assert.equal(clampCameraState({ x: -20, y: 140, zoom: 9 }).zoom, 2);
});

test("scene remapping preserves camera state through trim, split, cut, reorder, duplicate, and delete", () => {
  const camera = { enabled: true, interpolation: "linear", scenes: { a: { keyframes: keys } } };
  const original = [{ id: "a", source_start: 0, source_end: 8, order: 0, role: "body" }];
  const splitScenes = splitScene(original, "a", 4);
  const splitRightId = splitScenes.find((scene) => scene.source_start === 4).id;
  const split = remapCameraScenes(camera, original, splitScenes, 30, { [splitRightId]: "a" });
  assert.equal(split.scenes.a.keyframes.at(-1).frame, 119);
  assert.equal(split.scenes.a.keyframes.at(-1).x, 74.79166666666667);
  assert.equal(split.scenes[splitRightId].keyframes[0].frame, 0);
  assert.deepEqual(camera.scenes.a.keyframes, keys, "source camera data stays immutable");

  const trimmedScenes = updateSceneRange(original, "a", 2, 6, 10);
  const trimmed = remapCameraScenes(camera, original, trimmedScenes, 30);
  assert.equal(trimmed.scenes.a.keyframes[0].frame, 0);
  assert.equal(trimmed.scenes.a.keyframes.at(-1).frame, 119);

  const cutEdit = deleteOutputRangeEdit(original, 2, 6, {}, 30);
  const cutRightId = cutEdit.scenes.find((scene) => scene.source_start === 6).id;
  const cut = remapCameraScenes(camera, original, cutEdit.scenes, 30, { [cutRightId]: "a" });
  assert.equal(cut.scenes[cutRightId].keyframes[0].frame, 0);
  assert.equal(cut.scenes[cutRightId].keyframes[0].x, 75);

  const previous = [...original, { id: "b", source_start: 10, source_end: 12, order: 1, role: "body" }];
  const reorderedScenes = reorderScene(previous, "a", "b");
  const reordered = remapCameraScenes(camera, previous, reorderedScenes, 30);
  assert.deepEqual(reordered.scenes.a.keyframes, keys);
  const duplicatedScenes = duplicateScene(original, "a");
  const duplicateId = duplicatedScenes.find((scene) => scene.id !== "a").id;
  const duplicated = remapCameraScenes(camera, original, duplicatedScenes, 30, { [duplicateId]: "a" });
  assert.deepEqual(duplicated.scenes[duplicateId].keyframes.map(({ id, ...item }) => item), keys.map(({ id, ...item }) => item));
  assert.ok(duplicated.scenes[duplicateId].keyframes.every((item) => !keys.some((originalKey) => originalKey.id === item.id)));
  assert.equal(new Set([...duplicated.scenes.a.keyframes, ...duplicated.scenes[duplicateId].keyframes].map((item) => item.id)).size, 4);
  const afterDelete = deleteScene(previous, "b");
  assert.deepEqual(remapCameraScenes(camera, previous, afterDelete, 30).scenes.a.keyframes, keys);
  assert.deepEqual(remapCameraScenes(camera, original, [], 30).scenes, {});

  const doubledFps = remapCameraScenes(camera, original, original, 60, {}, 30);
  assert.equal(doubledFps.scenes.a.keyframes[1].frame, 240);
});

test("camera keyframe add overwrites same frame and delete preserves other frames", () => {
  const camera = upsertCameraKeyframe(null, "a", 0, { x: 50, y: 50, zoom: 1 });
  const replaced = upsertCameraKeyframe(camera, "a", 0, { x: 70, y: 55, zoom: 1.2 });
  assert.equal(replaced.scenes.a.keyframes.length, 1);
  assert.deepEqual({ x: replaced.scenes.a.keyframes[0].x, y: replaced.scenes.a.keyframes[0].y, zoom: replaced.scenes.a.keyframes[0].zoom }, { x: 70, y: 55, zoom: 1.2 });
  assert.equal(deleteCameraKeyframe(replaced, "a", replaced.scenes.a.keyframes[0].id).scenes.a.keyframes.length, 0);
});
