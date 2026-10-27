import assert from "node:assert/strict";
import test from "node:test";
import { deleteOutputRange, deleteScene, duplicateScene, mapSubtitlesToScenes, outputToSource, pushEditHistory, redoEditHistory, reorderScene, sceneTimeline, sourceToOutput, splitScene, undoEditHistory, updateSceneRange } from "./clip-timeline.mjs";

const scenes = [
  { id: "a", source_start: 17, source_end: 25, order: 1, role: "body" },
  { id: "b", source_start: 0, source_end: 3, order: 0, role: "hook" },
];

test("scene order derives contiguous output time without changing source time", () => {
  const timeline = sceneTimeline(scenes);
  assert.deepEqual(timeline.map(({ id, source_start, timeline_start, timeline_end }) => [id, source_start, timeline_start, timeline_end]), [
    ["b", 0, 0, 3], ["a", 17, 3, 11],
  ]);
  assert.equal(outputToSource(scenes, 5).sourceTime, 19);
  assert.deepEqual(sourceToOutput(scenes, 19), [{ sceneId: "a", outputTime: 5 }]);
  assert.equal(outputToSource(reorderScene(scenes, "a", "b"), 1).sourceTime, 18);
});

test("subtitle mapping clips at cuts and repeats only for repeated source ranges", () => {
  const repeated = [...scenes, { id: "c", source_start: 17, source_end: 25, order: 2, role: "ending" }];
  const mapped = mapSubtitlesToScenes(repeated, [{ id: "caption", start: 23, end: 28, text: "Cut safely." }]);
  assert.deepEqual(mapped.map(({ id, output_start, output_end }) => [id, output_start, output_end]), [
    ["a-caption", 9, 11], ["c-caption", 17, 19],
  ]);
  assert.equal(mapped.length, 2);
});

test("scene range, split, duplicate, and delete enforce safe bounds", () => {
  assert.equal(updateSceneRange(scenes, "a", 0, 0.2, 40), null);
  assert.equal(updateSceneRange(scenes, "a", 30, 31, 30), null);
  const changed = updateSceneRange(scenes, "a", 18, 24, 40);
  assert.equal(changed[0].source_start, 18);
  const split = splitScene(scenes, "a", 21);
  assert.equal(split.length, 3);
  assert.equal(split[1].source_end, split[2].source_start);
  assert.equal(split[2].source_end, 25);
  const duplicated = duplicateScene(scenes, "a");
  assert.equal(duplicated[2].source_start, 17);
  assert.equal(deleteScene(duplicated, "a").length, 2);
  assert.equal(deleteScene([scenes[0]], "a"), null);
  const twelve = Array.from({ length: 12 }, (_, order) => ({ id: `s${order}`, source_start: order * 2, source_end: order * 2 + 1, order, role: "body" }));
  assert.equal(splitScene(twelve, "s0", 0.5), null);
  assert.equal(duplicateScene(twelve, "s0"), null);
  const cuttableTwelve = [{ id: "long", source_start: 0, source_end: 2, order: 0, role: "body" }, ...twelve.slice(1).map((scene) => ({ ...scene, source_start: scene.order * 2, source_end: scene.order * 2 + 0.5 }))];
  assert.equal(deleteOutputRange(cuttableTwelve, 0.75, 1.25), null, "ripple cut cannot exceed scene cap by fragmenting a scene");
});

test("ripple delete cuts output range across reordered scenes and keeps source intact", () => {
  const result = deleteOutputRange(scenes, 2, 5);
  assert.deepEqual(result.map(({ id, source_start, source_end, order }) => [id === "b" ? id : id === "a" ? id : "split", source_start, source_end, order]), [
    ["b", 0, 2, 0], ["split", 19, 25, 1],
  ]);
  assert.deepEqual(sceneTimeline(result).map(({ timeline_start, timeline_end }) => [timeline_start, timeline_end]), [[0, 2], [2, 8]]);
  assert.equal(outputToSource(result, 2.5).sourceTime, 19.5);
  assert.deepEqual([scenes[0].source_start, scenes[0].source_end], [17, 25]);
  assert.equal(deleteOutputRange(scenes, 0, 2.7), null, "reject sub-minimum fragments instead of silently deleting them");
  assert.equal(deleteOutputRange(scenes, 0, 11), null, "keep one scene in the editor");
});

test("cut, reorder, and split preserve output duration and subtitle/audio source mapping", () => {
  const cut = deleteOutputRange(scenes, 1, 2);
  const duration = sceneTimeline(cut).at(-1).timeline_end;
  assert.equal(duration, 10);
  const captions = mapSubtitlesToScenes(cut, [{ id: "speech", start: 17, end: 20, text: "Audio stays aligned." }]);
  assert.deepEqual(captions.map(({ output_start, output_end }) => [output_start, output_end]), [[2, 5]]);
  const afterSplit = splitScene(cut, "a", 18.5);
  assert.equal(sceneTimeline(afterSplit).at(-1).timeline_end, duration);
  assert.equal(outputToSource(afterSplit, 3).sourceTime, 18);
});

test("bounded edit history supports undo and redo without retaining unbounded snapshots", () => {
  let history = { undo: [], redo: [] };
  let current = { value: 0 };
  for (let value = 1; value <= 45; value += 1) {
    history = pushEditHistory(history, current);
    current = { value };
  }
  assert.equal(history.undo.length, 40);
  const undone = undoEditHistory(history, current);
  assert.equal(undone.edit.value, 44);
  const redone = redoEditHistory(undone.history, undone.edit);
  assert.equal(redone.edit.value, 45);
  assert.deepEqual(pushEditHistory(redone.history, redone.edit).redo, []);
  const restored = JSON.parse(JSON.stringify({ scenes, history: redone.history }));
  assert.equal(sceneTimeline(restored.scenes).at(-1).timeline_end, 11);
});
