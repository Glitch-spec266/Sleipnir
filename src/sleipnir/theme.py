"""Terminal chrome for Sleipnir: green frame, CRT flicker, and the splash.

The TUI cannot run a browser animation library, so the part of GSAP that
actually matters here — its easing curves — is ported directly.  A reveal on
``power2.out`` reads differently from a linear one even in ASCII, and the curve
is three lines of maths rather than a dependency.

Everything in this module is a pure function of an explicit frame number.  That
keeps the animation deterministic, testable without a terminal, and free of any
hidden clock.  Rendering stays a pure function of state, exactly as the
dashboard already is.

Untrusted text never reaches here uncoloured: callers pass strings that have
already been through ``tui._clip``.  This module only ever *prepends* escape
sequences it generates itself.
"""

from __future__ import annotations

import math
import os
import random
import re
import sys

RESET = "\x1b[0m"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR = "\x1b[2J\x1b[H"
#: Switch to the terminal's alternate screen, and back. Without this a
#: full-screen redraw loop appends every frame to the user's scrollback: after a
#: few minutes at 12fps the history holds hundreds of stacked copies of the UI,
#: which on exit reads as though the program opened itself over and over. The
#: alternate buffer also restores the shell exactly as it was.
ENTER_FULLSCREEN = "\x1b[?1049h"
EXIT_FULLSCREEN = "\x1b[?1049l"
#: Ask the terminal to wrap pasted text in CSI 200/201 markers. Without this,
#: multiline paste is indistinguishable from pressing Enter and can submit a
#: partial prompt; with it, the console receives one atomic paste event.
ENABLE_BRACKETED_PASTE = "\x1b[?2004h"
DISABLE_BRACKETED_PASTE = "\x1b[?2004l"

# Phosphor greens, dimmest to brightest.  The flicker walks this ramp rather
# than fading to black, so a dip reads as a failing tube and not as a dropout.
_RAMP = (
    (0, 40, 0),
    (0, 70, 0),
    (0, 110, 20),
    (20, 160, 40),
    (60, 220, 90),
    (150, 255, 160),
    (210, 255, 215),
)

BRIGHT = len(_RAMP) - 1
NORMAL = 4
DIM = 2


def supports_colour(stream: object | None = None) -> bool:
    """True when it is safe to emit escape sequences.

    ``NO_COLOR`` is honoured (https://no-color.org) and a redirected stdout is
    treated as a file, so ``sleipnir tui > log.txt`` stays greppable.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") in (None, "", "dumb"):
        return False
    stream = sys.stdout if stream is None else stream
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def fg(level: int) -> str:
    """Truecolor foreground escape for a rung of the phosphor ramp."""
    red, green, blue = _RAMP[max(0, min(BRIGHT, level))]
    return f"\x1b[38;2;{red};{green};{blue}m"


def paint(text: str, level: int = NORMAL, *, colour: bool = True) -> str:
    return f"{fg(level)}{text}{RESET}" if colour else text


# ---------------------------------------------------------------------------
# Easing (ported from GSAP's curve definitions)
# ---------------------------------------------------------------------------


def ease_power2_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def ease_power4_in(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t**5


def ease_back_out(t: float, overshoot: float = 1.70158) -> float:
    """Overshoots past 1.0 then settles — GSAP's ``back.out``."""
    t = min(1.0, max(0.0, t)) - 1
    return t * t * ((overshoot + 1) * t + overshoot) + 1


def ease_elastic_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    if t in (0.0, 1.0):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1


# ---------------------------------------------------------------------------
# Flicker
# ---------------------------------------------------------------------------


def flicker_level(frame: int, *, seed: int = 0, base: int = NORMAL) -> int:
    """Brightness for one frame of border.

    Deliberately *occasional*: a fixed per-frame jitter reads as noise and gets
    annoying within a minute.  Instead most frames sit exactly on ``base`` and a
    dip or surge fires roughly one frame in nine, which reads as a tube
    struggling rather than as a broken renderer.
    """
    rng = random.Random((frame * 2654435761) ^ seed)
    roll = rng.random()
    if roll < 0.055:
        return max(0, base - rng.randint(1, 2))
    if roll < 0.11:
        return min(BRIGHT, base + 1)
    return base


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

# Sleipnir: Odin's eight-legged horse. This is an emblem rather than a rendered
# product name: the frame already carries the name, while the mark itself should
# remain recognisable without letters. Four pairs below the body make all eight
# legs explicit, including in the compact form.
LOGO = (
    "                 ╭╮",
    "        ╭────────╯╰──╮",
    "   ╭────╯             ╰╮",
    "≋≋╯    ╭────────╮   ◉  ╰╮",
    " ╰─────╯        ╰───────╯",
    "    ││   ││   ││   ││",
    "    ╱╲   ╱╲   ╱╲   ╱╲",
)

LOGO_WIDTH = max(len(line) for line in LOGO)

COMPACT_LOGO = ("♞  ││ ││ ││ ││", "   ╱╲ ╱╲ ╱╲ ╱╲")


def logo_lines(width: int) -> tuple[str, ...]:
    return LOGO if width >= LOGO_WIDTH + 4 else COMPACT_LOGO


