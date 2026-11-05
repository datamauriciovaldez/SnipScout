"""Spike 1: check candidate ffmpeg builds for libass + libx264 and really render ASS subs."""
import shutil
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
FONTS = OUT / "fonts"
FONTS.mkdir(exist_ok=True)
# Inter is OFL; copy one face into a private fontsdir to prove fontsdir loading.
src_font = Path("/usr/share/fonts/opentype/inter/Inter-Bold.otf")
if src_font.exists():
    shutil.copy(src_font, FONTS / "Inter-Bold.otf")

ASS = r"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,Inter,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,0,2,60,60,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:00.60,Pop,,0,0,0,,{\c&H00F0B428&}Hola{\c&H00FFFFFF&} mundo ñandú
Dialogue: 0,0:00:00.60,0:00:01.20,Pop,,0,0,0,,Hola {\c&H00F0B428&}mundo{\c&H00FFFFFF&} ñandú
Dialogue: 0,0:00:01.20,0:00:02.00,Pop,,0,0,0,,Hola mundo {\c&H00F0B428&}ñandú{\c&H00FFFFFF&}
"""


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=cwd)


def check(name: str, exe: str) -> dict:
    res: dict = {"name": name, "exe": exe}
    v = run([exe, "-hide_banner", "-version"])
    res["version"] = v.stdout.splitlines()[0] if v.stdout else v.stderr[:100]
    f = run([exe, "-hide_banner", "-filters"]).stdout
    e = run([exe, "-hide_banner", "-encoders"]).stdout
    res["ass_filter"] = any(line.split()[1:2] == ["ass"] for line in f.splitlines() if line.strip())
    res["libx264"] = "libx264" in e
    work = OUT / name
    work.mkdir(exist_ok=True)
    (work / "subs.ass").write_text(ASS, encoding="utf-8")
    shutil.copytree(FONTS, work / "fonts", dirs_exist_ok=True)
    t = time.perf_counter()
    # Relative names + cwd: the Windows-safe pattern planned in spec 4.1(10).
    r = run(
        [exe, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-vf", "ass=subs.ass:fontsdir=fonts", "-c:v", "libx264", "-crf", "23",
         "-preset", "veryfast", "-c:a", "aac", "-movflags", "+faststart", "out.mp4"],
        cwd=work,
    )
    res["render_ok"] = r.returncode == 0 and (work / "out.mp4").exists()
    res["render_s"] = round(time.perf_counter() - t, 2)
    res["render_err"] = r.stderr.strip()[:300]
    if res["render_ok"]:
        # Burned-in check: compare a frame with and without subtitles.
        run([exe, "-y", "-loglevel", "error", "-ss", "0.9", "-i", "out.mp4", "-frames:v", "1", "with.png"], cwd=work)
        run([exe, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=2",
             "-ss", "0.9", "-frames:v", "1", "without.png"], cwd=work)
        res["frames_differ"] = (work / "with.png").read_bytes() != (work / "without.png").read_bytes()
    return res


if __name__ == "__main__":
    for name, exe in [a.split("=", 1) for a in sys.argv[1:]]:
        print(check(name, exe))
