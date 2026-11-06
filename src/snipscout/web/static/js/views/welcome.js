// First run: 01 language → 02 computer check + model choice → 03 one-time model download.
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "../html.js";
import { api } from "../api.js";
import { Button, LiveStatus, Progress, Stepper } from "../components.js";
import { fmt, setLang, t } from "../i18n.js";
import { navigate } from "../router.js";
import { store, useStore } from "../store.js";

function LanguageStep() {
  const lang = useStore((s) => s.lang);
  return html`<section class="step">
    <div class="label">${t("welcome.lang_eyebrow")}</div>
    <h1 class="title-1">${t("welcome.lang_title")}</h1>
    <p class="lead">${t("welcome.lang_lead")}</p>
    <div class="choice-list" role="radiogroup" aria-label=${t("settings.language")}>
      ${["es", "en"].map((code) => html`<label class="choice-row">
        <input class="radio" type="radio" name="lang" checked=${lang === code} onChange=${() => setLang(code)} />
        <span class="choice-row__title">${t(`languages.${code}`)}</span></label>`)}
    </div>
  </section>`;
}

function ComputerStep({ model, setModel }) {
  const status = useStore((s) => s.status);
  const hw = status.hardware;
  return html`<section class="step">
    <div class="label">${t("welcome.check_eyebrow")}</div>
    <h1 class="title-1">${t("welcome.check_title")}</h1>
    <p class="lead">${t("welcome.check_lead")}</p>
    <div class="table checks">
      <div class="row kv"><div class="row__main">${t("welcome.cpu")}</div><span class="row__cell mono">${t("welcome.cpu_value", { n: hw.cpu_threads })}</span><span class="status-ok">${t("common.ok")}</span></div>
      <div class="row kv"><div class="row__main">${t("welcome.ram")}</div><span class="row__cell mono">${t("welcome.ram_value", { gb: hw.ram_gb })}</span>
        <span class=${hw.ram_gb >= 4 ? "status-ok" : "status-bad"}>${hw.ram_gb >= 4 ? t("common.ok") : t("welcome.low")}</span></div>
      <div class="row kv"><div class="row__main">${t("welcome.gpu")}</div><span class="row__cell mono">${t("welcome.gpu_value")}</span><span class="faint mono">—</span></div>
      <div class="row kv"><div class="row__main">${t("home.video_engine")}</div><span class="row__cell mono">${status.ffmpeg.source}</span>
        <span class=${status.ffmpeg.ok ? "status-ok" : "status-bad"}>${status.ffmpeg.ok ? t("common.ok") : t("welcome.missing")}</span></div>
    </div>
    <div class="label" style="margin-top:28px">${t("welcome.model_eyebrow")}</div>
    <div class="choice-list" role="radiogroup" aria-label=${t("welcome.model_eyebrow")}>
      ${status.models.map((m) => html`<label class=${`choice-row choice-row--model${model === m.name ? " is-selected" : ""}`}>
        <input class="radio" type="radio" name="model" checked=${model === m.name} onChange=${() => setModel(m.name)} />
        <span><span class="choice-row__title">${t(`models.${m.label}`)}
          ${m.name === status.recommended_model && html`<span class="tag" style="margin-left:6px">${t("welcome.recommended")}</span>`}</span>
          <small class="choice-row__sub">${t(`welcome.model_${m.label}`)}</small></span>
        <span class="mono muted">${fmt.bytes(m.bytes)}</span>
        <span class="mono muted">${t("welcome.per_hour", { min: Math.max(1, Math.round(m.rtf * 60)) })}</span>
      </label>`)}
    </div>
    ${status.models.some((m) => !m.measured) && html`<p class="field__hint" style="margin-top:8px">${t("welcome.estimate_note")}</p>`}
  </section>`;
}

