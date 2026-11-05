import { test } from "node:test";
import assert from "node:assert/strict";
import { createHistory, nearest, record, redo, undo, wordStep, sameDraft } from "../../src/snipscout/web/static/js/editing.js";

test("undo/redo walks snapshots and a new change clears redo", () => {
  const h = createHistory();
  let cur = { end: 10 };
  record(h, cur); cur = { end: 12 };
  record(h, cur); cur = { end: 15 };
  cur = undo(h, cur); assert.deepEqual(cur, { end: 12 });
  cur = undo(h, cur); assert.deepEqual(cur, { end: 10 });
  assert.equal(undo(h, cur), null);
  cur = redo(h, cur); assert.deepEqual(cur, { end: 12 });
  record(h, cur); cur = { end: 20 };
  assert.equal(redo(h, cur), null);
});

test("history is bounded", () => {
  const h = createHistory(3);
  for (let i = 0; i < 10; i++) record(h, { i });
  assert.equal(h.past.length, 3);
  assert.deepEqual(h.past[0], { i: 7 });
});

test("nearest boundary and word stepping", () => {
  assert.equal(nearest([1, 5, 9], 6.9), 5);
  assert.equal(nearest([1, 5, 9], 7.1), 9);
  const words = [{ start: 0.5 }, { start: 1.0 }, { start: 2.2 }];
  assert.equal(wordStep(words, 1.0, 1), 2.2);
  assert.equal(wordStep(words, 1.0, -1), 0.5);
  assert.equal(wordStep(words, 3, 1), 3);
  assert.equal(wordStep(words, 0.4, -1), 0);
  assert.ok(sameDraft({ a: 1, o: { 2: "x" } }, { a: 1, o: { 2: "x" } }));
});
