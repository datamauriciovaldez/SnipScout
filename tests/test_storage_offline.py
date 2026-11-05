import socket
import urllib.request
from pathlib import Path

import pytest

from clipforge.core import net
from clipforge.core.errors import OfflineError
from clipforge.core.models import MediaInfo, ProjectStatus, Transcript, Word
from clipforge.core.storage import ProjectNotFoundError, ProjectStore, StorageError, slugify


def _media(tmp_path: Path) -> MediaInfo:
    f = tmp_path / "vídeo 🎬.mp4"
    f.write_bytes(b"x")
    return MediaInfo(path=f, size_bytes=1, container="mp4", duration=12.5, has_video=True)


def test_project_roundtrip(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    p = store.create(_media(tmp_path))
    assert p.name == "vídeo 🎬"
    p.status = ProjectStatus.ANALYZED
    store.save(p)
    loaded = store.load(p.id)
    assert loaded.status == ProjectStatus.ANALYZED
    assert loaded.source.path == p.source.path
    assert [x.id for x in store.list()] == [p.id]


def test_transcript_resume_state(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    p = store.create(_media(tmp_path))
    assert store.load_transcript(p.id) is None
    t = Transcript(
        language="es", processed_until=6.0, words=[Word(text="hola", start=0.1, end=0.4, prob=0.9)]
    )
    store.save_transcript(p.id, t)
    again = store.load_transcript(p.id)
    assert again is not None and again.processed_until == 6.0 and not again.complete
    assert again.words[0].text == "hola"


@pytest.mark.parametrize("bad", ["../etc", "..", "ABCDEF123456", "a" * 13, "", "x/../../y"])
def test_rejects_path_traversal(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ProjectNotFoundError):
        ProjectStore(tmp_path).project_dir(bad)


def test_corrupted_json_is_typed_error(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    p = store.create(_media(tmp_path))
    (store.project_dir(p.id) / "project.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(StorageError):
        store.load(p.id)
    assert store.list() == []  # corrupted projects are skipped in listings


def test_delete(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    p = store.create(_media(tmp_path))
    store.delete(p.id)
    with pytest.raises(ProjectNotFoundError):
        store.load(p.id)


def test_slugify() -> None:
    assert slugify("¿Sabías que el 80 % de los vídeos…?") == "sabias-que-el-80-de-los-videos"
    assert slugify("🎬🎬") == "clip"


def test_offline_blocks_network_but_allows_loopback(
    monkeypatch: pytest.MonkeyPatch, no_offline_guard: None
) -> None:
    monkeypatch.setenv("CLIPFORGE_OFFLINE", "1")
    assert net.enforce_offline_if_requested()
    with pytest.raises(OfflineError):
        socket.create_connection(("huggingface.co", 443), timeout=2)
    with pytest.raises(OfflineError):
        socket.create_connection(("8.8.8.8", 53), timeout=2)
    with pytest.raises(OfflineError):
        urllib.request.urlopen("https://pypi.org", timeout=2)  # noqa: S310 - testing the block
    with pytest.raises(OfflineError):
        net.require_network("download the model")
    # Loopback still works (the UI server lives there).
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.create_connection(srv.getsockname(), timeout=2)
    c.close()
    srv.close()


def test_online_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIPFORGE_OFFLINE", raising=False)
    assert not net.enforce_offline_if_requested()
    net.require_network("anything")  # no error
