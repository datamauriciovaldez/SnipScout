// Simple clip editor (v0.1): in/out snapped to sentences, title, per-word subtitle corrections, style.
// The draggable timeline, undo and autosave arrive in v0.2 (E1–E3).
import { useEffect, useMemo, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button, ErrorNotice, Modal, Segmented, toast } from "../components.js";
import { fmt, t } from "../i18n.js";
import { navigate } from "../router.js";
import { useTopbar } from "../store.js";
import { ClipPlayer, clipWords } from "./player.js";
import { Timeline } from "./timeline.js";

const STYLES = ["bold-pop", "classic", "karaoke", "minimal"];

/** "00:14:32.4", "14:32.4" or "872.4" → seconds; null when invalid. */
export function parseTime(text) {
  const parts = String(text).trim().replace(",", ".").split(":");
  if (!parts.length || parts.length > 3 || parts.some((p) => p === "" || isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

export function Editor({ id, cid }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState(null);
  const [editing, setEditing] = useState(null); // word index being edited
  const [saving, setSaving] = useState(false);
  const [playhead, setPlayhead] = useState(0);
  const [seek, setSeek] = useState(null); // { t, n } → player
  const [frame, setFrame] = useState(null); // { url, at } real preview frame
  const [framing, setFraming] = useState(false);

  useEffect(() => {
    Promise.all([api.project(id), api.clips(id), api.transcript(id)])
      .then(([project, clips, tr]) => {
        const clip = clips.clips.find((c) => c.id === cid);
        if (!clip) throw Object.assign(new Error("clip"), { code: "project_not_found" });
        setData({ project, clip, words: tr.words, sentences: tr.sentences });
        setDraft({ start: clip.start, end: clip.end, title: clip.title, style: clip.subtitle_style || project.settings.subtitle_style,
                   overrides: { ...clip.text_overrides } });
      })
      .catch((e) => setError({ code: e.code || "unknown", message: e.message }));
  }, [id, cid]);

  const dirty = data && draft && (draft.start !== data.clip.start || draft.end !== data.clip.end || draft.title !== data.clip.title
    || draft.style !== (data.clip.subtitle_style || data.project.settings.subtitle_style)
    || JSON.stringify(draft.overrides) !== JSON.stringify(data.clip.text_overrides));

  const save = async () => {
    setSaving(true);
    try {
      const clip = await api.patchClip(id, cid, { start: draft.start, end: draft.end, title: draft.title,
        subtitle_style: draft.style, text_overrides: draft.overrides });
      setData((d) => ({ ...d, clip })); toast(t("editor.saved"));
    } catch (err) { toast(t(`errors.${err.code}.title`)); }
    setSaving(false);
  };
  useTopbar(data && {
    crumb: { name: data.project.name, duration: fmt.duration(data.project.source.duration), href: `#/proyecto/${id}`, sub: t("editor.crumb", { n: cid.slice(1) }) },
    actions: html`<span class="mono faint" style="font-size:12px" aria-live="polite">${dirty ? t("editor.unsaved") : t("editor.all_saved")}</span>
      <${Button} variant="primary" loading=${saving} disabled=${!dirty} onClick=${save} kbd="Ctrl ↵">${t("editor.save")}<//>`,
  }, [data, dirty, saving, draft]);
  useEffect(() => {
    const onKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && dirty) { e.preventDefault(); save(); } };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });

  const seekTo = (tt) => { setPlayhead(tt); setSeek((x) => ({ t: tt, n: (x ? x.n : 0) + 1 })); };
  const realFrame = async () => {
    const at = playhead >= draft.start && playhead <= draft.end ? playhead : draft.start + 0.5;
    setFraming(true);
    try {
      const url = await api.previewFrame(id, cid, { at, start: draft.start, end: draft.end, subtitle_style: draft.style,
        text_overrides: draft.overrides });
      if (frame) URL.revokeObjectURL(frame.url);
      setFrame({ url, at });
    } catch (err) { toast(t(`errors.${err.code}.title`)); }
    setFraming(false);
  };
  const cw = useMemo(() => (data && draft ? clipWords(data.words, draft.start, draft.end, draft.overrides) : []), [data, draft]);
  useEffect(() => { // keep the spoken word visible while playing
    const el = document.querySelector(".words__body .word.is-active");
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [Math.round(playhead * 4)]);
  if (error) return html`<div class="page"><${ErrorNotice} error=${error} action=${html`<${Button} variant="primary" size="lg" onClick=${() => navigate(`/proyecto/${id}`)}>${t("editor.back")}<//>`} /></div>`;
  if (!data || !draft) return html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`;

  const { project, sentences, words } = data;
  const dur = project.source.duration;
  const starts = sentences.map((s) => Math.max(0, s.start - 0.15));
  const ends = sentences.map((s) => Math.min(dur, s.end + 0.15));
  const snap = (field, dir) => {
    const list = field === "start" ? starts : ends;
    const cur = draft[field];
    const cand = dir < 0 ? [...list].reverse().find((v) => v < cur - 0.05) : list.find((v) => v > cur + 0.05);
    if (cand === undefined) return;
    const next = { ...draft, [field]: Math.round(cand * 1000) / 1000 };
    if (next.end - next.start >= 1) setDraft(next);
  };
  const setTime = (field, text) => {
    const v = parseTime(text);
    const next = { ...draft, [field]: v };
    if (v === null || v < 0 || v > dur || next.end - next.start < 1) { toast(t("editor.bad_time")); return; }
    setDraft(next);
  };
  // Words shown: the clip plus one sentence of context on each side (dimmed).
  const firstIn = cw.length ? cw[0].index : 0, lastIn = cw.length ? cw[cw.length - 1].index : 0;
  const sentenceOf = (wi) => sentences.findIndex((s) => wi >= s.word_start && wi < s.word_end);
  const sFirst = sentenceOf(firstIn), sLast = sentenceOf(lastIn);
  const ctxStart = sFirst > 0 ? sentences[sFirst - 1].word_start : Math.max(0, firstIn);
  const ctxEnd = sLast >= 0 && sLast + 1 < sentences.length ? sentences[sLast + 1].word_end : Math.min(words.length, lastIn + 1);
  const inClip = new Set(cw.map((w) => w.index));
  // Word under the playhead (last word that has started; cleared during long pauses).
  let activeWord = -1;
  for (let lo = 0, hi = words.length - 1; lo <= hi;) {
    const mid = (lo + hi) >> 1;
    if (words[mid].start <= playhead) { activeWord = mid; lo = mid + 1; } else hi = mid - 1;
  }
  if (activeWord >= 0 && playhead > words[activeWord].end + 0.4) activeWord = -1;
  return html`<div class="editor">
    <section class="editor__player" aria-label=${t("editor.preview")}>
      <${ClipPlayer} projectId=${id} hasVideo=${project.source.has_video} start=${draft.start} end=${draft.end} words=${cw} style=${draft.style} big
        seek=${seek} onTime=${setPlayhead} />
      <${Button} icon="image" loading=${framing} onClick=${realFrame} class="real-frame-btn">${t("editor.real_frame")}<//>
      <p class="faint" style="font-size:12px;margin:0">${t("editor.approx")}</p>
    </section>
    <main class="editor__work" id="main">
      <div><div class="label">${t("editor.eyebrow", { score: Math.round(data.clip.score) })}</div>
        <input class="input editor__title" aria-label=${t("editor.title_label")} value=${draft.title} maxlength="300"
          onInput=${(e) => setDraft({ ...draft, title: e.currentTarget.value })} /></div>
      <section class="timeline" aria-label=${t("editor.timeline")}>
        <${Timeline} projectId=${id} duration=${dur} start=${draft.start} end=${draft.end} time=${playhead} sentences=${sentences}
          onChange=${(r) => setDraft((d) => ({ ...d, start: r.start, end: r.end }))}
          onSeek=${seekTo} />
        <div class="inout">
          ${["start", "end"].map((f) => html`<div class="field"><label class="label" for=${`t-${f}`}>${t(`editor.${f}`)}</label>
            <div class="stepper-input">
              <${Button} icon="chevron-left" aria-label=${t("editor.prev_sentence")} onClick=${() => snap(f, -1)} />
              <input class="input input--mono" id=${`t-${f}`} key=${`${f}-${draft[f]}`} defaultValue=${fmt.precise(draft[f])}
                onChange=${(e) => setTime(f, e.currentTarget.value)} />
              <${Button} icon="chevron-right" aria-label=${t("editor.next_sentence")} onClick=${() => snap(f, 1)} />
            </div></div>`)}
          <div><div class="label">${t("editor.duration")}</div><div class="dur mono">${fmt.duration(draft.end - draft.start)}</div></div>
        </div>
        <p class="faint" style="font-size:12px">${t("editor.snap_hint")}</p>
      </section>
      <section class="words" aria-label=${t("editor.text")}>
        <div class="label">${t("editor.text")} · <span class="faint" style="text-transform:none;letter-spacing:0">${t("editor.text_hint")}</span></div>
        <div class="words__body">
          ${words.slice(ctxStart, ctxEnd).map((w, k) => {
            const i = ctxStart + k;
            if (!inClip.has(i) && draft.overrides[i] !== "") return html`<span class="word is-out">${w.text}</span> `;
            if (editing === i) {
              return html`<input class="input word-input" autofocus value=${draft.overrides[i] ?? w.text} aria-label=${t("editor.word_label")}
                onKeyDown=${(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setEditing(null); }}
                onBlur=${(e) => { const v = e.currentTarget.value.trim(); const o = { ...draft.overrides };
                  if (v === w.text) delete o[i]; else o[i] = v; setDraft({ ...draft, overrides: o }); setEditing(null); }} /> `;
            }
            const edited = draft.overrides[i] !== undefined;
            const active = i === activeWord;
            const shown = edited ? draft.overrides[i] : w.text;
            return html`<span class=${`word${edited ? " is-edited" : ""}${shown === "" ? " is-out" : ""}${active ? " is-active" : ""}`}
              tabindex="0" data-wi=${i} aria-current=${active ? "true" : undefined}
              onClick=${() => seekTo(w.start + 0.01)} onDblClick=${() => setEditing(i)} onKeyDown=${(e) => e.key === "Enter" && setEditing(i)}>${shown === "" ? `(${w.text})` : shown}</span> `;
          })}
        </div>
      </section>
    </main>
    <aside class="editor__side" aria-label=${t("editor.style")}>
      <div class="settings"><div class="settings__row"><span class="label">${t("editor.style")}</span>
        <${Segmented} label=${t("editor.style")} mono=${false} value=${draft.style} onChange=${(v) => setDraft({ ...draft, style: v })}
          options=${STYLES.map((v) => ({ value: v, label: t(`styles.${v.replace("-", "_")}`) }))} /></div></div>
      <div><div class="label" style="margin-bottom:10px">${t("editor.shortcuts")}</div>
        <div class="keys"><div><span>${t("editor.key_play")}</span><span class="kbd">${t("editor.key_space")}</span></div>
          <div><span>${t("editor.key_save")}</span><span class="kbd">Ctrl ↵</span></div></div></div>
      <${Modal} open=${Boolean(frame)} wide eyebrow=${t("editor.real_frame")} title=${frame ? t("editor.real_frame_title", { t: fmt.precise(frame.at) }) : ""}
        onClose=${() => setFrame(null)} actions=${html`<${Button} variant="primary" size="lg" onClick=${() => setFrame(null)}>${t("editor.close")}<//>`}>
        ${frame && html`<img class="real-frame" src=${frame.url} alt=${t("editor.real_frame_alt")} />`}
        <p class="faint" style="font-size:12px">${t("editor.real_frame_note")}</p><//>
      <div style="display:flex;gap:8px;margin-top:auto">
        <${Button} variant="ghost" disabled=${!dirty} onClick=${() => setDraft({ start: data.clip.start, end: data.clip.end, title: data.clip.title,
          style: data.clip.subtitle_style || project.settings.subtitle_style, overrides: { ...data.clip.text_overrides } })}>${t("editor.reset")}<//>
        <${Button} onClick=${() => navigate(`/proyecto/${id}`)}>${t("editor.back")}<//>
      </div>
    </aside>
  </div>`;
}
