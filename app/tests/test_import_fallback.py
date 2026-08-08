import asyncio
import errno
from pathlib import Path

import pytest
from fastapi import HTTPException

import main


def test_settings_defaults_to_hardlink_and_accepts_supported_modes(monkeypatch):
    monkeypatch.delenv("AUDIOBOOK_IMPORT_MODE", raising=False)
    assert main.Settings().AUDIOBOOK_IMPORT_MODE == "hardlink"
    for mode in main.AUDIOBOOK_IMPORT_MODES:
        monkeypatch.setenv("AUDIOBOOK_IMPORT_MODE", mode)
        assert main.Settings().AUDIOBOOK_IMPORT_MODE == mode


def test_settings_rejects_unknown_audiobook_import_mode(monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_IMPORT_MODE", "invalid")
    with pytest.raises(RuntimeError, match="AUDIOBOOK_IMPORT_MODE.*hardlink.*auto.*copy"):
        main.Settings()


def test_hardlink_mode_creates_a_real_hardlink(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "AUDIOBOOK_IMPORT_MODE", "hardlink")
    src = tmp_path / "source.m4b"
    dst = tmp_path / "library" / "book.m4b"
    src.write_bytes(b"audio")
    main.import_audiobook_one(src, dst)
    assert dst.read_bytes() == src.read_bytes()
    assert (src.stat().st_dev, src.stat().st_ino) == (dst.stat().st_dev, dst.stat().st_ino)


def test_hardlink_mode_keeps_exdev_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "AUDIOBOOK_IMPORT_MODE", "hardlink")
    src = tmp_path / "source.m4b"
    dst = tmp_path / "library" / "book.m4b"
    src.write_bytes(b"audio")
    monkeypatch.setattr(main.os, "link", lambda *_: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    with pytest.raises(HTTPException) as exc:
        main.import_audiobook_one(src, dst)
    assert exc.value.status_code == 400
    assert "different filesystems" in exc.value.detail
    assert not dst.exists()


def test_copy_mode_never_calls_os_link(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "AUDIOBOOK_IMPORT_MODE", "copy")
    src = tmp_path / "source.m4b"
    dst = tmp_path / "library" / "book.m4b"
    src.write_bytes(b"audio")
    monkeypatch.setattr(main.os, "link", lambda *_: (_ for _ in ()).throw(AssertionError("link called")))
    main.import_audiobook_one(src, dst)
    assert dst.read_bytes() == src.read_bytes()
    assert (src.stat().st_dev, src.stat().st_ino) != (dst.stat().st_dev, dst.stat().st_ino)


@pytest.mark.parametrize("link_errno", [errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP])
def test_auto_mode_copies_when_hardlink_is_unsupported(tmp_path, monkeypatch, link_errno):
    monkeypatch.setattr(main.settings, "AUDIOBOOK_IMPORT_MODE", "auto")
    src = tmp_path / "source.m4b"
    dst = tmp_path / "library" / "book.m4b"
    src.write_bytes(b"audio")
    monkeypatch.setattr(main.os, "link", lambda *_: (_ for _ in ()).throw(OSError(link_errno, "unsupported")))
    main.import_audiobook_one(src, dst)
    assert dst.read_bytes() == src.read_bytes()
    assert (src.stat().st_dev, src.stat().st_ino) != (dst.stat().st_dev, dst.stat().st_ino)


def test_auto_mode_does_not_mask_unrelated_io_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "AUDIOBOOK_IMPORT_MODE", "auto")
    src = tmp_path / "source.m4b"
    dst = tmp_path / "library" / "book.m4b"
    src.write_bytes(b"audio")
    monkeypatch.setattr(main.os, "link", lambda *_: (_ for _ in ()).throw(OSError(errno.EIO, "io")))
    with pytest.raises(HTTPException) as exc:
        main.import_audiobook_one(src, dst)
    assert exc.value.status_code == 400
    assert not dst.exists()


def test_import_torrent_to_library_uses_auto_fallback(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    source_dir = downloads / "torrent"
    source_dir.mkdir(parents=True)
    library = tmp_path / "library"
    library.mkdir()
    source = source_dir / "book.m4b"
    source.write_bytes(b"audio")
    monkeypatch.setattr(main.settings, "DOWNLOADS_DIR", str(downloads))
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(library))
    monkeypatch.setattr(main.settings, "AUDIOBOOK_IMPORT_MODE", "auto")

    class FakeClient:
        async def torrent_source(self, _hash):
            return ["book.m4b"], str(source_dir)

    monkeypatch.setattr(main, "get_torrent_client", lambda: FakeClient())
    monkeypatch.setattr(main.os, "link", lambda *_: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    destination = Path(asyncio.run(main.import_torrent_to_library("Author", "Title", "HASH")))
    assert (destination / "book.m4b").read_bytes() == b"audio"
    assert source.read_bytes() == b"audio"
