import { test } from "node:test";
import assert from "node:assert/strict";
import { activeWord, clipWords, lineFor } from "../../src/snipscout/web/static/js/subtitles.js";

const W = (text, start, end) => ({ text, start, end });
const words = [W("Hola", 0, 0.4), W("a", 0.5, 0.6), W("todos", 0.7, 1.1), W("hoy", 2.5, 2.8), W("vamos", 2.9, 3.2)];

test("clipWords keeps words by midpoint, applies overrides and drops deleted ones", () => {
  const cw = clipWords(words, 0.45, 3.0, { 2: "TODOS", 3: "  " });
  assert.deepEqual(cw.map((w) => [w.text, w.index]), [["a", 1], ["TODOS", 2]]);
});

test("activeWord follows speech and hides in long pauses", () => {
  assert.equal(activeWord(words, -1), -1);
  assert.equal(activeWord(words, 0.2), 0);
  assert.equal(activeWord(words, 0.45), 0); // between words: last started word stays
  assert.equal(activeWord(words, 1.3), 2); // just after "todos", within 0.4 s
  assert.equal(activeWord(words, 2.0), -1); // pause of 1.4 s before "hoy"
  assert.equal(activeWord(words, 3.0), 4);
  assert.equal(activeWord(words, 3.7), -1); // after the last word
});

test("lineFor groups four words and lights them per style", () => {
  assert.deepEqual(lineFor(words, 2, "bold-pop").map((w) => [w.text, w.lit]),
    [["HOLA", false], ["A", false], ["TODOS", true], ["HOY", false]]);
  assert.deepEqual(lineFor(words, 2, "karaoke").map((w) => w.lit), [true, true, true, false]);
  assert.ok(lineFor(words, 2, "classic").every((w) => !w.lit));
  assert.deepEqual(lineFor(words, 4, "minimal").map((w) => w.text), ["vamos"]);
});
