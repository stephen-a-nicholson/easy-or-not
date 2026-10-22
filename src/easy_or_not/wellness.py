"""Daily wellness data (overnight HRV, sleep, resting HR) from the Personal API.

Parsing is deliberately forgiving: a night the watch was not worn comes back
with nulls or is missing entirely, and either way it becomes None here rather
than an error or a zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class Day:
    """One calendar day. Overnight values belong to the morning you woke up."""

    day: date
    hrv: int | None = None  # last night's average, ms
    hrv_low: int | None = None  # Garmin's balanced range for you
    hrv_high: int | None = None
    hrv_status: str | None = None
    sleep_s: int | None = None
    sleep_score: int | None = None
    resting_hr: int | None = None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _records(payload: Any, key: str | None = None) -> list[dict[str, Any]]:
    if key and isinstance(payload, dict):
        payload = payload.get(key)
    return [r for r in payload if isinstance(r, dict)] if isinstance(payload, list) else []


def parse(hrv: Any, sleep: Any, summaries: Any) -> dict[date, Day]:
    """Merge the HRV summaries, sleep summaries and daily summaries responses."""
    days: dict[date, Day] = {}

    def day(value: Any) -> Day | None:
        d = _date(value)
        if d is None:
            return None
        return days.setdefault(d, Day(day=d))

    for r in _records(hrv, "hrvSummaries"):
        if (d := day(r.get("calendarDate"))) is None:
            continue
        baseline = r.get("baseline") or {}
        d.hrv = _int(r.get("lastNightAvg"))
        d.hrv_low = _int(baseline.get("balancedLow"))
        d.hrv_high = _int(baseline.get("balancedUpper"))
        d.hrv_status = r.get("status") if isinstance(r.get("status"), str) else None

    for r in _records(sleep):
        if (d := day(r.get("calendarDate"))) is None:
            continue
        d.sleep_s = _int(r.get("sleepTimeSeconds")) or None
        overall = (r.get("sleepScores") or {}).get("overall") or {}
        d.sleep_score = _int(overall.get("value"))

    for r in _records(summaries, "data"):
        if (d := day(r.get("calendarDate"))) is None:
            continue
        d.resting_hr = _int((r.get("heartRate") or {}).get("restingValue"))

    return days
