// One icon set: 24×24 grid, 2px round strokes, currentColor. Decorative unless a label is given.
import { html } from "./html.js";

const PATHS = {
  logo: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5L20 18M8 16.5L20 6"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  play: '<path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor" stroke="none"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  upload: '<path d="M12 15V4M7 9l5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
  "chevron-right": '<path d="M9 6l6 6-6 6"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 4.3L2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-9 9"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
};

export const ICON_NAMES = Object.keys(PATHS);

export function Icon({ name, label, size = 16, strokeWidth = 2 }) {
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": "true" };
  return html`<svg viewBox="0 0 24 24" width=${size} height=${size} fill="none" stroke="currentColor" stroke-width=${strokeWidth}
    stroke-linecap="round" stroke-linejoin="round" focusable="false" ...${a11y}
    dangerouslySetInnerHTML=${{ __html: PATHS[name] || "" }}></svg>`;
}

export function Logo() {
  return html`<span class="brand__mark" aria-hidden="true"><${Icon} name="logo" size=${13} strokeWidth=${2.6} /></span>`;
}
