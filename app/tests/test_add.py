"""POST /add error handling: account-lookup failures, network errors, and the
freeleech-to-plain download fallback. MAM is intercepted with respx; the torrent
client is replaced with a fake so no Transmission/qBittorrent is needed."""
import asyncio

import httpx
import pytest
import respx
from fastapi import HTTPException
from httpx import Response
from sqlalchemy import create_engine

import main

MAM = main.DEFAULT_MAM_BASE
PLAIN_URL = f"{MAM}/tor/download.php?tid=42"
FL_URL = f"{MAM}/tor/download.php?tid=42&fl=1"
TORRENT = b"d4:infod4:name4:booke6:lengthi1ee"
HTML_PAGE = b"<html><body>Not logged in</body></html>"


class FakeClient:
    def __init__(self, error=None):
        self.added = []
        self.error = error

    async def add_torrent(self, metainfo, mam_id, media_type, send_to_kindle):
        if self.error:
            raise self.error
        self.added.append(metainfo)
        return "HASH" + mam_id


@pytest.fixture
def client(monkeypatch, tmp_path):
    # A private DB per test, so assertions on its rows can't race other runs.
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/history.db", future=True))
    main.ensure_history_schema()
    monkeypatch.setattr(main.settings, "FL_WEDGE_MIN_RESERVE", 0)
    fake = FakeClient()
    monkeypatch.setattr(main, "get_torrent_client", lambda: fake)
    return fake


def add(media_type="audiobook", mam_id="42"):
    body = main.AddBody(id=mam_id, title="Book", author="Author", media_type=media_type)
    return asyncio.run(main.add_to_transmission(body))


def history_hashes():
    with main.engine.begin() as cx:
        return [r[0] for r in cx.exec_driver_sql("SELECT torrent_hash FROM history")]


def mock_account(wedges=None, **kwargs):
    route = respx.get(f"{MAM}/jsonLoad.php")
    if kwargs:
        return route.mock(**kwargs)
    return route.mock(return_value=Response(200, json={"uid": 1, "wedges": wedges}))


def mock_downloads(plain, fl=None):
    """Route download.php by its `fl` param. Each response is a Response or an
    exception to raise. Returns the list of requested URLs."""
    calls = []

    def respond(request):
        calls.append(str(request.url))
        result = fl if request.url.params.get("fl") == "1" else plain
        if isinstance(result, Exception):
            raise result
        return result

    respx.get(f"{MAM}/tor/download.php").mock(side_effect=respond)
    return calls


# ---------------------------- Finding 1: lookup and network failures ----------------------------

@respx.mock
@pytest.mark.parametrize("media_type", ["audiobook", "ebook"])
def test_add_succeeds_when_account_lookup_returns_error(client, media_type):
    mock_account(return_value=Response(500, text="oops"))
    calls = mock_downloads(plain=Response(200, content=TORRENT))

    result = add(media_type)

    assert result == {"ok": True}                 # no wedge count: page keeps its last value
    assert calls == [PLAIN_URL]                    # no freeleech without a known count
    assert client.added == [TORRENT]
    assert history_hashes() == ["HASH42"]


@respx.mock
def test_add_succeeds_when_account_lookup_has_network_error(client):
    mock_account(side_effect=httpx.ConnectError("boom"))
    mock_downloads(plain=Response(200, content=TORRENT))

    assert add() == {"ok": True}
    assert history_hashes() == ["HASH42"]


@respx.mock
def test_add_returns_known_zero_wedge_count(client):
    mock_account(wedges=0)
    calls = mock_downloads(plain=Response(200, content=TORRENT))

    assert add() == {"ok": True, "freeleech_wedges": 0}   # only an unknown count is omitted
    assert calls == [PLAIN_URL]


@respx.mock
def test_account_network_error_returns_502():
    # A real timeout's str() is empty; the detail must still say what happened.
    mock_account(side_effect=httpx.ReadTimeout(""))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.account_status())

    assert exc.value.status_code == 502
    assert exc.value.detail == "MAM account summary request failed: request timed out"


