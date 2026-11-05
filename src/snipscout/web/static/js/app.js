// SnipScout frontend entry (Preact + htm, no build step).
import { useEffect } from "preact/hooks";
import { html, render } from "./html.js";
import { api } from "./api.js";
import { fmt, preferredLang, setLang, t } from "./i18n.js";
import { useRoute } from "./router.js";
import { store, useStore } from "./store.js";

const LOGO = html`<span class="brand__mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5L20 18M8 16.5L20 6"/></svg></span>`;

function Topbar({ route }) {
  const status = useStore((s) => s.status);
  const tab = (name, href, key) => html`<a href=${href} aria-current=${route.name === name ? "page" : undefined}>${t(key)}</a>`;
  return html`<header class="topbar">
    <div class="topbar__left">
      <a class="brand" href="#/">${LOGO}SnipScout</a>
      <nav class="nav" aria-label=${t("nav.label")}>${tab("home", "#/", "nav.new")}${tab("settings", "#/ajustes", "nav.settings")}</nav>
    </div>
    <div class="topbar__right">
      <span class="label status-dot">${status && status.offline ? t("status.offline") : t("status.local")}</span>
    </div>
  </header>`;
}

export function ErrorNotice({ error, action }) {
  const details = [`code: ${error.code}`, error.message, error.details].filter(Boolean).join("\n");
  const copy = async () => { try { await navigator.clipboard.writeText(details); } catch (e) { /* selection fallback is fine */ } };
  return html`<section class="notice" role="alert">
    <div class="notice__code">${t("error.label")} · ${error.code}</div>
    <h1 class="title-1" style="margin:12px 0">${t(`errors.${error.code}.title`)}</h1>
    <p class="lead">${t(`errors.${error.code}.body`)}</p>
    ${action}
    <details><summary>${t("error.copy_details")}</summary><pre>${details}</pre>
      <button class="btn btn--ghost" type="button" onClick=${copy}>${t("common.copy")}</button></details>
  </section>`;
}

function Home() {
  const status = useStore((s) => s.status);
  const projects = useStore((s) => s.projects);
  if (!status) return html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`;
  if (!status.ffmpeg.ok) return html`<div class="page"><${ErrorNotice} error=${{ code: "ffmpeg_missing" }} /></div>`;
  const model = status.models.find((m) => m.name === status.recommended_model);
  return html`<main class="page" id="main">
    <div class="label">${t("home.eyebrow")}</div>
    <h1 class="title-1">${t("home.title")}</h1>
    <p class="lead">${t("home.lead")}</p>
    <section class="section" aria-labelledby="sys">
      <div class="label" id="sys">${t("home.system")}</div>
      <div class="table">
        <div class="row kv"><div class="row__main">${t("home.video_engine")}</div><span class="row__cell mono">${status.ffmpeg.source}</span><span class="status-ok">${t("common.ok")}</span></div>
        <div class="row kv"><div class="row__main">${t("home.speech_model")}</div><span class="row__cell mono">${t(`models.${model.label}`)} · ${fmt.bytes(model.bytes)}</span>
          <span class=${model.installed ? "status-ok" : "status-bad"}>${model.installed ? t("home.installed") : t("home.not_installed")}</span></div>
        <div class="row kv"><div class="row__main">${t("home.computer")}</div><span class="row__cell mono">${t("home.hardware", { cpu: status.hardware.cpu_threads, ram: status.hardware.ram_gb })}</span><span></span></div>
      </div>
    </section>
    <section class="section" aria-labelledby="recent">
      <div class="label" id="recent">${t("home.recent")}</div>
      ${projects.length
        ? html`<div class="table">${projects.map((p) => html`<a class="row kv" href=${`#/proyecto/${p.id}`} style="color:inherit;text-decoration:none">
            <div class="row__main"><div class="row__title">${p.name}</div></div>
            <span class="row__cell mono">${fmt.duration(p.source.duration)}</span>
            <span class="row__cell mono">${fmt.date(p.updated_at)}</span>
            <span class="tag">${t(`project_status.${p.status}`)}</span></a>`)}</div>`
        : html`<div class="empty"><p class="lead">${t("home.no_projects")}</p></div>`}
    </section>
  </main>`;
}

function Settings() {
  const lang = useStore((s) => s.lang);
  useEffect(() => { window.SnipScoutTheme && window.SnipScoutTheme.bind(); }, []);
  return html`<main class="page" id="main">
    <div class="label">${t("settings.eyebrow")}</div>
    <h1 class="title-1">${t("settings.title")}</h1>
    <div class="settings" style="margin-top:24px">
      <div class="settings__row"><span class="label" id="l-lang">${t("settings.language")}</span>
        <div class="seg seg--sans" role="group" aria-labelledby="l-lang">
          ${["es", "en"].map((code) => html`<button type="button" aria-pressed=${String(lang === code)} onClick=${() => setLang(code)}>${t(`languages.${code}`)}</button>`)}
        </div></div>
      <div class="settings__row"><span class="label" id="l-theme">${t("settings.theme")}</span>
        <div class="seg seg--sans" data-theme-switch role="group" aria-labelledby="l-theme">
          <button type="button" data-mode="light">${t("settings.theme_light")}</button>
          <button type="button" data-mode="dark">${t("settings.theme_dark")}</button>
          <button type="button" data-mode="system">${t("settings.theme_system")}</button>
        </div></div>
    </div>
  </main>`;
}

function Placeholder({ titleKey }) {
  return html`<main class="page" id="main"><div class="empty">
    <div class="label">${t("placeholder.eyebrow")}</div>
    <h1 class="title-2">${t(titleKey)}</h1>
    <p class="lead">${t("placeholder.body")}</p>
    <a class="btn btn--outline btn--lg" href="#/">${t("common.back_home")}</a>
  </div></main>`;
}

function App() {
  const route = useRoute();
  useStore((s) => s.lang); // re-render on language change
  const error = useStore((s) => s.error);
  const views = {
    home: () => html`<${Home} />`,
    settings: () => html`<${Settings} />`,
    welcome: () => html`<${Placeholder} titleKey="placeholder.welcome" />`,
    project: () => html`<${Placeholder} titleKey="placeholder.project" />`,
    clip: () => html`<${Placeholder} titleKey="placeholder.clip" />`,
    notFound: () => html`<${Placeholder} titleKey="placeholder.not_found" />`,
  };
  return html`<a class="skip-link" href="#main">${t("common.skip")}</a>
    <${Topbar} route=${route} />
    <div class="app-main">${error ? html`<div class="page"><${ErrorNotice} error=${error} /></div>` : views[route.name]()}</div>`;
}

async function boot() {
  await setLang(preferredLang());
  render(html`<${App} />`, document.getElementById("app"));
  try {
    const [status, projects] = await Promise.all([api.status(), api.projects()]);
    store.set({ status, projects });
  } catch (err) {
    store.set({ error: { code: err.code || "server_unreachable", message: err.message, details: err.details } });
  }
}

boot();