# ---------------------------------------------------------------------------
# Border
# ---------------------------------------------------------------------------

_CORNERS = ("╔", "╗", "╚", "╝")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def visible_width(text: str) -> int:
    """Printable width, ignoring colour escapes.

    Body lines arrive already coloured, so padding them by ``len()`` would
    count twenty invisible bytes as twenty columns and collapse the frame.
    """
    return len(_ANSI.sub("", text))


def _fit(line: str, width: int) -> str:
    """Pad or truncate to ``width`` visible columns, keeping colour intact."""
    current = visible_width(line)
    if current <= width:
        return line + " " * (width - current)
    kept: list[str] = []
    shown = 0
    index = 0
    while index < len(line) and shown < width:
        match = _ANSI.match(line, index)
        if match:  # escapes cost no columns, and must never be split
            kept.append(match.group())
            index = match.end()
            continue
        kept.append(line[index])
        shown += 1
        index += 1
    truncated = "".join(kept)
    # Only re-terminate if the cut could have orphaned an open colour.
    return truncated + RESET if "\x1b[" in truncated else truncated


def frame(
    body: str,
    *,
    width: int,
    frame_number: int = 0,
    title: str = "SLEIPNIR",
    footer: str = "",
    colour: bool = True,
) -> str:
    """Wrap already-clipped body text in the flickering green border.

    ``width`` is the total outer width; body lines are padded or truncated to
    fit inside it.  Truncation is on printable characters the caller supplied,
    so it cannot split an escape sequence this module wrote.
    """
    inner = max(4, width - 4)
    level = flicker_level(frame_number)
    edge = fg(level) if colour else ""
    end = RESET if colour else ""

    title_text = f" {title} "[:inner]
    top = _CORNERS[0] + "═" + title_text + "═" * (inner - len(title_text) + 1) + _CORNERS[1]
    bottom_text = f" {footer} "[:inner] if footer else ""
    bottom = (
        _CORNERS[2]
        + "═" * (inner - len(bottom_text) + 1)
        + bottom_text
        + "═"
        + _CORNERS[3]
    )

    out = [f"{edge}{top}{end}"]
    for line in body.split("\n"):
        out.append(f"{edge}║{end} {_fit(line, inner)} {edge}║{end}")
    out.append(f"{edge}{bottom}{end}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Splash
# ---------------------------------------------------------------------------

SPLASH_FRAMES = 46


def splash_frame(index: int, *, width: int, height: int, colour: bool = True) -> str:
    """One frame of the boot animation.

    Three overlapping tracks, the way a GSAP timeline would stagger them:
    the emblem eases in on ``back.out`` (overshoot, then settle), the eight legs
    strike one at a time on ``power2.out``, and the tagline fades last.
    """
    progress = index / max(1, SPLASH_FRAMES - 1)
    inner = max(4, width - 4)
    lines: list[str] = []

    def centred(text: str, level: int) -> str:
        pad = max(0, (inner - len(text)) // 2)
        return paint(" " * pad + text, level, colour=colour)

    art = logo_lines(width)
    art_width = max(len(line) for line in art)
    reveal = ease_back_out(min(1.0, progress / 0.7))
    visible_columns = int(reveal * (art_width + 2))

    for row, line in enumerate(art):
        # Rows light up staggered, so the emblem assembles rather than wipes.
        # The pad is computed from the *full* width so the logo does not slide
        # sideways as it reveals — it emerges in place.
        row_progress = min(1.0, max(0.0, progress * 1.4 - row * 0.06))
        level = DIM + round(ease_power2_out(row_progress) * (BRIGHT - DIM))
        pad = max(0, (inner - art_width) // 2)
        lines.append(paint(" " * pad + line[:visible_columns], level, colour=colour))

    legs = int(ease_power2_out(min(1.0, max(0.0, (progress - 0.4) / 0.45))) * 8)
    strike = "".join("▮" if i < legs else "▯" for i in range(8))
    lines.append("")
    lines.append(centred(strike, NORMAL + 1))

    if progress > 0.6:
        fade = ease_power2_out((progress - 0.6) / 0.4)
        level = DIM + round(fade * (NORMAL - DIM))
        lines.append("")
        lines.append(centred("budget-aware agentic orchestrator", level))

    body = "\n".join(lines)
    pad = max(0, (height - len(lines) - 4) // 2)
    body = "\n" * pad + body
    return frame(
        body,
        width=width,
        frame_number=index,
        title="SLEIPNIR",
        footer="booting",
        colour=colour,
    )


__all__ = [
    "BRIGHT",
    "CLEAR",
    "DISABLE_BRACKETED_PASTE",
    "DIM",
    "ENABLE_BRACKETED_PASTE",
    "HIDE_CURSOR",
    "LOGO",
    "NORMAL",
    "RESET",
    "SHOW_CURSOR",
    "SPLASH_FRAMES",
    "ease_back_out",
    "ease_elastic_out",
    "ease_power2_out",
    "ease_power4_in",
    "flicker_level",
    "fg",
    "frame",
    "logo_lines",
    "paint",
    "splash_frame",
    "supports_colour",
]
