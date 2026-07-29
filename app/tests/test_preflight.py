import os

import main


def test_db_dir_writable_ok_for_temp(tmp_path):
    url = f"sqlite:///{tmp_path}/history.db"
    assert main.db_dir_writable(url) is None


def test_db_dir_writable_flags_missing_dir():
    url = "sqlite:////nonexistent-xyz/history.db"
    msg = main.db_dir_writable(url)
    assert msg and "does not exist" in msg


def test_db_dir_writable_ignores_memory():
    assert main.db_dir_writable("sqlite://") is None


def test_hardlink_fs_warning_none_when_same_dir(tmp_path):
    d = str(tmp_path)
    assert main.hardlink_fs_warning(d, d) is None


def test_hardlink_fs_warning_none_when_dirs_absent():
    assert main.hardlink_fs_warning("/no/such/a", "/no/such/b") is None
