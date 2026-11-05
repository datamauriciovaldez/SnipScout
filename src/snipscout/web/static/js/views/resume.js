// "Continue where you left off": remember the last project screen and offer it on Home.
import { useEffect, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button } from "../components.js";
import { fmt, t } from "../i18n.js";
import { navigate } from "../router.js";

const KEY = "snipscout.last";
const PLACES = { project: "resume.results", clip: "resume.clip", export: "resume.export" };

export function rememberLocation(route) {
  if (!PLACES[route.name]) return;
  try {
    localStorage.setItem(KEY, JSON.stringify({ name: route.name, params: route.params, hash: location.hash, at: Date.now() }));
  } catch (e) { /* not remembered this time */ }
}

function readLast() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; }
}

export function ResumeBanner() {
  const [item, setItem] = useState(null);
  useEffect(() => {
    const last = readLast();
    if (!last) return;
    api.project(last.params[0]).then((p) => setItem({ last, project: p })).catch(() => {
      try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
    });
  }, []);
  if (!item) return null;
  const { last, project } = item;
  const place = t(PLACES[last.name], { n: last.params[1] ? last.params[1].slice(1) : "" });
  return html`<section class="resume" aria-label=${t("resume.title")}>
    <div><div class="label">${t("resume.title")}</div>
      <div class="resume__name">${project.name}</div>
      <div class="resume__meta mono">${place} · ${fmt.date(new Date(last.at).toISOString())}</div></div>
    <${Button} variant="primary" onClick=${() => navigate(last.hash.replace(/^#/, ""))}>${t("resume.continue")}<//>
  </section>`;
}
