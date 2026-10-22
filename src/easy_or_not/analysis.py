"""The three questions the tool answers.

1. How is your running time split between easy, middle and hard?
2. Of the runs that were meant to be easy, how much drifted into the middle?
3. At the same easy heart rate, are you getting faster over time?
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from easy_or_not.checks import IMPLAUSIBLE_Z5_S, skip_reason, trim_tail
from easy_or_not.models import Run
from easy_or_not.zones import Zones

# Gaps longer than this between samples are pauses (traffic lights, stopping
# the watch) and are not counted as time in any zone.
MAX_GAP_S = 10.0

# A run with less hard time than this was not a session, so it counts as a
# run that was meant to be easy.
SESSION_HARD_FRACTION = 0.10

# Ignore the first few minutes when measuring efficiency: heart rate lags
# pace while you warm up and would make everyone look efficient.
WARMUP_S = 300.0


@dataclass
class RunSummary:
    run: Run
    seconds: dict[str, float]  # band -> seconds
    efficiency: float | None  # metres per heartbeat while in the easy band

    @property
    def total_s(self) -> float:
        return sum(self.seconds.values())

    def fraction(self, band: str) -> float:
        return self.seconds.get(band, 0.0) / self.total_s if self.total_s else 0.0

    @property
    def is_session(self) -> bool:
        return self.fraction("hard") >= SESSION_HARD_FRACTION


@dataclass
class Report:
    zones: Zones
    runs: list[RunSummary]
    skipped: list[tuple[Run, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def total_fraction(self, band: str) -> float:
        total = sum(r.total_s for r in self.runs)
        return sum(r.seconds.get(band, 0.0) for r in self.runs) / total if total else 0.0

    @property
    def easy_runs(self) -> list[RunSummary]:
        return [r for r in self.runs if not r.is_session]

    @property
    def sessions(self) -> list[RunSummary]:
        return [r for r in self.runs if r.is_session]

    def easy_run_middle_fraction(self) -> float:
        runs = self.easy_runs
        total = sum(r.total_s for r in runs)
        return sum(r.seconds.get("middle", 0.0) for r in runs) / total if total else 0.0

    def weekly(self) -> list[tuple[date, dict[str, float]]]:
        weeks: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in self.runs:
            monday = r.run.start.date() - timedelta(days=r.run.start.weekday())
            for band, s in r.seconds.items():
                weeks[monday][band] += s
        return sorted((k, dict(v)) for k, v in weeks.items())

    def efficiency_trend(self) -> tuple[float, float] | None:
        """Median efficiency of the first and last third of outdoor easy runs."""
        points = [r.efficiency for r in self.easy_runs if r.efficiency and not r.run.treadmill]
        if len(points) < 6:
            return None
        third = len(points) // 3
        return median(points[:third]), median(points[-third:])


def summarise(run: Run, zones: Zones) -> RunSummary:
    seconds: dict[str, float] = defaultdict(float)
    metres = 0.0
    beats = 0.0
    samples = run.samples
    for prev, cur in zip(samples, samples[1:], strict=False):
        dt = cur.elapsed_s - prev.elapsed_s
        if dt <= 0 or dt > MAX_GAP_S or prev.heart_rate is None or prev.heart_rate <= 0:
            continue
        band = zones.band(prev.heart_rate)
        seconds[band] += dt
        if band == "easy" and prev.elapsed_s >= WARMUP_S and prev.speed_mps:
            metres += prev.speed_mps * dt
            beats += prev.heart_rate * dt / 60.0
    efficiency = metres / beats if beats > 60 else None
    return RunSummary(run=run, seconds=dict(seconds), efficiency=efficiency)


def median_hr(run: Run) -> float | None:
    rates = [s.heart_rate for s in run.samples if s.heart_rate]
    return median(rates) if rates else None


def zone_warnings(runs: list[RunSummary], zones: Zones) -> list[str]:
    """Flag zones that the data says are too low."""
    suspicious = [
        (r, hr)
        for r in runs
        if r.total_s >= IMPLAUSIBLE_Z5_S and (hr := median_hr(r.run)) and hr >= zones.z5
    ]
    if not suspicious:
        return []
    r, hr = max(suspicious, key=lambda pair: pair[1])
    return [
        f"Your zones may be set too low. On {r.run.start:%a %d %b} you held a median of "
        f"{hr:.0f} bpm for {r.total_s / 60:.0f} min, above your zone 5 floor of {zones.z5}. "
        "Zone 5 is meant to be a few minutes at most, so your real max heart rate is "
        "probably higher than your zones assume. If you know it, pass --max-hr."
    ]


def analyse(runs: list[Run], zones: Zones) -> Report:
    kept: list[RunSummary] = []
    skipped: list[tuple[Run, str]] = []
    for run in sorted(runs, key=lambda r: r.start):
        summary = summarise(trim_tail(run), zones)
        reason = skip_reason(run, summary.total_s)
        if reason:
            skipped.append((run, reason))
        else:
            kept.append(summary)
    return Report(zones=zones, runs=kept, skipped=skipped, warnings=zone_warnings(kept, zones))
