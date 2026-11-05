// Home / new project: drop zone, file queue, simple settings, subtitle preview, recent projects.
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api, native } from "../api.js";
import { Button, Checkbox, ErrorNotice, Progress, Segmented, Tag, Thumb, Wave, toast } from "../components.js";
import { fmt, t } from "../i18n.js";
import { navigate } from "../router.js";
import { ResumeBanner } from "./resume.js";
import { store, useStore } from "../store.js";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v,.mp3,.wav,.m4a";
const DEFAULTS_KEY = "snipscout.defaults";
const DEFAULTS = { clip_length: "short", aspect: "9:16", subtitle_style: "bold-pop", language: null, model: "base", quick_analysis: false };
const DROP_PEAKS = Array.from({ length: 140 }, (_, i) => (6 + Math.abs(Math.sin(i * 0.7) * 14 + Math.sin(i * 1.9) * 8)) / 32);

function loadDefaults() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(DEFAULTS_KEY) || "{}") }; } catch (e) { return { ...DEFAULTS }; }
}
function saveDefaults(s) {
  try { localStorage.setItem(DEFAULTS_KEY, JSON.stringify(s)); } catch (e) { /* not remembered this time */ }
}

let nextKey = 1;
const setQueue = (fn) => store.set((s) => ({ queue: fn(s.queue || []) }));
const update = (key, patch) => setQueue((q) => q.map((it) => (it.key === key ? { ...it, ...patch } : it)));

async function addPath(path) {
  const key = nextKey++;
  setQueue((q) => [...q, { key, name: path.split(/[\\/]/).pop(), state: "adding" }]);
  try { update(key, { state: "ready", project: await api.createProject(path) }); }
  catch (err) { update(key, { state: "error", error: err }); }
}

async function addFile(file) {
  const key = nextKey++;
  setQueue((q) => [...q, { key, name: file.name, state: "adding", upload: 0 }]);
  try { update(key, { state: "ready", project: await api.upload(file, (f) => update(key, { upload: f })) }); }
  catch (err) { update(key, { state: "error", error: err }); }
}

async function removeItem(item) {
  setQueue((q) => q.filter((it) => it.key !== item.key));
  if (item.project) await api.deleteProject(item.project.id).catch(() => null);
}

// Window mode: Python forwards real paths of dropped files.
window.snipscoutDropped = (paths) => paths.forEach(addPath);

