import hashlib
from pathlib import Path

import httpx
import pytest

from snipscout.core import modelstore
from snipscout.core.errors import CancelledError, ModelDownloadError, OfflineError
from snipscout.core.procs import CancelToken

FILES = {
    "config.json": b"{}",
    "tokenizer.json": b'{"t": 1}',
    "vocabulary.txt": b"a\nb\n",
    "model.bin": bytes(range(256)) * 20_000,  # ~5 MB so it spans several chunks
}


def _spec(sha: str | None = None) -> modelstore.WhisperSpec:
    return modelstore.WhisperSpec(
        "fake",
        "fast",
        "org/fake",
        "rev123",
        sha or hashlib.sha256(FILES["model.bin"]).hexdigest(),
        sum(len(v) for v in FILES.values()),
        0.1,
    )


def _transport(log: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        assert "/org/fake/resolve/rev123/" in request.url.path
        data = FILES[name]
        rng = request.headers.get("range")
        log.append(f"{name}:{rng}")
        if rng:
            start = int(rng.removeprefix("bytes=").split("-")[0])
            return httpx.Response(206, content=data[start:])
        return httpx.Response(200, content=data)

    return httpx.MockTransport(handler)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SNIPSCOUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SNIPSCOUT_OFFLINE", raising=False)
    monkeypatch.setitem(modelstore.MODELS, "fake", _spec())


def test_download_verify_and_progress(fake_model: None) -> None:
    log: list[str] = []
    progress: list[tuple[int, int]] = []
    with httpx.Client(transport=_transport(log)) as c:
        d = modelstore.download_model("fake", client=c, on_progress=lambda a, b: progress.append((a, b)))
    assert modelstore.is_installed("fake")
    assert (d / "model.bin").read_bytes() == FILES["model.bin"]
    assert progress[-1][0] == progress[-1][1] == _spec().total_bytes
    assert not list(d.glob("*.part"))


def test_pause_and_resume_with_range(fake_model: None) -> None:
    log: list[str] = []
    token = CancelToken()
    seen = 0

    def pause_midway(done: int, total: int) -> None:
        nonlocal seen
        seen = done
        if done > 2_000_000:
            token.cancel()

    with httpx.Client(transport=_transport(log)) as c, pytest.raises(CancelledError):
        modelstore.download_model("fake", client=c, on_progress=pause_midway, cancel=token)
    part = modelstore.model_dir("fake") / "model.bin.part"
    assert part.exists() and 0 < part.stat().st_size < len(FILES["model.bin"])
    assert not modelstore.is_installed("fake")
    with httpx.Client(transport=_transport(log)) as c:
        modelstore.download_model("fake", client=c)
    assert any(entry.startswith("model.bin:bytes=") for entry in log)  # resumed with Range
    assert (modelstore.model_dir("fake") / "model.bin").read_bytes() == FILES["model.bin"]


def test_checksum_mismatch(monkeypatch: pytest.MonkeyPatch, fake_model: None) -> None:
    monkeypatch.setitem(modelstore.MODELS, "fake", _spec(sha="0" * 64))
    with httpx.Client(transport=_transport([])) as c, pytest.raises(ModelDownloadError) as exc:
        modelstore.download_model("fake", client=c)
    assert "corrupted" in str(exc.value)
    assert not (modelstore.model_dir("fake") / "model.bin").exists()
    assert not modelstore.is_installed("fake")


def test_http_error_is_typed(fake_model: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c, pytest.raises(ModelDownloadError):
        modelstore.download_model("fake", client=c)


def test_offline_refuses_download(monkeypatch: pytest.MonkeyPatch, fake_model: None) -> None:
    monkeypatch.setenv("SNIPSCOUT_OFFLINE", "1")
    with pytest.raises(OfflineError):
        modelstore.download_model("fake")


def test_unknown_model() -> None:
    with pytest.raises(ModelDownloadError):
        modelstore.get_spec("huge")


def test_catalogue_is_pinned() -> None:
    for spec in modelstore.MODELS.values():
        assert len(spec.revision) == 40 and len(spec.model_sha256) == 64
    assert modelstore.DEFAULT_MODEL == "base"
