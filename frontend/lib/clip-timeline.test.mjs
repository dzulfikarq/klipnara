import assert from "node:assert/strict";
import test from "node:test";
import { compositionSignature, deleteOutputRange, deleteOutputRangeEdit, deleteScene, duplicateScene, formatTimeInput, mapSubtitlesToScenes, outputToSource, pushEditHistory, reconcileSceneTransitions, redoEditHistory, reorderScene, sceneTimeline, sourceToOutput, splitScene, TRANSITION_TYPES, transitionKey, undoEditHistory, updateSceneRange, validateSceneTransitions } from "./clip-timeline.mjs";

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

test("legacy transitions default to frame-aligned overlap output time", () => {
  const ordered = [
    { id: "a", source_start: 0, source_end: 4, order: 0, role: "body" },
    { id: "b", source_start: 10, source_end: 14, order: 1, role: "body" },
    { id: "c", source_start: 20, source_end: 24, order: 2, role: "ending" },
  ];
  const transitions = {
    [transitionKey("a", "b")]: { type: "crossfade", duration: 0.5, smooth_audio: true },
    [transitionKey("b", "c")]: { type: "dip_to_black", duration: 0.2, smooth_audio: false },
  };
  const timeline = sceneTimeline(ordered, transitions);
  assert.deepEqual(timeline.map(({ timeline_start, timeline_end }) => [timeline_start, timeline_end]), [[0, 4], [3.5, 7.5], [7.3, 11.3]]);
  assert.equal(timeline.at(-1).timeline_end, 12 - 0.7);
  assert.deepEqual(outputToSource(ordered, 3.75, transitions).transition, {
    type: "crossfade", timing_mode: "overlap", smooth_audio: true, fromSceneId: "a", toSceneId: "b",
    fromSourceTime: 3.75, toSourceTime: 10.25, start: 3.5, end: 4, duration: 0.5, progress: 0.5,
  });
  assert.equal(outputToSource(ordered, 4, transitions).sourceTime, 10.5);
  assert.deepEqual(mapSubtitlesToScenes(ordered, [
    { id: "before", start: 3.6, end: 4, text: "Before" },
    { id: "after", start: 10, end: 10.4, text: "After" },
  ], transitions).map(({ output_start, output_end }) => [Number(output_start.toFixed(3)), Number(output_end.toFixed(3))]), [[3.6, 3.75], [3.75, 3.9]]);
  assert.notEqual(compositionSignature(ordered, transitions), compositionSignature(ordered));
  assert.equal(validateSceneTransitions(ordered, transitions), "");
  assert.match(validateSceneTransitions(ordered, {
    ...transitions,
    [transitionKey("b", "c")]: { type: "crossfade", duration: 3.6, smooth_audio: false },
  }), /Total overlap/);
});

