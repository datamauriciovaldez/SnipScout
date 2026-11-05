// Minimal global store: one state object, shallow-merge updates, subscriptions, a Preact hook.
import { useEffect, useState } from "preact/hooks";

export function createStore(initial) {
  let state = initial;
  const subs = new Set();
  return {
    get: () => state,
    set(patch) {
      state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
      subs.forEach((fn) => fn(state));
    },
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}

export const store = createStore({
  lang: "es",
  status: null, // /system/status
  projects: [],
  error: null, // { code, message, details }
  toast: null, // { text, action?: { label, run } }
});

export function useStore(select = (s) => s) {
  const [value, setValue] = useState(() => select(store.get()));
  useEffect(() => store.subscribe((s) => setValue(select(s))), []);
  return value;
}
