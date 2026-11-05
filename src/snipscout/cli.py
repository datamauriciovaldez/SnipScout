"""Command-line entry point: ``snipscout doctor``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from snipscout import __version__
from snipscout.core import system
from snipscout.core.errors import SnipScoutError
from snipscout.core.net import enforce_offline_if_requested


def _print_doctor(report: system.SystemReport) -> None:
    def line(ok: bool | None, label: str, value: object) -> None:
        mark = {True: "OK  ", False: "FAIL", None: "INFO"}[ok]
        print(f"[{mark}] {label:<14} {value}")

    print(f"SnipScout {report.snipscout} — system check\n")
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


def _run(args: argparse.Namespace) -> int:
    from pathlib import Path

    from snipscout.core import ingest, modelstore
    from snipscout.core.binaries import resolve_ffmpeg
    from snipscout.core.models import AspectRatio, ClipLength, JobEvent, ProjectSettings
    from snipscout.core.pipeline import Pipeline
    from snipscout.core.storage import ProjectStore

    last: dict[str, int] = {}

    def show(e: JobEvent) -> None:
        pct = int(e.progress * 100)
        key = f"{e.stage}:{e.params.get('clip', '')}"
        if last.get(key, -1) // 10 == pct // 10 and pct < 100:
            return  # print every 10%
        last[key] = pct
        extra = ""
        if e.stage == "transcribe" and e.params.get("eta_s") is not None:
            extra = f"  ~{int(e.params['eta_s'])}s left"
        if e.stage == "render":
            extra = f"  clip {e.params.get('clip')}/{e.params.get('clips')}"
        print(f"  {e.stage:<14} {pct:3d}%{extra}", flush=True)

    bins = resolve_ffmpeg()
    media = ingest.probe(Path(args.video), bins.ffprobe)
    print(
        f"Input: {media.path.name} — {media.duration:.0f}s, "
        f"{'video' if media.has_video else 'audio only'}, {len(media.audio_tracks)} audio track(s)"
    )
    if not modelstore.is_installed(args.model):
        spec = modelstore.get_spec(args.model)
        print(f"Downloading speech model '{args.model}' ({spec.total_bytes / 1e6:.0f} MB, one time only)...")
        shown = [-1]

        def dl(done: int, total: int) -> None:
            pct = done * 100 // total
            if pct // 10 != shown[0] // 10:
                shown[0] = pct
                print(f"  download {pct:3d}%", flush=True)

        modelstore.download_model(args.model, on_progress=dl)
    store = ProjectStore()
    settings = ProjectSettings(
        clip_length=ClipLength(args.length),
        aspect=AspectRatio(args.aspect),
        subtitle_style=args.style,
        language=args.lang,
        model=args.model,
        quick_analysis=args.quick,
        audio_track=args.track,
    )
    project = store.create(media, settings)
    pipe = Pipeline(store, bins)
    print("Analyzing...")
    clip_set = pipe.analyze(project.id, on_event=show)
    for c in clip_set.clips:
        c.included = c.rank <= args.count
    store.save_clips(project.id, clip_set)
    n_render = min(args.count, len(clip_set.clips))
    print(f"Found {len(clip_set.clips)} candidate clips; rendering the top {n_render}:")
    for c in clip_set.clips[: args.count]:
        print(f"  #{c.rank} {c.score:5.1f}  {c.start:7.1f}-{c.end:7.1f}s  {c.title}")
    result = pipe.render(
        project.id,
        out_dir=Path(args.out) if args.out else None,
        on_event=show,
        hardware=args.hardware or None,
        loudnorm=args.loudnorm or None,
    )
    print(f"\nDone. {len(result.clips)} clip(s) in: {result.folder}")
    for ec in result.clips:
        print(f"  {ec.video.name}")
    return 0


def _ui(args: argparse.Namespace) -> int:
    from snipscout.desktop import run_ui

    return run_ui(browser=args.browser, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snipscout", description="Local video-to-clips tool.")
    parser.add_argument("--version", action="version", version=f"snipscout {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Check this computer: ffmpeg, CPU, RAM, disk.")
    doctor.add_argument("--json", action="store_true", help="Machine-readable output.")
    doctor.add_argument("--no-cache", action="store_true", help="Re-run the ffmpeg capability check.")
    doctor.set_defaults(func=_doctor)

    run = sub.add_parser("run", help="Analyze a video and export the best clips (no UI).")
    run.add_argument("video", help="Path to a video or audio file.")
    run.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small"],
        help="tiny = fast, base = balanced (default), small = accurate.",
    )
    run.add_argument(
        "--length",
        default="short",
        choices=["short", "medium", "long"],
        help="short 15-30 s, medium 30-60 s, long 60-90 s.",
    )
    run.add_argument("--aspect", default="9:16", choices=["9:16", "1:1", "16:9", "original"])
    run.add_argument("--style", default="bold-pop", choices=["classic", "bold-pop", "karaoke", "minimal"])
    run.add_argument("--lang", default=None, help="Force language (e.g. es, en). Default: auto-detect.")
    run.add_argument("--track", type=int, default=0, help="Audio track index (default 0).")
    run.add_argument("--count", type=int, default=3, help="How many top clips to render (default 3).")
    run.add_argument("--quick", action="store_true", help="Quick analysis: only the first 10 minutes.")
    run.add_argument("--out", help="Output folder (default: inside the project folder).")
    run.add_argument("--hardware", action="store_true", help="Try a hardware H.264 encoder first.")
    run.add_argument("--loudnorm", action="store_true", help="Normalize loudness (-14 LUFS).")
    run.set_defaults(func=_run)

    ui = sub.add_parser("ui", help="Open the SnipScout window (or your browser if no window is available).")
    ui.add_argument("--browser", action="store_true", help="Use the default browser instead of a window.")
    ui.add_argument("--port", type=int, default=0, help="Port for the local server (default: a free one).")
    ui.set_defaults(func=_ui)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Windows consoles may default to a legacy code page; never crash on non-ASCII paths.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    enforce_offline_if_requested()
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except SnipScoutError as exc:  # friendly message, never a traceback
        print(f"\nError [{exc.code}]: {exc}", file=sys.stderr)
        if exc.details:
            print(f"Details: {exc.details}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return result


if __name__ == "__main__":
    raise SystemExit(main())
