"""Training load from heart rate, for watches that do not work it out for you.

Each run's load is its Edwards TRIMP: minutes in zone 1 count once, minutes
in zone 5 count five times. It needs nothing but your heart-rate zones, so it
is only as right as they are.

The load ratio compares the last 7 days with your average week over the last
28. It describes change; it is not a readiness score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from easy_or_not.analysis import Report, RunSummary

ACUTE_DAYS = 7
CHRONIC_DAYS = 28


@dataclass(frozen=True)
class LoadStatus:
    as_of: date
    acute: float  # load in the last 7 days
    chronic: float | None  # average 7-day load over the last 28 days, if there is enough history

    @property
    def ratio(self) -> float | None:
        return self.acute / self.chronic if self.chronic else None

    @property
    def verdict(self) -> str | None:
        r = self.ratio
        if r is None:
            return None
        if r < 0.8:
            return "lighter than your recent weeks"
        if r <= 1.3:
            return "in line with your recent weeks"
        if r <= 1.5:
            return "a step up on your recent weeks"
        return "a big jump on your recent weeks; sudden jumps in load are often linked to injury"


def _all_runs(report: Report) -> list[RunSummary]:
    return sorted(report.runs + report.load_only, key=lambda r: r.run.start)


def _load_between(runs: list[RunSummary], first: date, last: date) -> float:
    return sum(r.load for r in runs if first <= r.run.start.date() <= last)


def status(report: Report) -> LoadStatus | None:
    runs = _all_runs(report)
    if not runs or report.as_of is None:
        return None
    end = report.as_of
    acute = _load_between(runs, end - timedelta(days=ACUTE_DAYS - 1), end)
    history_start = end - timedelta(days=CHRONIC_DAYS - 1)
    chronic = None
    if runs[0].run.start.date() <= history_start:
        weeks = CHRONIC_DAYS / ACUTE_DAYS
        chronic = _load_between(runs, history_start, end) / weeks
    return LoadStatus(as_of=end, acute=acute, chronic=chronic)


def weekly(report: Report) -> list[tuple[date, float]]:
    """Load per Monday-to-Sunday week, including empty weeks, up to `as_of`."""
    runs = _all_runs(report)
    if not runs or report.as_of is None:
        return []
    first = runs[0].run.start.date()
    monday = first - timedelta(days=first.weekday())
    weeks: list[tuple[date, float]] = []
    while monday <= report.as_of:
        weeks.append((monday, _load_between(runs, monday, monday + timedelta(days=6))))
        monday += timedelta(days=7)
    return weeks
