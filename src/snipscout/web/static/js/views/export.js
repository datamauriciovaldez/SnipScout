// Export: per-clip progress while rendering, then the finished clips (hover to play, download, copy).
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api, native } from "../api.js";
import { Button, ErrorNotice, LiveStatus, Modal, Progress, toast } from "../components.js";
import { Icon } from "../icons.js";
import { fmt, t } from "../i18n.js";
import { navigate } from "../router.js";
import { useTopbar } from "../store.js";

export function Export({ id }) {
  const [project, setProject] = useState(null);
  const [error, setError] = useState(null);
  const load = () => api.project(id).then(setProject).catch((e) => setError({ code: e.code, message: e.message }));
  useEffect(() => { load(); }, [id]);
  useTopbar(project && { crumb: { name: project.name, duration: fmt.duration(project.source.duration), href: `#/proyecto/${id}`, sub: t("export.crumb") } }, [project]);
  if (error) return html`<div class="page"><${ErrorNotice} error=${error} action=${html`<${Button} variant="primary" size="lg" onClick=${() => navigate("/")}>${t("common.back_home")}<//>`} /></div>`;
  if (!project) return html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`;
  const rendering = project.job && project.job.kind === "render";
  if (rendering) return html`<${Rendering} project=${project} onDone=${load} />`;
  if (project.status === "done") return html`<${Finished} project=${project} />`;
  if (project.status === "error" && project.error_code) {
    return html`<div class="page"><${ErrorNotice} error=${{ code: project.error_code }} action=${html`
      <${Button} variant="primary" size="lg" onClick=${() => navigate(`/proyecto/${id}`)}>${t("export.back_results")}<//>`} /></div>`;
  }
  // Cancelled or interrupted render: offer to go back to the results.
  return html`<main class="page" id="main"><div class="empty">
    <div class="label">${t("export.eyebrow")}</div><h1 class="title-2">${t("export.stopped_title")}</h1>
    <p class="lead">${t("export.stopped_lead")}</p>
    <div><${Button} variant="primary" size="lg" onClick=${() => navigate(`/proyecto/${id}`)}>${t("export.back_results")}<//></div>
  </div></main>`;
}

function Rendering({ project, onDone }) {
  const [rows, setRows] = useState([]); // index → { id, title, duration, progress }
  const [overall, setOverall] = useState(0);
  const [confirm, setConfirm] = useState(false);
  const [failed, setFailed] = useState(null);
  const close = useRef(null);
  useEffect(() => {
    close.current = api.events(project.id, (e) => {
      if (e.stage === "render" && e.params) {
        const p = e.params;
        setOverall(e.progress);
        setRows((r) => {
          const next = Array.from({ length: p.clips }, (_, k) => r[k] || null);
          for (let k = 0; k < p.clip - 1; k++) if (next[k]) next[k] = { ...next[k], progress: 1 };
          next[p.clip - 1] = { id: p.clip_id, title: p.title, duration: p.duration, progress: p.clip_progress };
          return next;
        });
      }
      if (e.state === "done") { close.current(); onDone(); }
      if (e.state === "error") { close.current(); setFailed(e.error_code); }
      if (e.state === "cancelled") { close.current(); onDone(); }
    });
    return () => close.current && close.current();
  }, []);
  if (failed) return html`<div class="page"><${ErrorNotice} error=${{ code: failed }} action=${html`<${Button} variant="primary" size="lg" onClick=${() => navigate(`/proyecto/${project.id}`)}>${t("export.back_results")}<//>`} /></div>`;
  const done = rows.filter((r) => r && r.progress >= 1).length;
  return html`<main class="page export" id="main">
    <div class="label">${t("export.eyebrow")}</div>
    <h1 class="title-1">${t("export.rendering_title")}</h1>
    <p class="lead">${t("export.rendering_lead")}</p>
    <${LiveStatus} step=${`${done}|${Math.floor(overall * 10)}`} message=${`${Math.floor(overall * 100)} % · ${rows.length ? t("export.count", { done, total: rows.length }) : t("export.preparing")}`} />
    <div class="export__overall">
      <span class="dl__pct mono">${Math.floor(overall * 100)} %</span>
      <span class="mono muted">${rows.length ? t("export.count", { done, total: rows.length }) : t("export.preparing")}</span>
    </div>
    <${Progress} value=${rows.length ? overall : null} label=${t("export.rendering_title")} />
    <div class="table export__list">
      ${rows.map((r, k) => html`<div class="row">
        <span class="row__num mono" style="padding-left:12px">${String(k + 1).padStart(2, "0")}</span>
        <div class="row__main"><div class="row__title">${r ? r.title : t("export.queued")}</div></div>
        <span class="row__cell mono c-dur">${r ? fmt.duration(r.duration) : ""}</span>
        <span class="export__state mono">${!r ? t("export.state_queued") : r.progress >= 1 ? t("export.state_done") : `${Math.round(r.progress * 100)} %`}</span>
      </div>`)}
    </div>
    <div style="margin-top:20px"><${Button} size="lg" onClick=${() => setConfirm(true)}>${t("common.cancel")}<//></div>
    <${Modal} open=${confirm} eyebrow=${t("export.cancel_eyebrow")} title=${t("export.cancel_title")} onClose=${() => setConfirm(false)}
      actions=${html`<${Button} size="lg" onClick=${() => { setConfirm(false); api.cancel(project.id); }}>${t("export.cancel_confirm")}<//>
        <${Button} variant="primary" size="lg" onClick=${() => setConfirm(false)}>${t("export.keep_going")}<//>`}>${t("export.cancel_body")}<//>
  </main>`;
}

function Finished({ project }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.exports(project.id).then(setData).catch((e) => setError({ code: e.code, message: e.message })); }, [project.id]);
  if (error) return html`<div class="page"><${ErrorNotice} error=${error} /></div>`;
  if (!data) return html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`;
  const reveal = () => api.reveal(project.id).then(() => toast(t("export.revealed"))).catch((e) => toast(t(`errors.${e.code}.title`)));
  const copy = async (text) => { try { await navigator.clipboard.writeText(text); toast(t("components.copied")); } catch (e) { toast(t("components.copy_failed")); } };
  return html`<main class="page export" id="main">
    <div class="label">${t("export.eyebrow")}</div>
    <h1 class="title-1">${t(data.clips.length === 1 ? "export.done_one" : "export.done_many", { n: data.clips.length })}</h1>
    <p class="lead">${t("export.done_lead")}</p>
    <div class="export__folder"><span class="label">${t("export.folder")}</span><span class="mono">${data.folder}</span></div>
    <div class="export__actions">
      <${Button} variant=${native.available() ? "primary" : "outline"} size="lg" icon="folder" onClick=${reveal}>${t("export.reveal")}<//>
      <a class="btn btn--outline btn--lg" href=${api.zipUrl(project.id)} download><${Icon} name="download" />${t("export.zip")}</a>
      <${Button} variant="ghost" size="lg" onClick=${() => navigate(`/proyecto/${project.id}`)}>${t("export.back_results")}<//>
    </div>
    <div class="table export__list">
      ${data.clips.map((c) => html`<${FinishedRow} project=${project} clip=${c} onCopy=${copy} />`)}
    </div>
  </main>`;
}

