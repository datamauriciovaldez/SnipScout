// htm bound to Preact: html`<div class=${x}>…</div>` without a build step.
import { h, render, Fragment } from "preact";
import htm from "htm";

export const html = htm.bind(h);
export { h, render, Fragment };
