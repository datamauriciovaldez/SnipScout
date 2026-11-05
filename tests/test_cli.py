import json

import pytest

from snipscout import cli
from snipscout.core import system
from snipscout.core.errors import FfmpegMissingError


def test_doctor_json_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["ffmpeg"]["source"] in {"env", "system", "imageio"}
    assert data["ram_gb"] > 0


def test_doctor_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[OK  ] ffmpeg" in out
    assert "All good." in out


def test_doctor_reports_missing_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(**_: object) -> None:
        raise FfmpegMissingError("No usable ffmpeg", details="[system] /x: ass=False")

    monkeypatch.setattr(system, "resolve_ffmpeg", boom)
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] ffmpeg" in out and "ass=False" in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("snipscout ")
