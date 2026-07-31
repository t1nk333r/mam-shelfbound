import asyncio

import httpx
import respx

import main


@respx.mock
def test_warning_none_when_qb_reachable(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "qbittorrent")
    respx.post(f"{main.settings.QB_URL}/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    assert asyncio.run(main.torrent_client_warning()) is None


@respx.mock
def test_warning_flags_qb_unreachable(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "qbittorrent")
    respx.post(f"{main.settings.QB_URL}/api/v2/auth/login").mock(
        side_effect=httpx.ConnectError("refused")
    )
    msg = asyncio.run(main.torrent_client_warning())
    assert msg and "qbittorrent" in msg and "not reachable" in msg