test("insert slots add real output time while mixed overlap keeps frame-exact mapping", () => {
  const ordered = [
    { id: "a", source_start: 0, source_end: 4, order: 0, role: "body" },
    { id: "b", source_start: 10, source_end: 14, order: 1, role: "body" },
    { id: "c", source_start: 20, source_end: 24, order: 2, role: "ending" },
  ];
  const transitions = {
    [transitionKey("a", "b")]: { type: "crossfade", timing_mode: "insert_slot", duration: 0.5, smooth_audio: true },
    [transitionKey("b", "c")]: { type: "dip_to_black", timing_mode: "overlap", duration: 0.2, smooth_audio: false },
  };
  const timeline = sceneTimeline(ordered, transitions, 30);
  assert.deepEqual(timeline.map(({ timeline_start, timeline_end }) => [timeline_start, timeline_end]), [[0, 4], [4.5, 8.5], [8.3, 12.3]]);
  assert.equal(timeline.at(-1).timeline_end, 12.3);
  assert.deepEqual([timeline[0].transition_start, timeline[0].transition_end], [4, 4.5]);
  const slot = outputToSource(ordered, 4.25, transitions, 30);
  assert.equal(slot.transition.timing_mode, "insert_slot");
  assert.equal(slot.transition.progress, 0.5);
  assert.equal(slot.transition.toSourceTime, 10);
  assert.equal(outputToSource(ordered, slot.transition.fromSourceTime, transitions, 30).transition, undefined,
    "the held source frame maps before the Insert Slot, so source timeupdates must not drive slot time");
  assert.equal(outputToSource(ordered, 4.5, transitions, 30).sourceTime, 10);
  assert.deepEqual(mapSubtitlesToScenes(ordered, [
    { id: "out", start: 3.8, end: 4, text: "Before slot" },
    { id: "in", start: 10, end: 10.2, text: "After slot" },
  ], transitions, 30).map(({ output_start, output_end }) => [Number(output_start.toFixed(3)), Number(output_end.toFixed(3))]), [[3.8, 4], [4.5, 4.7]]);
  assert.match(validateSceneTransitions(ordered, transitions, 30), /^$/);
  assert.notEqual(compositionSignature(ordered, transitions, 30), compositionSignature(ordered, {
    ...transitions,
    [transitionKey("a", "b")]: { ...transitions[transitionKey("a", "b")], timing_mode: "overlap" },
  }, 30));
});

test("transition half-frame rounding and source duration use shared FPS frame rules", () => {
  const ordered = [
    { id: "a", source_start: 0, source_end: 4.01, order: 0, role: "body" },
    { id: "b", source_start: 10, source_end: 12, order: 1, role: "ending" },
  ];
  const transitions = { [transitionKey("a", "b")]: { type: "crossfade", timing_mode: "insert_slot", duration: 0.15, smooth_audio: false } };
  const timeline = sceneTimeline(ordered, transitions, 30);
  assert.equal(timeline[0].duration, 4);
  assert.equal(timeline[0].transition_frames, 5);
  assert.equal(timeline[1].timeline_start, 4 + 5 / 30);
  assert.equal(outputToSource(ordered, 4.01, transitions, 30).transition.fromSourceTime, 4 - 1 / 30);
  assert.equal(mapSubtitlesToScenes(ordered, [{ id: "tail", start: 4.005, end: 4.01, text: "Not rendered" }], transitions, 30).length, 0);
});

test("legacy overlap frame allocation prevents cumulative rounding overflow", () => {
  const ordered = [
    { id: "a", source_start: 0, source_end: 4, order: 0, role: "body" },
    { id: "b", source_start: 10, source_end: 10 + 61 / 30, order: 1, role: "body" },
    { id: "c", source_start: 20, source_end: 24, order: 2, role: "ending" },
  ];
  const transitions = {
    [transitionKey("a", "b")]: { type: "crossfade", duration: 61 / 60, smooth_audio: false },
    [transitionKey("b", "c")]: { type: "crossfade", duration: 61 / 60, smooth_audio: false },
  };
  const timeline = sceneTimeline(ordered, transitions, 30);
  assert.deepEqual(timeline.map((scene) => scene.transition_frames), [31, 30, 0]);
  assert.equal(timeline[1].transition_frames + timeline[0].transition_frames, 61);
  assert.equal(validateSceneTransitions(ordered, transitions, 30), "");
});

test("transition validation rejects nonpositive durations and unsupported insert effects", () => {
  const ordered = [
    { id: "a", source_start: 0, source_end: 0.5, order: 0, role: "body" },
    { id: "b", source_start: 1, source_end: 1.5, order: 1, role: "body" },
  ];
  const key = transitionKey("a", "b");
  for (const duration of [0, Number.NaN]) {
    assert.notEqual(validateSceneTransitions(ordered, { [key]: { type: "crossfade", timing_mode: "insert_slot", duration, smooth_audio: false } }), "");
  }
  assert.match(validateSceneTransitions(ordered, { [key]: { type: "zoom_blur", timing_mode: "insert_slot", duration: 0.5, smooth_audio: false } }), /Overlap/);
  assert.equal(validateSceneTransitions(ordered, { [key]: { type: "crossfade", timing_mode: "insert_slot", duration: 0.1, smooth_audio: false } }, 60), "");
  assert.notEqual(validateSceneTransitions(ordered, { [key]: { type: "crossfade", timing_mode: "overlap", duration: 0.6, smooth_audio: false } }), "");
});

