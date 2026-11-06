// Reusable Preact components. Styling lives in css/components.css; colours only in css/tokens.css.
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "./html.js";
import { Icon } from "./icons.js";
import { t } from "./i18n.js";
import { store, useStore } from "./store.js";

const cx = (...parts) => parts.filter(Boolean).join(" ");

/** Screen-reader progress: announces `message` only when `step` changes (stage, every 10 %), not on every tick. */
export function LiveStatus({ message, step }) {
  const [said, setSaid] = useState(message);
  useEffect(() => setSaid(message), [step]);
  return html`<div class="sr-only" role="status" aria-live="polite">${said}</div>`;
}

/** variant: primary | accent | outline | ghost ; size: md | lg ; icon-only when `icon` and no children. */
export function Button({ variant = "outline", size = "md", icon, kbd, loading, block, class: extra, children, ...rest }) {
  const iconOnly = icon && (children === undefined || children === null);
  return html`<button type="button" class=${cx("btn", `btn--${variant}`, size === "lg" && "btn--lg", iconOnly && "btn--icon",
      block && "btn--block", loading && "is-loading", extra)} aria-busy=${loading ? "true" : undefined} ...${rest}>
    ${icon && html`<${Icon} name=${icon} />`}${children}${kbd && html`<kbd>${kbd}</kbd>`}
  </button>`;
}

export function Checkbox({ checked, onChange, label, ...rest }) {
  return html`<input class="check" type="checkbox" checked=${checked} aria-label=${label}
    onChange=${(e) => onChange && onChange(e.currentTarget.checked)} ...${rest} />`;
}

/** options: [{ value, label }] ; mono=false uses the sans variant. */
export function Segmented({ options, value, onChange, label, mono = true }) {
  return html`<div class=${cx("seg", !mono && "seg--sans")} role="group" aria-label=${label}>
    ${options.map((o) => html`<button type="button" aria-pressed=${String(o.value === value)}
      onClick=${() => onChange && onChange(o.value)}>${o.label}</button>`)}
  </div>`;
}

export function Tag({ children }) {
  return html`<span class="tag">${children}</span>`;
}

/** Score 0-100. High scores (≥ threshold) use the accent; low ones use ink. */
export function ScoreBar({ value, threshold = 85 }) {
  const v = Math.round(value);
  return html`<div class=${cx("score", v >= threshold && "score--high")} style=${`--v:${v}`}>
    <div class="score__track" aria-hidden="true"><div class="score__fill"></div></div>
    <span class="score__value" aria-label=${t("components.score", { v })}>${v}</span>
  </div>`;
}

/** value 0..1, or null for indeterminate. */
export function Progress({ value, label }) {
  const indeterminate = value === null || value === undefined;
  return html`<div class=${cx("progress", indeterminate && "progress--indeterminate")} role="progressbar"
    aria-label=${label} aria-valuemin="0" aria-valuemax="100" aria-valuenow=${indeterminate ? undefined : Math.round(value * 100)}>
    <div class="progress__fill" style=${indeterminate ? "" : `--p:${Math.max(0, Math.min(1, value))}`}></div>
  </div>`;
}

/** Thumbnail with grain. `src` = real frame; otherwise a muted placeholder gradient. */
export function Thumb({ src, variant, badge, alt = "" }) {
  return html`<div class=${cx("thumb", variant && `thumb--${variant}`)}>
    ${src && html`<img src=${src} alt=${alt} loading="lazy" style="width:100%;height:100%;object-fit:cover" />`}
    ${badge && html`<span class="thumb__badge">${badge}</span>`}
  </div>`;
}

/** Waveform from peaks (0..1). classFor(i, n) → "", "in", "done", "todo". */
export function Wave({ peaks, height = 54, classFor, barWidth = 2, children }) {
  const n = peaks.length;
  return html`<div class="wave" style=${`height:${height}px`} aria-hidden="true">
    ${peaks.map((p, i) => html`<i class=${classFor ? classFor(i, n) : ""}
      style=${`--h:${Math.max(2, p * height).toFixed(1)};--bar-w:${barWidth}px`}></i>`)}
    ${children}
  </div>`;
}