function FinishedRow({ project, clip, onCopy }) {
  const video = useRef(null);
  const play = () => video.current && video.current.play().catch(() => null);
  const stop = () => { const v = video.current; if (v) { v.pause(); v.currentTime = 0; } };
  return html`<div class="row export__row" onMouseEnter=${play} onMouseLeave=${stop}>
    <div class="export__video thumb">
      ${clip.exists && html`<video ref=${video} src=${api.exportUrl(project.id, clip.file)} muted loop playsinline preload="metadata"
        aria-label=${t("export.preview_of", { title: clip.title })} onFocus=${play} onBlur=${stop} tabindex="0"></video>`}
    </div>
    <div class="row__main">
      <div class="row__title">${clip.title}</div>
      <div class="row__sub">${clip.hook}</div>
      <div class="export__meta mono">${fmt.duration(clip.duration)} · ${fmt.bytes(clip.size_bytes)} · ${clip.file}</div>
      <div class="export__links">
        <a class="btn btn--accent" href=${api.exportUrl(project.id, clip.file, true)} download><${Icon} name="download" />${t("export.download")}</a>
        <${Button} variant="outline" icon="copy" onClick=${() => onCopy(clip.caption)}>${t("export.copy_caption")}<//>
        <a class="btn btn--ghost" href=${api.exportUrl(project.id, clip.subtitles.srt, true)} download>.srt</a>
        <a class="btn btn--ghost" href=${api.exportUrl(project.id, clip.subtitles.vtt, true)} download>.vtt</a>
      </div>
    </div>
  </div>`;
}
