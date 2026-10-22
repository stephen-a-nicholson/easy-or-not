"""Plain-text and JSON output."""

from __future__ import annotations

import json
import textwrap
from collections import Counter
from dataclasses import dataclass

from easy_or_not import load
from easy_or_not.analysis import Report

BAR_WIDTH = 30
BANDS = ("easy", "middle", "hard")

# ANSI colour codes. Only used when writing to a terminal (see cli.use_colour).
RESET = "\033[0m"
BOLD = "1"
DIM = "2"
COLOURS = {"easy": "32", "middle": "33", "hard": "31", "load": "36", "warning": "1;33"}
VERDICT_COLOURS = {"in line": "32", "a step up": "33", "a big jump": "31"}


@dataclass(frozen=True)
class Style:
    colour: bool = False
    blocks: bool = False  # Unicode block bars instead of ASCII

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}{RESET}" if self.colour and code else text

    def bar(self, fraction: float, code: str = "") -> str:
        filled = round(max(0.0, min(1.0, fraction)) * BAR_WIDTH)
        full, empty = ("\u2588", "\u2591") if self.blocks else ("#", ".")
        return self.paint(full * filled, code) + self.paint(empty * (BAR_WIDTH - filled), DIM)


def _pct(fraction: float) -> str:
    return f"{fraction * 100:4.0f}%"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def render_text(report: Report, style: Style | None = None) -> str:
    st = style or Style()
    z = report.zones
    heading = lambda text: st.paint(text, BOLD)  # noqa: E731
    note = lambda text: st.paint(text, DIM)  # noqa: E731
    band_names = {b: st.paint(f"{b:<7}", COLOURS[b]) for b in BANDS}

    lines = [heading(f"{_plural(len(report.runs), 'run')}, heart-rate bands from {z.source}")]
    name = {b: st.paint(b, COLOURS[b]) for b in BANDS}
    lines.append(
        f"  {name['easy']} below {z.easy_ceiling} bpm   "
        f"{name['middle']} {z.easy_ceiling}-{z.hard_floor - 1} bpm   "
        f"{name['hard']} {z.hard_floor}+ bpm"
    )
    if report.skipped:
        lines.append("")
        lines.append(note(f"  {len(report.skipped)} more left out:"))
        for reason, count in Counter(reason for _, reason in report.skipped).items():
            lines.append(note(f"    {count} with {reason}"))
    for warning in report.warnings:
        lines.append("")
        wrapped = textwrap.wrap(warning, width=78, initial_indent="! ", subsequent_indent="  ")
        lines += [st.paint(line, COLOURS["warning"]) for line in wrapped]

    lines += ["", heading("Where your running time went")]
    for band in BANDS:
        f = report.total_fraction(band)
        lines.append(f"  {band_names[band]}{_pct(f)}  {st.bar(f, COLOURS[band])}")
    lines.append(note("  A common target is around 80% easy with the rest mostly hard."))
    lines.append("")

    easy = report.easy_runs
    lines.append(heading(f"Your easy runs ({len(easy)} of {len(report.runs)}, sessions excluded)"))
    if easy:
        drift = report.easy_run_middle_fraction()
        lines.append(f"  {_pct(drift).strip()} of easy-run time was in the middle band.")
        worst = sorted(easy, key=lambda r: r.fraction("middle"), reverse=True)[:3]
        for r in worst:
            where = "treadmill" if r.run.treadmill else "outdoor"
            middle = st.paint(f"{_pct(r.fraction('middle'))} middle", COLOURS["middle"])
            lines.append(
                f"    {r.run.start:%a %d %b}  {r.total_s / 60:4.0f} min  {middle}  ({where})"
            )
    else:
        lines.append("  None: every run had at least 10% of its time in the hard band.")
    lines.append("")

    lines.append(heading("Same heart rate, faster?") + note(" (outdoor easy runs only)"))
    trend = report.efficiency_trend()
    if trend is None:
        lines.append(note("  Not enough outdoor easy runs yet; needs at least six."))
    else:
        first, last = trend
        change = (last - first) / first
        lines.append(f"  {first:.2f} -> {last:.2f} metres per heartbeat ({change * 100:+.1f}%).")
        lines.append(
            note("  Higher means you cover more ground for the same effort.")
            if change > 0
            else note("  Flat or falling; worth checking sleep, heat and whether easy is easy.")
        )
    if any(r.run.treadmill for r in report.runs):
        lines.append(note("  Treadmill runs are left out: wrist pace indoors is an estimate."))
    lines.append("")
    lines += _load_lines(report, st)
    return "\n".join(lines)


def _load_lines(report: Report, st: Style) -> list[str]:
    lines = [
        st.paint("Training load", BOLD)
        + st.paint(" (heart-rate minutes, weighted 1 to 5 by zone)", DIM)
    ]
    current = load.status(report)
    if current is None:
        return [*lines, "  No heart-rate data."]
    lines.append(f"  Last 7 days to {current.as_of:%a %d %b}: {current.acute:.0f}")
    if current.chronic is None:
        lines.append(st.paint("  Needs 4 weeks of runs to compare with your usual week.", DIM))
    else:
        lines.append(f"  Your average week over the last 4: {current.chronic:.0f}")
        verdict = current.verdict or ""
        code = next((c for k, c in VERDICT_COLOURS.items() if verdict.startswith(k)), "")
        lines.append(f"  Ratio {current.ratio:.2f}: {st.paint(verdict, code)}.")
    weeks = load.weekly(report)[-8:]
    top = max((w for _, w in weeks), default=0.0)
    if top > 0:
        lines.append(st.paint("  Week of", DIM))
        for monday, week_load in weeks:
            lines.append(
                f"    {monday:%d %b}  {week_load:5.0f}  {st.bar(week_load / top, COLOURS['load'])}"
            )
    return lines


def render_json(report: Report) -> str:
    return json.dumps(
        {
            "zones": vars(report.zones),
            "totals": {b: report.total_fraction(b) for b in ("easy", "middle", "hard")},
            "easy_run_middle_fraction": report.easy_run_middle_fraction(),
            "efficiency_trend": report.efficiency_trend(),
            "warnings": report.warnings,
            "skipped": [
                {"id": run.run_id, "start": run.start.isoformat(), "reason": reason}
                for run, reason in report.skipped
            ],
            "load": _load_json(report),
            "weekly": [
                {"week": week.isoformat(), "seconds": seconds} for week, seconds in report.weekly()
            ],
            "runs": [
                {
                    "id": r.run.run_id,
                    "start": r.run.start.isoformat(),
                    "treadmill": r.run.treadmill,
                    "session": r.is_session,
                    "seconds": r.seconds,
                    "efficiency": r.efficiency,
                    "load": r.load,
                }
                for r in report.runs
            ],
        },
        indent=2,
    )


def _load_json(report: Report) -> dict | None:
    current = load.status(report)
    if current is None:
        return None
    return {
        "method": "Edwards TRIMP",
        "as_of": current.as_of.isoformat(),
        "last_7_days": current.acute,
        "average_week_last_28_days": current.chronic,
        "ratio": current.ratio,
        "weekly": [{"week": m.isoformat(), "load": w} for m, w in load.weekly(report)],
    }
