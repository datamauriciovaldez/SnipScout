"""i18n completeness: ES and EN have the same keys, and every key used by the frontend exists."""

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "snipscout" / "web" / "static"


def _flatten(d: dict[str, object], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = str(v)
    return out


def _load(lang: str) -> dict[str, str]:
    return _flatten(json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8")))


def test_same_keys_in_both_languages() -> None:
    es, en = _load("es"), _load("en")
    assert set(es) == set(en), {"only_es": sorted(set(es) - set(en)), "only_en": sorted(set(en) - set(es))}
    assert all(v.strip() for v in es.values()) and all(v.strip() for v in en.values())


def test_placeholders_match() -> None:
    es, en = _load("es"), _load("en")
    ph = re.compile(r"\{(\w+)\}")
    for key in es:
        assert set(ph.findall(es[key])) == set(ph.findall(en[key])), key


def test_every_static_key_used_in_js_exists() -> None:
    keys = set(_load("es"))
    used: set[str] = set()
    for js in (STATIC / "js").rglob("*.js"):
        used |= set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", js.read_text(encoding="utf-8")))
        used |= set(re.findall(r"""titleKey=["']([\w.]+)["']""", js.read_text(encoding="utf-8")))
    missing = sorted(used - keys)
    assert not missing, missing


def test_every_error_code_has_a_screen() -> None:
    keys = set(_load("es"))
    src = Path(__file__).resolve().parents[1] / "src" / "snipscout"
    codes = set()
    for py in src.rglob("*.py"):
        codes |= set(re.findall(r'^\s+code = "(\w+)"', py.read_text(encoding="utf-8"), flags=re.M))
    missing = sorted(c for c in codes if f"errors.{c}.title" not in keys or f"errors.{c}.body" not in keys)
    assert not missing, missing


def test_every_project_status_and_stage_is_translated() -> None:
    from snipscout.core.models import ProjectStatus
    from snipscout.core.pipeline import ANALYZE_STAGES

    keys = set(_load("es"))
    assert all(f"project_status.{s.value}" in keys for s in ProjectStatus)
    assert all(f"stage.{s}" in keys for s in [*ANALYZE_STAGES, "render", "done", "exported"])
