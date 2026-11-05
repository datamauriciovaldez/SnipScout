// SnipScout frontend entry (Preact + htm, no build step).
import { useEffect } from "preact/hooks";
import { html, render } from "./html.js";
import { api } from "./api.js";
import { Button, ErrorNotice, Toaster } from "./components.js";
import { Logo } from "./icons.js";
import { fmt, preferredLang, setLang, t } from "./i18n.js";
import { navigate, useRoute } from "./router.js";
import { Home } from "./views/home.js";
import { Welcome } from "./views/welcome.js";
import { store, useStore } from "./store.js";

function Topbar({ route }) {
  const status = useStore((s) => s.status);
  const tab = (name, href, key) => html`<a href=${href} aria-current=${route.name === name ? "page" : undefined}>${t(key)}</a>`;
  return html`<header class="topbar">
    <div class="topbar__left">
      <a class="brand" href="#/"><${Logo} />SnipScout</a>
      <nav class="nav" aria-label=${t("nav.label")}>${tab("home", "#/", "nav.new")}${tab("settings", "#/ajustes", "nav.settings")}</nav>
    </div>
    <div class="topbar__right">
      <span class="label status-dot">${status && status.offline ? t("status.offline") : t("status.local")}</span>
    </div>
  </header>`;
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
    <div><${Button} size="lg" onClick=${() => (location.hash = "#/")}>${t("common.back_home")}<//></div>
  </div></main>`;
}

function App() {
  const route = useRoute();
  useStore((s) => s.lang); // re-render on language change
  const error = useStore((s) => s.error);
  const status = useStore((s) => s.status);
  useEffect(() => {
    if (status && status.first_run && route.name === "home") navigate("/bienvenida");
  }, [status, route.name]);
  const ready = (view) => (status ? view() : html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`);
  const views = {
    home: () => ready(() => html`<${Home} />`),
    settings: () => html`<${Settings} />`,
    welcome: () => ready(() => html`<${Welcome} />`),
    project: () => html`<${Placeholder} titleKey="placeholder.project" />`,
    clip: () => html`<${Placeholder} titleKey="placeholder.clip" />`,
    notFound: () => html`<${Placeholder} titleKey="placeholder.not_found" />`,
  };
  return html`<a class="skip-link" href="#main">${t("common.skip")}</a>
    <${Topbar} route=${route} />
    <div class="app-main">${error ? html`<div class="page"><${ErrorNotice} error=${error}
      action=${html`<${Button} variant="primary" size="lg" onClick=${() => location.reload()}>${t("common.retry")}<//>`} /></div>` : views[route.name]()}</div>
    <${Toaster} />`;
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
