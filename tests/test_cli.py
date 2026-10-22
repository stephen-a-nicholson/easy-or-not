from __future__ import annotations

import json

from easy_or_not.cli import main

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
