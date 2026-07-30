import main


def test_ensure_history_schema_upgrades_legacy_table_without_torrent_columns():
    # Simulate a pre-existing `history` table from an older/upstream build that
    # predates torrent_status / torrent_hash — this is what crash-looped in prod.
    with main.engine.begin() as cx:
        cx.exec_driver_sql("DROP TABLE IF EXISTS history")
        cx.exec_driver_sql(
            "CREATE TABLE history ("
            "  id INTEGER PRIMARY KEY, mam_id TEXT, title TEXT, author TEXT,"
            "  narrator TEXT, media_type TEXT, dl TEXT,"
            "  added_at TEXT, imported_at TEXT"
            ")"
        )
        cx.exec_driver_sql(
            "INSERT INTO history (title, author) VALUES ('Legacy Book', 'Someone')"
        )

    # Must not raise (previously: 'no such column: torrent_status').
    main.ensure_history_schema()

    with main.engine.begin() as cx:
        cols = {r[1] for r in cx.exec_driver_sql("PRAGMA table_info(history)")}
    assert "torrent_status" in cols
    assert "torrent_hash" in cols


def test_ensure_history_schema_is_idempotent_on_fresh_db():
    # Running twice in a row must not raise.
    main.ensure_history_schema()
    main.ensure_history_schema()
