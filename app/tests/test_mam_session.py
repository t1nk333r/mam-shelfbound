import pytest

import main


def test_current_mam_cookie_uses_static_when_no_file():
    assert main.settings.MAM_ID_FILE == ""
    assert main.current_mam_cookie() == main.settings.MAM_COOKIE


def test_current_mam_cookie_reads_and_wraps_file(monkeypatch, tmp_path):
    f = tmp_path / "mamid"
    f.write_text("bareToken123\n")
    monkeypatch.setattr(main.settings, "MAM_ID_FILE", str(f))
    assert main.current_mam_cookie() == "mam_id=bareToken123"


def test_current_mam_cookie_falls_back_when_file_missing(monkeypatch):
    monkeypatch.setattr(main.settings, "MAM_ID_FILE", "/no/such/mamid-file")
    assert main.current_mam_cookie() == main.settings.MAM_COOKIE


def test_settings_accepts_file_without_cookie(monkeypatch):
    monkeypatch.setenv("MAM_COOKIE", "")
    monkeypatch.setenv("MAM_ID_FILE", "/some/path")
    s = main.Settings()          # must not raise
    assert s.MAM_ID_FILE == "/some/path"


def test_settings_requires_cookie_or_file(monkeypatch):
    monkeypatch.setenv("MAM_COOKIE", "")
    monkeypatch.delenv("MAM_ID_FILE", raising=False)
    with pytest.raises(RuntimeError):
        main.Settings()