function DownloadStep({ model, onDone }) {
  const spec = useStore((s) => s.status.models.find((m) => m.name === model));
  const [state, setState] = useState(spec.installed ? "done" : "running"); // running | paused | done | error
  const [prog, setProg] = useState({ done: 0, total: spec.bytes, speed: 0 });
  const [error, setError] = useState(null);
  const ctrl = useRef(null);

  async function start() {
    setState("running"); setError(null);
    ctrl.current = new AbortController();
    const sample = { t: performance.now(), done: null };
    try {
      await api.downloadModel(model, (e) => {
        if (e.state === "done") setState("done");
        else if (e.state === "paused") setState("paused");
        else if (e.state === "error") { setState("error"); setError(e.error_code); }
        else if (e.done !== undefined) {
          const now = performance.now();
          if (sample.done === null) Object.assign(sample, { t: now, done: e.done }); // resumed bytes don't count
          const elapsed = (now - sample.t) / 1000;
          setProg((p) => ({ done: e.done, total: e.total, speed: elapsed >= 0.5 ? (e.done - sample.done) / elapsed : p.speed }));
        }
      }, ctrl.current.signal);
    } catch (err) {
      if (err.name === "AbortError") setState("paused");
      else { setState("error"); setError(err.code || "model_download"); }
    }
  }
  useEffect(() => { if (state === "running") start(); return () => ctrl.current && ctrl.current.abort(); }, []);
  useEffect(() => { if (state === "done") onDone(); }, [state]);

  const frac = prog.total ? prog.done / prog.total : 0;
  const left = prog.speed > 0 ? (prog.total - prog.done) / prog.speed : null;
  return html`<section class="step">
    <div class="label">${t("welcome.dl_eyebrow", { model: t(`models.${spec.label}`) })}</div>
    <h1 class="title-1">${state === "done" ? t("welcome.dl_done_title") : t("welcome.dl_title")}</h1>
    <p class="lead">${t("welcome.dl_lead")}</p>
    <${LiveStatus} step=${`${state}|${Math.floor(frac * 10)}`} message=${state === "done" ? t("welcome.dl_done_title") : `${Math.floor(frac * 100)} %`} />
    <div class="dl">
      <div class="dl__nums"><span class="dl__pct mono">${Math.floor(frac * 100)} %</span>
        <span class="mono muted">${state === "done" ? t("welcome.dl_verified", { size: fmt.bytes(prog.total) })
          : t("welcome.dl_bytes", { done: fmt.bytes(prog.done), total: fmt.bytes(prog.total) })}${
          state === "running" && left !== null ? ` · ${t("welcome.dl_left", { s: Math.ceil(left) })}` : ""}</span></div>
      <${Progress} value=${state === "done" ? 1 : frac} label=${t("welcome.dl_title")} />
      <div class="dl__actions">
        ${state === "running" && html`<${Button} onClick=${() => ctrl.current && ctrl.current.abort()}>${t("welcome.pause")}<//>`}
        ${(state === "paused" || state === "error") && html`<${Button} variant="primary" onClick=${start}>${state === "paused" ? t("welcome.resume") : t("common.retry")}<//>`}
        <span class="faint">${state === "error" ? t(`errors.${error}.body`) : t("welcome.dl_resume_note")}</span>
      </div>
    </div>
    <div class="once"><strong>${t("welcome.once_title")}</strong><div class="muted">${t("welcome.once_body")}</div></div>
  </section>`;
}

export function Welcome() {
  const status = useStore((s) => s.status);
  const [step, setStep] = useState(1);
  const [model, setModel] = useState(status.recommended_model);
  const [done, setDone] = useState(false);
  const finish = async () => {
    store.set({ status: await api.status() });
    navigate("/");
  };
  const steps = [t("welcome.step_lang"), t("welcome.step_check"), t("welcome.step_model")];
  return html`<main class="welcome" id="main">
    <${Stepper} steps=${steps} current=${step} />
    ${step === 1 && html`<${LanguageStep} />`}
    ${step === 2 && html`<${ComputerStep} model=${model} setModel=${setModel} />`}
    ${step === 3 && html`<${DownloadStep} model=${model} onDone=${() => setDone(true)} />`}
    <div class="welcome__nav">
      <${Button} variant="ghost" size="lg" style=${step === 1 ? "visibility:hidden" : ""} onClick=${() => setStep(step - 1)}>${t("welcome.back")}<//>
      ${step < 3
        ? html`<${Button} variant="primary" size="lg" disabled=${step === 2 && !status.ffmpeg.ok} onClick=${() => setStep(step + 1)}>
            ${step === 2 ? t("welcome.download_continue") : t("welcome.continue")}<//>`
        : html`<${Button} variant="primary" size="lg" disabled=${!done} onClick=${finish}>${t("welcome.start")}<//>`}
    </div>
  </main>`;
}
