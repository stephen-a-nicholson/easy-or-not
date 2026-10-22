from __future__ import annotations

import pytest
from fit_tool.profile.profile_type import Sport, SubSport

from easy_or_not.fit import NotARun, load_bytes, load_path, parse_fit

from .conftest import fit_bytes, zipped


def test_parses_outdoor_run() -> None:
    run = parse_fit(fit_bytes(minutes=10, hr=130, speed=3.33), run_id="a")
    assert not run.treadmill
    assert len(run.samples) == 600
    assert run.samples[0].heart_rate == 130
    assert run.samples[0].speed_mps == pytest.approx(3.33, abs=0.01)
    assert run.duration_s == pytest.approx(599)


def test_treadmill_flagged() -> None:
    run = parse_fit(fit_bytes(sub_sport=SubSport.TREADMILL), run_id="t")
    assert run.treadmill


def test_rejects_other_sports() -> None:
    with pytest.raises(NotARun):
        parse_fit(fit_bytes(sport=Sport.CYCLING), run_id="bike")


def test_reads_garmin_zip() -> None:
    runs = load_bytes(zipped(fit_bytes()), run_id="z")
    assert len(runs) == 1


def test_directory_skips_non_runs(tmp_path) -> None:
    (tmp_path / "run.fit").write_bytes(fit_bytes())
    (tmp_path / "ride.fit").write_bytes(fit_bytes(sport=Sport.CYCLING))
    (tmp_path / "notes.txt").write_text("ignore me")
    assert len(load_path(tmp_path)) == 1


def test_cadence_is_read_as_steps_per_minute() -> None:
    run = parse_fit(fit_bytes(minutes=1, cadence=85), run_id="c")
    assert run.samples[0].cadence_spm == 170


def test_cadence_missing_is_none() -> None:
    run = parse_fit(fit_bytes(minutes=1), run_id="n")
    assert run.samples[0].cadence_spm is None
