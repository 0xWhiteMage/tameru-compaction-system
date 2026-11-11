#!/usr/bin/env python3
"""Render ``assets/demo-cli.gif``: a terminal recording of the real compactor on a sample Gradle build log.

Nothing in the animation is invented. The script builds a deterministic sample log, runs the engine on it
(``compress_context``, the function behind ``tameru-compress``) and draws what the commands would print: the line counts
come from the input and the output, and the extract is the engine's actual text. Run it again after an engine change and the
GIF follows the engine.

    python scripts/render_demo_gif.py [OUTPUT.gif]

Needs Pillow and a monospace font (Cascadia Mono, Consolas, DejaVu Sans Mono or Menlo, whichever it finds; set
``TAMERU_DEMO_FONT`` to a ``.ttf`` path to choose one).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from tameru.compress_context import compress_context  # noqa: E402

QUERY = "Why did the build fail?"
FONT_CANDIDATES = (
    "C:/Windows/Fonts/CascadiaMono.ttf", "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/System/Library/Fonts/Menlo.ttc",
)
BG, FG, DIM, GREEN, RED, AMBER, BAR = "#14161c", "#d7dae0", "#7b8190", "#7ee787", "#ff7b72", "#e3b341", "#232733"
WIDTH, HEIGHT, PAD, TOP, SIZE = 1000, 640, 22, 54, 15


def sample_log() -> str:
    """A Gradle build log of the kind an agent reads: hundreds of routine task lines, one failing test buried in the middle."""
    lines = ["> Configure project :", "Gradle 8.9 | JVM 21.0.4 | 38 projects", ""]
    for n in range(1, 61):
        lines.append(f"> Task :service-{n:02d}:compileJava UP-TO-DATE")
        lines.append(f"> Task :service-{n:02d}:processResources UP-TO-DATE")
    lines += [
        "> Task :checkout:compileTestJava",
        "> Task :checkout:test",
        "",
        "RefundTest > refundRoundsToCents() FAILED",
        "    org.opentest4j.AssertionFailedError: expected: <20.00> but was: <19.99>",
        "        at app//com.acme.checkout.RefundTest.refundRoundsToCents(RefundTest.java:88)",
        "",
        "212 tests completed, 1 failed",
        "> Task :checkout:test FAILED",
    ]
    for n in range(61, 121):
        lines.append(f"> Task :service-{n:02d}:compileJava UP-TO-DATE")
    lines += ["", "FAILURE: Build failed with an exception.", "* What went wrong:",
              "Execution failed for task ':checkout:test'.",
              "> There were failing tests. See the report at: file:///ci/checkout/build/reports/tests/test/index.html",
              "", "BUILD FAILED in 41s", "118 actionable tasks: 6 executed, 112 up-to-date"]
    return "\n".join(lines)


def load_font() -> ImageFont.FreeTypeFont:
    paths = ([os.environ["TAMERU_DEMO_FONT"]] if os.environ.get("TAMERU_DEMO_FONT") else []) + list(FONT_CANDIDATES)
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, SIZE)
    raise SystemExit("no monospace font found; set TAMERU_DEMO_FONT to a .ttf path")


def colour_for(line: str) -> str:
    if "RefundTest" in line or "AssertionFailedError" in line:   # the one failure the animation points at; nothing else is red
        return RED
    if line.strip() == "[…]":
        return DIM
    return FG


def main(out: Path) -> None:
    log = sample_log()
    result = compress_context(log, QUERY, ccr=False, citations=False)
    extract = result.compressed_text.rstrip("\n")
    in_lines, out_lines = len(log.splitlines()), len(extract.splitlines())
    shown = [line if len(line) <= 104 else line[:101] + "..." for line in extract.splitlines()]

    # What the terminal shows, as (text, colour, is_typed) rows; typed rows appear character by character.
    script: list[tuple[str, str, bool]] = [
        ("$ wc -l build.log", FG, True), (f"{in_lines} build.log", DIM, False), ("", FG, False),
        (f'$ tameru-compress build.log "{QUERY}" --no-ccr', FG, True),
        *[(line, colour_for(line), False) for line in shown], ("", FG, False),
        (f"# {in_lines} lines in, {out_lines} out: {result.tokens_saved_pct:.0f}% fewer tokens, and the failing test is still there.", GREEN, False),
    ]
    note_row = next(i for i, (text, _c, _t) in enumerate(script) if "RefundTest" in text)
    NOTE = "<- kept: the failing test and why it failed"

    font = load_font()
    line_h = SIZE + 6
    capacity = (HEIGHT - TOP - PAD) // line_h

    def frame(rows: list[tuple[str, str]], cursor: bool, note: bool = False) -> Image.Image:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, WIDTH, 34], fill=BAR)
        for i, colour in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
            d.ellipse([PAD + i * 22, 11, PAD + 12 + i * 22, 23], fill=colour)
        d.text((WIDTH // 2 - 90, 9), "tameru-compress", font=font, fill=DIM)
        visible = rows[-capacity:]
        for index, (text, colour) in enumerate(visible):
            d.text((PAD, TOP + index * line_h), text, font=font, fill=colour)
        if note:
            index = note_row - max(0, len(rows) - capacity)
            if 0 <= index < len(visible):
                x = PAD + d.textlength(visible[index][0], font=font) + 18
                d.text((x, TOP + index * line_h), NOTE, font=font, fill=AMBER)
        if cursor:
            y = TOP + (len(visible) - 1) * line_h if visible else TOP
            width = d.textlength(visible[-1][0], font=font) if visible else 0
            d.rectangle([PAD + width + 2, y + 2, PAD + width + 10, y + line_h - 2], fill=FG)
        return img

    frames: list[Image.Image] = []
    durations: list[int] = []
    rows: list[tuple[str, str]] = []

    def add(rows_now, ms, cursor=False, note=False):
        frames.append(frame(rows_now, cursor, note))
        durations.append(ms)

    add(rows, 350, True)
    for text, colour, typed in script:
        if typed:
            for end in range(4, len(text) + 4, 4):
                add(rows + [(text[:end], colour)], 28, True)
            rows.append((text, colour))
            add(rows, 260)
        else:
            rows.append((text, colour))
            if len(rows) % 4 == 0:
                add(rows, 60)
    add(rows, 400)
    add(rows, 3400, note=True)

    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print(f"wrote {out} ({out.stat().st_size // 1024} KiB, {len(frames)} frames); {in_lines} lines -> {out_lines}, "
          f"{result.tokens_saved_pct:.1f}% tokens saved")
    print("--- extract ---")
    print("\n".join(shown))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "demo-cli.gif")
