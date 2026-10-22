"""Plain-text and JSON output."""

from __future__ import annotations

import json

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
        "Where your running time went",
    ]
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
    return "\n".join(lines)


def render_json(report: Report) -> str:
    return json.dumps(
        {
            "zones": vars(report.zones),
            "totals": {b: report.total_fraction(b) for b in ("easy", "middle", "hard")},
            "easy_run_middle_fraction": report.easy_run_middle_fraction(),
            "efficiency_trend": report.efficiency_trend(),
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
                }
                for r in report.runs
            ],
        },
        indent=2,
    )
