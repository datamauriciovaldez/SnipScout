// Pure framing helpers: what part of the source the export keeps, expressed for the <video> preview.

/** Source size as the viewer sees it (after rotation), like MediaInfo.display_size. */
export function displaySize(source) {
  if (!source || !source.width || !source.height) return [16, 9];
  return source.rotation === 90 || source.rotation === 270 ? [source.height, source.width] : [source.width, source.height];
}

/** Output width/height ratio for a project aspect ("9:16", "1:1", "16:9", "original"). */
export function outputRatio(aspect, srcW, srcH) {
  if (aspect === "9:16") return 9 / 16;
  if (aspect === "1:1") return 1;
  if (aspect === "16:9") return 16 / 9;
  return srcW && srcH ? srcW / srcH : 9 / 16;
}

/** CSS object-position x (0..1) that shows the same window as the export's crop centred on `fx`
 *  (fraction of the source width, clamped inside the frame like ffmpeg's crop). */
export function objectPositionX(fx, srcRatio, outRatio) {
  const k = srcRatio / outRatio; // source width / crop width after scaling to cover
  if (k <= 1.0001) return 0.5; // nothing is cropped horizontally
  return Math.min(1, Math.max(0, (fx * k - 0.5) / (k - 1)));
}

/** Crop centre the export will use for a clip, or null for the centred crop. */
export function effectiveFocus(framing, focusX, autoFocusX) {
  if (framing === "manual" && focusX != null) return focusX;
  if (framing === "auto" && autoFocusX != null) return autoFocusX;
  return null;
}