test("all added FFmpeg transition names validate and remain available beyond legacy effects", () => {
  const ordered = [
    { id: "a", source_start: 0, source_end: 3, order: 0, role: "body" },
    { id: "b", source_start: 5, source_end: 8, order: 1, role: "ending" },
  ];
  const added = TRANSITION_TYPES.filter((type) => !["none", "crossfade", "dip_to_black", "zoom_blur"].includes(type));
  assert.ok(added.length >= 10);
  for (const type of added) {
    assert.equal(validateSceneTransitions(ordered, {
      [transitionKey("a", "b")]: { type, timing_mode: "overlap", duration: 0.5, smooth_audio: false },
    }), "", `${type} should validate`);
  }
});

test("ripple delete shortens insert slot without changing source ranges", () => {
  const ordered = [
    { id: "a", source_start: 0, source_end: 4, order: 0, role: "body" },
    { id: "b", source_start: 10, source_end: 14, order: 1, role: "body" },
  ];
  const transitions = { [transitionKey("a", "b")]: { type: "crossfade", timing_mode: "insert_slot", duration: 0.5, smooth_audio: false } };
  const deleted = deleteOutputRangeEdit(ordered, 4.1, 4.2, transitions, 30);
  assert.equal(deleted.transitions[transitionKey("a", "b")].duration, 0.4);
  assert.equal(sceneTimeline(deleted.scenes, deleted.transitions, 30).at(-1).timeline_end, 8.4);
  assert.deepEqual(ordered.map(({ source_start, source_end }) => [source_start, source_end]), [[0, 4], [10, 14]]);
});

test("transition keys follow a split continuation and disappear after reorder", () => {
  const original = [
    { id: "a", source_start: 0, source_end: 4, order: 0, role: "body" },
    { id: "b", source_start: 10, source_end: 14, order: 1, role: "body" },
    { id: "c", source_start: 20, source_end: 24, order: 2, role: "ending" },
  ];
  const transitions = {
    [transitionKey("a", "b")]: { type: "crossfade", duration: 0.5, smooth_audio: false },
    [transitionKey("b", "c")]: { type: "dip_to_black", duration: 0.25, smooth_audio: false },
  };
  const split = splitScene(original, "a", 2);
  const afterSplit = reconcileSceneTransitions(original, split, transitions);
  const continuation = split.find((scene) => scene.source_end === 4 && scene.id !== "a");
  assert.deepEqual(afterSplit, {
    [transitionKey(continuation.id, "b")]: transitions[transitionKey("a", "b")],
    [transitionKey("b", "c")]: transitions[transitionKey("b", "c")],
  });
  const reordered = reorderScene(original, "b", "c");
  assert.deepEqual(reconcileSceneTransitions(original, reordered, transitions), {});
  const duplicated = duplicateScene(original, "a");
  assert.deepEqual(reconcileSceneTransitions(original, duplicated, transitions), {
    [transitionKey("b", "c")]: transitions[transitionKey("b", "c")],
  });
});

test("time inputs format to three decimals without changing stored precision", () => {
  const exact = 12.123456;
  assert.equal(formatTimeInput(exact), "12.123");
  assert.equal(formatTimeInput(12.9999), "12.999");
  assert.equal(formatTimeInput(1e-7), "0");
  assert.equal(formatTimeInput(1.234e21), "1234000000000000000000");
  assert.equal(exact, 12.123456);
  assert.equal(formatTimeInput(Number.NaN), "");
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
