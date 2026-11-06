"""Export: per-clip MP4 + subtitles, plus metadata.json and captions.txt for the whole set."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from snipscout.core.models import Clip, MediaInfo, Word
from snipscout.core.procs import CancelToken
from snipscout.core.render import RenderOptions, for_clip, render_clip
from snipscout.core.storage import atomic_write_text, slugify
from snipscout.core.subtitles import build_ass, build_srt, build_vtt, clip_words
from snipscout.core.text import lexicon


@dataclass
class ExportedClip:
    clip_id: str
    video: Path
    srt: Path
    vtt: Path


@dataclass
class ExportResult:
    folder: Path
    clips: list[ExportedClip] = field(default_factory=list)
    metadata: Path | None = None
    captions: Path | None = None


def base_name(clip: Clip, number: int) -> str:
    return f"clip_{number:02d}_{slugify(clip.title or clip.hook)}"


def _description(clip: Clip) -> str:
    tags = " ".join("#" + slugify(k, 20).replace("-", "") for k in clip.keywords[:4] if k)
    return f"{clip.hook}\n\n{tags}".strip()


def export_clips(
    ffmpeg: Path,
    media: MediaInfo,
    words: list[Word],
    clips: list[Clip],
    out_dir: Path,
    *,
    default_style: str,
    opts: RenderOptions,
    language: str | None,
    on_clip_progress: Callable[[int, int, float], None] | None = None,
    cancel: CancelToken | None = None,
) -> ExportResult:
    """Render every included clip into ``out_dir`` and write the metadata files.

    ``on_clip_progress(index, total, fraction)`` reports per-clip progress.
    """
    selected = [c for c in clips if c.included]
    result = ExportResult(folder=out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    vertical = opts.height > opts.width
    reasons_text = lexicon(language).get("reasons", {})
    work = out_dir / ".snipscout-work"  # .ass + fonts; removed at the end
    meta: list[dict[str, object]] = []
    captions: list[str] = []
    try:
        for n, clip in enumerate(selected, 1):
            if cancel:
                cancel.raise_if_cancelled()
            name = base_name(clip, n)
            cw = clip_words(words, clip)
            ass_name = f"{name}.ass"
            atomic_write_text(
                work / ass_name,
                build_ass(
                    cw, clip.subtitle_style or default_style, opts.width, opts.height, vertical=vertical
                ),
            )
            srt, vtt = out_dir / f"{name}.srt", out_dir / f"{name}.vtt"
            atomic_write_text(srt, build_srt(cw))
            atomic_write_text(vtt, build_vtt(cw))

            def progress(f: float, i: int = n) -> None:
                if on_clip_progress:
                    on_clip_progress(i, len(selected), f)

            clip_opts = for_clip(ffmpeg, media, opts, clip.start, clip.end, cancel=cancel)
            video = render_clip(
                ffmpeg,
                media,
                clip.start,
                clip.end,
                work,
                out_dir / f"{name}.mp4",
                ass_name,
                clip_opts,
                on_progress=progress,
                cancel=cancel,
            )
            result.clips.append(ExportedClip(clip.id, video, srt, vtt))
            meta.append(
                {
                    "file": video.name,
                    "id": clip.id,
                    "rank": clip.rank,
                    "title": clip.title,
                    "hook": clip.hook,
                    "score": clip.score,
                    "reasons": [{"key": r, "text": reasons_text.get(r, r)} for r in clip.reasons],
                    "signals": clip.signals,
                    "start": clip.start,
                    "end": clip.end,
                    "duration": round(clip.end - clip.start, 3),
                    "reframe": {"mode": clip_opts.mode.value, "focus": clip_opts.focus},
                    "keywords": clip.keywords,
                    "subtitles": {
                        "srt": srt.name,
                        "vtt": vtt.name,
                        "style": clip.subtitle_style or default_style,
                    },
                }
            )
            captions.append(f"=== {video.name} ===\n{clip.title}\n\n{_description(clip)}\n")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    result.metadata = out_dir / "metadata.json"
    atomic_write_text(
        result.metadata,
        json.dumps(
            {
                "source": media.path.name,
                "language": language,
                "note": "Titles, hooks and keywords are extracted from the transcript (not AI-generated).",
                "clips": meta,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    result.captions = out_dir / "captions.txt"
    atomic_write_text(result.captions, "\n".join(captions))
    return result
