// i18n: every visible string comes from /static/i18n/<lang>.json (a test checks both files and the keys used here).
import { store } from "./store.js";

const LANGS = ["es", "en"];
const KEY = "snipscout.lang";
let dict = {};

export function preferredLang() {
  try {
    const saved = localStorage.getItem(KEY);
    if (LANGS.includes(saved)) return saved;
  } catch (e) { /* storage blocked: fall back to the browser language */ }
  const nav = (navigator.language || "es").slice(0, 2);
  return LANGS.includes(nav) ? nav : "es";
}

export async function setLang(lang, base = "/static") {
  const res = await fetch(`${base}/i18n/${lang}.json`, { cache: "no-cache" });
  dict = await res.json();
  document.documentElement.lang = lang;
  try { localStorage.setItem(KEY, lang); } catch (e) { /* not persisted this time */ }
  store.set({ lang });
}

/** t("home.title", { n: 3 }) → string with {n} replaced. Missing keys show the key (and a test fails). */
export function t(key, params) {
  let s = key.split(".").reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), dict);
  if (typeof s !== "string") return key;
  if (params) s = s.replace(/\{(\w+)\}/g, (_, k) => (params[k] !== undefined ? fmtValue(params[k]) : `{${k}}`));
  return s;
}

function fmtValue(v) {
  return typeof v === "number" ? new Intl.NumberFormat(store.get().lang).format(v) : String(v);
}

export const fmt = {
  number: (n, opts) => new Intl.NumberFormat(store.get().lang, opts).format(n),
  /** 3725.4 → "1:02:05" ; 42 → "0:42" */
  duration(seconds) {
    const s = Math.max(0, Math.round(seconds));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
  },
  bytes(n) {
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1000 && i < units.length - 1) { n /= 1000; i++; }
    return `${new Intl.NumberFormat(store.get().lang, { maximumFractionDigits: i > 1 ? 1 : 0 }).format(n)} ${units[i]}`;
  },
  date: (iso) => new Intl.DateTimeFormat(store.get().lang, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso)),
};
