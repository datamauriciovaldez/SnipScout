import { test } from "node:test";
import assert from "node:assert/strict";
import { displaySize, effectiveFocus, objectPositionX, outputRatio, pathAt, previewPosition } from "../../src/snipscout/web/static/js/framing.js";

test("output ratios", () => {
  assert.equal(outputRatio("9:16"), 9 / 16);
  assert.equal(outputRatio("1:1"), 1);
  assert.equal(outputRatio("original", 1920, 1080), 1920 / 1080);
});

test("object-position matches the export crop (16:9 source → 9:16)", () => {
  const k = (16 / 9) / (9 / 16); // ≈ 3.16: the crop is ~32 % of the width
  assert.equal(objectPositionX(0.5, 16 / 9, 9 / 16), 0.5); // centre stays centre
  assert.equal(objectPositionX(0.0, 16 / 9, 9 / 16), 0); // clamped to the left edge
  assert.equal(objectPositionX(1.0, 16 / 9, 9 / 16), 1); // clamped to the right edge
  const p = objectPositionX(0.3, 16 / 9, 9 / 16);
  // Crop left edge in source-width units: ffmpeg x = fx*iw - W/2 ; CSS shows offset p*(iw - W).
  assert.ok(Math.abs(p * (k - 1) - (0.3 * k - 0.5)) < 1e-9);
  assert.equal(objectPositionX(0.9, 9 / 16, 9 / 16), 0.5); // same shape: nothing cropped
});

test("effective focus per framing", () => {
  assert.equal(effectiveFocus("manual", 0.2, 0.7), 0.2);
  assert.equal(effectiveFocus("auto", null, 0.7), 0.7);
  assert.equal(effectiveFocus("auto", 0.2, null), null);
  assert.equal(effectiveFocus("center", 0.2, 0.7), null);
});

test("display size follows rotation", () => {
  assert.deepEqual(displaySize({ width: 1920, height: 1080, rotation: 90 }), [1080, 1920]);
  assert.deepEqual(displaySize({ width: 1920, height: 1080, rotation: 0 }), [1920, 1080]);
  assert.deepEqual(displaySize({}), [16, 9]);
});

test("pan paths for the preview", () => {
  const path = [[0, 0.2], [10, 0.6]];
  assert.equal(pathAt(path, -1), 0.2);
  assert.ok(Math.abs(pathAt(path, 5) - 0.4) < 1e-9);
  assert.equal(pathAt(path, 20), 0.6);
  const info = { crops: true, auto_focus: [0.4, 0.4], auto_path: path };
  const auto = previewPosition("auto", null, info, 16 / 9, 9 / 16);
  assert.equal(auto.posPath.length, 2);
  assert.equal(auto.posPath[0][1], objectPositionX(0.2, 16 / 9, 9 / 16));
  const manual = previewPosition("manual", 0.3, info, 16 / 9, 9 / 16);
  assert.equal(manual.posPath, null);
  assert.equal(manual.posX, objectPositionX(0.3, 16 / 9, 9 / 16));
  assert.equal(previewPosition("center", 0.3, info, 16 / 9, 9 / 16).posX, 0.5);
});
