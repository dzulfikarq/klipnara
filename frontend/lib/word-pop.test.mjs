import assert from "node:assert/strict";
import test from "node:test";
import { activeWordIndexAt, joinWordText, validWordAlignment } from "./word-pop.mjs";

const segment = {
  start: 0,
  end: 2,
  text: "I'm gonna build rumah!",
  word_alignment_reviewed: true,
  words: [
    { id: "1", text: "I'm", start: 0, end: 0.2 },
    { id: "2", text: "gonna", start: 0.25, end: 0.55 },
    { id: "3", text: "build", start: 0.8, end: 1.1 },
    { id: "4", text: "rumah!", start: 1.2, end: 1.6 },
  ],
};

test("word alignment accepts punctuation, Indonesian/English text, and silence gaps", () => {
  assert.equal(joinWordText(segment.words), segment.text);
  assert.equal(validWordAlignment(segment), true);
  assert.equal(activeWordIndexAt(segment.words, 0.6), -1);
  assert.equal(activeWordIndexAt(segment.words, 1), 2);
  assert.equal(activeWordIndexAt(segment.words, 0.25), 1);
});

test("word alignment rejects missing, overlapping, out-of-cue, and unreviewed timing", () => {
  assert.equal(validWordAlignment({ ...segment, words: undefined }), false);
  assert.equal(validWordAlignment({ ...segment, word_alignment_reviewed: false }), false);
  assert.equal(validWordAlignment({ ...segment, words: [{ ...segment.words[0], end: null }] }), false);
  assert.equal(validWordAlignment({ ...segment, words: [segment.words[0], { ...segment.words[1], start: 0.1 }] }), false);
  assert.equal(validWordAlignment({ ...segment, words: [segment.words[0], { ...segment.words[1], text: "different" }, ...segment.words.slice(2)] }), false);
});

test("word join preserves opening and closing punctuation", () => {
  assert.equal(joinWordText([{ text: "(hello" }, { text: "," }, { text: "world!" }, { text: ")" }]), "(hello, world!)");
  assert.equal(joinWordText([{ text: " I'm " }, { text: " gonna " }]), "I'm gonna");
  assert.equal(validWordAlignment({ ...segment, start: Number.NaN }), false);
});
