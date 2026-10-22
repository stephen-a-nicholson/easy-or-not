"""A readiness view built from data the watch already records.

Garmin's Training Readiness blends the same kinds of signal with weightings
that are not public, so this does not try to reproduce its score. It rates each
signal against your own normal, says which ones are off, and gives a plain
verdict. Every rule is here to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from easy_or_not.load import LoadStatus
from easy_or_not.wellness import Day

OK, WATCH, LOW = "ok", "watch", "low"

# Resting HR is compared with the median of the previous four weeks, and
# needs at least a week of values to mean anything.
RHR_BASELINE_DAYS = 28
RHR_MIN_DAYS = 7
RHR_WATCH_BPM = 3
RHR_LOW_BPM = 5

# Garmin rates sleep scores under 60 as poor.
POOR_SLEEP_SCORE = 60
SHORT_SLEEP_S = 6 * 3600


@dataclass(frozen=True)
class Signal:
    name: str
    value: str
    detail: str
    rating: str | None  # OK, WATCH, LOW, or None when there is no data


@dataclass(frozen=True)
class Readiness:
    day: date
    signals: list[Signal]

    @property
    def verdict(self) -> str:
        rated = [s.rating for s in self.signals if s.rating]
        if len(rated) < 2:
            return "not enough data from last night to say"
        score = 2 * rated.count(LOW) + rated.count(WATCH)
        if score == 0:
            return "good to train"
        if score <= 2:
            return "go easy today"
        return "rest or keep it very easy today"


def _hrv(today: Day | None) -> Signal:
    if today is None or today.hrv is None:
        return Signal("HRV", "-", "no reading last night", None)
    value = f"{today.hrv} ms"
    if today.hrv_low is None or today.hrv_high is None:
        return Signal("HRV", value, "no baseline yet", None)
    span = f"({today.hrv_low}-{today.hrv_high})"
    if today.hrv < today.hrv_low:
        return Signal("HRV", value, f"below your normal range {span}", LOW)
    if today.hrv > today.hrv_high:
        return Signal("HRV", value, f"above your normal range {span}", WATCH)
    return Signal("HRV", value, f"in your normal range {span}", OK)


def _resting_hr(today: Day | None, history: list[Day]) -> Signal:
    if today is None or today.resting_hr is None:
        return Signal("Resting HR", "-", "no reading today", None)
    value = f"{today.resting_hr} bpm"
    earlier = [d.resting_hr for d in history if d.resting_hr is not None]
    if len(earlier) < RHR_MIN_DAYS:
        return Signal("Resting HR", value, "needs a week of history", None)
    usual = median(earlier)
    diff = today.resting_hr - usual
    if diff >= RHR_WATCH_BPM:
        rating = LOW if diff >= RHR_LOW_BPM else WATCH
        return Signal("Resting HR", value, f"{diff:.0f} above your usual {usual:.0f}", rating)
    return Signal("Resting HR", value, f"your usual is {usual:.0f}", OK)


def _sleep(today: Day | None) -> Signal:
    if today is None or (today.sleep_s is None and today.sleep_score is None):
        return Signal("Sleep", "-", "no sleep recorded last night", None)
    value = f"{today.sleep_s / 3600:.1f} h" if today.sleep_s else "-"
    if today.sleep_score is not None:
        poor = today.sleep_score < POOR_SLEEP_SCORE
        quality = "poor" if poor else "fair" if today.sleep_score < 80 else "good"
        return Signal("Sleep", value, f"score {today.sleep_score} ({quality})", LOW if poor else OK)
    short = today.sleep_s is not None and today.sleep_s < SHORT_SLEEP_S
    return Signal("Sleep", value, "short night" if short else "no score", LOW if short else OK)


def _load(status: LoadStatus | None) -> Signal:
    if status is None or status.ratio is None:
        return Signal("Load", "-", "needs 4 weeks of runs", None)
    ratio = status.ratio
    rating = LOW if ratio > 1.5 else WATCH if ratio > 1.3 else OK
    return Signal("Load", f"ratio {ratio:.2f}", status.verdict or "", rating)


def assess(days: dict[date, Day], as_of: date, load_status: LoadStatus | None) -> Readiness:
    today = days.get(as_of)
    start = as_of - timedelta(days=RHR_BASELINE_DAYS)
    history = [d for k, d in days.items() if start <= k < as_of]
    return Readiness(
        day=as_of,
        signals=[_hrv(today), _resting_hr(today, history), _sleep(today), _load(load_status)],
    )
