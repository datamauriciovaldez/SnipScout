// Projects & history: search, rename, open, show exported folder, delete with confirmation.
import { useEffect, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button, Modal, Tag, toast } from "../components.js";
import { fmt, t } from "../i18n.js";
import { navigate } from "../router.js";
import { store } from "../store.js";

const where = (p) => (p.status === "done" ? `/proyecto/${p.id}/exportar` : `/proyecto/${p.id}`);

export function Projects() {
  const [list, setList] = useState(null);
  const [query, setQuery] = useState("");
  const [renaming, setRenaming] = useState(null);
  const [toDelete, setToDelete] = useState(null);
  const load = () => api.projects().then((ps) => { setList(ps); store.set({ projects: ps }); }).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const rename = async (p, name) => {
    setRenaming(null);
    if (!name.trim() || name === p.name) return;
    try { await api.patchProject(p.id, { name: name.trim() }); load(); } catch (e) { toast(t(`errors.${e.code}.title`)); }
  };
  const remove = async () => {
    const p = toDelete; setToDelete(null);
    try { await api.deleteProject(p.id); toast(t("projects.deleted", { name: p.name })); load(); }
    catch (e) { toast(t(`errors.${e.code}.title`)); }
  };
  const reveal = (p) => api.reveal(p.id).catch((e) => toast(t(`errors.${e.code}.title`)));

  if (!list) return html`<div class="page"><div class="skeleton" style="height:28px;width:40%"></div></div>`;
  const q = query.trim().toLowerCase();
  const shown = list.filter((p) => !q || p.name.toLowerCase().includes(q) || p.source.path.toLowerCase().includes(q));
  return html`<main class="page projects" id="main">
    <div class="label">${t("projects.eyebrow")}</div>
    <h1 class="title-1">${t("projects.title")}</h1>
    <div class="projects__tools">
      <input class="input" type="search" placeholder=${t("projects.search")} aria-label=${t("projects.search")} value=${query}
        onInput=${(e) => setQuery(e.currentTarget.value)} />
      <${Button} variant="primary" icon="plus" onClick=${() => navigate("/")}>${t("projects.new")}<//>
    </div>
    ${list.length === 0
      ? html`<div class="empty"><h2 class="title-2">${t("projects.empty_title")}</h2><p class="lead">${t("projects.empty_lead")}</p>
          <div><${Button} variant="primary" size="lg" onClick=${() => navigate("/")}>${t("projects.new")}<//></div></div>`
      : html`<div class="table projects__table">
          <div class="table__head label" aria-hidden="true"><span style="flex:1;padding-left:12px">${t("projects.col_name")}</span>
            <span class="projects__c">${t("projects.col_length")}</span><span class="projects__c">${t("projects.col_clips")}</span>
            <span class="projects__date">${t("projects.col_date")}</span><span class="projects__state">${t("projects.col_state")}</span><span class="projects__act"></span></div>
          ${shown.map((p) => html`<div class="row projects__row">
            <div class="row__main" style="padding-left:12px">
              ${renaming === p.id
                ? html`<input class="input" autofocus value=${p.name} aria-label=${t("projects.rename")}
                    onKeyDown=${(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setRenaming(null); }}
                    onBlur=${(e) => rename(p, e.currentTarget.value)} />`
                : html`<a class="row__title projects__name" href=${`#${where(p)}`}>${p.name}</a>`}
              <div class="row__sub mono">${p.source.path}</div>
            </div>
            <span class="row__cell mono projects__c">${fmt.duration(p.source.duration)}</span>
            <span class="row__cell mono projects__c">${p.clips_total ? t("projects.clips_count", { n: p.clips_included, total: p.clips_total }) : "—"}</span>
            <span class="row__cell mono projects__date">${fmt.date(p.updated_at)}</span>
            <span class="projects__state"><${Tag}>${t(`project_status.${p.job ? (p.job.kind === "render" ? "rendering" : "analyzing") : p.status}`)}<//></span>
            <span class="projects__act">
              <${Button} variant="ghost" onClick=${() => setRenaming(p.id)}>${t("projects.rename")}<//>
              ${p.export_dir && html`<${Button} variant="ghost" icon="folder" aria-label=${t("export.reveal")} onClick=${() => reveal(p)} />`}
              <${Button} variant="ghost" icon="trash" aria-label=${t("projects.delete_named", { name: p.name })} disabled=${Boolean(p.job)} onClick=${() => setToDelete(p)} />
            </span>
          </div>`)}
          ${shown.length === 0 && html`<p class="faint" style="padding:16px 12px">${t("projects.no_match")}</p>`}
        </div>`}
    <${Modal} open=${Boolean(toDelete)} eyebrow=${t("projects.delete")} title=${toDelete ? t("projects.delete_title", { name: toDelete.name }) : ""}
      onClose=${() => setToDelete(null)} actions=${html`<${Button} size="lg" onClick=${remove}>${t("projects.delete_confirm")}<//>
        <${Button} variant="primary" size="lg" onClick=${() => setToDelete(null)}>${t("common.cancel")}<//>`}>
      ${t("projects.delete_body")}<//>
  </main>`;
}
