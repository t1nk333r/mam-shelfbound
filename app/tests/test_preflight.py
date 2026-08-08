import main
from types import SimpleNamespace


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
    assert main.hardlink_fs_warning(d, d, "hardlink") is None


def test_hardlink_fs_warning_none_when_dirs_absent():
    assert main.hardlink_fs_warning("/no/such/a", "/no/such/b", "hardlink") is None


def _different_devices(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()
    real_stat = main.os.stat
    real_isdir = main.os.path.isdir

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path) == str(downloads):
            return SimpleNamespace(st_dev=result.st_dev, st_ino=result.st_ino)
        if str(path) == str(library):
            return SimpleNamespace(st_dev=result.st_dev + 1, st_ino=result.st_ino)
        return result

    monkeypatch.setattr(main.os, "stat", fake_stat)
    monkeypatch.setattr(main.os.path, "isdir", lambda path: True if str(path) in (str(downloads), str(library)) else real_isdir(path))
    return str(downloads), str(library)


def test_hardlink_fs_warning_strict_different_devices(tmp_path, monkeypatch):
    downloads, library = _different_devices(tmp_path, monkeypatch)
    warning = main.hardlink_fs_warning(downloads, library, "hardlink")
    assert warning and "will fail" in warning and "EXDEV" in warning


def test_hardlink_fs_warning_auto_different_devices_mentions_copy_and_disk(tmp_path, monkeypatch):
    downloads, library = _different_devices(tmp_path, monkeypatch)
    warning = main.hardlink_fs_warning(downloads, library, "auto")
    assert warning and "copied" in warning and "extra disk" in warning


def test_hardlink_fs_warning_copy_different_devices_is_none(tmp_path, monkeypatch):
    downloads, library = _different_devices(tmp_path, monkeypatch)
    assert main.hardlink_fs_warning(downloads, library, "copy") is None
