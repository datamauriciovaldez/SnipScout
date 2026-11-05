// Clip preview: plays [start, end) of the source with an approximate word-by-word subtitle overlay.
// The browser draws text differently from libass; the exported video is the source of truth.
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button } from "../components.js";
import { fmt, t } from "../i18n.js";

const GROUP = 4;

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

function subtitleAt(words, time, style) {
  // Active word = last word that has started; it stays until the next one starts (or 0.4 s after its end).
  let k = -1;
  for (let i = 0; i < words.length && words[i].start <= time; i++) k = i;
  if (k < 0) return null;
  const next = words[k + 1];
  if (!next && time > words[k].end + 0.4) return null;
  if (next && next.start - words[k].end > 0.5 && time > words[k].end + 0.4) return null; // pause: hide
  const g0 = Math.floor(k / GROUP) * GROUP;
  const group = words.slice(g0, g0 + GROUP);
  const upper = style === "bold-pop";
  return group.map((w, j) => {
    const text = upper ? w.text.toUpperCase() : w.text;
    const lit = g0 + j === k || (style === "karaoke" && g0 + j < k);
    return lit && style !== "classic" && style !== "minimal" ? html`<mark>${text}</mark> ` : `${text} `;
  });
}

export function ClipPlayer({ projectId, hasVideo, start, end, words, style, big, seek, onTime: report }) {
  const video = useRef(null);
  const [time, setTime] = useState(start);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => { // moving the in-point shows its frame; moving the out-point doesn't jump
    const v = video.current;
    if (v && v.readyState >= 1) v.currentTime = start;
    setTime(start);
  }, [start]);
  useEffect(() => { // external seek from the timeline: { t, n } (n changes on every request)
    if (!seek) return;
    const v = video.current;
    if (v && v.readyState >= 1) v.currentTime = seek.t;
    setTime(seek.t);
  }, [seek && seek.n]);

  const toggle = () => {
    const v = video.current; if (!v) return;
    if (v.paused) { if (v.currentTime < start || v.currentTime >= end) v.currentTime = start; v.play().catch(() => setFailed(true)); }
    else v.pause();
  };
  useEffect(() => {
    const onKey = (e) => {
      if (e.code !== "Space" || /INPUT|TEXTAREA|SELECT|BUTTON/.test(e.target.tagName) || e.target.isContentEditable) return;
      e.preventDefault(); toggle();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [start, end]);

  const onTime = (e) => {
    const v = e.currentTarget; // not the ref: events can arrive while the component unmounts
    if (!v) return;
    if (!v.paused && v.currentTime >= end) { v.pause(); v.currentTime = start; } // loop only while playing
    setTime(v.currentTime);
    if (report) report(v.currentTime);
  };
  const sub = subtitleAt(words, time, style);
  const frac = Math.max(0, Math.min(1, (time - start) / Math.max(0.1, end - start)));
  const shown = Math.max(0, Math.min(end - start, time - start));
  return html`<div class=${`player${big ? " player--big" : ""}`}>
    <div class="thumb thumb--preview player__screen">
      ${hasVideo && !failed
        ? html`<video ref=${video} src=${api.mediaUrl(projectId)} preload="metadata" playsinline
            onLoadedMetadata=${(e) => { e.currentTarget.currentTime = start; }} onTimeUpdate=${onTime}
            onPlay=${() => setPlaying(true)} onPause=${() => setPlaying(false)} onError=${() => setFailed(true)}></video>`
        : html`<div class="player__note">${failed ? t("player.cannot_play") : t("player.audio_only")}</div>`}
      <div class="thumb__shade"></div>
      ${sub && html`<div class="subtitle">${sub}</div>`}
    </div>
    <div class="player__bar">
      <${Button} variant="primary" icon=${playing ? "pause" : "play"} aria-label=${playing ? t("player.pause") : t("player.play")} onClick=${toggle} />
      <span class="mono">${fmt.duration(shown)} / ${fmt.duration(end - start)}</span>
      <div class="progress" style="flex:1"><div class="progress__fill" style=${`--p:${frac}`}></div></div>
    </div>
  </div>`;
}
