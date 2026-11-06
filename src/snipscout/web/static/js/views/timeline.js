// Canvas timeline: server waveform for the visible range, draggable in/out handles that snap to
// sentence boundaries (hold Alt for free movement), click/drag to scrub, Ctrl+wheel to zoom.
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button } from "../components.js";
import { fmt, t } from "../i18n.js";

const HEIGHT = 96;
const RULER = 20;
const HANDLE_PX = 9; // grab distance
const MIN_CLIP = 1.0;
const MIN_VIEW = 4.0;

function tokens() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  return { in: v("--wave-in"), out: v("--wave-out"), accent: v("--accent"), text: v("--text"), faint: v("--text-3"),
           region: v("--selected"), line: v("--line"), mono: v("--font-mono") };
}

function niceStep(seconds, maxTicks = 8) {
  for (const s of [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]) if (seconds / s <= maxTicks) return s;
  return 7200;
}

export function Timeline({ projectId, duration, start, end, time, sentences, onChange, onCommit, onSeek }) {
  const canvas = useRef(null);
  const wrap = useRef(null);
  const [width, setWidth] = useState(800);
  const initPad = Math.max((end - start) * 0.25, 3);
  const [view, setView] = useState(() => clampView(start - initPad, end + initPad, duration));
  const [peaks, setPeaks] = useState({ view: null, data: [] });
  const [themeTick, setThemeTick] = useState(0);
  const drag = useRef(null);

  // Track the element width (responsive) and theme changes (repaint with new token colours).
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(200, Math.floor(e.contentRect.width))));
    ro.observe(wrap.current);
    const mo = new MutationObserver(() => setThemeTick((n) => n + 1));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onMq = () => setThemeTick((n) => n + 1);
    mq.addEventListener("change", onMq);
    return () => { ro.disconnect(); mo.disconnect(); mq.removeEventListener("change", onMq); };
  }, []);

  // Fetch peaks for the visible range at one value per CSS pixel (debounced while zooming/panning).
  useEffect(() => {
    const id = setTimeout(() => {
      api.waveform(projectId, width, view[0], view[1]).then((w) => setPeaks({ view: [w.start, w.end], data: w.peaks })).catch(() => null);
    }, 120);
    return () => clearTimeout(id);
  }, [projectId, width, view[0], view[1]]);

  const x = (s) => ((s - view[0]) / (view[1] - view[0])) * width;
  const s = (px) => view[0] + (px / width) * (view[1] - view[0]);

  // Paint.
  useEffect(() => {
    const c = canvas.current; if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = width * dpr; c.height = (HEIGHT + RULER) * dpr;
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, HEIGHT + RULER);
    const k = tokens();
    // Region.
    g.fillStyle = k.region;
    g.fillRect(x(start), 0, x(end) - x(start), HEIGHT);
    // Bars (peaks may belong to the previous view while the new ones load: map by time).
    if (peaks.view && peaks.data.length) {
      const [p0, p1] = peaks.view, n = peaks.data.length, bw = (p1 - p0) / n;
      const step = Math.max(2, Math.round(width / 260)); // ~3px bars with gaps
      for (let px = 0; px < width; px += step) {
        const tt = s(px + step / 2);
        const i = Math.floor((tt - p0) / bw);
        if (i < 0 || i >= n) continue;
        const h = Math.max(2, peaks.data[i] * (HEIGHT - 8));
        g.fillStyle = tt >= start && tt <= end ? k.in : k.out;
        g.fillRect(px, (HEIGHT - h) / 2, Math.max(1, step - 1), h);
      }
    }
    // Handles.
    g.fillStyle = k.accent;
    for (const [pos, side] of [[x(start), -1], [x(end), 1]]) {
      g.fillRect(pos - 1, 0, 2, HEIGHT);
      g.fillRect(side < 0 ? pos - 8 : pos - 2, 0, 10, 6);
      g.fillRect(side < 0 ? pos - 8 : pos - 2, HEIGHT - 6, 10, 6);
    }
    // Playhead.
    if (time >= view[0] && time <= view[1]) { g.fillStyle = k.text; g.fillRect(x(time) - 0.5, 0, 1, HEIGHT); }
    // Ruler.
    g.fillStyle = k.line; g.fillRect(0, HEIGHT, width, 1);
    g.fillStyle = k.faint; g.font = `11px ${k.mono}`; g.textBaseline = "top";
    const st = niceStep(view[1] - view[0], Math.max(2, Math.min(8, Math.floor(width / 64)))); // labels never touch
    for (let tt = Math.ceil(view[0] / st) * st; tt <= view[1]; tt += st) {
      const px = x(tt);
      g.fillRect(px, HEIGHT, 1, 4);
      const label = fmt.duration(tt);
      if (px + 3 + g.measureText(label).width <= width) g.fillText(label, px + 3, HEIGHT + 6);
    }
  }, [width, view, peaks, start, end, time, themeTick]);

  // --- interaction ------------------------------------------------------------------------------
  const snapTo = (sec, kind, free) => {
    if (free) return sec;
    const list = sentences.map((x2) => (kind === "start" ? Math.max(0, x2.start - 0.15) : Math.min(duration, x2.end + 0.15)));
    // Always the nearest sentence boundary, so a clip never starts or ends mid-sentence.
    let best = sec, bestD = Infinity;
    for (const v of list) { const d = Math.abs(v - sec); if (d < bestD) { best = v; bestD = d; } }
    return Math.round(best * 1000) / 1000;
  };
  const local = (e) => e.clientX - canvas.current.getBoundingClientRect().left;
  const onDown = (e) => {
    const px = local(e);
    const which = Math.abs(px - x(start)) <= HANDLE_PX ? "start" : Math.abs(px - x(end)) <= HANDLE_PX ? "end" : "seek";
    drag.current = { which };
    canvas.current.setPointerCapture(e.pointerId);
    if (which === "seek") onSeek(Math.max(0, Math.min(duration, s(px))));
  };
  const onMove = (e) => {
    const px = local(e);
    if (!drag.current) {
      const near = Math.abs(px - x(start)) <= HANDLE_PX || Math.abs(px - x(end)) <= HANDLE_PX;
      canvas.current.style.cursor = near ? "ew-resize" : "text";
      return;
    }
    const sec = Math.max(0, Math.min(duration, s(px)));
    if (drag.current.which === "seek") { onSeek(sec); return; }
    const snapped = snapTo(sec, drag.current.which, e.altKey);
    if (drag.current.which === "start") onChange({ start: Math.min(snapped, end - MIN_CLIP), end });
    else onChange({ start, end: Math.max(snapped, start + MIN_CLIP) });
  };
  const onUp = () => { if (drag.current && drag.current.which !== "seek") onCommit && onCommit(); drag.current = null; };
  const zoom = (factor, centerPx = width / 2) => {
    const c = s(centerPx), span = Math.max(MIN_VIEW, Math.min(duration, (view[1] - view[0]) * factor));
    const left = c - (centerPx / width) * span;
    setView(clampView(left, left + span, duration));
  };
  const onWheel = (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) zoom(e.deltaY > 0 ? 1.25 : 0.8, local(e));
    else {
      const shift = ((e.deltaX || e.deltaY) / width) * (view[1] - view[0]);
      setView(clampView(view[0] + shift, view[1] + shift, duration));
    }
  };
  useEffect(() => {
    const c = canvas.current;
    c.addEventListener("wheel", onWheel, { passive: false }); // passive:false so preventDefault works
    return () => c.removeEventListener("wheel", onWheel);
  });
  const fit = () => { const pad = Math.max((end - start) * 0.25, 3); setView(clampView(start - pad, end + pad, duration)); };

  return html`<div class="tl2">
    <div class="tl2__bar">
      <span class="label">${t("editor.timeline_range", { a: fmt.timecode(view[0]), b: fmt.timecode(view[1]) })}</span>
      <span class="tl2__zoom">
        <${Button} variant="ghost" icon="minus" aria-label=${t("timeline.zoom_out")} onClick=${() => zoom(1.5)} />
        <${Button} variant="ghost" icon="plus" aria-label=${t("timeline.zoom_in")} onClick=${() => zoom(1 / 1.5)} />
        <${Button} variant="ghost" onClick=${fit}>${t("timeline.fit")}<//>
      </span>
    </div>
    <div class="tl2__canvas" ref=${wrap}>
      <canvas ref=${canvas} style=${`width:${width}px;height:${HEIGHT + RULER}px`} role="img"
        aria-label=${t("timeline.label", { a: fmt.precise(start), b: fmt.precise(end) })}
        onPointerDown=${onDown} onPointerMove=${onMove} onPointerUp=${onUp} onPointerCancel=${onUp}></canvas>
    </div>
    <p class="faint tl2__hint">${t("timeline.hint")}</p>
  </div>`;
}

function clampView(a, b, duration) {
  let span = Math.min(Math.max(MIN_VIEW, b - a), duration);
  let left = Math.max(0, Math.min(a, duration - span));
  return [left, left + span];
}
