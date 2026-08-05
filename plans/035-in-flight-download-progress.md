# Plan 035: Show in-flight download progress in the History table

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f587737..HEAD -- app/main.py app/static/app.js`
> If either changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: MED
- **Depends on**: none (independent of plans 033/034)
- **Category**: direction
- **Planned at**: commit `f587737`, 2026-08-04

## Why this matters

Between "Add" and "Imported" a torrent is invisible in the app. The history row
sits at `added`, and the auto-import poller only acts once the torrent's hash shows
up in `completed_hashes` (`app/main.py:1187`). For a slow/VPN download that can be
many minutes with **zero in-app feedback** — the user has to open qBittorrent to see
if anything is happening. The data is already one field away: Transmission's
`torrent-get` returns `percentDone` (the code fetches it and *discards* anything
< 1 at `app/main.py:727`), and qBittorrent's `torrents/info` returns `progress`.
This plan surfaces it: a new `in_progress()` client method, a best-effort merge into
`/history`, and a "Downloading 63%" label in the History table. No DB schema change —
progress is ephemeral and read live.

## Current state

- `app/main.py` — single-file FastAPI app. Relevant regions:
  - **The torrent-client abstraction** (`app/main.py:746-759`) — add one method:
    ```python
    class TorrentClient:
        async def add_torrent(self, metainfo, mam_id, media_type, send_to_kindle) -> str | None: ...
        async def completed_hashes(self) -> set[str]: ...
        async def torrent_source(self, torrent_hash) -> tuple[list[str], str]: ...
        async def reachable(self) -> None: ...
    ```
  - **`TransmissionClient`** already has the shape to mirror — `list_completed_torrents`
    fetches `percentDone` and keeps only complete ones (`app/main.py:716-733`):
    ```python
    args = await transmission_rpc(c, "torrent-get", {"fields": ["hashString", "percentDone", "labels"]})
    for t in infos:
        if settings.TRANSMISSION_LABEL and settings.TRANSMISSION_LABEL not in (t.get("labels") or []): continue
        if float(t.get("percentDone") or 0) < 1: continue      # <-- keeps COMPLETE; in_progress inverts this
    ```
    `transmission_rpc` (`app/main.py:484`) handles the 409/CSRF handshake and returns
    the `arguments` dict.
  - **`QbittorrentClient.completed_hashes`** is the model for the qB method
    (`app/main.py:846-857`): `_login`, then GET `torrents/info` with
    `params={"category": settings.QB_CATEGORY, "filter": "completed"}`, tolerate
    non-JSON. qB torrents carry a `progress` float in `[0,1]`.
  - **`get_torrent_client()`** (`app/main.py:886-889`) returns the configured client.
  - **The `/history` endpoint** (`app/main.py:644-667`) — a **sync** `def` (FastAPI
    runs it in a threadpool), returns rows as read-only mappings:
    ```python
    @app.get("/history")
    def history():
        with engine.begin() as cx:
            rows = cx.execute(text(""" SELECT id, mam_id, ..., torrent_hash, ..., torrent_status, ... FROM history ORDER BY id DESC LIMIT 200 """)).mappings().all()
        return {"items": list(rows)}
    ```
- `app/static/app.js` — **`renderHistoryStatusCell`** maps status → label
  (`app/static/app.js:318-340`):
  ```js
  function renderHistoryStatusCell(item) {
    const status = item?.torrent_status || '';
    const detail = item?.status_detail || '';
    const classes = [];
    if (status === 'import_failed') classes.push('history-status-failed');
    if (status === 'importing') classes.push('history-status-active');
    const labels = { added:'Added', importing:'Importing', imported:'Imported', import_failed:'Failure' };
    const label = labels[status] || status;
    const statusHtml = classes.length ? `<span class="${classes.join(' ')}">${escapeHtml(label)}</span>` : escapeHtml(label);
    const detailHtml = detail ? `<div class="history-status-detail">${escapeHtml(truncateText(detail))}</div>` : '';
    return `${statusHtml}${detailHtml}`;
  }
  ```
  `loadHistory` renders each row through this function (`app/static/app.js:485`). The
  `.history-status-active` class already exists in CSS (used for `importing`).

**Conventions**: flat `snake_case` helpers in `main.py`; async client methods each
open their own `httpx.AsyncClient`; outbound calls are best-effort and must never
break a page. Frontend is vanilla JS, no framework/build. Tests: `import main`,
`respx`, and (for qB) the default URL constant `QB = "http://qbittorrent:8080"` —
see `app/tests/test_qbittorrent.py`. JS is validated with `node --check`.

## Commands you will need

| Purpose      | Command                                             | Expected on success |
|--------------|-----------------------------------------------------|---------------------|
| Install deps | `pip install -r requirements.txt -r requirements-dev.txt` | exit 0 |
| Syntax check | `python -m py_compile app/main.py`                  | exit 0              |
| JS check     | `node --check app/static/app.js`                    | exit 0, no output   |
| Tests        | `cd app && python -m pytest -q`                     | all pass            |

## Scope

**In scope** (only these files):
- `app/main.py` — add `in_progress` to `TorrentClient` + both subclasses; add
  `current_download_progress()`; annotate `/history`.
- `app/static/app.js` — `renderHistoryStatusCell` only.
- `app/tests/test_download_progress.py` (create).
- `plans/README.md` — status row.

**Out of scope** (do NOT touch):
- The DB schema / `ensure_history_schema` — progress is **not** persisted.
- `completed_hashes`, `torrent_source`, the auto-import loop, `add_torrent`.
- The History table's HTML/columns in `app/templates/index.html` — the new text
  reuses the existing Status cell.
- Any polling/auto-refresh of history — out of scope (see Maintenance notes).

## Git workflow

- Branch: `advisor/035-in-flight-download-progress`
- Commit style: short, present-tense, no prefix. One or two commits is fine.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Declare `in_progress` on the base class

In `TorrentClient` (after `reachable`, `app/main.py:759`):

```python
    async def in_progress(self) -> dict:
        """Return {hash: percent_complete 0-100} for not-yet-complete torrents."""
        raise NotImplementedError
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 2: Implement it for Transmission

