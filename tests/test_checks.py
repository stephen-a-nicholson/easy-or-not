from __future__ import annotations

from datetime import UTC, datetime

from easy_or_not.analysis import analyse
from easy_or_not.checks import trim_tail
from easy_or_not.models import Run, Sample

from .conftest import make_run


def _run_then(tail: list[Sample]) -> Run:
    run = make_run([(1200, 130)], cadence=170)
    return Run("t", run.start, run.samples + tail)


def test_trim_tail_drops_walk_home() -> None:
    walk = [Sample(1200.0 + i, 110, 1.4, 115) for i in range(900)]
    trimmed = trim_tail(_run_then(walk))
    assert trimmed.duration_s < 1200


def test_trim_tail_keeps_run_that_ends_running() -> None:
    run = make_run([(1200, 130)], cadence=170)
    assert trim_tail(run) is run


def test_trim_tail_uses_speed_without_cadence() -> None:
    standing = [Sample(1200.0 + i, 80, 0.0) for i in range(600)]
    run = make_run([(1200, 130)])
    trimmed = trim_tail(Run("s", run.start, run.samples + standing))
    assert trimmed.duration_s < 1200


def test_short_activity_is_skipped(zones) -> None:
    report = analyse([make_run([(300, 130)])], zones)
    assert report.runs == []
    assert report.skipped[0][1] == "under 10 minutes of heart-rate data"


def test_ten_minute_activity_is_kept(zones) -> None:
    report = analyse([make_run([(700, 130)])], zones)
    assert len(report.runs) == 1
    assert report.skipped == []


def test_walk_logged_as_run_is_skipped(zones) -> None:
    report = analyse([make_run([(1800, 110)], speed=1.6, cadence=118)], zones)
    assert report.runs == []
    assert report.skipped[0][1] == "walking cadence"


def test_running_cadence_is_kept(zones) -> None:
    report = analyse([make_run([(1800, 130)], cadence=166)], zones)
    assert len(report.runs) == 1


def test_long_spell_in_zone_5_warns_about_zones(zones) -> None:
    run = make_run([(2400, 180)], start=datetime(2026, 10, 4, 7, tzinfo=UTC))
    report = analyse([run], zones)
    assert len(report.warnings) == 1
    assert "180 bpm for 40 min" in report.warnings[0]
    assert "Sun 04 Oct" in report.warnings[0]


def test_normal_hard_session_does_not_warn(zones) -> None:
    short_z5 = make_run([(900, 180)])
    long_z4 = make_run([(2400, 165)])
    assert analyse([short_z5, long_z4], zones).warnings == []
