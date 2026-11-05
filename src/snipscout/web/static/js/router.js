// Hash router: "#/", "#/proyecto/:id", "#/proyecto/:id/clip/:cid", "#/ajustes", "#/bienvenida".
import { useEffect, useState } from "preact/hooks";

const ROUTES = [
  ["home", /^\/?$/],
  ["welcome", /^\/bienvenida$/],
  ["settings", /^\/ajustes$/],
  ["project", /^\/proyecto\/([a-f0-9]{12})$/],
  ["clip", /^\/proyecto\/([a-f0-9]{12})\/clip\/(c\d{2})$/],
  ["export", /^\/proyecto\/([a-f0-9]{12})\/exportar$/],
];

export function parse(hash) {
  const path = (hash || "").replace(/^#/, "") || "/";
  for (const [name, re] of ROUTES) {
    const m = path.match(re);
    if (m) return { name, params: m.slice(1) };
  }
  return { name: "notFound", params: [] };
}

export function navigate(path) { location.hash = path; }

export function useRoute() {
  const [route, setRoute] = useState(() => parse(location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(location.hash));
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return route;
}
