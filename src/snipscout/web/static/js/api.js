// API client for /api/v1. The session cookie is sent automatically (same origin).
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(status, body) {
    const err = (body && body.error) || {};
    super(err.message || `HTTP ${status}`);
    this.status = status;
    this.code = err.code || "unknown";
    this.details = err.details || null;
  }
}

async function request(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  status: () => request("GET", "/system/status"),
  projects: () => request("GET", "/projects"),
  project: (id) => request("GET", `/projects/${id}`),
  createProject: (path, settings) => request("POST", "/projects", { path, settings }),
  patchProject: (id, patch) => request("PATCH", `/projects/${id}`, patch),
  deleteProject: (id) => request("DELETE", `/projects/${id}`),
  analyze: (id, settings) => request("POST", `/projects/${id}/analyze`, settings),
  cancel: (id) => request("POST", `/projects/${id}/cancel`),
  clips: (id) => request("GET", `/projects/${id}/clips`),
  patchClip: (id, cid, patch) => request("PATCH", `/projects/${id}/clips/${cid}`, patch),
  render: (id, opts) => request("POST", `/projects/${id}/render`, opts || {}),
  reveal: (id) => request("POST", `/projects/${id}/reveal`),
  waveform: (id, points = 800) => request("GET", `/projects/${id}/waveform?points=${points}`),
  mediaUrl: (id) => `${BASE}/projects/${id}/media`,
  thumbUrl: (id, cid) => `${BASE}/projects/${id}/clips/${cid}/thumbnail`,
  zipUrl: (id) => `${BASE}/projects/${id}/export.zip`,

  /** Browser mode: stream a File object to the server. */
  async upload(file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/projects/upload?filename=${encodeURIComponent(file.name)}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        const data = JSON.parse(xhr.responseText || "null");
        xhr.status < 300 ? resolve(data) : reject(new ApiError(xhr.status, data));
      };
      xhr.onerror = () => reject(new ApiError(0, null));
      xhr.send(file);
    });
  },

  /** Project progress events (SSE). Returns a close() function. */
  events(id, onEvent) {
    const es = new EventSource(`${BASE}/projects/${id}/events`);
    es.addEventListener("progress", (m) => onEvent(JSON.parse(m.data)));
    return () => es.close();
  },

  /** Model download progress: POST + streamed SSE body (EventSource cannot POST). */
  async downloadModel(model, onEvent, signal) {
    const res = await fetch(`${BASE}/system/models/download`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }), signal,
    });
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const data = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (data) onEvent(JSON.parse(data.slice(6)));
      }
    }
  },
};

/** Native window helpers (pywebview). Absent in browser mode. */
export const native = {
  available: () => Boolean(window.pywebview && window.pywebview.api),
  pickFiles: () => window.pywebview.api.pick_files(),
  pickFolder: () => window.pywebview.api.pick_folder(),
};
