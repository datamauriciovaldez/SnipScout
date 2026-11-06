"""Desktop launcher: local server on a free port + native window (pywebview), browser as fallback."""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from snipscout.core.binaries import FfmpegBinaries, resolve_ffmpeg
from snipscout.core.errors import FfmpegMissingError
from snipscout.core.ingest import SUPPORTED_EXTS
from snipscout.core.storage import ProjectStore
from snipscout.web.app import create_app
from snipscout.web.common import Context

log = logging.getLogger("snipscout")


class Bridge:
    """Methods exposed to the page as ``window.pywebview.api.*`` (native window mode only)."""

    def __init__(self) -> None:
        self.window: Any = None

    def pick_files(self) -> list[str]:
        import webview

        if self.window is None:
            return []
        patterns = ";".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True, file_types=(f"Video or audio ({patterns})",)
        )
        return [str(Path(p)) for p in (result or [])]

    def pick_folder(self) -> str | None:
        import webview

        if self.window is None:
            return None
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return str(result[0]) if result else None


def start_server(ctx: Context, port: int = 0) -> tuple[uvicorn.Server, int]:
    config = uvicorn.Config(
        create_app(ctx), host="127.0.0.1", port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="snipscout-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("The local server did not start.")
        time.sleep(0.05)
    real_port = int(server.servers[0].sockets[0].getsockname()[1])
    ctx.allowed_hosts = {f"127.0.0.1:{real_port}", f"localhost:{real_port}"}
    return server, real_port


def _bind_native_drop(window: Any) -> None:
    """Forward dropped files' full paths to the page (``window.snipscoutDropped(paths)``).

    Browsers never expose real paths; pywebview adds ``pywebviewFullPath`` only to drop events
    handled from Python, so the drop is caught here and passed back to the frontend.
    """
    from webview.dom import DOMEventHandler

    def on_drop(event: dict[str, Any]) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js(f"window.snipscoutDropped && window.snipscoutDropped({json.dumps(paths)})")

    def bind() -> None:
        doc = window.dom.document
        doc.events.dragover += DOMEventHandler(lambda e: None, prevent_default=True)
        doc.events.drop += DOMEventHandler(on_drop, prevent_default=True)

    window.events.loaded += bind


def _open_window(url: str) -> bool:
    """Try the native window. Returns False when no GUI backend is usable (then use the browser)."""
    try:
        import webview
    except ImportError:
        return False
    bridge = Bridge()
    webview.settings["ALLOW_DOWNLOADS"] = True  # Download buttons on the export screen
    try:
        bridge.window = webview.create_window(
            "SnipScout", url, js_api=bridge, width=1440, height=900, min_size=(1000, 680), text_select=True
        )
        _bind_native_drop(bridge.window)
        webview.start()  # blocks until the window closes
    except webview.errors.WebViewException as exc:
        log.warning("Native window unavailable (%s); falling back to the browser.", exc)
        return False
    return True


def run_ui(*, browser: bool = False, port: int = 0) -> int:
    binaries: FfmpegBinaries | None
    try:
        binaries = resolve_ffmpeg()
    except FfmpegMissingError:
        binaries = None  # the UI shows a help screen instead of crashing
    ctx = Context(ProjectStore(), binaries, secrets.token_urlsafe(32))
    server, real_port = start_server(ctx, port)
    url = f"http://127.0.0.1:{real_port}/?t={ctx.token}"
    try:
        if browser or not _open_window(url):
            print(f"SnipScout is running at http://127.0.0.1:{real_port}/ (opening your browser).")
            print("Keep this window open while you use SnipScout. Press Ctrl+C to quit.")
            webbrowser.open(url)
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
    return 0
