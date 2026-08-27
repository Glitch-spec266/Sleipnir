"""The chrome must stay a pure function of the frame number, and must never
be able to widen a line beyond the terminal or leak an unterminated escape."""

from __future__ import annotations

import re

from sleipnir import theme

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _visible(text: str) -> str:
    return ANSI.sub("", text)


def test_easings_are_bounded_and_monotonic_at_the_ends():
    for ease in (theme.ease_power2_out, theme.ease_power4_in, theme.ease_elastic_out):
        assert ease(0.0) == 0.0
        assert abs(ease(1.0) - 1.0) < 1e-9
    # back.out overshoots on purpose; it must still land exactly on 1.
    assert theme.ease_back_out(0.8) > 1.0
    assert abs(theme.ease_back_out(1.0) - 1.0) < 1e-9


def test_easing_clamps_out_of_range_input():
    assert theme.ease_power2_out(-5) == 0.0
    assert theme.ease_power2_out(5) == 1.0


def test_flicker_is_deterministic_and_mostly_quiet():
    assert theme.flicker_level(17) == theme.flicker_level(17)
    levels = [theme.flicker_level(n) for n in range(400)]
    quiet = sum(1 for level in levels if level == theme.NORMAL)
    # Occasional, not constant: a jittering border every frame is noise.
    assert 0.80 < quiet / len(levels) < 0.97
    assert all(0 <= level <= theme.BRIGHT for level in levels)


def test_frame_lines_never_exceed_requested_width():
    body = "\n".join("x" * 500 for _ in range(4))
    rendered = theme.frame(body, width=60, frame_number=3, footer="q quits")
    for line in rendered.split("\n"):
        assert len(_visible(line)) == 60, repr(_visible(line))


def test_frame_works_without_colour():
    rendered = theme.frame("hello", width=40, colour=False)
    assert "\x1b[" not in rendered
    assert "SLEIPNIR" in rendered


def test_logo_has_a_full_wordmark_and_eight_leg_strokes():
    full = "\n".join(theme.logo_lines(theme.LOGO_WIDTH + 4))
    compact = "\n".join(theme.logo_lines(20))

    assert len(theme.logo_lines(theme.LOGO_WIDTH + 4)) == 7
    assert theme.COMPACT_LOGO[0] == "SLEIPNIR"
    assert full.count("╲") == 4 and full.count("╱") == 4
    assert compact == "SLEIPNIR\n╲╱ ╲╱ ╲╱ ╲╱"


def test_every_escape_sequence_is_terminated():
    rendered = theme.splash_frame(20, width=80, height=24)
    # Equal counts of colour-set and reset means nothing bleeds past the frame.
    assert rendered.count("\x1b[38;2;") == rendered.count(theme.RESET)


def test_splash_renders_every_frame_at_a_narrow_terminal():
    for index in range(theme.SPLASH_FRAMES):
        rendered = theme.splash_frame(index, width=32, height=12)
        for line in rendered.split("\n"):
            assert len(_visible(line)) == 32


def test_splash_ends_fully_revealed():
    final = _visible(theme.splash_frame(theme.SPLASH_FRAMES - 1, width=90, height=24))
    assert "▮▮▮▮▮▮▮▮" in final  # all eight legs have struck
    assert "orchestrator" in final


def test_colour_is_suppressed_when_no_color_is_set(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert theme.supports_colour() is False