Add to `TransmissionClient` (after its `reachable`, near `app/main.py:795`). Invert
the `list_completed_torrents` filter — keep torrents with `percentDone < 1`:

```python
    async def in_progress(self):
        async with httpx.AsyncClient(timeout=30) as c:
            args = await transmission_rpc(c, "torrent-get", {
                "fields": ["hashString", "percentDone", "labels"],
            })
            out = {}
            for t in args.get("torrents") or []:
                if settings.TRANSMISSION_LABEL and settings.TRANSMISSION_LABEL not in (t.get("labels") or []):
                    continue
                pct = float(t.get("percentDone") or 0)
                if pct >= 1:
                    continue
                h = t.get("hashString")
                if h:
                    out[h] = round(pct * 100, 1)
            return out
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 3: Implement it for qBittorrent

Add to `QbittorrentClient` (after its `reachable`, near `app/main.py:883`):

```python
    async def in_progress(self):
        async with httpx.AsyncClient(timeout=30) as c:
            await self._login(c)
            r = await c.get(
                f"{settings.QB_URL}/api/v2/torrents/info",
                params={"category": settings.QB_CATEGORY, "filter": "downloading"},
            )
            try:
                arr = r.json()
            except ValueError:
                arr = []
            out = {}
            for t in arr:
                if not isinstance(t, dict):
                    continue
                h = t.get("hash")
                try:
                    p = float(t.get("progress"))
                except (TypeError, ValueError):
                    continue
                if h and p < 1:
                    out[h] = round(p * 100, 1)
            return out
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 4: Add a sync, best-effort progress fetch

Add right after `get_torrent_client()` (after `app/main.py:889`):

