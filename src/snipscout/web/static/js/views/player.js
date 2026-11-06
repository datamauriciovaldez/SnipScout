// Clip preview: plays [start, end) of the source with an approximate word-by-word subtitle overlay.
// The browser draws text differently from libass; the exported video is the source of truth.
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button } from "../components.js";
import { fmt, t } from "../i18n.js";
import { activeWord, clipWords, lineFor } from "../subtitles.js";

export { clipWords }; // re-exported for the views that already import it from here

function subtitleAt(words, time, style) {
  const k = activeWord(words, time);
  if (k < 0) return null;
  return lineFor(words, k, style).map((w) => (w.lit ? html`<mark>${w.text}</mark> ` : `${w.text} `));
}

/** `ratio`: output width/height (screen shape); `posX`: CSS object-position x (0..1) matching the export crop. */
export function ClipPlayer({ projectId, hasVideo, start, end, words, style, big, seek, onTime: report, ratio = 9 / 16, posX = 0.5 }) {
  const video = useRef(null);
  const [time, setTime] = useState(start);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [variant, setVariant] = useState("original"); // "proxy" once a playable copy exists
  const [preparing, setPreparing] = useState(null); // 0..1 while the playable copy is encoded

  // The window can't play this file (e.g. HEVC on Windows, H.264 on Qt): ask for a WebM copy and switch to it.
  const fallBack = async () => {
    if (variant === "proxy") { setFailed(true); return; }
    setPreparing(0);
    try {
      let st = await api.makeProxy(projectId);
      while (st.state === "working") {
        setPreparing(st.progress || 0);
        await new Promise((r) => setTimeout(r, 1500));
        st = await api.proxyStatus(projectId);
      }
      if (st.state === "ready") { setVariant("proxy"); setPreparing(null); return; }
    } catch (e) { /* fall through to the message */ }
    setPreparing(null); setFailed(true);
  };

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
    if (v.paused) { if (v.currentTime < start || v.currentTime >= end) v.currentTime = start; v.play().catch((e) => { if (e && e.name === "NotSupportedError") fallBack(); }); }
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
    <div class="thumb thumb--preview player__screen" style=${Math.abs(ratio - 9 / 16) > 0.01 ? `height:auto;aspect-ratio:${ratio}` : undefined}>
      ${hasVideo && !failed && preparing === null
        ? html`<video ref=${video} key=${variant} src=${api.mediaUrl(projectId, variant)} preload="metadata" playsinline
            style=${`object-position:${(posX * 100).toFixed(2)}% 50%`}
            onLoadedMetadata=${(e) => { // no picture size = codec not supported here (Chromium plays HEVC audio only)
              if (!e.currentTarget.videoWidth) { fallBack(); return; } e.currentTarget.currentTime = start; }} onTimeUpdate=${onTime}
            onPlay=${() => setPlaying(true)} onPause=${() => setPlaying(false)} onError=${fallBack}></video>`
        : html`<div class="player__note" role="status">${preparing !== null
            ? t("player.preparing", { pct: Math.floor(preparing * 100) })
            : failed ? t("player.cannot_play") : t("player.audio_only")}</div>`}
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