function DropZone() {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const input = useRef(null);
  const pick = async () => {
    if (native.available()) (await native.pickFiles()).forEach(addPath);
    else input.current.click();
  };
  const onDrop = (e) => {
    e.preventDefault(); depth.current = 0; setOver(false);
    if (!native.available()) [...e.dataTransfer.files].forEach(addFile); // window mode gets paths from Python
  };
  useEffect(() => {
    const onKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") { e.preventDefault(); pick(); } };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
  return html`<div class=${`drop${over ? " is-over" : ""}`}
      onDragEnter=${(e) => { e.preventDefault(); depth.current++; setOver(true); }}
      onDragOver=${(e) => e.preventDefault()}
      onDragLeave=${() => { if (--depth.current <= 0) { depth.current = 0; setOver(false); } }}
      onDrop=${onDrop}>
    <div class="drop__wave"><${Wave} peaks=${DROP_PEAKS} height=${40} classFor=${() => "todo"} /></div>
    <div class="drop__body">
      <div class="drop__idle">
        <div class="drop__title">${t("home.drop_title")}</div>
        <p class="muted" style="margin:4px 0 14px">${t("home.drop_or")}</p>
        <${Button} size="lg" icon="folder" kbd="Ctrl O" onClick=${pick}>${t("home.choose_file")}<//>
        <div class="label" style="margin-top:14px">${t("home.formats")}</div>
      </div>
      <div class="drop__over drop__title">${t("home.drop_release")}</div>
    </div>
    <input ref=${input} type="file" multiple accept=${ACCEPT} hidden
      onChange=${(e) => { [...e.currentTarget.files].forEach(addFile); e.currentTarget.value = ""; }} />
  </div>`;
}

function Queue({ selected, onSelect }) {
  const queue = useStore((s) => s.queue || []);
  if (!queue.length) return null;
  return html`<section aria-label=${t("home.queue")}><div class="table">
    <div class="table__head label"><span style="width:56px"></span><span style="flex:1">${t("home.file")}</span><span style="width:160px">${t("home.state")}</span><span style="width:40px"></span></div>
    ${queue.map((it) => {
      const p = it.project, src = p && p.source;
      const meta = src && [fmt.duration(src.duration), src.width && `${src.width}×${src.height}`, src.fps && `${Math.round(src.fps)} fps`,
        fmt.bytes(src.size_bytes), t(src.audio_tracks.length === 1 ? "home.tracks_one" : "home.tracks_other", { n: src.audio_tracks.length })].filter(Boolean).join(" · ");
      return html`<div class="row" aria-selected=${String(selected === it.key)} onClick=${() => it.state === "ready" && onSelect(it.key)}>
        <span style="width:16px"></span>
        <${Thumb} variant="wide" badge=${src ? fmt.duration(src.duration) : ""} />
        <div class="row__main" style="padding-left:16px"><div class="row__title">${it.name}</div>
          <div class="row__sub mono">${it.state === "error" ? t(`errors.${it.error.code}.title`) : meta || t("home.reading")}</div>
          ${it.state === "adding" && it.upload !== undefined && html`<div style="max-width:260px;margin-top:6px"><${Progress} value=${it.upload} label=${t("home.uploading")} /></div>`}</div>
        <span style="width:160px"><${Tag}>${t(`home.item_${it.state}`)}<//></span>
        <${Button} variant="ghost" icon="close" aria-label=${t("home.remove", { name: it.name })} onClick=${(e) => { e.stopPropagation(); removeItem(it); }} />
      </div>`;
    })}
  </div></section>`;
}

const SAMPLE = { pop: ["¿Y si lo que ", "estudias", " no es lo que necesitas?"] };
function StylePreview({ style }) {
  const [a, b, c] = SAMPLE.pop;
  const text = {
    "bold-pop": html`<span style="text-transform:uppercase">${a}<mark>${b}</mark>${c}</span>`,
    classic: html`${a}${b}${c}`,
    karaoke: html`<mark>${a}${b}</mark>${c}`,
    minimal: html`<span style="font-weight:500;font-size:9px">${a}${b}${c}</span>`,
  }[style];
  return html`<div class="style-preview"><div class="thumb thumb--style"><div class="thumb__shade"></div><div class="subtitle">${text}</div></div>
    <div class="settings__help" style="margin:0">${t(`home.style_help_${style.replace("-", "_")}`)}<br /><span class="faint">${t("home.preview_approx")}</span></div></div>`;
}

function SettingsPanel({ settings, setSettings, selectedItem }) {
  const status = useStore((s) => s.status);
  const set = (k) => (v) => setSettings({ ...settings, [k]: v });
  const [busy, setBusy] = useState(false);
  const project = selectedItem && selectedItem.project;
  const go = async () => {
    setBusy(true);
    try {
      await api.patchProject(project.id, { settings });
      await api.analyze(project.id);
      saveDefaults(settings);
      setQueue((q) => q.filter((it) => it.key !== selectedItem.key));
      navigate(`/proyecto/${project.id}`);
    } catch (err) {
      toast(t(`errors.${err.code}.title`));
      setBusy(false);
    }
  };
  const model = status.models.find((m) => m.name === settings.model);
  const estimate = project && Math.round((settings.quick_analysis ? Math.min(project.source.duration, 600) : project.source.duration) * model.rtf);
  return html`<aside class="home__right" aria-label=${t("home.settings")}>
    <div class="label" style="margin-bottom:12px">${t("home.settings")}</div>
    <div class="settings">
      <div class="settings__row"><span class="label">${t("home.duration")}</span><div>
        <${Segmented} label=${t("home.duration")} mono=${false} value=${settings.clip_length} onChange=${set("clip_length")}
          options=${["short", "medium", "long"].map((v) => ({ value: v, label: t(`home.length_${v}`) }))} />
        <div class="settings__help">${t(`home.length_help_${settings.clip_length}`)}</div></div></div>
      <div class="settings__row"><span class="label">${t("home.format")}</span><div>
        <${Segmented} label=${t("home.format")} value=${settings.aspect} onChange=${set("aspect")}
          options=${["9:16", "1:1", "16:9", "original"].map((v) => ({ value: v, label: v === "original" ? t("home.original") : v }))} />
        <div class="settings__help">${t(`home.format_help_${settings.aspect.replace(":", "_")}`)}</div></div></div>
      <div class="settings__row"><span class="label">${t("home.subtitles")}</span><div>
        <${Segmented} label=${t("home.subtitles")} mono=${false} value=${settings.subtitle_style} onChange=${set("subtitle_style")}
          options=${["bold-pop", "classic", "karaoke", "minimal"].map((v) => ({ value: v, label: t(`styles.${v.replace("-", "_")}`) }))} />
        <${StylePreview} style=${settings.subtitle_style} /></div></div>
      <div class="settings__row"><label class="label" for="lang">${t("home.video_language")}</label>
        <select class="select" id="lang" value=${settings.language || ""} onChange=${(e) => set("language")(e.currentTarget.value || null)}>
          <option value="">${t("home.lang_auto")}</option><option value="es">${t("languages.es")}</option><option value="en">${t("languages.en")}</option>
        </select></div>
    </div>
    <details class="adv"><summary>${t("home.advanced")}</summary>
      <div class="settings" style="border-top:0">
        <div class="settings__row"><span class="label">${t("home.precision")}</span><div>
          <div class="seg seg--sans" role="group" aria-label=${t("home.precision")}>
            ${status.models.map((m) => html`<button type="button" aria-pressed=${String(settings.model === m.name)} disabled=${!m.installed}
              title=${m.installed ? "" : t("home.model_missing")} onClick=${() => set("model")(m.name)}>${t(`models.${m.label}`)}</button>`)}
          </div>
          ${status.models.some((m) => !m.installed) && html`<div class="settings__help">${t("home.model_missing")}</div>`}</div></div>
        <div class="settings__row"><span class="label">${t("home.test")}</span>
          <label class="inline-check"><${Checkbox} checked=${settings.quick_analysis} onChange=${set("quick_analysis")} label=${t("home.quick")} /> ${t("home.quick")}</label></div>
      </div>
    </details>
    <div class="home__go">
      <${Button} variant="primary" block loading=${busy} disabled=${!project} onClick=${go}>${t("home.go")}<//>
      <p class="mono">${project ? t(model.measured ? "home.estimate_measured" : "home.estimate", { min: Math.max(1, Math.round(estimate / 60)) }) : t("home.go_hint")}</p>
    </div>
  </aside>`;
}

function Recent() {
  const projects = useStore((s) => s.projects);
  const queued = useStore((s) => new Set((s.queue || []).map((it) => it.project && it.project.id)));
  const list = projects.filter((p) => !queued.has(p.id)).slice(0, 6);
  if (!list.length) return null;
  return html`<section aria-labelledby="recent-t">
    <div class="label" id="recent-t" style="margin-bottom:8px">${t("home.recent")}</div>
    <div class="table">${list.map((p) => html`<a class="row" href=${`#/proyecto/${p.id}`} style="color:inherit;text-decoration:none;padding-left:8px">
      <div class="row__main"><div class="row__title" style="font-size:14px">${p.name}</div></div>
      <span class="row__cell mono" style="width:90px">${fmt.duration(p.source.duration)}</span>
      <span class="row__cell mono" style="width:140px">${fmt.date(p.updated_at)}</span>
      <span style="width:120px"><${Tag}>${t(`project_status.${p.status}`)}<//></span></a>`)}</div>
  </section>`;
}

export function Home() {
  const status = useStore((s) => s.status);
  const queue = useStore((s) => s.queue || []);
  const [settings, setSettings] = useState(loadDefaults);
  const [selected, setSelected] = useState(null);
  useEffect(() => { api.projects().then((projects) => store.set({ projects })).catch(() => null); }, []);
  // Keep a ready item selected; fall back to an installed model.
  const ready = queue.filter((it) => it.state === "ready");
  const sel = ready.find((it) => it.key === selected) || ready[0] || null;
  useEffect(() => {
    const m = status.models.find((x) => x.name === settings.model);
    if (!m || !m.installed) {
      const inst = status.models.find((x) => x.installed);
      if (inst) setSettings((s) => ({ ...s, model: inst.name }));
    }
  }, [status]);
  if (!status.ffmpeg.ok) return html`<div class="page"><${ErrorNotice} error=${{ code: "ffmpeg_missing" }} /></div>`;
  return html`<div class="home">
    <main class="home__left" id="main">
      <div><div class="label">${t("home.eyebrow")}</div><h1 class="title-1">${t("home.title")}</h1><p class="lead">${t("home.lead")}</p></div>
      <${ResumeBanner} />
      <${DropZone} />
      <${Queue} selected=${sel && sel.key} onSelect=${setSelected} />
      <${Recent} />
    </main>
    <${SettingsPanel} settings=${settings} setSettings=${setSettings} selectedItem=${sel} />
  </div>`;
}
