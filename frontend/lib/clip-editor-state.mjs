export function clipEditorStatus({ edit, saved, saving = false, saveFailure = "", rendered = false, clipStatus = "" }) {
  const snapshot = edit ? JSON.stringify(edit) : "";
  const dirty = Boolean(snapshot && saved && snapshot !== saved);
  const draft = saving ? "saving" : dirty ? snapshot === saveFailure ? "failed" : "unsaved" : "saved";
  const renderRequired = Boolean(dirty || !rendered || clipStatus === "needs_render");
  return { draft, dirty, renderRequired, renderOutdated: Boolean(rendered && renderRequired) };
}
