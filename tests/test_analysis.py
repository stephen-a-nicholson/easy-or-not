from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from easy_or_not.analysis import analyse, summarise
from easy_or_not.models import Run, Sample
from easy_or_not.zones import from_garmin, from_max_hr

from .conftest import make_run


def test_time_split_into_bands(zones) -> None:
    run = make_run([(600, 130), (300, 150), (100, 170)])
    s = summarise(run, zones)
    assert s.seconds["easy"] == pytest.approx(600, abs=1)
    assert s.seconds["middle"] == pytest.approx(300, abs=1)
    assert s.seconds["hard"] == pytest.approx(100, abs=1)


def test_pauses_are_not_counted(zones) -> None:
    samples = [
        Sample(0, 130, 3.0),
        Sample(5, 130, 3.0),
        Sample(65, 130, 3.0),  # 60 s gap: watch paused
        Sample(70, 130, 3.0),
    ]
    s = summarise(Run("p", datetime(2026, 1, 1, tzinfo=UTC), samples), zones)
    assert s.total_s == pytest.approx(10)


def test_missing_heart_rate_ignored(zones) -> None:
    samples = [Sample(t, None, 3.0) for t in range(100)]
    s = summarise(Run("n", datetime(2026, 1, 1, tzinfo=UTC), samples), zones)
    assert s.total_s == 0


def test_session_detection(zones) -> None:
    easy = summarise(make_run([(1800, 130), (60, 165)]), zones)
    session = summarise(make_run([(600, 130), (1200, 168), (300, 130)]), zones)
    assert not easy.is_session
    assert session.is_session


def test_easy_run_drift_excludes_sessions(zones) -> None:
    runs = [
        make_run([(1500, 130), (500, 150)], run_id="drifty"),
        make_run([(2000, 130)], run_id="clean"),
        make_run([(600, 130), (1200, 168)], run_id="session"),
    ]
    report = analyse(runs, zones)
    assert len(report.easy_runs) == 2
    assert report.easy_run_middle_fraction() == pytest.approx(500 / 4000, abs=0.01)


def test_efficiency_ignores_warmup_and_treadmill(zones) -> None:
    base = datetime(2026, 9, 1, tzinfo=UTC)
    runs = [
        make_run([(2400, 130)], speed=3.0 + i * 0.05, start=base + timedelta(days=i * 3))
        for i in range(9)
    ]
    runs.append(make_run([(2400, 130)], speed=9.0, start=base + timedelta(days=40), treadmill=True))
    trend = analyse(runs, zones).efficiency_trend()
    assert trend is not None
    first, last = trend
    assert last > first
    assert last < 9.0 * 60 / 130  # treadmill run did not leak in


def test_efficiency_needs_enough_runs(zones) -> None:
    report = analyse([make_run([(2400, 130)])], zones)
    assert report.efficiency_trend() is None


def test_weekly_buckets_by_monday(zones) -> None:
    mon = datetime(2026, 10, 5, 7, tzinfo=UTC)
    runs = [make_run([(600, 130)], start=mon), make_run([(600, 130)], start=mon + timedelta(6))]
    weeks = analyse(runs, zones).weekly()
    assert len(weeks) == 1
    assert weeks[0][0].isoformat() == "2026-10-05"


def test_zones_from_max_hr() -> None:
    z = from_max_hr(190)
    assert (z.z2, z.z3, z.z4, z.z5) == (133, 152, 171, 180)
    assert z.band(150) == "easy" and z.band(160) == "middle" and z.band(175) == "hard"


def test_zones_from_garmin_prefers_running() -> None:
    payload = [
        {
            "sport": "DEFAULT",
            "zone2Floor": 110,
            "zone3Floor": 130,
            "zone4Floor": 150,
            "zone5Floor": 170,
        },
        {
            "sport": "RUNNING",
            "zone2Floor": 120,
            "zone3Floor": 140,
            "zone4Floor": 160,
            "zone5Floor": 175,
        },
    ]
    z = from_garmin(payload)
    assert z is not None and z.z3 == 140 and "running" in z.source


@pytest.mark.parametrize("payload", [None, {}, [], [{"foo": 1}], {"zone2Floor": "x"}])
def test_zones_from_garmin_unexpected_shape_returns_none(payload) -> None:
    assert from_garmin(payload) is None


def test_easy_up_to_three_moves_the_boundary() -> None:
    from dataclasses import replace

    z = replace(from_max_hr(190), easy_up_to=3)
    assert z.easy_ceiling == z.z4 and z.hard_floor == z.z5
    assert z.band(160) == "easy" and z.band(175) == "middle" and z.band(185) == "hard"
