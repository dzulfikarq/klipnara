export function joinWordText(words) {
  return words.reduce((text, word) => {
    const token = word.text.trim();
    return `${text && token && !/^[,.;:!?%)\]}]/.test(token) && !"([{“‘¿¡".includes(text.at(-1) || "") ? " " : ""}${token}`;
  }, "");
}

export function validWordAlignment(segment) {
  if (!segment || typeof segment.text !== "string") return false;
  const words = segment.words || [];
  if (!Number.isFinite(segment.start) || !Number.isFinite(segment.end) || segment.start >= segment.end
    || !words.length || segment.word_alignment_reviewed !== true
    || !words.every((word) => typeof word?.text === "string")
    || joinWordText(words).replace(/\s+/g, " ").trim() !== segment.text.replace(/\s+/g, " ").trim()) return false;
  let previousEnd = segment.start;
  for (const word of words) {
    if (!word.text?.trim() || !Number.isFinite(word.start) || !Number.isFinite(word.end)
      || word.start < segment.start || word.start >= word.end || word.end > segment.end || word.start < previousEnd) return false;
    previousEnd = word.end;
  }
  return true;
}

export function activeWordIndexAt(words, time) {
  return words.findIndex((word) => Number.isFinite(word.start) && Number.isFinite(word.end) && word.start <= time && word.end > time);
}
