// Pure editing helpers (no DOM, no Preact) — unit-tested with `node --test` (tests/js/).

/** Undo/redo history of immutable snapshots. */
export function createHistory(limit = 100) {
  return { past: [], future: [], limit };
}

/** Remember `previous` before a change; a new change clears the redo stack. */
export function record(h, previous) {
  h.past.push(previous);
  if (h.past.length > h.limit) h.past.shift();
  h.future.length = 0;
}

/** Returns the snapshot to restore, or null when there is nothing to undo. */
export function undo(h, current) {
  if (!h.past.length) return null;
  h.future.push(current);
  return h.past.pop();
}

export function redo(h, current) {
  if (!h.future.length) return null;
  h.past.push(current);
  return h.future.pop();
}

/** Nearest value in `list` to `t` (sentence boundaries for I/O and the handles). */
export function nearest(list, t) {
  let best = t, d = Infinity;
  for (const v of list) if (Math.abs(v - t) < d) { best = v; d = Math.abs(v - t); }
  return best;
}

/** Start time of the next (dir = 1) or previous (dir = -1) word relative to `t`. */
export function wordStep(words, t, dir) {
  if (dir > 0) {
    const w = words.find((x) => x.start > t + 0.01);
    return w ? w.start : t;
  }
  for (let i = words.length - 1; i >= 0; i--) if (words[i].start < t - 0.05) return words[i].start;
  return 0;
}

/** Same snapshot? (drafts are small plain objects) */
export const sameDraft = (a, b) => JSON.stringify(a) === JSON.stringify(b);
