"""qBittorrent client tests. The client builds its own httpx.AsyncClient
internally, so requests are intercepted at the transport layer with respx."""
import asyncio

import pytest
import respx
from fastapi import HTTPException
from httpx import Response

import main

QB = "http://qbittorrent:8080"


def _login_ok():
    return respx.post(f"{QB}/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))


# ---------------------------- _login ----------------------------

@respx.mock
def test_login_failure_raises_502():
    respx.post(f"{QB}/api/v2/auth/login").mock(return_value=Response(200, text="Fails."))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().completed_hashes())
    assert exc.value.status_code == 502


# ---------------------------- add_torrent ----------------------------

@respx.mock
def test_add_torrent_sends_torrent_category_and_tags():
    _login_ok()
    add = respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"hash": "ABC123", "added_on": 500}]))

    got = asyncio.run(main.QbittorrentClient().add_torrent(b"BYTES", "42", "ebook", False))

    assert got == "ABC123"
    body = add.calls.last.request.content
    assert b"mam.torrent" in body and b"BYTES" in body
    assert b"mamid=42" in body
    assert b"kindle-nosend" in body          # ebook + send_to_kindle False
    assert main.settings.QB_CATEGORY.encode() in body


@respx.mock
def test_add_torrent_audiobook_has_no_nosend_tag():
    _login_ok()
    add = respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"hash": "H", "added_on": 1}]))

    asyncio.run(main.QbittorrentClient().add_torrent(b"B", "7", "audiobook", True))

    assert b"kindle-nosend" not in add.calls.last.request.content


@respx.mock
def test_add_torrent_raises_502_when_add_rejected():
    _login_ok()
    respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Fails."))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().add_torrent(b"B", "1", "audiobook", True))
    assert exc.value.status_code == 502


@respx.mock
def test_add_torrent_returns_none_when_qb_never_lists_the_torrent():
    _login_ok()
    respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=Response(200, json=[]))

    got = asyncio.run(main.QbittorrentClient().add_torrent(b"B", "42", "audiobook", True))
    assert got is None


# ---------------------------- completed_hashes ----------------------------

@respx.mock
def test_completed_hashes_queries_category_and_returns_hashes():
    _login_ok()
    route = respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"hash": "H1"}, {"hash": "H2"}, {"no": "hash"}, "junk"]))

    got = asyncio.run(main.QbittorrentClient().completed_hashes())

    assert got == {"H1", "H2"}
    params = route.calls.last.request.url.params
    assert params["category"] == main.settings.QB_CATEGORY
    assert params["filter"] == "completed"


@respx.mock
def test_completed_hashes_tolerates_non_json():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=Response(200, text="<html>nope"))
    assert asyncio.run(main.QbittorrentClient().completed_hashes()) == set()


# ---------------------------- torrent_source ----------------------------

@respx.mock
def test_torrent_source_returns_names_and_save_path():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"save_path": "/downloads/", "hash": "H"}]))
    files = respx.get(f"{QB}/api/v2/torrents/files").mock(
        return_value=Response(200, json=[{"name": "Book/01.mp3"}, {"name": "/Book/02.mp3"}]))

    names, path = asyncio.run(main.QbittorrentClient().torrent_source("H"))

    assert path == "/downloads"                        # trailing slash stripped
    assert names == ["Book/01.mp3", "Book/02.mp3"]     # leading slash stripped
    assert files.calls.last.request.url.params["hash"] == "H"


@respx.mock
def test_torrent_source_raises_404_when_save_path_missing():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=Response(200, json=[]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().torrent_source("H"))
    assert exc.value.status_code == 404


@respx.mock
def test_torrent_source_raises_404_when_no_files():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"save_path": "/downloads"}]))
    respx.get(f"{QB}/api/v2/torrents/files").mock(return_value=Response(200, json=[]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().torrent_source("H"))
    assert exc.value.status_code == 404
