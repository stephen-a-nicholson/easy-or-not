from __future__ import annotations

import json

from easy_or_not.cli import main
from easy_or_not.zones import from_max_hr

from .conftest import fit_bytes, zipped


def test_files_end_to_end(tmp_path, capsys) -> None:
    (tmp_path / "easy.fit").write_bytes(fit_bytes(minutes=30, hr=135))
    (tmp_path / "drift.zip").write_bytes(zipped(fit_bytes(minutes=30, hr=160)))
    assert main(["--max-hr", "190", "files", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2 runs" in out
    assert "middle" in out


def test_json_output(tmp_path, capsys) -> None:
    (tmp_path / "a.fit").write_bytes(fit_bytes())
    assert main(["--max-hr", "190", "--json", "files", str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["totals"]) == {"easy", "middle", "hard"}
    assert len(data["runs"]) == 1
    # 130 bpm is zone 1 on max HR 190; every zone is listed, empty ones as 0.
    zone_seconds = data["runs"][0]["zone_seconds"]
    assert list(zone_seconds) == ["1", "2", "3", "4", "5"]
    assert zone_seconds["1"] > 0
    assert sum(zone_seconds.values()) == sum(data["runs"][0]["seconds"].values())


def test_files_without_zones_is_an_error(tmp_path, capsys) -> None:
    (tmp_path / "a.fit").write_bytes(fit_bytes())
    assert main(["files", str(tmp_path)]) == 2
    assert "--max-hr" in capsys.readouterr().err


def test_no_runs(tmp_path, capsys) -> None:
    assert main(["--max-hr", "190", "files", str(tmp_path)]) == 1


def test_bare_command_reads_garmin(monkeypatch, tmp_path, capsys) -> None:
    from easy_or_not import garmin

    from .conftest import make_run

    calls = []

    def fake_fetch(days, cache_dir, quiet=False):
        calls.append(days)
        return [make_run([(1800, 130)], cadence=166)], from_max_hr(190)

    monkeypatch.setattr(garmin, "fetch", fake_fetch)
    monkeypatch.setattr(garmin, "fetch_wellness", lambda days, quiet=False: {})
    assert main([]) == 0
    assert calls == [56]  # the 8-week default, which covers the readiness window
    assert "1 run," in capsys.readouterr().out


def test_missing_key_points_to_setup(monkeypatch, capsys) -> None:
    from easy_or_not import garmin

    def no_key(days, cache_dir, quiet=False):
        raise garmin.GarminPersonalApiError("No personal API key was provided.")

    monkeypatch.setattr(garmin, "fetch", no_key)
    assert main([]) == 2
    assert "easy-or-not setup" in capsys.readouterr().err


def test_skipped_runs_and_warnings_are_reported(tmp_path, capsys) -> None:
    (tmp_path / "long.fit").write_bytes(fit_bytes(minutes=40, hr=185))
    (tmp_path / "blip.fit").write_bytes(fit_bytes(minutes=2, hr=120))
    assert main(["--max-hr", "190", "files", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1 more left out" in out
    assert "under 10 minutes" in out
    assert "zones may be set too low" in out


def test_load_section_in_text_and_json(tmp_path, capsys) -> None:
    (tmp_path / "a.fit").write_bytes(fit_bytes(minutes=30, hr=135))
    assert main(["--max-hr", "190", "files", str(tmp_path)]) == 0
    assert "Training load" in capsys.readouterr().out
    assert main(["--max-hr", "190", "--json", "files", str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["load"]["method"] == "Edwards TRIMP"
    assert data["load"]["last_7_days"] > 0
    assert data["runs"][0]["load"] > 0


def test_garmin_load_is_measured_to_today(monkeypatch, capsys) -> None:
    from datetime import date

    from easy_or_not import garmin

    from .conftest import make_run

    def fake_fetch(days, cache_dir, quiet=False):
        return [make_run([(1800, 130)])], from_max_hr(190)

    monkeypatch.setattr(garmin, "fetch", fake_fetch)
    monkeypatch.setattr(garmin, "fetch_wellness", lambda days, quiet=False: {})
    assert main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["load"]["as_of"] == date.today().isoformat()


def _fake_garmin(monkeypatch, wellness):
    from easy_or_not import garmin

    from .conftest import make_run

    def fake_fetch(days, cache_dir, quiet=False):
        return [make_run([(1800, 130)])], from_max_hr(190)

    monkeypatch.setattr(garmin, "fetch", fake_fetch)
    monkeypatch.setattr(garmin, "fetch_wellness", lambda days, quiet=False: wellness)


def _wellness(sleep_score: int):
    from datetime import date, timedelta

    from easy_or_not.wellness import Day

    today = date.today()
    days = {today - timedelta(i): Day(day=today - timedelta(i), resting_hr=45) for i in range(28)}
    days[today] = Day(
        day=today, hrv=90, hrv_low=82, hrv_high=97, sleep_s=25000, sleep_score=sleep_score
    )
    days[today].resting_hr = 45
    return days


def test_readiness_command(monkeypatch, capsys) -> None:
    _fake_garmin(monkeypatch, _wellness(sleep_score=44))
    assert main(["readiness"]) == 0
    out = capsys.readouterr().out
    assert "go easy today" in out
    assert "score 44 (poor)" in out
    assert "Last 7 nights" in out
    assert "not Garmin's Training Readiness" in out


def test_readiness_command_json(monkeypatch, capsys) -> None:
    _fake_garmin(monkeypatch, _wellness(sleep_score=85))
    assert main(["--json", "readiness"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["signals"][0]["name"] == "HRV"
    assert len(data["days"]) == 28


def test_main_report_includes_readiness(monkeypatch, capsys) -> None:
    _fake_garmin(monkeypatch, _wellness(sleep_score=85))
    assert main([]) == 0
    assert "Readiness for" in capsys.readouterr().out


def _fake_garmin_as_of(monkeypatch):
    """Runs either side of 31 Oct 2026, wellness for that day, and the fetch windows asked for."""
    from datetime import UTC, date, datetime

    from easy_or_not import garmin
    from easy_or_not.wellness import Day

    from .conftest import make_run

    asked = {}
    runs = [
        make_run([(1800, 130)], start=datetime(2026, 10, 29, 7, tzinfo=UTC), run_id="before"),
        make_run([(1800, 130)], start=datetime(2026, 11, 1, 7, tzinfo=UTC), run_id="after"),
    ]
    wellness = {
        date(2026, 10, 31): Day(day=date(2026, 10, 31), hrv=90, hrv_low=82, hrv_high=97),
        date(2026, 11, 1): Day(day=date(2026, 11, 1), hrv=50, hrv_low=82, hrv_high=97),
    }

    def fake_fetch(days, cache_dir, quiet=False):
        asked["runs"] = days
        return runs, from_max_hr(190)

    def fake_wellness(days, quiet=False):
        asked["wellness"] = days
        return wellness

    monkeypatch.setattr(garmin, "fetch", fake_fetch)
    monkeypatch.setattr(garmin, "fetch_wellness", fake_wellness)
    return asked


def test_as_of_reports_an_earlier_day(monkeypatch, capsys) -> None:
    from datetime import date

    asked = _fake_garmin_as_of(monkeypatch)
    assert main(["--json", "--as-of", "2026-10-31"]) == 0
    data = json.loads(capsys.readouterr().out)
    # The run after that day is left out, and readiness is for that day's night.
    assert [r["id"] for r in data["runs"]] == ["before"]
    assert data["readiness"]["day"] == "2026-10-31"
    assert data["readiness"]["signals"][0]["value"] == "90 ms"
    assert data["load"]["as_of"] == "2026-10-31"
    # Garmin's windows end today, so the fetch reached back far enough to cover the day.
    back = (date.today() - date(2026, 10, 31)).days
    assert asked == {"runs": 56 + back, "wellness": 35 + back}


def test_as_of_readiness_command(monkeypatch, capsys) -> None:
    _fake_garmin_as_of(monkeypatch)
    assert main(["--as-of", "2026-10-31", "readiness"]) == 0
    out = capsys.readouterr().out
    assert "Readiness for Sat 31 Oct" in out
    assert "Sun 01 Nov" not in out


def test_as_of_with_files_sets_the_load_date(tmp_path, capsys) -> None:
    (tmp_path / "a.fit").write_bytes(fit_bytes())  # 20 Oct 2026
    assert main(["--max-hr", "190", "--as-of", "2026-10-31", "files", str(tmp_path)]) == 0
    assert "Last 7 days to Sat 31 Oct" in capsys.readouterr().out


def test_as_of_rejects_the_future(capsys) -> None:
    import pytest

    with pytest.raises(SystemExit):
        main(["--as-of", "2999-01-01"])
    assert "in the future" in capsys.readouterr().err


def test_as_of_rejects_a_bad_date() -> None:
    import pytest

    with pytest.raises(SystemExit):
        main(["--as-of", "31/10/2026"])


def test_files_report_has_no_readiness(tmp_path, capsys) -> None:
    (tmp_path / "a.fit").write_bytes(fit_bytes(minutes=30, hr=135))
    assert main(["--max-hr", "190", "files", str(tmp_path)]) == 0
    assert "Readiness" not in capsys.readouterr().out
