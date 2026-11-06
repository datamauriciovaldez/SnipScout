# Local API (`/api/v1`)

The UI talks to a FastAPI server bound to `127.0.0.1` on a random free port. It is **not** a public API: it is
documented to make the code easier to follow and to script against your own running app.

## Session and safety

- The launcher opens `/?t=<token>` once; the server answers with a redirect and an `HttpOnly`, `SameSite=Strict`
  cookie. Every `/api` request needs that cookie (or the `X-SnipScout-Token` header), otherwise `401`.
- `Host` must be the server's own `127.0.0.1:<port>` / `localhost:<port>`, and a cross-site `Origin` is refused
  (`403`). No CORS headers are sent.
- Project ids are 12 hex characters; file names in exports are checked against the export folder (no traversal).
- Uploads are streamed with a 20 GB limit and sanitised names.

## Errors

Errors are JSON: `{"error": {"code": "...", "message": "...", "details": "..."}}`. `code` is stable and matches an
i18n key `errors.<code>` (see [troubleshooting](troubleshooting.md)). Typical statuses: `400 bad_request`,
`404 project_not_found`, `409 job_busy`, `422 no_speech`, `502 model_download` / `ollama_failed`,
`503 ffmpeg_missing` / `offline` / `ollama_unavailable`.

## Progress (SSE)

`GET /projects/{id}/events` is a `text/event-stream`. Each `progress` event carries a `JobEvent`:

```json
{"stage": "transcribe", "progress": 0.42, "message": "stage.transcribe",
 "params": {"overall": 0.39, "processed_s": 312.5, "total_s": 744.0, "eta_s": 210, "text": "..."},
 "state": "running", "error_code": null}
```

`state` ends as `done`, `error` or `cancelled`. Events of the current job are replayed to late subscribers.
Stages: analyze → `prepare_audio`, `transcribe`, `understand`, `find_moments`; render → `render` (per clip, with
`clip_id`, `title`); improve → `improve` (with `done`, `total`). The final event has `stage: "done"`. Model downloads stream their own
SSE body from `POST /system/models/download`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/system/status` | Version, OS/CPU/RAM, ffmpeg/ffprobe, speech models (installed, size, measured speed), recommended model, first run, offline flag, output folder. |
| POST | `/system/models/download` | Download a speech model (`{"model": "base"}`); SSE with bytes, resumable. |
| DELETE | `/system/models/{name}` | Delete a downloaded speech model. |
| GET | `/system/storage` | Disk used by models, projects and caches, free space. |
| POST | `/system/storage/free` | Delete caches and orphan uploads only (never clips or projects). |
| GET | `/system/ollama` | Is a local Ollama running, its models, the model that would be used. |
| GET / PATCH | `/settings` | Output folder, export quality, hardware encoder, loudnorm, Ollama model. |
| GET / POST | `/projects` | List projects / create one from a local path (`{"path", "settings"}`). |
| POST | `/projects/upload` | Browser mode: stream a file in the body (`?filename=`). |
| GET / PATCH / DELETE | `/projects/{id}` | Read, rename or change settings, delete (cancels a running job). |
| POST | `/projects/{id}/analyze` | Start (or resume) analysis. `202`. |
| POST | `/projects/{id}/improve` | Optional: re-rank with local Ollama (`{"model"}` optional). `202`. |
| POST | `/projects/{id}/render` | Render (`{"clip_ids", "out_dir", "hardware", "loudnorm"}`, all optional). `202`. |
| POST | `/projects/{id}/cancel` | Cancel the running job; work done so far is kept. |
| GET | `/projects/{id}/events` | SSE progress (above). |
| GET | `/projects/{id}/clips` | Clips with signals, reasons, `contributions` (score points per signal), `ai_score`, `ai_title`. |
| PATCH | `/projects/{id}/clips/{cid}` | `start`, `end`, `title`, `included`, `subtitle_style`, `text_overrides`, `framing` (`auto`/`center`/`manual`), `focus_x` (0–1). |
| GET | `/projects/{id}/clips/{cid}/thumbnail` | JPEG thumbnail. |
| GET | `/projects/{id}/clips/{cid}/framing` | Whether the export crops, and the face focus *Automatic* framing would use (`start`/`end` for a draft). |
| POST | `/projects/{id}/clips/{cid}/preview-frame` | One real frame (JPEG) for an unsaved draft (`at`, `start`, `end`, style, overrides). |
| GET | `/projects/{id}/transcript` | Words and sentences. |
| GET | `/projects/{id}/media` | Source media with HTTP Range support (`?variant=proxy`: the WebM preview copy). |
| GET / POST | `/projects/{id}/media/proxy` | Status of / start the WebM preview copy for formats the window can't play. |
| GET | `/projects/{id}/waveform` | Peaks (`points`, optional `start`/`end` for the zoomed timeline). |
| GET | `/projects/{id}/exports` | Files of the last export with caption text. |
| GET | `/projects/{id}/exports/{name}` | One exported file (Range, download). |
| GET | `/projects/{id}/export.zip` | Everything exported, zipped. |
| POST | `/projects/{id}/reveal` | Show the export folder in the system file manager. |
