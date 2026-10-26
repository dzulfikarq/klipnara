import assert from "node:assert/strict";
import test from "node:test";
import { createSerializedSaveQueue } from "./mood-draft.mjs";
import {
  duplicateSegment,
  mergeSegment,
  musicPlaybackSpan,
  resetSegmentTimings,
  semanticSegments,
  snapTimelineTime,
  splitSegment,
  timeAtPosition,
  updateSegmentTiming,
} from "./mood-timeline.mjs";

const segments = [
  { id: "a", text: "Awal yang tenang", start: 0, end: 2, animation: "fade_up", animation_duration: 0.4 },
  { id: "b", text: "Langkah berikutnya", start: 3, end: 5, animation: "fade_up", animation_duration: 0.4 },
  { id: "c", text: "Akhir yang baik", start: 6, end: 8, animation: "fade_up", animation_duration: 0.4 },
];

test("timeline maps pointer coordinates to bounded fractional seconds", () => {
  assert.equal(timeAtPosition(150, 100, 20, 10), 2.5);
  assert.equal(timeAtPosition(20, 100, 20, 10), 0);
  assert.equal(timeAtPosition(500, 100, 20, 10), 10);
  assert.equal(snapTimelineTime(2.94, [3]), 3);
});

test("segment move and resize snap without ripple or overlap", () => {
  const moved = updateSegmentTiming(segments, "b", "move", -2, 10, { start: 3, end: 5 });
  assert.deepEqual(moved.segments.map(({ start, end }) => [start, end]), [[0, 2], [2, 4], [6, 8]]);
  const resized = updateSegmentTiming(segments, "b", "resize-end", 2, 10, { start: 3, end: 5 });
  assert.deepEqual(resized.segments.map(({ start, end }) => [start, end]), [[0, 2], [3, 6], [6, 8]]);
  assert.deepEqual(segments.map(({ start, end }) => [start, end]), [[0, 2], [3, 5], [6, 8]]);
});

test("split, merge, duplicate, and reset preserve text and valid timing", () => {
  const source = [{ ...segments[0], text: "Kita tumbuh perlahan, lalu belajar menerima perubahan bersama.", end: 4 }];
  const split = splitSegment(source, "a", 10);
  assert.equal(split.length, 2);
  assert.equal(split[0].start, 0);
  assert.equal(split[0].end, split[1].start);
  assert.equal(split[1].end, 4);
  assert.equal(split.map((item) => item.text).join(" "), source[0].text);
  const merged = mergeSegment(split, split[1].id, -1);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].text, source[0].text);
  const duplicate = duplicateSegment(segments, "b", 10);
  assert.equal(duplicate.length, 4);
  assert.equal(duplicate[2].text, "Langkah berikutnya");
  assert.equal(duplicate[2].end, segments[2].start);
  const reset = resetSegmentTimings(segments, 10);
  assert.equal(reset[0].start, 0);
  assert.equal(reset.at(-1).end, 10);
  assert.ok(reset.every((item) => item.end - item.start >= 0.5));
});

test("semantic segmentation keeps Indonesian openers and connector phrases together", () => {
  const text = "Terkadang, kita butuh jeda agar pikiran tenang, lalu hati kembali jernih. Karena kita bertahan, harapan tumbuh.";
  const output = semanticSegments(text, 10);
  const normalized = (value) => (value.match(/[\p{L}\p{N}]+/gu) || []).join(" ").toLocaleLowerCase();
  assert.equal(normalized(output.map((item) => item.text).join(" ")), normalized(text));
  assert.ok(output[0].text.toLocaleLowerCase().startsWith("terkadang,"));
  assert.ok(output.every((item) => !/^(dan|lalu|karena|agar)\b/iu.test(item.text)));
});

test("music timeline accounts for offset, trim, loop, and missing asset", () => {
  const music = { asset_id: "music-1", offset: 2, trim_start: 5, trim_end: 9, loop: false };
  assert.equal(musicPlaybackSpan(music, 10, 20), 4);
  assert.equal(musicPlaybackSpan({ ...music, loop: true }, 10, 20), 8);
  assert.equal(musicPlaybackSpan({ ...music, trim_end: 5.02 }, 10, 20), 0);
  assert.equal(musicPlaybackSpan({ ...music, asset_id: null }, 10, 20), 0);
});

test("draft save queue waits for in-flight writes and recovers after a failed save", async () => {
  const enqueue = createSerializedSaveQueue();
  const calls = [];
  let releaseFirst;
  let startedFirst;
  const firstStarted = new Promise((resolve) => { startedFirst = resolve; });
  const first = enqueue(() => new Promise((resolve) => {
    calls.push("revision-1");
    releaseFirst = resolve;
    startedFirst();
  }));
  const second = enqueue(() => { calls.push("revision-2"); });
  await firstStarted;
  assert.deepEqual(calls, ["revision-1"]);
  releaseFirst();
  await Promise.all([first, second]);
  assert.deepEqual(calls, ["revision-1", "revision-2"]);

  await assert.rejects(enqueue(() => Promise.reject(new Error("save failed"))));
  await enqueue(() => { calls.push("revision-3"); });
  assert.equal(calls.at(-1), "revision-3");
});
