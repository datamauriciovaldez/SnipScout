"""Command-line entry point: ``clipforge doctor``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from clipforge import __version__
from clipforge.core import system
from clipforge.core.net import enforce_offline_if_requested


def _print_doctor(report: system.SystemReport) -> None:
    def line(ok: bool | None, label: str, value: object) -> None:
        mark = {True: "OK  ", False: "FAIL", None: "INFO"}[ok]
        print(f"[{mark}] {label:<14} {value}")

    print(f"ClipForge {report.clipforge} — system check\n")
    line(None, "Python", report.python)
    line(None, "OS", report.os)
    line(
        None, "CPU", f"{report.cpu_cores_logical} logical / {report.cpu_cores_physical or '?'} physical cores"
    )
    line(None, "RAM", f"{report.ram_gb} GB")
    line(
        None,
        "GPU",
        "NVIDIA tools found (optional)" if report.nvidia_gpu_tool else "none detected (not required)",
    )
    line(None, "Data folder", report.data_dir)
    line(None, "Free disk", f"{report.disk_free_gb} GB" if report.disk_free_gb is not None else "unknown")
    line(None, "Offline mode", "on" if report.offline else "off")
    if report.ffmpeg_ok:
        ff = report.ffmpeg
        line(True, "ffmpeg", f"{ff['version']}  [{ff['source']}]")
        line(None, "ffmpeg path", ff["path"])
        line(None, "ffprobe", ff["ffprobe"] or "not found (PyAV will be used for probing)")
    else:
        line(False, "ffmpeg", "no build with libass + libx264 found")
        print("\n" + (report.ffmpeg_error or ""))
    print("\nAll good." if report.ok else "\nSome checks failed.")


def _doctor(args: argparse.Namespace) -> int:
    report = system.collect(use_cache=not args.no_cache)
    if args.json:
        print(json.dumps({**asdict(report), "ok": report.ok}, indent=2, ensure_ascii=False))
    else:
        _print_doctor(report)
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clipforge", description="Local video-to-clips tool.")
    parser.add_argument("--version", action="version", version=f"clipforge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Check this computer: ffmpeg, CPU, RAM, disk.")
    doctor.add_argument("--json", action="store_true", help="Machine-readable output.")
    doctor.add_argument("--no-cache", action="store_true", help="Re-run the ffmpeg capability check.")
    doctor.set_defaults(func=_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Windows consoles may default to a legacy code page; never crash on non-ASCII paths.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    enforce_offline_if_requested()
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
