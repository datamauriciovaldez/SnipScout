"""Word-by-word subtitles: ASS (burned in by libass) plus plain SRT/VTT for export.

Words are grouped in 3-5 word lines; each word gets its own Dialogue event in which the
active word is highlighted. Times are relative to the clip start.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from snipscout.core.models import Clip, Word

FONTS_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
MIN_GROUP, MAX_GROUP = 3, 5
MAX_GROUP_CHARS = 26
BREAK_GAP_S = 0.5  # a pause longer than this starts a new line
HOLD_S = 0.35  # keep a line visible this long after its last word if nothing follows


def _ass_color(rgb: str, alpha: int = 0) -> str:
    """'#RRGGBB' → '&HAABBGGRR' (ASS colour order is reversed; alpha 0 = opaque)."""
    r, g, b = rgb[1:3], rgb[3:5], rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


@dataclass(frozen=True)
class Preset:
    name: str
    font: str
    bold: bool
    size_ratio: float  # font size as a fraction of output height
    text: str
    highlight: str
    outline: str
    outline_ratio: float
    shadow: float
    uppercase: bool
    mode: str  # "word" = only the active word highlighted; "karaoke" = all spoken words highlighted
    pop: int  # % scale of the active word (100 = none)
    box: bool = False  # opaque box behind text (BorderStyle 3)
    box_color: str = "#000000"
    box_alpha: int = 0x60


PRESETS: dict[str, Preset] = {
    "classic": Preset(
        "classic", "Inter", True, 0.042, "#FFFFFF", "#FFD84D", "#000000", 0.0035, 0.0, False, "word", 100
    ),
    "bold-pop": Preset(
        "bold-pop",
        "Inter Black",
        False,
        0.056,
        "#FFFFFF",
        "#8B5CF6",
        "#000000",
        0.0055,
        0.0,
        True,
        "word",
        112,
    ),
    "karaoke": Preset(
        "karaoke",
        "Inter Black",
        False,
        0.05,
        "#FFFFFF",
        "#4D9FFF",
        "#000000",
        0.005,
        0.0,
        False,
        "karaoke",
        100,
    ),
    "minimal": Preset(
        "minimal",
        "Inter",
        False,
        0.034,
        "#FFFFFF",
        "#FFFFFF",
        "#000000",
        0.008,
        0.0,
        False,
        "word",
        100,
        box=True,
    ),
}
DEFAULT_PRESET = "bold-pop"


def escape_ass(text: str) -> str:
    """ASS has no escape for override braces or backslashes: replace them with look-alikes."""
    return (
        text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", " ").replace("\r", " ")
    )


def clip_words(words: list[Word], clip: Clip) -> list[Word]:
    """Words whose midpoint lies inside the clip, with user corrections applied
    (``clip.text_overrides`` is keyed by transcript word index), re-timed relative to the clip start."""
    out = []
    length = clip.end - clip.start
    for idx, w in enumerate(words):
        mid = (w.start + w.end) / 2
        if mid < clip.start:
            continue
        if mid > clip.end:
            break
        text = clip.text_overrides.get(idx, w.text).strip()
        if not text:
            continue  # the user deleted this word
        start = max(0.0, w.start - clip.start)
        end = min(length, w.end - clip.start)
        out.append(Word(text=text, start=round(start, 3), end=round(max(end, start + 0.05), 3), prob=w.prob))
    return out


def shift_words(words: list[Word], offset: float) -> list[Word]:
    """Move word times by ``offset`` seconds (used to time a single preview frame)."""
    return [
        w.model_copy(update={"start": round(w.start + offset, 3), "end": round(w.end + offset, 3)})
        for w in words
    ]


def group_words(words: list[Word]) -> list[list[Word]]:
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for k, w in enumerate(words):
        cur.append(w)
        nxt = words[k + 1] if k + 1 < len(words) else None
        chars = sum(len(x.text) + 1 for x in cur)
        punct_end = w.text.endswith((".", "?", "!", "…", ",", ";", ":"))
        gap = (nxt.start - w.end) if nxt else 0.0
        if (
            nxt is None
            or len(cur) >= MAX_GROUP
            or (len(cur) >= MIN_GROUP and (punct_end or chars >= MAX_GROUP_CHARS))
            or gap > BREAK_GAP_S
            or (punct_end and w.text.endswith((".", "?", "!", "…")))
        ):
            groups.append(cur)
            cur = []
    # Avoid orphan one-word lines: join the previous line if it has room, otherwise borrow its last word.
    merged: list[list[Word]] = []
    for g in groups:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and len(g) == 1
            and g[0].start - prev[-1].end <= BREAK_GAP_S
            and not prev[-1].text.endswith((".", "?", "!", "…"))
        ):
            if len(prev) < MAX_GROUP:
                prev.append(g[0])
                continue
            g.insert(0, prev.pop())
        merged.append(g)
    return merged


def _ts(t: float) -> str:
    cs = max(0, int(round(t * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(words: list[Word], preset_name: str, width: int, height: int, *, vertical: bool) -> str:
    p = PRESETS.get(preset_name, PRESETS[DEFAULT_PRESET])
    size = round(height * p.size_ratio * (1.0 if vertical else 1.25))
    outline = max(1.0, round(height * p.outline_ratio, 1))
    # Safe zone: vertical platforms overlay UI at the bottom ~20%; sit in the lower third above it.
    margin_v = round(height * (0.24 if vertical else 0.07))
    margin_h = round(width * 0.08)
    border_style = 3 if p.box else 1
    back = _ass_color(p.box_color, p.box_alpha) if p.box else _ass_color("#000000", 0xFF)
    outline_col = back if p.box else _ass_color(p.outline)
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Main,{p.font},{size},{_ass_color(p.text)},{_ass_color(p.highlight)},{outline_col},{back},"
        f"{-1 if p.bold else 0},0,0,0,100,100,0,0,{border_style},{outline},{p.shadow},2,"
        f"{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    hl = _ass_color(p.highlight)
    base = _ass_color(p.text)
    lines: list[str] = []
    groups = group_words(words)
    for g_idx, group in enumerate(groups):
        next_start = groups[g_idx + 1][0].start if g_idx + 1 < len(groups) else None
        group_end = group[-1].end + HOLD_S
        if next_start is not None:
            group_end = min(group_end, next_start)
        texts = [escape_ass(w.text.upper() if p.uppercase else w.text) for w in group]
        for k, w in enumerate(group):
            start = w.start
            end = group[k + 1].start if k + 1 < len(group) else group_end
            if end <= start:
                continue
            parts = []
            for m, t in enumerate(texts):
                active = m == k
                lit = active or (p.mode == "karaoke" and m < k)
                if lit and p.pop != 100 and active:
                    parts.append(f"{{\\c{hl}\\fscx{p.pop}\\fscy{p.pop}}}{t}{{\\c{base}\\fscx100\\fscy100}}")
                elif lit and p.highlight != p.text:
                    parts.append(f"{{\\c{hl}}}{t}{{\\c{base}}}")
                else:
                    parts.append(t)
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(lines) + "\n"


def _srt_ts(t: float, sep: str) -> str:
    ms = max(0, int(round(t * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def build_srt(words: list[Word]) -> str:
    out = []
    for n, g in enumerate(group_words(words), 1):
        text = " ".join(w.text for w in g)
        out.append(f"{n}\n{_srt_ts(g[0].start, ',')} --> {_srt_ts(g[-1].end, ',')}\n{text}\n")
    return "\n".join(out)


def build_vtt(words: list[Word]) -> str:
    cues = []
    for g in group_words(words):
        # Word-level timing tags let compatible players highlight words, others just show the line.
        body = " ".join(f"<{_srt_ts(w.start, '.')}>{w.text.replace('<', '&lt;')}" for w in g)
        cues.append(f"{_srt_ts(g[0].start, '.')} --> {_srt_ts(g[-1].end, '.')}\n{body}\n")
    return "WEBVTT\n\n" + "\n".join(cues)
