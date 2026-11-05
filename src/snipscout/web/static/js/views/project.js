// Project route: Processing while analyzing, Results once clips exist.
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button, Checkbox, ErrorNotice, Modal, ScoreBar, Wave, toast } from "../components.js";
import { fmt, t } from "../i18n.js";
import { navigate } from "../router.js";
import { useStore, useTopbar } from "../store.js";
import { ClipPlayer, clipWords } from "./player.js";

const STAGES = ["prepare_audio", "transcribe", "understand", "find_moments"];
const HIGH = 85;
const PLACEHOLDER_PEAKS = Array.from({ length: 220 }, (_, i) => (8 + Math.abs(Math.sin(i * 0.7) * 18 + Math.sin(i * 1.9) * 10)) / 40);

export function Project({ id }) {
  const [project, setProject] = useState(null);
  const [error, setError] = useState(null);
  const reload = () => api.project(id).then(setProject).catch((e) => setError({ code: e.code, message: e.message }));
  useEffect(() => { reload(); }, [id]);
  if (error) return html`<div class="page"><${ErrorNotice} error=${error} action=${html`<${Button} variant="primary" size="lg" onClick=${() => navigate("/")}>${t("common.back_home")}<//>`} /></div>`;
  if (!project) return html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`;
  const busy = project.job && project.job.kind === "analyze";
  if (busy || ["new", "analyzing", "cancelled", "error"].includes(project.status)) {
    return html`<${Processing} project=${project} running=${Boolean(busy)} onDone=${reload} />`;
  }
  return html`<${Results} project=${project} />`;
}

/* ------------------------------------------------------------------ Processing */

function Processing({ project, running, onDone }) {
  const [state, setState] = useState(running ? "running" : project.status === "error" ? "error" : "idle");
  const [stages, setStages] = useState({});
  const [info, setInfo] = useState({ processed: 0, total: project.source.duration, eta: project.estimate_s });
  const [lines, setLines] = useState([]);
  const [peaks, setPeaks] = useState(null);
  const [errorCode, setErrorCode] = useState(project.error_code);
  const [confirm, setConfirm] = useState(false);
  const closeRef = useRef(null);
  const peaksRequested = useRef(false);

  useTopbar({ crumb: { name: project.name, duration: fmt.duration(project.source.duration) } }, [project.id]);

  const listen = () => {
    closeRef.current && closeRef.current();
    closeRef.current = api.events(project.id, (e) => {
      if (STAGES.includes(e.stage)) {
        setStages((s) => ({ ...s, [e.stage]: e.progress, ...Object.fromEntries(STAGES.slice(0, STAGES.indexOf(e.stage)).map((k) => [k, 1])) }));
      }
      if (e.stage === "transcribe" && e.params) {
        setInfo({ processed: e.params.processed_s || 0, total: e.params.total_s || project.source.duration, eta: e.params.eta_s });
        if (e.params.text) setLines((l) => [...l.slice(-40), { t: e.params.processed_s, text: e.params.text }]);
      }
      if (e.stage === "transcribe" && !peaksRequested.current) { // audio exists from here on: fetch real peaks once
        peaksRequested.current = true;
        api.waveform(project.id, 220).then((w) => setPeaks(w.peaks)).catch(() => { peaksRequested.current = false; });
      }
      if (e.state === "done") { closeRef.current(); onDone(); }
      if (e.state === "error") { closeRef.current(); setErrorCode(e.error_code); setState("error"); }
      if (e.state === "cancelled") { closeRef.current(); setState("cancelled"); }
    });
  };
  useEffect(() => { if (running) listen(); return () => closeRef.current && closeRef.current(); }, []);

  const start = async () => {
    try { await api.analyze(project.id); setState("running"); setErrorCode(null); listen(); }
    catch (err) { toast(t(`errors.${err.code}.title`)); }
  };
  const cancel = async () => { setConfirm(false); await api.cancel(project.id).catch(() => null); };

  if (state === "error" && errorCode) {
    return html`<div class="page"><${ErrorNotice} error=${{ code: errorCode }} action=${html`
      <${Button} variant="primary" size="lg" onClick=${() => navigate("/")}>${t("processing.other_file")}<//>
      <${Button} size="lg" onClick=${start}>${t("common.retry")}<//>`} /></div>`;
  }
  const frac = info.total ? info.processed / info.total : 0;
  const waveClass = (i, n) => (i / n < frac ? "done" : "todo");
  const headline = state === "cancelled" || state === "idle" ? t("processing.paused_title")
    : t(`stage.${STAGES.find((s) => (stages[s] || 0) < 1) || "find_moments"}`);
  return html`<div class="processing">
    <main class="processing__main" id="main">
      <div class="label">${t("processing.eyebrow")}</div>
      <h1 class="title-1">${headline}</h1>
      <p class="lead">${state === "running" ? t("processing.lead") : t("processing.paused_lead")}</p>
      <div class="eta" aria-live="polite">
        <div><div class="label">${t("processing.left")}</div><b class="mono">${info.eta != null ? t("processing.minutes", { m: Math.floor(info.eta / 60), s: String(Math.round(info.eta % 60)).padStart(2, "0") }) : "—"}</b></div>
        <div><div class="label">${t("processing.heard")}</div><b class="mono">${fmt.duration(info.processed)}</b> <span class="mono faint">/ ${fmt.duration(info.total)}</span></div>
      </div>
      <div class="big-wave">
        <div class="wave-wrap"><${Wave} peaks=${peaks || PLACEHOLDER_PEAKS} height=${96} barWidth=${3} classFor=${waveClass} />
          <span class="wave__playhead" style=${`left:${frac * 100}%`}></span></div>
        <div class="ruler mono">${[0, 0.25, 0.5, 0.75, 1].map((f) => html`<span>${fmt.duration(info.total * f)}</span>`)}</div>
      </div>
      <div class="stages" role="list">
        ${STAGES.map((s) => {
          const p = stages[s] || 0;
          const cls = p >= 1 ? "is-done" : p > 0 || (state === "running" && s === STAGES.find((x) => (stages[x] || 0) < 1)) ? "is-active" : "";
          return html`<div class=${`stage ${cls}`} role="listitem"><span class="stage__dot" aria-hidden="true"></span><span>${t(`stage.${s}`)}</span><span class="stage__pct">${Math.round(p * 100)} %</span></div>`;
        })}
      </div>
    </main>
    <aside class="processing__side" aria-label=${t("processing.live")}>
      <div class="label">${t("processing.live")}</div>
      <div class="transcript transcript--live" aria-live="off">
        ${lines.length ? lines.map((l) => html`<div class="transcript__line"><span class="transcript__time">${fmt.duration(l.t)}</span><span>${l.text}</span></div>`)
          : html`<p class="faint">${t("processing.waiting_text")}</p>`}
      </div>
      <div class="processing__foot">
        ${state === "running"
          ? html`<${Button} size="lg" onClick=${() => setConfirm(true)}>${t("common.cancel")}<//><span class="faint">${t("processing.saved_note")}</span>`
          : html`<${Button} variant="primary" size="lg" onClick=${start}>${state === "idle" && project.status === "new" ? t("processing.start") : t("processing.resume")}<//>
              <${Button} variant="ghost" size="lg" onClick=${() => navigate("/")}>${t("common.back_home")}<//>`}
      </div>
    </aside>
    <${Modal} open=${confirm} eyebrow=${t("processing.cancel_eyebrow")} title=${t("processing.cancel_title")} onClose=${() => setConfirm(false)}
      actions=${html`<${Button} size="lg" onClick=${cancel}>${t("processing.cancel_confirm")}<//><${Button} variant="primary" size="lg" onClick=${() => setConfirm(false)}>${t("processing.keep_going")}<//>`}>
      ${t("processing.cancel_body", { time: fmt.duration(info.processed) })}<//>
  </div>`;
}

/* ------------------------------------------------------------------ Results */

const shortPath = (p) => (p || "").split(/[\\/]/).filter(Boolean).slice(-2).join("/");

function Results({ project }) {
  const appStatus = useStore((s) => s.status);
  const [clips, setClips] = useState(null);
  const [words, setWords] = useState([]);
  const [sentences, setSentences] = useState([]);
  const [peaks, setPeaks] = useState([]);
  const [active, setActive] = useState(0);
  const [rendering, setRendering] = useState(false);
  const status = project.settings;

  useEffect(() => {
    api.clips(project.id).then((r) => setClips(r.clips));
    api.transcript(project.id).then((tr) => { setWords(tr.words); setSentences(tr.sentences); }).catch(() => null);
    api.waveform(project.id, 2000).then((w) => setPeaks(w.peaks)).catch(() => null);
  }, [project.id]);

  const included = (clips || []).filter((c) => c.included);
  const render = async (ids) => {
    setRendering(true);
    try { await api.render(project.id, ids ? { clip_ids: ids } : {}); navigate(`/proyecto/${project.id}/exportar`); }
    catch (err) { toast(t(`errors.${err.code}.title`)); setRendering(false); }
  };
  useTopbar({
    crumb: { name: project.name, duration: fmt.duration(project.source.duration) },
    actions: html`<${Button} variant="primary" loading=${rendering} disabled=${!included.length} onClick=${() => render()}>
      ${included.length ? t(included.length === 1 ? "results.render_one" : "results.render_many", { n: included.length }) : t("results.render_none")}<//>`,
  }, [project.id, included.length, rendering]);

  const toggle = async (c, value) => {
    setClips((cs) => cs.map((x) => (x.id === c.id ? { ...x, included: value } : x)));
    await api.patchClip(project.id, c.id, { included: value }).catch(() => toast(t("errors.storage.title")));
  };
  const onKey = (e) => {
    if (!clips) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = Math.max(0, Math.min(clips.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
      setActive(n); document.getElementById(`row-${clips[n].id}`).focus();
    }
    if (e.key === " " && e.target.classList.contains("row")) { e.preventDefault(); toggle(clips[active], !clips[active].included); }
    if (e.key === "Enter" && e.target.classList.contains("row")) navigate(`/proyecto/${project.id}/clip/${clips[active].id}`);
  };

  if (!clips) return html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`;
  if (!clips.length) return html`<${EmptyResults} project=${project} />`;
  const total = included.reduce((a, c) => a + (c.end - c.start), 0);
  const clip = clips[Math.min(active, clips.length - 1)];
  return html`<div class="results">
    <section class="results__main" aria-labelledby="r-title" id="main">
      <div class="label">${t("results.eyebrow")}</div>
      <h1 class="title-1" id="r-title">${t(clips.length === 1 ? "results.title_one" : "results.title_many", { n: clips.length })}</h1>
      <p class="lead">${t("results.lead")}</p>
      <div class="table results__table">
        <div class="table__head label" aria-hidden="true"><span style="width:56px"></span><span style="width:36px">${t("results.col_n")}</span><span style="width:54px"></span>
          <span style="flex:1">${t("results.col_clip")}</span><span class="c-in-out">${t("results.col_inout")}</span><span class="c-dur">${t("results.col_dur")}</span><span class="c-score">${t("results.col_score")}</span></div>
        <div role="listbox" aria-label=${t("results.list_label")} onKeyDown=${onKey}>
          ${clips.map((c, i) => html`<div class="row" id=${`row-${c.id}`} role="option" tabindex=${i === active ? 0 : -1} aria-selected=${String(i === active)}
              onClick=${(e) => !e.target.closest(".check-hit") && setActive(i)} onDblClick=${() => navigate(`/proyecto/${project.id}/clip/${c.id}`)}>
            <label class="check-hit"><${Checkbox} checked=${c.included} onChange=${(v) => toggle(c, v)} label=${t("results.include", { title: c.title })} /></label>
            <div class="row__num mono">${String(i + 1).padStart(2, "0")}</div>
            <div class="thumb">${project.source.has_video && html`<img src=${api.thumbUrl(project.id, c.id)} alt="" loading="lazy" class="thumb__img" />`}</div><div class="gap-20"></div>
            <div class="row__main"><div class="row__title">${c.title}</div><div class="row__sub">${c.hook}</div></div>
            <div class="row__cell mono c-in-out">${fmt.timecode(c.start)} → ${fmt.timecode(c.end)}</div>
            <div class="row__cell mono c-dur" style="color:var(--text)">${fmt.duration(c.end - c.start)}</div>
            <div class="c-score"><${ScoreBar} value=${c.score} threshold=${HIGH} /></div>
          </div>`)}
        </div>
      </div>
      <div class="statusbar">
        <span><b>${t("results.selected", { n: included.length, total: clips.length })}</b></span>
        <span>${t("results.total", { d: fmt.duration(total) })}</span>
        <span>${t("results.format_style", { f: status.aspect === "original" ? t("home.original") : status.aspect, s: t(`styles.${status.subtitle_style.replace("-", "_")}`) })}</span>
        <span class="statusbar__end">${t("results.output", { dir: shortPath(appStatus.output_dir) })}</span>
      </div>
    </section>
    <${PreviewPanel} project=${project} clip=${clip} index=${active} words=${words} sentences=${sentences} peaks=${peaks} onDownload=${() => render([clip.id])} />
  </div>`;
}

function PreviewPanel({ project, clip, index, words, sentences, peaks, onDownload }) {
  const cw = useMemo(() => clipWords(words, clip.start, clip.end, clip.text_overrides), [words, clip]);
  const top = Object.entries(clip.contributions || {}).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const lines = sentences.filter((s) => s.end > clip.start && s.start < clip.end).slice(0, 3);
  // Waveform window: the clip plus 15 % of context on each side.
  const dur = project.source.duration, pad = (clip.end - clip.start) * 0.15;
  const w0 = Math.max(0, clip.start - pad), w1 = Math.min(dur, clip.end + pad);
  const slice = peaks.length ? peaks.slice(Math.floor((w0 / dur) * peaks.length), Math.ceil((w1 / dur) * peaks.length)) : [];
  const bars = slice.length > 86 ? Array.from({ length: 86 }, (_, i) => slice[Math.floor((i * slice.length) / 86)]) : slice;
  const inStart = (clip.start - w0) / (w1 - w0), inEnd = (clip.end - w0) / (w1 - w0);
  const copyTitle = async () => { try { await navigator.clipboard.writeText(clip.title); toast(t("components.copied")); } catch (e) { toast(t("components.copy_failed")); } };
  return html`<aside class="results__side" aria-label=${t("results.preview_label")}>
    <div class="results__side-head"><span class="label">${t("results.preview", { n: String(index + 1).padStart(2, "0") })}</span>
      <span><${Button} variant="ghost" icon="copy" onClick=${copyTitle}>${t("results.copy_title")}<//>
      <span class="mono faint" style="font-size:12px">${fmt.duration(clip.end - clip.start)}</span></span></div>
    <div class="results__side-top">
      <${ClipPlayer} projectId=${project.id} hasVideo=${project.source.has_video} start=${clip.start} end=${clip.end} words=${cw}
        style=${clip.subtitle_style || project.settings.subtitle_style} />
      <div class="why">
        <div class="label" style="margin-bottom:8px">${t("results.why")}</div>
        <div class="why__text">${clip.reasons.length ? clip.reasons.map((r) => t(`reasons.${r}`)).join(" · ") : t("results.why_none")}</div>
        <div class="why__list mono">${top.map(([k, v]) => html`<div><span>${t(`signals.${k}`)}</span><b>+${Math.round(v)}</b></div>`)}</div>
      </div>
    </div>
    ${bars.length > 0 && html`<div class="mini-wave"><${Wave} peaks=${bars} classFor=${(i, n) => (i / n >= inStart && i / n <= inEnd ? "in" : "")}>
        <span class="wave__marker wave__marker--in" style=${`left:calc(${inStart * 100}% - 4px)`}></span>
        <span class="wave__marker wave__marker--out" style=${`left:calc(${inEnd * 100}% + 2px)`}></span><//>
      <div class="side__times mono"><span>${fmt.timecode(clip.start)}</span><span>${fmt.timecode(clip.end)}</span></div></div>`}
    <div class="transcript">${lines.map((s, k) => html`<div class="transcript__line"><span class="transcript__time">${fmt.duration(s.start)}</span>
      <span class=${k ? "transcript__text--dim" : ""}>${s.text}</span></div>`)}</div>
    <div class="results__side-actions">
      <${Button} variant="outline" size="lg" onClick=${() => navigate(`/proyecto/${project.id}/clip/${clip.id}`)}>${t("results.edit")}<//>
      <${Button} variant="accent" size="lg" icon="download" onClick=${onDownload}>${t("results.download")}<//>
    </div>
  </aside>`;
}

function EmptyResults({ project }) {
  const retry = async (patch) => {
    await api.patchProject(project.id, { settings: patch });
    await api.analyze(project.id);
    location.reload();
  };
  useTopbar({ crumb: { name: project.name, duration: fmt.duration(project.source.duration) } }, [project.id]);
  return html`<main class="page" id="main">
    <div class="label">${t("results.eyebrow")}</div>
    <h1 class="title-1">${t("results.empty_title")}</h1>
    <p class="lead">${t("results.empty_lead")}</p>
    <div style="display:flex;gap:8px;margin-top:20px">
      <${Button} variant="primary" size="lg" onClick=${() => retry({ clip_length: "medium" })}>${t("results.try_medium")}<//>
      <${Button} size="lg" onClick=${() => navigate("/")}>${t("common.back_home")}<//>
    </div>
  </main>`;
}
