"""Readiness rules and wellness parsing, on made-up data shaped like the API's."""

from __future__ import annotations

from datetime import date, timedelta

from easy_or_not.load import LoadStatus
from easy_or_not.readiness import LOW, OK, WATCH, assess
from easy_or_not.wellness import Day, parse

TODAY = date(2026, 10, 22)


def _history(resting_hr: int = 45, days: int = 28) -> dict[date, Day]:
    return {
        TODAY - timedelta(days=i): Day(day=TODAY - timedelta(days=i), resting_hr=resting_hr)
        for i in range(1, days + 1)
    }


def _today(**values) -> dict[date, Day]:
    base = dict(hrv=90, hrv_low=82, hrv_high=97, sleep_s=7 * 3600, sleep_score=75, resting_hr=45)
    return {**_history(), TODAY: Day(day=TODAY, **{**base, **values})}


STEADY = LoadStatus(as_of=TODAY, acute=300, chronic=300)


def _rating(days, name, load=STEADY):
    readiness = assess(days, TODAY, load)
    return next(s for s in readiness.signals if s.name == name).rating


def test_all_normal_is_good_to_train() -> None:
    readiness = assess(_today(), TODAY, STEADY)
    assert [s.rating for s in readiness.signals] == [OK, OK, OK, OK]
    assert readiness.verdict == "good to train"


def test_hrv_below_range_is_low() -> None:
    assert _rating(_today(hrv=75), "HRV") == LOW


def test_hrv_above_range_is_watch() -> None:
    assert _rating(_today(hrv=105), "HRV") == WATCH


def test_resting_hr_well_above_usual_is_low() -> None:
    assert _rating(_today(resting_hr=51), "Resting HR") == LOW


def test_resting_hr_slightly_above_usual_is_watch() -> None:
    assert _rating(_today(resting_hr=48), "Resting HR") == WATCH


def test_resting_hr_needs_a_week_of_history() -> None:
    days = {**_history(days=3), TODAY: Day(day=TODAY, resting_hr=60)}
    assert _rating(days, "Resting HR") is None


def test_poor_sleep_score_is_low() -> None:
    assert _rating(_today(sleep_score=44), "Sleep") == LOW


def test_short_night_without_score_is_low() -> None:
    assert _rating(_today(sleep_score=None, sleep_s=5 * 3600), "Sleep") == LOW


def test_big_load_jump_is_low() -> None:
    jump = LoadStatus(as_of=TODAY, acute=500, chronic=300)
    assert _rating(_today(), "Load", jump) == LOW


def test_poor_sleep_alone_means_go_easy() -> None:
    assert assess(_today(sleep_score=44), TODAY, STEADY).verdict == "go easy today"


def test_several_bad_signals_mean_rest() -> None:
    days = _today(hrv=70, resting_hr=52, sleep_score=40)
    assert assess(days, TODAY, STEADY).verdict == "rest or keep it very easy today"


def test_watch_not_worn_overnight_is_not_treated_as_bad() -> None:
    days = {**_history(), TODAY: Day(day=TODAY, resting_hr=45)}
    readiness = assess(days, TODAY, None)
    assert [s.rating for s in readiness.signals] == [None, OK, None, None]
    assert readiness.verdict == "not enough data from last night to say"


HRV = {
    "hrvSummaries": [
        {
            "calendarDate": "2026-10-22",
            "weeklyAvg": 92,
            "lastNightAvg": 90,
            "baseline": {"lowUpper": 79, "balancedLow": 82, "balancedUpper": 97},
            "status": "BALANCED",
        },
        {"calendarDate": "2026-10-21", "lastNightAvg": None, "baseline": None},
    ]
}
SLEEP = [
    {
        "calendarDate": "2026-10-22",
        "sleepTimeSeconds": 22320,
        "sleepScores": {"overall": {"value": 44, "qualifierKey": "POOR"}},
    },
    {"calendarDate": None, "sleepTimeSeconds": None},
]
SUMMARIES = {
    "data": [
        {"calendarDate": "2026-10-22", "heartRate": {"restingValue": 43}},
        {"calendarDate": "2026-10-21", "heartRate": {}},
    ]
}


def test_parse_merges_the_three_sources() -> None:
    days = parse(HRV, SLEEP, SUMMARIES)
    d = days[TODAY]
    assert (d.hrv, d.hrv_low, d.hrv_high, d.hrv_status) == (90, 82, 97, "BALANCED")
    assert (d.sleep_s, d.sleep_score, d.resting_hr) == (22320, 44, 43)


def test_parse_turns_missing_nights_into_none() -> None:
    d = parse(HRV, SLEEP, SUMMARIES)[date(2026, 10, 21)]
    assert d.hrv is None and d.hrv_low is None and d.resting_hr is None and d.sleep_s is None


def test_parse_survives_unexpected_shapes() -> None:
    assert parse(None, {"error": "x"}, [1, "a"]) == {}
