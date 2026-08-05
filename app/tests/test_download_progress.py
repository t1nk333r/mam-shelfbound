import asyncio

import respx
from httpx import Response

import main

QB = "http://qbittorrent:8080"


@respx.mock
def test_qb_in_progress_returns_percent_and_excludes_complete(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "qbittorrent")
    respx.post(f"{QB}/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=Response(200, json=[
        {"hash": "H1", "progress": 0.5},
        {"hash": "H2", "progress": 1.0},   # complete -> excluded
        {"no": "hash", "progress": 0.2},   # no hash -> skipped
        "junk",
    ]))
    got = asyncio.run(main.QbittorrentClient().in_progress())
    assert got == {"H1": 50.0}


@respx.mock
def test_transmission_in_progress_filters_by_label_and_completeness(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "transmission")
    label = main.settings.TRANSMISSION_LABEL
    respx.post(main.settings.TRANSMISSION_URL).mock(return_value=Response(200, json={
        "result": "success",
        "arguments": {"torrents": [
            {"hashString": "A", "percentDone": 0.25, "labels": [label]},
            {"hashString": "B", "percentDone": 1.0, "labels": [label]},   # complete -> excluded
            {"hashString": "C", "percentDone": 0.5, "labels": ["other"]}, # wrong label -> excluded
        ]},
    }))
    got = asyncio.run(main.TransmissionClient().in_progress())
    assert got == {"A": 25.0}


def test_history_annotates_in_flight_rows(monkeypatch):
    with main.engine.begin() as cx:
        cx.exec_driver_sql("DROP TABLE IF EXISTS history")
    main.ensure_history_schema()
    with main.engine.begin() as cx:
        cx.exec_driver_sql("INSERT INTO history (id, title, torrent_hash, torrent_status) VALUES (1, 'Downloading Book', 'abc', 'added')")
        cx.exec_driver_sql("INSERT INTO history (id, title, torrent_hash, torrent_status) VALUES (2, 'Done Book', 'xyz', 'imported')")
    monkeypatch.setattr(main, "current_download_progress", lambda: {"abc": 42.0, "xyz": 100.0})

    items = {it["id"]: it for it in main.history()["items"]}
    assert items[1]["download_progress"] == 42.0        # in-flight row annotated
    assert "download_progress" not in items[2]          # imported row not annotated


def test_history_no_client_call_when_nothing_in_flight(monkeypatch):
    with main.engine.begin() as cx:
        cx.exec_driver_sql("DROP TABLE IF EXISTS history")
    main.ensure_history_schema()
    with main.engine.begin() as cx:
        cx.exec_driver_sql("INSERT INTO history (id, title, torrent_hash, torrent_status) VALUES (1, 'Done', 'xyz', 'imported')")
    called = {"n": 0}
    def boom():
        called["n"] += 1
        return {}
    monkeypatch.setattr(main, "current_download_progress", boom)
    main.history()
    assert called["n"] == 0                              # not queried when no in-flight rows
