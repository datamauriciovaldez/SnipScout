from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from snipscout.core.binaries import FfmpegBinaries
from snipscout.core.storage import ProjectStore
from snipscout.web.app import COOKIE, Context, create_app

sys.path.insert(0, str(Path(__file__).parent))
from test_transcribe_segment import FakeModel  # noqa: E402

TOKEN = "t" * 43


@pytest.fixture
def ctx(tmp_path: Path, ff: FfmpegBinaries) -> Context:
    c = Context(
        ProjectStore(tmp_path / "projects"),
        ff,
        TOKEN,
        model_loader=lambda name: FakeModel([]),  # type: ignore[arg-type,return-value]
        uploads_dir=tmp_path / "uploads",
    )
    c.allowed_hosts = {"testserver"}
    return c


@pytest.fixture
def client(ctx: Context) -> TestClient:
    c = TestClient(create_app(ctx))
    r = c.get(f"/?t={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and COOKIE in r.cookies
    return c


def _events_until_done(client: TestClient, pid: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with client.stream("GET", f"/api/v1/projects/{pid}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                e = json.loads(line[6:])
                out.append(e)
                if e["state"] != "running":
                    break
    return out


# --- security ---------------------------------------------------------------------------------------


def test_api_requires_session(ctx: Context) -> None:
    c = TestClient(create_app(ctx))
    assert c.get("/api/v1/system/status").status_code == 401
    assert c.get("/api/v1/system/status", headers={"X-SnipScout-Token": TOKEN}).status_code == 200
    assert c.get("/").status_code == 403  # no cookie yet
    assert c.get("/?t=wrong").status_code == 403


def test_index_after_login(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200 and 'type="importmap"' in r.text
    assert r.headers["x-content-type-options"] == "nosniff"


def test_host_and_origin_checks(client: TestClient) -> None:
    assert client.get("/api/v1/system/status", headers={"host": "evil.example"}).status_code == 403
    r = client.post("/api/v1/projects", json={"path": "x"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in client.get("/api/v1/system/status").headers


def test_static_assets_served(client: TestClient) -> None:
    for path in [
        "/static/vendor/preact.module.js",
        "/static/js/app.js",
        "/static/css/tokens.css",
        "/static/i18n/es.json",
        "/static/fonts/ibm-plex-sans-latin-400-normal.woff2",
    ]:
        assert client.get(path).status_code == 200, path


# --- system & projects ----------------------------------------------------------------------------


def test_system_status(client: TestClient) -> None:
    s = client.get("/api/v1/system/status").json()
    assert s["ffmpeg"]["ok"] is True
    assert {m["name"] for m in s["models"]} == {"tiny", "base", "small"}
    assert s["recommended_model"] == "base"


def test_project_lifecycle(client: TestClient, video_mp4: Path) -> None:
    r = client.post("/api/v1/projects", json={"path": str(video_mp4), "settings": {"aspect": "1:1"}})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["source"]["has_video"] and p["settings"]["aspect"] == "1:1" and p["estimate_s"] >= 0
    pid = p["id"]
    assert [x["id"] for x in client.get("/api/v1/projects").json()] == [pid]
    r = client.patch(
        f"/api/v1/projects/{pid}", json={"name": "Mi charla", "settings": {"clip_length": "medium"}}
    )
    assert r.json()["name"] == "Mi charla" and r.json()["settings"]["clip_length"] == "medium"
    assert client.patch(f"/api/v1/projects/{pid}", json={"settings": {"model": "huge"}}).status_code == 400
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 204
    assert client.get(f"/api/v1/projects/{pid}").json()["error"]["code"] == "project_not_found"


def test_bad_inputs_are_typed_errors(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/api/v1/projects", json={"path": str(tmp_path / "nope.mp4")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_media"
    for bad in ["..%2F..%2Fetc", "ABCDEF123456", "x" * 12]:
        assert client.get(f"/api/v1/projects/{bad}").status_code == 404


def test_upload_streaming(client: TestClient, video_mp4: Path) -> None:
    r = client.post(
        "/api/v1/projects/upload", params={"filename": "../../mi vídeo.mp4"}, content=video_mp4.read_bytes()
    )
    assert r.status_code == 201, r.text
    path = Path(r.json()["source"]["path"])
    assert path.name == "mi-video.mp4" and ".." not in path.parts
    assert r.json()["name"] == "mi vídeo"  # display name keeps the original
    r = client.post("/api/v1/projects/upload", params={"filename": "virus.exe"}, content=b"MZ")
    assert r.status_code == 400


def test_media_range(client: TestClient, video_mp4: Path) -> None:
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    r = client.get(f"/api/v1/projects/{pid}/media", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and len(r.content) == 100
    assert r.content == video_mp4.read_bytes()[100:200]


# --- analyze → clips → render → export -------------------------------------------------------------


def test_analyze_events_clips_render_zip(
    client: TestClient, ctx: Context, video_mp4: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    assert client.post(f"/api/v1/projects/{pid}/analyze").status_code == 202
    events = _events_until_done(client, pid)
    assert events[-1]["state"] == "done", events[-1]
    assert {"prepare_audio", "transcribe", "find_moments"} <= {e["stage"] for e in events}
    clips = client.get(f"/api/v1/projects/{pid}/clips").json()["clips"]
    assert clips, "fake model words should produce at least one clip"
    cid = clips[0]["id"]

    r = client.patch(
        f"/api/v1/projects/{pid}/clips/{cid}", json={"title": "Nuevo título", "subtitle_style": "karaoke"}
    )
    assert r.status_code == 200 and r.json()["title"] == "Nuevo título"
    assert client.patch(f"/api/v1/projects/{pid}/clips/{cid}", json={"start": 4, "end": 2}).status_code == 400
    assert (
        client.patch(f"/api/v1/projects/{pid}/clips/{cid}", json={"subtitle_style": "comic"}).status_code
        == 400
    )
    assert client.patch(f"/api/v1/projects/{pid}/clips/c99", json={"title": "x"}).status_code == 404

    w = client.get(f"/api/v1/projects/{pid}/waveform", params={"points": 100}).json()
    assert 1 <= w["points"] <= 100 and max(w["peaks"]) <= 1.0
    z = client.get(f"/api/v1/projects/{pid}/waveform", params={"points": 50, "start": 1, "end": 2}).json()
    assert (z["start"], z["end"], z["points"]) == (1, 2, 20)  # 1 s = 20 envelope frames < 50 requested
    thumb = client.get(f"/api/v1/projects/{pid}/clips/{cid}/thumbnail")
    assert thumb.status_code == 200 and thumb.content[:2] == b"\xff\xd8"  # JPEG

    out = tmp_path / "salida"
    assert client.post(f"/api/v1/projects/{pid}/render", json={"out_dir": str(out)}).status_code == 202
    events = _events_until_done(client, pid)
    assert events[-1]["state"] == "done", events[-1]
    assert client.get(f"/api/v1/projects/{pid}").json()["status"] == "done"
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/projects/{pid}/export.zip").content))
    names = z.namelist()
    assert any(n.endswith(".mp4") for n in names) and "metadata.json" in names

    opened: list[Path] = []
    monkeypatch.setattr("snipscout.web.routes.exports._reveal", opened.append)
    assert client.post(f"/api/v1/projects/{pid}/reveal").status_code == 204
    assert opened == [out]


def test_busy_and_cancel(client: TestClient, ctx: Context, video_mp4: Path) -> None:
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    started = client.post(f"/api/v1/projects/{pid}/analyze")
    assert started.status_code == 202
    second = client.post(f"/api/v1/projects/{pid}/analyze")
    if ctx.jobs.running(pid):  # the fake run is fast; only assert when it is still running
        assert second.status_code == 409 and second.json()["error"]["code"] == "job_busy"
    client.post(f"/api/v1/projects/{pid}/cancel")
    ctx.jobs.wait(pid, timeout=30)
    assert client.get(f"/api/v1/projects/{pid}").json()["status"] in {"cancelled", "analyzed"}


def test_waveform_before_analysis(client: TestClient, video_mp4: Path) -> None:
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    r = client.get(f"/api/v1/projects/{pid}/waveform")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_missing_ffmpeg_is_reported(tmp_path: Path, video_mp4: Path) -> None:
    c = Context(ProjectStore(tmp_path / "p"), None, TOKEN)
    c.allowed_hosts = {"testserver"}
    client = TestClient(create_app(c))
    h = {"X-SnipScout-Token": TOKEN}
    assert client.get("/api/v1/system/status", headers=h).json()["ffmpeg"]["ok"] is False
    r = client.post("/api/v1/projects", json={"path": str(video_mp4)}, headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "ffmpeg_missing"


def test_transcript_contributions_and_single_clip_render(
    client: TestClient, ctx: Context, video_mp4: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "Descargas" / "SnipScout"
    monkeypatch.setenv("SNIPSCOUT_OUTPUT_DIR", str(out_root))
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    assert client.get(f"/api/v1/projects/{pid}/transcript").status_code == 400  # before analysis
    client.post(f"/api/v1/projects/{pid}/analyze")
    assert _events_until_done(client, pid)[-1]["state"] == "done"

    tr = client.get(f"/api/v1/projects/{pid}/transcript").json()
    assert tr["words"] and tr["sentences"] and tr["complete"]
    assert tr["sentences"][0]["word_start"] == 0 and tr["sentences"][-1]["word_end"] == len(tr["words"])

    clips = client.get(f"/api/v1/projects/{pid}/clips").json()["clips"]
    for c in clips:
        assert sum(c["contributions"].values()) == pytest.approx(c["score"], abs=0.6)

    target = clips[-1]["id"]
    assert client.post(f"/api/v1/projects/{pid}/render", json={"clip_ids": [target]}).status_code == 202
    assert _events_until_done(client, pid)[-1]["state"] == "done"
    project = client.get(f"/api/v1/projects/{pid}").json()
    folder = Path(project["export_dir"])
    assert folder.parent == out_root  # default output folder
    assert len(list(folder.glob("*.mp4"))) == 1
    assert client.get("/api/v1/system/status").json()["output_dir"] == str(out_root)


def test_job_not_running_after_terminal_event() -> None:
    """Regression: the UI reloads the project as soon as the 'done' event arrives; it must not look busy."""
    import threading

    from snipscout.core.models import JobEvent, JobState
    from snipscout.web.jobs import JobManager

    jobs = JobManager()
    release = threading.Event()

    def work(emit: Any, cancel: Any) -> None:
        emit(JobEvent(stage="done", state=JobState.DONE, progress=1.0))
        release.wait(5)  # the thread is still alive after publishing the terminal event

    jobs.start("abcdef123456", "analyze", work)
    job = jobs.get("abcdef123456")
    assert job is not None and job.thread is not None and job.thread.is_alive()
    assert not jobs.running("abcdef123456")
    release.set()
    jobs.wait("abcdef123456", timeout=5)


def test_exports_listing_and_files(client: TestClient, video_mp4: Path) -> None:
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    assert client.get(f"/api/v1/projects/{pid}/exports").status_code == 400  # nothing yet
    client.post(f"/api/v1/projects/{pid}/analyze")
    _events_until_done(client, pid)
    client.post(f"/api/v1/projects/{pid}/render")
    events = _events_until_done(client, pid)
    renders = [e for e in events if e["stage"] == "render"]
    assert renders and renders[0]["params"]["clip_id"].startswith("c") and renders[0]["params"]["title"]
    ex = client.get(f"/api/v1/projects/{pid}/exports").json()
    clip = ex["clips"][0]
    assert clip["exists"] and clip["size_bytes"] > 0 and clip["caption"].startswith(clip["title"])
    r = client.get(f"/api/v1/projects/{pid}/exports/{clip['file']}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    srt = client.get(f"/api/v1/projects/{pid}/exports/{clip['subtitles']['srt']}", params={"download": True})
    assert srt.status_code == 200 and "attachment" in srt.headers["content-disposition"]
    for bad in ["..%2Fproject.json", "metadata.json.bak", "x.exe"]:
        assert client.get(f"/api/v1/projects/{pid}/exports/{bad}").status_code == 404


def test_reveal_without_file_manager_is_typed(
    client: TestClient, ctx: Context, video_mp4: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess as sp

    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    p = ctx.store.load(pid)
    p.export_dir = tmp_path
    ctx.store.save(p)

    def missing(*a: Any, **k: Any) -> None:
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(sp, "Popen", missing)
    monkeypatch.setattr("sys.platform", "linux")
    r = client.post(f"/api/v1/projects/{pid}/reveal")
    assert r.status_code == 500 and r.json()["error"]["code"] == "reveal_failed"


def test_preview_frame_real_subtitles(client: TestClient, video_mp4: Path) -> None:
    pid = client.post(
        "/api/v1/projects", json={"path": str(video_mp4), "settings": {"aspect": "1:1"}}
    ).json()["id"]
    client.post(f"/api/v1/projects/{pid}/analyze")
    _events_until_done(client, pid)
    clip = client.get(f"/api/v1/projects/{pid}/clips").json()["clips"][0]
    words = client.get(f"/api/v1/projects/{pid}/transcript").json()["words"]
    w = next(w for w in words if clip["start"] <= w["start"] < clip["end"])
    at = w["start"] + 0.05
    url = f"/api/v1/projects/{pid}/clips/{clip['id']}/preview-frame"
    with_subs = client.post(url, json={"at": at, "subtitle_style": "bold-pop"})
    assert with_subs.status_code == 200 and with_subs.content[:2] == b"\xff\xd8"
    hidden = {str(i): "" for i in range(len(words))}  # every word hidden → no subtitle drawn
    without = client.post(url, json={"at": at, "text_overrides": hidden})
    assert without.status_code == 200 and without.content != with_subs.content
    assert client.post(url, json={"at": 9999}).status_code == 400
    assert client.post(url, json={"at": at, "subtitle_style": "comic"}).status_code == 400


def test_settings_storage_and_models(
    client: TestClient, ctx: Context, video_mp4: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SNIPSCOUT_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("SNIPSCOUT_DATA_DIR", str(tmp_path / "data"))
    s = client.get("/api/v1/settings").json()
    assert s["quality"] == "standard" and s["output_dir"] is None and not s["output_dir_locked"]
    target = tmp_path / "Mis clips"
    s = client.patch(
        "/api/v1/settings", json={"output_dir": str(target), "quality": "high", "loudnorm": True}
    ).json()
    assert (
        s["output_dir_resolved"] == str(target)
        and target.is_dir()
        and s["quality"] == "high"
        and s["loudnorm"]
    )
    assert client.patch("/api/v1/settings", json={"output_dir": "relativo/carpeta"}).status_code == 400
    assert client.patch("/api/v1/settings", json={"quality": "ultra"}).status_code == 422
    # Render uses the preferences: output folder and CRF 17 (high).
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    client.post(f"/api/v1/projects/{pid}/analyze")
    _events_until_done(client, pid)
    from snipscout.core.pipeline import Pipeline

    assert Pipeline(ctx.store, ctx.require_ffmpeg()).render_options(ctx.store.load(pid)).crf == 17
    client.post(f"/api/v1/projects/{pid}/render")
    _events_until_done(client, pid)
    assert Path(client.get(f"/api/v1/projects/{pid}").json()["export_dir"]).parent == target
    listed = client.get("/api/v1/projects").json()[0]
    assert listed["clips_total"] >= 1 and listed["clips_included"] >= 1
    # Storage: caches are counted and freed; projects and audio survive.
    client.get(f"/api/v1/projects/{pid}/waveform", params={"points": 100})
    st = client.get("/api/v1/system/storage").json()
    assert st["cache_bytes"] > 0 and st["projects_bytes"] > 0 and st["free_bytes"] > 0
    freed = client.post("/api/v1/system/storage/free").json()["freed_bytes"]
    assert freed > 0 and ctx.store.audio_path(pid).exists()
    assert (
        client.get(f"/api/v1/projects/{pid}/waveform", params={"points": 100}).status_code == 200
    )  # regenerated
    # Models: unknown name rejected; deleting a model that isn't installed is harmless.
    assert client.delete("/api/v1/system/models/huge").status_code == 502
    assert client.delete("/api/v1/system/models/small").status_code == 204
    s = client.patch("/api/v1/settings", json={"output_dir": ""}).json()
    assert s["output_dir"] is None and s["output_dir_resolved"] == s["output_dir_default"]


def test_playback_proxy_for_unplayable_sources(client: TestClient, video_mp4: Path) -> None:
    import time

    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    assert client.get(f"/api/v1/projects/{pid}/media/proxy").json()["state"] == "none"
    assert client.get(f"/api/v1/projects/{pid}/media", params={"variant": "proxy"}).status_code == 400
    assert client.post(f"/api/v1/projects/{pid}/media/proxy").json()["state"] in {"working", "ready"}
    deadline = time.monotonic() + 60
    while (st := client.get(f"/api/v1/projects/{pid}/media/proxy").json())["state"] == "working":
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert st["state"] == "ready"
    r = client.get(
        f"/api/v1/projects/{pid}/media", params={"variant": "proxy"}, headers={"Range": "bytes=0-99"}
    )
    assert r.status_code == 206 and r.headers["content-type"] == "video/webm" and len(r.content) == 100
    assert client.post(f"/api/v1/projects/{pid}/media/proxy").json()["state"] == "ready"  # idempotent
    assert client.get(f"/api/v1/projects/{pid}/media").headers["content-type"] != "video/webm"  # original


def test_per_clip_framing(client: TestClient, ctx: Context, video_mp4: Path) -> None:
    pid = client.post("/api/v1/projects", json={"path": str(video_mp4)}).json()["id"]
    client.post(f"/api/v1/projects/{pid}/analyze")
    assert _events_until_done(client, pid)[-1]["state"] == "done"
    cid = client.get(f"/api/v1/projects/{pid}/clips").json()["clips"][0]["id"]
    info = client.get(f"/api/v1/projects/{pid}/clips/{cid}/framing").json()
    assert info == {"crops": True, "auto_focus": None, "auto_path": None}  # 4:3 test pattern → 9:16, no face
    r = client.patch(f"/api/v1/projects/{pid}/clips/{cid}", json={"framing": "manual", "focus_x": 0.2})
    assert r.status_code == 200 and r.json()["framing"] == "manual" and r.json()["focus_x"] == 0.2
    assert client.patch(f"/api/v1/projects/{pid}/clips/{cid}", json={"focus_x": 1.5}).status_code == 422
    assert client.patch(f"/api/v1/projects/{pid}/clips/{cid}", json={"framing": "zoom"}).status_code == 422
    frame = client.post(
        f"/api/v1/projects/{pid}/clips/{cid}/preview-frame",
        json={"at": 1.0, "framing": "manual", "focus_x": 0.9},
    )
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
