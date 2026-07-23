import pytest
from fastapi import HTTPException

import main


def test_is_truthy():
    assert main.is_truthy(True) is True
    assert main.is_truthy("yes") is True
    assert main.is_truthy("ON") is True
    assert main.is_truthy("0") is False
    assert main.is_truthy("no") is False
    assert main.is_truthy(None) is False


def test_build_mam_cookie_passthrough_and_wrap():
    assert main.build_mam_cookie("mam_id=abc; other=1") == "mam_id=abc; other=1"
    assert main.build_mam_cookie("bareToken") == "mam_id=bareToken"
    assert main.build_mam_cookie("  ") == ""


def test_normalize_media_type():
    assert main.normalize_media_type("audiobooks") == main.MEDIA_TYPE_AUDIOBOOK
    assert main.normalize_media_type("E-Book") == main.MEDIA_TYPE_EBOOK
    assert main.normalize_media_type(None) == main.MEDIA_TYPE_AUDIOBOOK
    with pytest.raises(HTTPException):
        main.normalize_media_type("magazine")


def test_sanitize_strips_separators():
    assert "/" not in main.sanitize("a/b")
    assert "\\" not in main.sanitize("a\\b")
    assert main.sanitize("  ") == "Unknown"
    assert main.sanitize("Title: Subtitle") == "Title - Subtitle"


def test_next_available(tmp_path):
    p = tmp_path / "Book"
    assert main.next_available(p) == p  # does not exist yet
    p.mkdir()
    assert main.next_available(p) == tmp_path / "Book (2)"


def test_validate_download_path():
    assert main.validate_download_path("/downloads/x") == "/downloads/x"
    assert main.validate_download_path("") == ""
    with pytest.raises(HTTPException):
        main.validate_download_path("/etc")


def test_transmission_labels():
    labels = main.transmission_labels("123", main.MEDIA_TYPE_EBOOK, send_to_kindle=False)
    assert main.settings.TRANSMISSION_LABEL in labels
    assert "mamid=123" in labels
    assert main.TRANSMISSION_NOSEND_LABEL in labels
    # audiobook never gets the nosend label
    assert main.TRANSMISSION_NOSEND_LABEL not in main.transmission_labels("1", main.MEDIA_TYPE_AUDIOBOOK, False)


def test_clean_status_detail():
    assert main.clean_status_detail("  a\n\n b ") == "a b"
    assert main.clean_status_detail("") is None
    assert len(main.clean_status_detail("x" * 999)) == 500


def test_torrent_hash_from_add_result():
    assert main.torrent_hash_from_add_result({"torrent-added": {"hashString": "AB"}}) == "AB"
    assert main.torrent_hash_from_add_result({"torrent-duplicate": {"hashString": "CD"}}) == "CD"
    assert main.torrent_hash_from_add_result({}) is None
