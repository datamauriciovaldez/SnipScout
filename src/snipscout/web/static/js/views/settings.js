// Settings: language, theme, output folder, export quality, speech models, disk space.
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api, native } from "../api.js";
import { Button, Checkbox, Modal, Progress, Segmented, toast } from "../components.js";
import { fmt, setLang, t } from "../i18n.js";
import { store, useStore } from "../store.js";

const DEFAULTS_KEY = "snipscout.defaults";
const getDefaultModel = () => { try { return JSON.parse(localStorage.getItem(DEFAULTS_KEY) || "{}").model || "base"; } catch (e) { return "base"; } };
const setDefaultModel = (m) => {
  try { const d = JSON.parse(localStorage.getItem(DEFAULTS_KEY) || "{}"); d.model = m; localStorage.setItem(DEFAULTS_KEY, JSON.stringify(d)); }
  catch (e) { /* not remembered this time */ }
};

function Row({ label, id, children, help }) {
  return html`<div class="settings__row"><span class="label" id=${id}>${label}</span><div>${children}${help && html`<div class="settings__help">${help}</div>`}</div></div>`;
}

function ThemeSwitch() {
  const current = () => (window.SnipScoutTheme ? window.SnipScoutTheme.get() : "system");
  const [mode, setMode] = useState(current);
  const set = (m) => { window.SnipScoutTheme && window.SnipScoutTheme.set(m); setMode(m); };
  return html`<${Segmented} label=${t("settings.theme")} mono=${false} value=${mode} onChange=${set}
    options=${[{ value: "light", label: t("settings.theme_light") }, { value: "dark", label: t("settings.theme_dark") }, { value: "system", label: t("settings.theme_system") }]} />`;
}

