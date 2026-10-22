"""Plain-text and JSON output."""

from __future__ import annotations

import json
import textwrap
from collections import Counter

from easy_or_not import load
from easy_or_not.analysis import Report

BAR_WIDTH = 30


def _bar(fraction: float) -> str:
    filled = round(fraction * BAR_WIDTH)
    return "#" * filled + "." * (BAR_WIDTH - filled)


def _pct(fraction: float) -> str:
    return f"{fraction * 100:4.0f}%"


def render_text(report: Report) -> str:
    z = report.zones
    lines = [
        f"{len(report.runs)} runs, heart-rate bands from {z.source}",
        f"  easy below {z.easy_ceiling} bpm   middle {z.easy_ceiling}-{z.hard_floor - 1} bpm"
        f"   hard {z.hard_floor}+ bpm",
        "",
    ]
    if report.skipped:
        lines.append(f"  {len(report.skipped)} more left out:")
        reasons = Counter(reason for _, reason in report.skipped)
        for reason, count in reasons.items():
            lines.append(f"    {count} with {reason}")
    for warning in report.warnings:
        lines.append("")
        lines += textwrap.wrap(warning, width=78, initial_indent="! ", subsequent_indent="  ")
    lines += ["", "Where your running time went"]
    for band in ("easy", "middle", "hard"):
        f = report.total_fraction(band)
        lines.append(f"  {band:<7}{_pct(f)}  {_bar(f)}")
    lines.append("  A common target is around 80% easy with the rest mostly hard.")
    lines.append("")

    easy = report.easy_runs
    lines.append(f"Your easy runs ({len(easy)} of {len(report.runs)}, sessions excluded)")
    if easy:
        drift = report.easy_run_middle_fraction()
        lines.append(f"  {_pct(drift).strip()} of easy-run time was in the middle band.")
        worst = sorted(easy, key=lambda r: r.fraction("middle"), reverse=True)[:3]
        for r in worst:
            where = "treadmill" if r.run.treadmill else "outdoor"
            lines.append(
                f"    {r.run.start:%a %d %b}  {r.total_s / 60:4.0f} min  "
                f"{_pct(r.fraction('middle'))} middle  ({where})"
            )
    lines.append("")

    lines.append("Same heart rate, faster? (outdoor easy runs only)")
    trend = report.efficiency_trend()
    if trend is None:
        lines.append("  Not enough outdoor easy runs yet; needs at least six.")
    else:
        first, last = trend
        change = (last - first) / first
        lines.append(f"  {first:.2f} -> {last:.2f} metres per heartbeat ({change * 100:+.1f}%).")
        lines.append(
            "  Higher means you cover more ground for the same effort."
            if change > 0
            else "  Flat or falling; worth checking sleep, heat and whether easy is easy."
        )
    if any(r.run.treadmill for r in report.runs):
        lines.append("  Treadmill runs are left out: wrist pace indoors is an estimate.")
    lines.append("")
    lines += _load_lines(report)
    return "\n".join(lines)


def _load_lines(report: Report) -> list[str]:
    lines = ["Training load (heart-rate minutes, weighted 1 to 5 by zone)"]
    current = load.status(report)
    if current is None:
        return [*lines, "  No heart-rate data."]
    lines.append(f"  Last 7 days to {current.as_of:%a %d %b}: {current.acute:.0f}")
    if current.chronic is None:
        lines.append("  Needs 4 weeks of runs to compare with your usual week.")
    else:
        lines.append(f"  Your average week over the last 4: {current.chronic:.0f}")
        lines.append(f"  Ratio {current.ratio:.2f}: {current.verdict}.")
    weeks = load.weekly(report)[-8:]
    top = max((w for _, w in weeks), default=0.0)
    if top > 0:
        lines.append("  Week of")
        for monday, week_load in weeks:
            lines.append(f"    {monday:%d %b}  {week_load:5.0f}  {_bar(week_load / top)}")
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
