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


def test_safe_child_path_allows_normal_names(tmp_path):
    root = tmp_path
    assert main.safe_child_path(root, "book.m4b") == root / "book.m4b"
    assert main.safe_child_path(root, "Author/book.m4b") == root / "Author/book.m4b"


def test_safe_child_path_rejects_traversal(tmp_path):
    with pytest.raises(HTTPException):
        main.safe_child_path(tmp_path, "../evil")
    with pytest.raises(HTTPException):
        main.safe_child_path(tmp_path, "a/../../evil")
    with pytest.raises(HTTPException):
        main.safe_child_path(tmp_path, "/etc/passwd")


def test_sanitize_rejects_dot_components():
    # Bare dot components would escape the library root once joined.
    assert main.sanitize("..") == "Unknown"
    assert main.sanitize(".") == "Unknown"
    assert main.sanitize("  ..  ") == "Unknown"
    # ...but these are ordinary names and must survive.
    assert main.sanitize("...") == "..."
    assert main.sanitize("Vol. 2") == "Vol. 2"


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


def test_normalize_perpage():
    assert main.normalize_perpage(50) == 50
    assert main.normalize_perpage("100") == 100
    assert main.normalize_perpage(None) == 25      # missing -> default
    assert main.normalize_perpage(999) == 25       # out of allowed set -> default
    assert main.normalize_perpage("abc") == 25     # non-int -> default
    assert main.normalize_perpage(-1) == 25


def test_validate_mam_id_accepts_numeric():
    assert main.validate_mam_id("12345") == "12345"
    assert main.validate_mam_id("0") == "0"


def test_validate_mam_id_rejects_query_injection():
    # "&fl=1" would spend a freeleech wedge on an ebook add.
    with pytest.raises(HTTPException):
        main.validate_mam_id("12345&fl=1")
    for bad in ["abc", "-1", "1.5", "1 2", "", "²", "١٢٣"]:
        with pytest.raises(HTTPException):
            main.validate_mam_id(bad)


def test_is_torrent_metainfo_accepts_bencoded_metainfo_and_rejects_html():
    assert main.is_torrent_metainfo(b"d4:infod4:name4:Bookee") is True
    assert main.is_torrent_metainfo(b"<html>Please sign in</html>") is False
    assert main.is_torrent_metainfo(b"d4:info4:Book") is False


def test_should_use_freeleech_respects_reserve_and_media_type():
    AB = main.MEDIA_TYPE_AUDIOBOOK
    EB = main.MEDIA_TYPE_EBOOK

    # reserve 0 reproduces the historical behavior: spend whenever any exist
    assert main.should_use_freeleech(AB, 1, 0) is True
    assert main.should_use_freeleech(AB, 0, 0) is False
    assert main.should_use_freeleech(AB, None, 0) is False

    # a reserve holds the last N back
    assert main.should_use_freeleech(AB, 6, 5) is True
    assert main.should_use_freeleech(AB, 5, 5) is False   # at the reserve, stop
    assert main.should_use_freeleech(AB, 2, 5) is False   # below it, stop

    # ebooks never spend a wedge, whatever the balance
    assert main.should_use_freeleech(EB, 99, 0) is False


def test_ensure_history_schema_resets_stale_importing():
    from sqlalchemy import text

    try:
        with main.engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO history (mam_id, title, author, media_type, torrent_status, torrent_hash, status_detail)
                VALUES ('t012', 'T', 'A', 'audiobook', 'importing', 'HASH_STALE_012', 'stale detail')
            """))

        main.ensure_history_schema()

        with main.engine.begin() as cx:
            row = cx.execute(text("""
                SELECT torrent_status, status_detail
                FROM history
                WHERE torrent_hash = 'HASH_STALE_012'
            """)).mappings().first()

        assert row is not None
        assert row["torrent_status"] == "added"
        assert row["status_detail"] is None
    finally:
        with main.engine.begin() as cx:
            cx.execute(text("DELETE FROM history WHERE torrent_hash = 'HASH_STALE_012'"))


def test_default_send_to_kindle_defaults_to_nosend():
    assert main.default_send_to_kindle(None) is False   # new default: no-send
    assert main.default_send_to_kindle(True) is True
    assert main.default_send_to_kindle(False) is False


def test_get_torrent_client_selects_backend(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "transmission")
    assert type(main.get_torrent_client()).__name__ == "TransmissionClient"
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "qbittorrent")
    assert type(main.get_torrent_client()).__name__ == "QbittorrentClient"


def test_qb_tags():
    tags = main.qb_tags("123", main.MEDIA_TYPE_EBOOK, send_to_kindle=False)
    assert "mamid=123" in tags
    assert main.TRANSMISSION_NOSEND_LABEL in tags
    # audiobook, kindle on -> just the mamid tag (no nosend)
    assert main.TRANSMISSION_NOSEND_LABEL not in main.qb_tags("1", main.MEDIA_TYPE_AUDIOBOOK, True)


def test_engine_is_pointed_at_a_temp_database():
    # conftest must FORCE the test DB. If this ever regresses to setdefault, a
    # developer with HISTORY_DB_URL exported would have the suite mutate their
    # real database at import time (ensure_history_schema rewrites rows).
    import tempfile

    url = str(main.engine.url)
    assert tempfile.gettempdir() in url
    assert "/data/history.db" not in url


def test_qb_find_added_hash_prefers_newest_and_retries():
    import asyncio

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        """Returns an empty list N times, then two torrents out of age order."""

        def __init__(self, empties):
            self.empties = empties
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            if self.calls <= self.empties:
                return _Resp([])
            return _Resp([
                {"hash": "OLDER", "added_on": 100},
                {"hash": "NEWEST", "added_on": 900},
            ])

    client = _Client(empties=2)
    got = asyncio.run(
        main.QbittorrentClient()._find_added_hash(client, "42", attempts=5, delay=0)
    )
    assert got == "NEWEST"      # newest wins, not arr[0]
    assert client.calls == 3    # retried past the two empty responses


def test_qb_find_added_hash_gives_up_and_returns_none():
    import asyncio

    class _Resp:
        def json(self):
            return []

    class _Client:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            return _Resp()

    client = _Client()
    got = asyncio.run(
        main.QbittorrentClient()._find_added_hash(client, "42", attempts=3, delay=0)
    )
    assert got is None
    assert client.calls == 3    # exhausted its attempts, no infinite loop


def test_format_failure_message_with_and_without_author():
    msg = main.format_failure_message({"title": "Dune", "author": "Frank Herbert"}, "disk full")
    assert "Dune by Frank Herbert" in msg
    assert "disk full" in msg
    # missing author, and a completely absent row, must not raise
    assert "Dune" in main.format_failure_message({"title": "Dune", "author": ""}, "x")
    assert "Unknown title" in main.format_failure_message(None, None)


def test_schedule_failure_notification_is_a_noop_without_config(monkeypatch):
    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "")
    main.schedule_failure_notification("anything")
    assert not main._notification_tasks


def test_schedule_failure_notification_is_a_noop_without_event_loop(monkeypatch):
    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "http://example.invalid/hook")
    main.schedule_failure_notification("anything")
    assert not main._notification_tasks


def test_send_failure_notification_swallows_transport_errors(monkeypatch):
    import asyncio

    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "http://127.0.0.1:1/hook")
    monkeypatch.setattr(main.settings, "NOTIFY_TIMEOUT", 1)
    asyncio.run(main.send_failure_notification("boom"))  # must simply return