function OutputFolder({ settings, onChange }) {
  const [editing, setEditing] = useState(false);
  const input = useRef(null);
  const save = async (value) => {
    try { onChange(await api.patchSettings({ output_dir: value })); setEditing(false); toast(t("settings.saved")); }
    catch (e) { toast(t(`errors.${e.code}.title`)); }
  };
  const change = async () => {
    if (native.available()) { const folder = await native.pickFolder(); if (folder) save(folder); }
    else setEditing(true);
  };
  if (settings.output_dir_locked) return html`<span class="mono muted">${settings.output_dir_resolved}</span>`;
  return html`<div class="path-row">
    ${editing
      ? html`<input ref=${input} class="input input--mono" autofocus defaultValue=${settings.output_dir_resolved} aria-label=${t("settings.output")}
          onKeyDown=${(e) => { if (e.key === "Enter") save(e.currentTarget.value); if (e.key === "Escape") setEditing(false); }} />
          <${Button} variant="primary" onClick=${() => save(input.current.value)}>${t("settings.save")}<//>`
      : html`<span class="mono path-row__value">${settings.output_dir_resolved}</span>
          <${Button} icon="folder" onClick=${change}>${t("settings.change")}<//>
          ${settings.output_dir && html`<${Button} variant="ghost" onClick=${() => save("")}>${t("settings.use_default")}<//>`}`}
  </div>`;
}

function Models() {
  const status = useStore((s) => s.status);
  const [busy, setBusy] = useState(null); // { name, frac }
  const [toDelete, setToDelete] = useState(null);
  const [def, setDef] = useState(getDefaultModel);
  const refresh = async () => store.set({ status: await api.status() });
  const download = async (m) => {
    setBusy({ name: m.name, frac: 0 });
    try {
      await api.downloadModel(m.name, (e) => {
        if (e.done !== undefined) setBusy({ name: m.name, frac: e.done / e.total });
        if (e.state === "error") toast(t(`errors.${e.error_code}.title`));
      });
    } catch (e) { toast(t(`errors.${e.code || "model_download"}.title`)); }
    setBusy(null); refresh();
  };
  const remove = async () => {
    const m = toDelete; setToDelete(null);
    await api.deleteModel(m.name).catch((e) => toast(t(`errors.${e.code}.title`)));
    refresh();
  };
  const installed = status.models.filter((m) => m.installed);
  return html`<div class="table models">
    ${status.models.map((m) => html`<div class=${`row${def === m.name ? " is-default" : ""}`}>
      <div class="row__main" style="padding-left:12px"><div class="row__title" style="font-size:14px">${t(`models.${m.label}`)}
        ${def === m.name && html` <span class="tag" style="margin-left:6px">${t("settings.default_model")}</span>`}</div>
        <div class="row__sub">${t(`welcome.model_${m.label}`)}</div></div>
      <span class="row__cell mono" style="width:90px">${fmt.bytes(m.bytes)}</span>
      <span class="row__cell" style="width:150px">${busy && busy.name === m.name
        ? html`<${Progress} value=${busy.frac} label=${t("welcome.dl_title")} />`
        : m.installed ? html`<span class="status-ok">${t("home.installed")}</span>` : t("home.not_installed")}</span>
      <span class="models__act">
        ${!m.installed && html`<${Button} disabled=${Boolean(busy)} onClick=${() => download(m)}>${t("settings.download")}<//>`}
        ${m.installed && def !== m.name && html`<${Button} variant="ghost" onClick=${() => { setDefaultModel(m.name); setDef(m.name); toast(t("settings.saved")); }}>${t("settings.make_default")}<//>`}
        ${m.installed && html`<${Button} variant="ghost" icon="trash" aria-label=${t("settings.delete_model", { name: t(`models.${m.label}`) })}
          disabled=${installed.length <= 1 || Boolean(busy)} onClick=${() => setToDelete(m)} />`}
      </span>
    </div>`)}
    <${Modal} open=${Boolean(toDelete)} eyebrow=${t("settings.models")} title=${toDelete ? t("settings.delete_model", { name: t(`models.${toDelete.label}`) }) : ""}
      onClose=${() => setToDelete(null)} actions=${html`<${Button} size="lg" onClick=${remove}>${t("settings.delete")}<//>
        <${Button} variant="primary" size="lg" onClick=${() => setToDelete(null)}>${t("common.cancel")}<//>`}>
      ${toDelete && t("settings.delete_model_body", { size: fmt.bytes(toDelete.bytes) })}<//>
  </div>`;
}

function Disk() {
  const [st, setSt] = useState(null);
  const [freeing, setFreeing] = useState(false);
  const load = () => api.storage().then(setSt).catch(() => null);
  useEffect(() => { load(); }, []);
  if (!st) return html`<div class="skeleton" style="height:12px;width:60%"></div>`;
  const used = st.models_bytes + st.projects_bytes + st.cache_bytes || 1;
  const pct = (n) => `${(n / used) * 100}%`;
  const free = async () => {
    setFreeing(true);
    try { const r = await api.freeStorage(); toast(t("settings.freed", { size: fmt.bytes(r.freed_bytes) })); await load(); }
    catch (e) { toast(t(`errors.${e.code}.title`)); }
    setFreeing(false);
  };
  return html`<div>
    <div class="disk__head"><span><b class="mono">${fmt.bytes(used)}</b> <span class="muted">${t("settings.used")}</span></span>
      <span class="mono faint" style="font-size:12px">${t("settings.free_on_disk", { size: fmt.bytes(st.free_bytes) })}</span></div>
    <div class="disk__bar" aria-hidden="true"><span class="a" style=${`width:${pct(st.models_bytes)}`}></span><span class="b" style=${`width:${pct(st.projects_bytes)}`}></span><span class="c" style=${`width:${pct(st.cache_bytes)}`}></span></div>
    <div class="disk__legend"><span><i class="a"></i>${t("settings.disk_models", { size: fmt.bytes(st.models_bytes) })}</span>
      <span><i class="b"></i>${t("settings.disk_projects", { size: fmt.bytes(st.projects_bytes) })}</span>
      <span><i class="c"></i>${t("settings.disk_cache", { size: fmt.bytes(st.cache_bytes) })}</span></div>
    <div class="disk__act"><${Button} size="lg" loading=${freeing} disabled=${st.cache_bytes === 0} onClick=${free}>${t("settings.free_up")}<//>
      <span class="faint">${t("settings.free_up_help")}</span></div>
  </div>`;
}

export function Settings() {
  const lang = useStore((s) => s.lang);
  const [prefs, setPrefs] = useState(null);
  useEffect(() => { api.settings().then(setPrefs).catch(() => null); }, []);
  const patch = async (p) => { try { setPrefs(await api.patchSettings(p)); } catch (e) { toast(t(`errors.${e.code}.title`)); } };
  return html`<main class="page settings-page" id="main">
    <div class="label">${t("settings.eyebrow")}</div>
    <h1 class="title-1">${t("settings.title")}</h1>
    <div class="settings" style="margin-top:24px">
      <${Row} label=${t("settings.language")}>
        <${Segmented} label=${t("settings.language")} mono=${false} value=${lang} onChange=${(v) => setLang(v)}
          options=${[{ value: "es", label: t("languages.es") }, { value: "en", label: t("languages.en") }]} /><//>
      <${Row} label=${t("settings.theme")} help=${t("settings.theme_help")}><${ThemeSwitch} /><//>
      ${prefs && html`
        <${Row} label=${t("settings.output")}><${OutputFolder} settings=${prefs} onChange=${setPrefs} /><//>
        <${Row} label=${t("settings.quality")} help=${t(`settings.quality_help_${prefs.quality}`)}>
          <${Segmented} label=${t("settings.quality")} mono=${false} value=${prefs.quality} onChange=${(v) => patch({ quality: v })}
            options=${["light", "standard", "high"].map((v) => ({ value: v, label: t(`settings.quality_${v}`) }))} /><//>
        <${Row} label=${t("settings.extras")}>
          <label class="inline-check"><${Checkbox} checked=${prefs.hardware} onChange=${(v) => patch({ hardware: v })} label=${t("settings.hardware")} /> ${t("settings.hardware")}</label>
          <label class="inline-check"><${Checkbox} checked=${prefs.loudnorm} onChange=${(v) => patch({ loudnorm: v })} label=${t("settings.loudnorm")} /> ${t("settings.loudnorm")}</label><//>`}
      <div class="settings__row settings__row--top"><span class="label">${t("settings.models")}</span><${Models} /></div>
      <div class="settings__row settings__row--top"><span class="label">${t("settings.disk")}</span><${Disk} /></div>
    </div>
  </main>`;
}
