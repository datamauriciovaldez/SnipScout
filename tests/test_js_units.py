"""Runs the pure JavaScript unit tests (tests/js/*.test.mjs) with Node when it is available."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = sorted((Path(__file__).parent / "js").glob("*.test.mjs"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_js_units() -> None:
    r = subprocess.run(
        ["node", "--test", *map(str, JS_TESTS)], capture_output=True, text=True, timeout=120, check=False
    )
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