```python
def current_download_progress() -> dict:
    """Best-effort {hash: percent 0-100} for in-flight torrents. Never raises.

    Called from the sync /history route (threadpool, no running loop), so
    asyncio.run is safe here. Any client error yields {} — progress is a
    nice-to-have and must never break history.
    """
    try:
        return asyncio.run(get_torrent_client().in_progress())
    except Exception:
        logger.warning("Could not fetch download progress", exc_info=True)
        return {}
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 5: Annotate `/history` rows with live progress

Replace the body of `history()` (`app/main.py:645-667`) so it converts rows to
mutable dicts and annotates only in-flight rows. Keep the SELECT exactly as-is:

```python
@app.get("/history")
def history():
    with engine.begin() as cx:
        rows = cx.execute(text("""
            SELECT
                id, mam_id, title, author, narrator, media_type, send_to_kindle,
                dl, torrent_hash, added_at, imported_at, torrent_status,
                status_detail, status_updated_at
            FROM history
            ORDER BY id DESC
            LIMIT 200
        """)).mappings().all()
    items = [dict(r) for r in rows]
    in_flight = [
        it for it in items
        if it.get("torrent_status") in (None, "", "added") and (it.get("torrent_hash") or "").strip()
    ]
    if in_flight:
        progress = current_download_progress()
        if progress:
            for it in in_flight:
                pct = progress.get((it.get("torrent_hash") or "").strip())
                if pct is not None:
                    it["download_progress"] = pct
    return {"items": items}
```

**Verify**: `python -m py_compile app/main.py` → exit 0. (The client is only
queried when at least one row is still in flight, so a history full of `imported`
rows costs nothing.)

### Step 6: Render the percent in the History Status cell

In `renderHistoryStatusCell` (`app/static/app.js:318`), change the `const label`
line into a `let` and add a progress branch just before `statusHtml` is built:

```js
    let label = labels[status] || status;
    const pct = item?.download_progress;
    if ((status === '' || status === 'added') && typeof pct === 'number') {
      label = `Downloading ${pct}%`;
      classes.push('history-status-active');
    }
```

Leave the rest of the function unchanged.

**Verify**: `node --check app/static/app.js` → exit 0.

### Step 7: Write tests

Create `app/tests/test_download_progress.py`:

```python
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
```

**Verify**: `cd app && python -m pytest -q test_download_progress.py` → 4 passed.

## Test plan

- `app/tests/test_download_progress.py` (4 tests): qB `in_progress` parsing +
  complete-exclusion (respx, model `test_qbittorrent.py`); Transmission
  `in_progress` label + completeness filtering (respx, return 200 directly so the
  CSRF branch is skipped); `/history` annotates in-flight rows but not imported
  ones; `/history` skips the client call when nothing is in flight.
- Full suite still green.
- Verification: `cd app && python -m pytest -q` → all pass, +4; `node --check app/static/app.js` → exit 0.

## Done criteria

ALL must hold:

- [ ] `python -m py_compile app/main.py` exits 0
- [ ] `node --check app/static/app.js` exits 0
- [ ] `cd app && python -m pytest -q` exits 0; `test_download_progress.py` (4) passes
- [ ] `grep -n "async def in_progress" app/main.py` → 3 matches (base + 2 clients)
- [ ] `grep -n "download_progress" app/static/app.js` → ≥1 match
- [ ] `git status` shows only: `app/main.py`, `app/static/app.js`, `app/tests/test_download_progress.py`, `plans/README.md`
- [ ] `plans/README.md` status row for 035 updated to DONE

## STOP conditions

Stop and report if:

- The "Current state" excerpts don't match live code (drift since `f587737`).
- A verification fails twice after a reasonable fix.
- Implementing `in_progress` for either client appears to need a new dependency or
  a request the client doesn't already make elsewhere (it should not — both fields
  come from calls the code already performs).
- Wiring progress into `/history` tempts you to add a DB column or a background
  poller — both are explicitly out of scope; report instead.

## Maintenance notes

- **No auto-refresh**: the percent updates only when the History panel is
  (re)loaded — after a search/add, or when the user clicks History. A future
  "live-refresh history every N seconds" feature would make this feel real-time;
  it was left out to keep scope contained. If added, throttle it so
  `current_download_progress()` (one client round-trip per call) isn't hammered.
- `/history` now makes an outbound client call **only when a row is in flight**.
  If the History query's `LIMIT 200` or the status vocabulary changes, re-check the
  `in_flight` predicate (`torrent_status in (None, "", "added")`).
- A reviewer should confirm: the client call is best-effort (a down client returns
  `{}`, history still renders); imported/failed rows never show a percent; and the
  new label reuses the existing `.history-status-active` style (no CSS added).
- `round(pct*100, 1)` yields values like `42.0`/`63.5`; if integer percents are
  preferred in the UI, change the formatter in `renderHistoryStatusCell`, not the
  backend (keep the API numeric).
