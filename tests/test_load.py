from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from easy_or_not import load
from easy_or_not.analysis import analyse, summarise

from .conftest import make_run

MONDAY = datetime(2026, 9, 7, 7, tzinfo=UTC)


def _runs_every_other_day(weeks: int, hr: int = 130, minutes: int = 30):
    return [
        make_run([(minutes * 60, hr)], start=MONDAY + timedelta(days=d))
        for d in range(0, weeks * 7, 2)
    ]


def test_run_load_weights_minutes_by_zone(zones) -> None:
    # zones fixture: z2 120, z3 140, z4 160, z5 175
    s = summarise(make_run([(600, 110), (600, 150), (601, 180)]), zones)
    assert s.load == pytest.approx(10 * 1 + 10 * 3 + 10 * 5, abs=0.1)


def test_harder_run_has_more_load(zones) -> None:
    easy = summarise(make_run([(1800, 130)]), zones)
    hard = summarise(make_run([(1800, 170)]), zones)
    assert hard.load == pytest.approx(2 * easy.load, rel=0.01)


def test_steady_training_is_in_line(zones) -> None:
    report = analyse(_runs_every_other_day(5), zones)
    s = load.status(report)
    assert s is not None and s.ratio is not None
    assert 0.8 <= s.ratio <= 1.3
    assert s.verdict == "in line with your recent weeks"


def test_sudden_jump_is_flagged(zones) -> None:
    runs = _runs_every_other_day(4)
    jump_start = MONDAY + timedelta(days=28)
    runs += [make_run([(3600, 170)], start=jump_start + timedelta(days=d)) for d in range(6)]
    s = load.status(analyse(runs, zones))
    assert s is not None and s.ratio is not None and s.ratio > 1.5
    assert "big jump" in s.verdict


def test_week_off_is_lighter(zones) -> None:
    runs = _runs_every_other_day(4)
    s = load.status(analyse(runs, zones, as_of=(MONDAY + timedelta(days=34)).date()))
    assert s is not None and s.acute == 0
    assert s.verdict == "lighter than your recent weeks"


def test_needs_four_weeks_of_history(zones) -> None:
    s = load.status(analyse(_runs_every_other_day(2), zones))
    assert s is not None
    assert s.chronic is None and s.ratio is None and s.verdict is None


def test_short_runs_count_towards_load_but_walks_do_not(zones) -> None:
    run = make_run([(1800, 130)], start=MONDAY, cadence=166)
    short = make_run([(300, 150)], start=MONDAY + timedelta(hours=5), cadence=166)
    walk = make_run([(1800, 110)], start=MONDAY + timedelta(hours=9), speed=1.5, cadence=115)
    report = analyse([run, short, walk], zones)
    s = load.status(report)
    assert s is not None
    assert s.acute == pytest.approx(30 * 2 + 5 * 3, abs=0.2)


def test_weekly_includes_empty_weeks(zones) -> None:
    runs = [
        make_run([(1800, 130)], start=MONDAY),
        make_run([(1800, 130)], start=MONDAY + timedelta(days=15)),
    ]
    weeks = load.weekly(analyse(runs, zones))
    assert [m for m, _ in weeks] == [date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 21)]
    assert weeks[1][1] == 0


def test_no_runs_no_load(zones) -> None:
    report = analyse([], zones)
    assert load.status(report) is None
    assert load.weekly(report) == []