export function Field({ id, label, hint, error, children }) {
  return html`<div class=${cx("field", error && "field--error")}>
    <label class="label" for=${id}>${label}</label>${children}
    ${(error || hint) && html`<div class="field__hint" id=${`${id}-hint`}>${error || hint}</div>`}
  </div>`;
}

/** Modal dialog: focus trap, Esc closes, focus returns to the opener. */
export function Modal({ open, title, eyebrow, onClose, children, actions, wide }) {
  const box = useRef(null);
  const opener = useRef(null);
  // Capture the opener during the render that opens the dialog: effects run after paint, when the
  // active element is no longer reliable.
  if (open && !opener.current) opener.current = document.activeElement;
  useEffect(() => {
    if (!open) return undefined;
    const focusables = () => [...box.current.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")];
    (focusables()[0] || box.current).focus();
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      if (e.key === "Tab") {
        const f = focusables(); if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const back = opener.current;
      opener.current = null;
      // Wait until the dialog has left the DOM, then give focus back.
      setTimeout(() => back && back.isConnected && back.focus(), 0);
    };
  }, [open]);
  return html`<div class=${cx("scrim", open && "is-open")} aria-hidden=${open ? "false" : "true"}
      onClick=${(e) => e.target === e.currentTarget && onClose()}>
    ${open && html`<div class=${cx("modal", wide && "modal--wide")} role="dialog" aria-modal="true" aria-labelledby="modal-title" ref=${box} tabindex="-1">
      ${eyebrow && html`<div class="label">${eyebrow}</div>`}
      <h2 class="title-2" id="modal-title" style="margin-top:6px">${title}</h2>
      <div class="muted" style="margin-top:8px">${children}</div>
      <div class="modal__actions">${actions}</div>
    </div>`}
  </div>`;
}

/** Toasts: call toast("text") anywhere; render <Toaster/> once. */
let toastTimer;
export function toast(text, action) {
  clearTimeout(toastTimer);
  store.set({ toast: { text, action, id: Date.now() } });
  toastTimer = setTimeout(() => store.set({ toast: null }), action ? 6000 : 3200);
}

export function Toaster() {
  const item = useStore((s) => s.toast);
  return html`<div class=${cx("toast", item && "is-open")} role="status" aria-live="polite">
    ${item && html`<span>${item.text}</span>`}
    ${item && item.action && html`<${Button} variant="ghost" onClick=${() => { item.action.run(); store.set({ toast: null }); }}>${item.action.label}<//>`}
  </div>`;
}

/** steps: [labelKey…] ; current: 1-based. */
export function Stepper({ steps, current }) {
  return html`<div>
    <div class="label" aria-hidden="true"><span style="color:var(--text)">${String(current).padStart(2, "0")}</span> / ${String(steps.length).padStart(2, "0")}</div>
    <nav class="stepper" aria-label=${t("components.steps")}>
      ${steps.map((label, i) => html`<span class=${cx("stepper__item", i + 1 < current && "is-done")}
        aria-current=${i + 1 === current ? "step" : undefined}><span class="mono">${String(i + 1).padStart(2, "0")}</span> ${label}</span>`)}
    </nav>
  </div>`;
}

/** Full-width help screen for a typed error code (texts from i18n errors.<code>). */
export function ErrorNotice({ error, action }) {
  const details = [`code: ${error.code}`, error.message, error.details].filter(Boolean).join("\n");
  const copy = async () => {
    try { await navigator.clipboard.writeText(details); toast(t("components.copied")); }
    catch (e) { toast(t("components.copy_failed")); }
  };
  return html`<section class="notice" role="alert">
    <div class="notice__code">${t("error.label")} · ${error.code}</div>
    <h1 class="title-1" style="margin:12px 0">${t(`errors.${error.code}.title`)}</h1>
    <p class="lead">${t(`errors.${error.code}.body`)}</p>
    ${action && html`<div style="display:flex;gap:8px;margin-top:24px">${action}</div>`}
    <details><summary>${t("error.copy_details")}</summary><pre>${details}</pre>
      <div style="display:flex;justify-content:flex-end"><${Button} variant="ghost" icon="copy" onClick=${copy}>${t("common.copy")}<//></div>
    </details>
  </section>`;
}
