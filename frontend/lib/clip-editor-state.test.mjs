import assert from "node:assert/strict";
import test from "node:test";
import { clipEditorStatus } from "./clip-editor-state.mjs";

const savedEdit = { subtitle_color: "#fff", crop_x: 50 };

test("draft state distinguishes saved, pending, saving, and failed snapshots", () => {
  const saved = JSON.stringify(savedEdit);
  assert.deepEqual(clipEditorStatus({ edit: savedEdit, saved, rendered: true }), { draft: "saved", dirty: false, renderRequired: false, renderOutdated: false });
  const changed = { ...savedEdit, subtitle_color: "#000" };
  assert.equal(clipEditorStatus({ edit: changed, saved }).draft, "unsaved");
  assert.equal(clipEditorStatus({ edit: changed, saved, saving: true }).draft, "saving");
  assert.equal(clipEditorStatus({ edit: changed, saved, saveFailure: JSON.stringify(changed) }).draft, "failed");
  assert.equal(clipEditorStatus({ edit: changed, saved, saveFailure: JSON.stringify(savedEdit) }).draft, "unsaved");
});

test("render becomes outdated only when saved output no longer matches edit", () => {
  const saved = JSON.stringify(savedEdit);
  assert.equal(clipEditorStatus({ edit: savedEdit, saved, rendered: true, clipStatus: "completed" }).renderOutdated, false);
  assert.equal(clipEditorStatus({ edit: { ...savedEdit, crop_x: 30 }, saved, rendered: true }).renderOutdated, true);
  assert.equal(clipEditorStatus({ edit: savedEdit, saved, rendered: true, clipStatus: "needs_render" }).renderOutdated, true);
  assert.equal(clipEditorStatus({ edit: savedEdit, saved, rendered: false, clipStatus: "needs_render" }).renderOutdated, false);
  assert.equal(clipEditorStatus({ edit: savedEdit, saved, rendered: false }).renderRequired, true);
});
