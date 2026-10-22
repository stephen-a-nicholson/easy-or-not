from __future__ import annotations

import stat

from easy_or_not import setup as setup_mod

KEY = "not-a-real-key-123"


def _answer(monkeypatch, value: str) -> None:
    monkeypatch.setattr(setup_mod.getpass, "getpass", lambda prompt: value)


def test_setup_saves_key_privately(monkeypatch, tmp_path, capsys) -> None:
    _answer(monkeypatch, f"  {KEY}\n")
    monkeypatch.setattr(setup_mod, "check_key", lambda key: None)
    path = tmp_path / "garmin" / "key"
    assert setup_mod.setup(path) == 0
    assert path.read_text().strip() == KEY
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    out = capsys.readouterr().out
    assert KEY not in out
    assert "Key works" in out


def test_setup_tightens_existing_file(monkeypatch, tmp_path) -> None:
    path = tmp_path / "key"
    path.write_text("old")
    path.chmod(0o644)
    _answer(monkeypatch, KEY)
    monkeypatch.setattr(setup_mod, "check_key", lambda key: None)
    setup_mod.setup(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_setup_rejected_key(monkeypatch, tmp_path, capsys) -> None:
    _answer(monkeypatch, KEY)
    monkeypatch.setattr(setup_mod, "check_key", lambda key: "401 Unauthorized")
    assert setup_mod.setup(tmp_path / "key") == 1
    out = capsys.readouterr().out
    assert "did not accept" in out
    assert KEY not in out


def test_setup_empty_key_saves_nothing(monkeypatch, tmp_path) -> None:
    _answer(monkeypatch, "   ")
    path = tmp_path / "key"
    assert setup_mod.setup(path) == 1
    assert not path.exists()