def test_describe_http_error_never_blank_and_hides_header_values():
    assert main.describe_http_error(httpx.ConnectTimeout("")) == "request timed out"
    assert main.describe_http_error(httpx.ConnectError("refused")) == "refused"
    assert main.describe_http_error(httpx.RemoteProtocolError("")) == "RemoteProtocolError"
    leaked = httpx.LocalProtocolError("Illegal header value b'mam_id=SECRET\\n'")
    assert "SECRET" not in main.describe_http_error(leaked)


@respx.mock
def test_add_torrent_download_network_error_returns_502(client):
    mock_account(wedges=0)
    mock_downloads(plain=httpx.ConnectError("refused"))

    with pytest.raises(HTTPException) as exc:
        add()

    assert exc.value.status_code == 502
    assert "Could not fetch .torrent from MAM" in exc.value.detail
    assert history_hashes() == []


@respx.mock
def test_add_torrent_client_network_error_returns_502(client):
    client.error = httpx.ConnectError("client down")
    mock_account(wedges=0)
    mock_downloads(plain=Response(200, content=TORRENT))

    with pytest.raises(HTTPException) as exc:
        add()

    assert exc.value.status_code == 502
    assert "request failed" in exc.value.detail
    assert history_hashes() == []


# ---------------------------- Finding 2: freeleech fallback ----------------------------

@respx.mock
def test_add_uses_freeleech_when_wedges_available(client):
    mock_account(wedges=5)
    calls = mock_downloads(plain=Response(200, content=TORRENT), fl=Response(200, content=TORRENT))

    result = add()

    assert result == {"ok": True, "freeleech_wedges": 4}
    assert calls == [FL_URL]


@respx.mock
def test_add_falls_back_to_plain_when_freeleech_returns_non_torrent(client):
    mock_account(wedges=5)
    calls = mock_downloads(plain=Response(200, content=TORRENT), fl=Response(200, content=HTML_PAGE))

    result = add()

    assert result == {"ok": True, "freeleech_wedges": 5}   # no wedge was spent
    assert calls == [FL_URL, PLAIN_URL]
    assert client.added == [TORRENT]


@respx.mock
def test_add_falls_back_to_plain_when_freeleech_request_errors(client):
    mock_account(wedges=5)
    calls = mock_downloads(plain=Response(200, content=TORRENT), fl=httpx.ReadTimeout("slow"))

    assert add() == {"ok": True, "freeleech_wedges": 5}
    assert calls == [FL_URL, PLAIN_URL]
    assert client.added == [TORRENT]


@respx.mock
def test_add_reports_expired_session_only_when_plain_download_is_not_a_torrent(client):
    mock_account(wedges=5)
    calls = mock_downloads(plain=Response(200, content=HTML_PAGE), fl=Response(200, content=HTML_PAGE))

    with pytest.raises(HTTPException) as exc:
        add()

    assert exc.value.status_code == 422
    assert calls == [FL_URL, PLAIN_URL]           # the plain URL was tried before giving up
    assert client.added == []
    assert history_hashes() == []


@respx.mock
def test_add_reports_plain_download_status_after_freeleech_failure(client):
    mock_account(wedges=5)
    mock_downloads(plain=Response(404), fl=Response(200, content=HTML_PAGE))

    with pytest.raises(HTTPException) as exc:
        add()

    assert exc.value.status_code == 502
    assert "status: 404" in exc.value.detail


@respx.mock
def test_add_reports_plain_network_error_after_freeleech_failure(client):
    mock_account(wedges=5)
    calls = mock_downloads(plain=httpx.ConnectError("refused"), fl=Response(200, content=HTML_PAGE))

    with pytest.raises(HTTPException) as exc:
        add()

    assert exc.value.status_code == 502          # not the misleading 422 "session expired"
    assert exc.value.detail == "Could not fetch .torrent from MAM: refused"
    assert calls == [FL_URL, PLAIN_URL]
