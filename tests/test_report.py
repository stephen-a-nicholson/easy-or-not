from __future__ import annotations

import io

from easy_or_not.analysis import analyse
from easy_or_not.cli import terminal_style
from easy_or_not.report import Style, render_text

from .conftest import make_run

ESC = "\033["


class FakeTerminal(io.StringIO):
    def __init__(self, tty: bool, encoding: str = "utf-8") -> None:
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    def isatty(self) -> bool:
        return self._tty

    @property
    def encoding(self) -> str:
        return self._encoding


def _report(zones):
    return analyse([make_run([(1200, 130), (600, 150)])], zones)


def test_plain_style_has_no_escape_codes(zones) -> None:
    out = render_text(_report(zones))
    assert ESC not in out
    assert "#" in out


def test_colour_style_paints_bands(zones) -> None:
    out = render_text(_report(zones), Style(colour=True, blocks=True))
    assert ESC + "32m" in out  # easy in green
    assert "█" in out


def test_colour_on_a_terminal() -> None:
    assert terminal_style(FakeTerminal(tty=True), {}).colour


def test_no_colour_when_piped() -> None:
    assert not terminal_style(FakeTerminal(tty=False), {}).colour


def test_no_colour_when_no_color_set() -> None:
    assert not terminal_style(FakeTerminal(tty=True), {"NO_COLOR": "1"}).colour


def test_blocks_when_encoding_allows() -> None:
    assert terminal_style(FakeTerminal(tty=False), {}).blocks


def test_ascii_bars_on_narrow_encoding() -> None:
    assert not terminal_style(FakeTerminal(tty=False, encoding="cp1252"), {}).blocks


def test_no_easy_runs_says_so(zones) -> None:
    out = render_text(analyse([make_run([(1200, 170)])], zones))
    assert "None: every run had at least 10% of its time in the hard band." in out


def test_one_run_is_singular(zones) -> None:
    assert render_text(_report(zones)).startswith("1 run,")
