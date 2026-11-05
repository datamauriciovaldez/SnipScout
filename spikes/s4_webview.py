"""Spike 4: Range-capable media server + seek test in (a) Chromium via Playwright
(browser fallback mode) and (b) pywebview window (Qt backend under Xvfb here).
Usage: s4_webview.py browser|webview"""
import json
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

OUT = Path(__file__).parent / "out"
app = FastAPI()
range_log: list[str] = []

PAGE = """<!doctype html><html><body>
<video id=v src="/media/{name}" preload=metadata muted></video>
<script>
window.result = null;
const v = document.getElementById('v');
v.addEventListener('loadedmetadata', () => {{ v.currentTime = 15.0; }});
v.addEventListener('seeked', () => {{ window.result = {{ok: true, t: v.currentTime, dur: v.duration}}; }});
v.addEventListener('error', () => {{ window.result = {{ok: false, err: v.error && v.error.code}}; }});
</script></body></html>"""


@app.get("/page/{name}", response_class=HTMLResponse)
def page(name: str) -> str:
    return PAGE.format(name=name)


@app.get("/media/{name}")
def media(name: str, request: Request) -> Response:
    data = (OUT / name).read_bytes()  # spike only: whole file in RAM
    ctype = "video/mp4" if name.endswith("mp4") else "video/webm"
    rng = request.headers.get("range")
    range_log.append(rng or "none")
    if not rng:
        return Response(data, media_type=ctype, headers={"Accept-Ranges": "bytes"})
    start_s, _, end_s = rng.removeprefix("bytes=").partition("-")
    start = int(start_s)
    end = min(int(end_s) if end_s else len(data) - 1, len(data) - 1)
    return Response(data[start : end + 1], status_code=206, media_type=ctype, headers={
        "Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{len(data)}"})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


port = free_port()
threading.Thread(target=uvicorn.run, args=(app,), kwargs={"host": "127.0.0.1", "port": port, "log_level": "error"},
                 daemon=True).start()
time.sleep(1.5)
mode = sys.argv[1]
results = {}

if mode == "browser":
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        pg = b.new_page()
        for name in ["media.mp4", "media.webm"]:
            range_log.clear()
            pg.goto(f"http://127.0.0.1:{port}/page/{name}")
            pg.wait_for_function("window.result !== null", timeout=15000)
            results[name] = {**pg.evaluate("window.result"), "ranges": list(range_log)[:6]}
        b.close()
else:
    import webview
    win = webview.create_window("spike", f"http://127.0.0.1:{port}/page/media.webm")

    def probe(w):
        for name in ["media.webm", "media.mp4"]:
            range_log.clear()
            w.load_url(f"http://127.0.0.1:{port}/page/{name}")
            r = None
            for _ in range(60):
                time.sleep(0.25)
                try:
                    r = w.evaluate_js("window.result")
                except Exception as e:  # spike: record and continue
                    r = {"eval_error": str(e)}
                if r:
                    break
            results[name] = {"result": r, "ranges": list(range_log)[:6]}
        results["gui"] = webview.guilib.renderer if webview.guilib else None
        w.destroy()

    webview.start(probe, win, gui="qt")

print(json.dumps(results, indent=1))
