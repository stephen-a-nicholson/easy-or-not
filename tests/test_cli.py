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
    assert main([]) == 0
    assert calls == [56]
    assert "1 runs" in capsys.readouterr().out


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
