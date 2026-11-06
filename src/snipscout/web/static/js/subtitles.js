// Pure helpers for the in-app subtitle preview (no DOM, no Preact): unit-tested with `node --test`.

export const GROUP = 4; // words per on-screen line in the preview

/** Words inside the clip (by midpoint) with overrides applied; deleted words are dropped. */
export function clipWords(words, start, end, overrides = {}) {
  const out = [];
  words.forEach((w, i) => {
    const mid = (w.start + w.end) / 2;
    if (mid < start || mid > end) return;
    const text = (overrides[i] !== undefined ? overrides[i] : w.text).trim();
    if (text) out.push({ ...w, text, index: i });
  });
  return out;
}

/** Index of the word to highlight at `time`, or -1 when nothing should show (before speech or in a pause).
 *  The active word is the last one that started; it stays until the next starts, or 0.4 s after it ends
 *  when a pause (> 0.5 s) follows. */
export function activeWord(words, time) {
  let k = -1;
  for (let i = 0; i < words.length && words[i].start <= time; i++) k = i;
  if (k < 0) return -1;
  const next = words[k + 1];
  if (!next && time > words[k].end + 0.4) return -1;
  if (next && next.start - words[k].end > 0.5 && time > words[k].end + 0.4) return -1;
  return k;
}

/** The line containing word `k`, with each word marked lit/unlit for a subtitle style. */
export function lineFor(words, k, style) {
  const g0 = Math.floor(k / GROUP) * GROUP;
  const upper = style === "bold-pop";
  return words.slice(g0, g0 + GROUP).map((w, j) => ({
    text: upper ? w.text.toUpperCase() : w.text,
    lit: style !== "classic" && style !== "minimal" && (g0 + j === k || (style === "karaoke" && g0 + j < k)),
  }));
}
