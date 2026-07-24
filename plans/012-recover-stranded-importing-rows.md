# Plan 012: A history row left in `importing` by a crash is retried instead of stranded forever

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f8d3d32..HEAD -- app/main.py`
> If `app/main.py` changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/001-establish-verification-baseline.md (soft — only for the test in Step 2)
- **Category**: bug
- **Planned at**: commit `f8d3d32`, 2026-07-23

## Why this matters

Before importing, the app marks a history row `importing`. If the process dies
between that mark and the outcome, the row stays `importing` **permanently** —
there is no code path anywhere that can move it out again:

- the auto-import poller **excludes** `importing` from its candidate query,
- the retry endpoint **rejects** anything that is not `import_failed`,
- the UI only renders a Retry button for `import_failed`,
- the startup backfill only rewrites `NULL`/empty statuses, not stale ones.

The user sees a row stuck on "Importing" forever, the book never reaches the
library, and nothing in the UI or API can recover it — the only fix today is
hand-editing SQLite. The trigger is wider than a hard kill: `asyncio.CancelledError`
inherits from `BaseException`, so the `except Exception` handlers around both
import call sites do **not** catch a task cancellation during shutdown. A
container restart at the wrong moment is enough.

The fix is one `UPDATE` at startup. Any row still `importing` when the process
starts is stale by definition — nothing can be actively importing in a process
that has just begun — so resetting it to `added` puts it back in front of the
poller, which will either import it or mark it `import_failed` (which *is*
retryable from the UI).

## Current state

Facts the executor needs, inlined.

- **Where the mark is set** — two call sites, both in `app/main.py`:
  ```python
  # app/main.py:528 — inside retry_history_import
  update_history_status(history_id, "importing")

  # app/main.py:843 — inside auto_import_cycle
  update_history_status(history_id, "importing")
  ```

- **Why the poller can't pick it back up** (`app/main.py:714-725`, inside
  `get_auto_import_candidates`):
  ```python
  SELECT id, title, author, torrent_hash, torrent_status, media_type, send_to_kindle
  FROM history
  WHERE
      torrent_hash IS NOT NULL
      AND trim(torrent_hash) != ''
      AND (
          torrent_status IS NULL
          OR torrent_status NOT IN ('imported', 'import_failed', 'importing')
      )
  ORDER BY id ASC
  ```

- **Why manual retry can't either** (`app/main.py:509-510`):
  ```python
  if row.get("torrent_status") != "import_failed":
      raise HTTPException(status_code=400, detail="Only failed imports can be retried")
  ```

- **Why the UI shows no button** (`app/static/app.js:245-246`):
  ```javascript
  function buildRetryButton(item) {
    if (item?.torrent_status !== 'import_failed') return null;
  ```

- **The function you will edit** — `ensure_history_schema` already performs
  exactly this kind of idempotent backfill `UPDATE`, and runs at import time
  (`ensure_history_schema()` is called at `app/main.py:141`, module scope). The
  tail of it today (`app/main.py:120-139`):
  ```python
  cx.execute(text("""
      UPDATE history
      SET send_to_kindle = 1
      WHERE send_to_kindle IS NULL
  """))
  cx.execute(text("""
      UPDATE history
      SET torrent_status = 'added'
      WHERE torrent_status IS NULL OR trim(torrent_status) = ''
  """))
  cx.execute(text("""
      UPDATE history
      SET status_updated_at = COALESCE(status_updated_at, imported_at, added_at)
      WHERE status_updated_at IS NULL
  """))
  ```

- **Conventions to match**: the statements above use raw `text("""...""")` with
  no bound parameters and SQLite's own `datetime('now')` for timestamps — the
  same function used at `app/main.py:105` (`added_at TEXT DEFAULT (datetime('now'))`).
  Follow that; do **not** introduce a Python-side timestamp parameter here.
  Python is 4-space indent, `snake_case` (`AGENTS.md:23-26`).

- **Status vocabulary** (used across backend and frontend — do not invent new
  values): `added`, `importing`, `imported`, `import_failed`. The frontend maps
  them to the labels Added / Importing / Imported / Failure
  (`app/static/app.js:227-232`).

## Commands you will need

| Purpose      | Command                                                                                                          | Expected on success  |
|--------------|------------------------------------------------------------------------------------------------------------------|----------------------|
| Syntax check | `python3 -m py_compile app/main.py`                                                                              | exit 0               |
| Run tests    | `cd app && python -m pytest -q`                                                                                  | all pass             |
| Import smoke | `cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_012.db python -c "import main; print('ok')"; rm -f app/tmp_012.db` | prints `ok`          |

The import smoke command relies on the `HISTORY_DB_URL` hook added by plan 001.
If plan 001 has not landed, that env var does nothing and the command will fail
trying to open `/data/history.db` — that is expected; use `py_compile` alone and
see STOP conditions.

## Scope

**In scope** (the only files you should modify):
- `app/main.py` — add one `UPDATE` statement inside `ensure_history_schema`.
- `app/tests/test_helpers.py` — add one test (file created by plan 001).

**Out of scope** (do NOT touch, even though they look related):
- `get_auto_import_candidates` (`app/main.py:710-734`) — do **not** widen its
  `NOT IN` list to include `importing`. That would let the poller pick up a row
  that a *concurrent, live* import is working on, causing a double import. The
  startup reset is safe precisely because it only runs when nothing is in flight.
- `retry_history_import` (`app/main.py:498-542`) — do **not** relax its
  `import_failed` guard.
- `app/static/app.js` — do **not** add a Retry button for `importing` rows. A
  row that is genuinely mid-import must not be retryable.
- `update_history_status` / `mark_history_failed` / `mark_history_imported` —
  unchanged.
- The auto-import loop's exception handling (`app/main.py:845-858`) — tempting to
  add a `BaseException`/`CancelledError` handler there; do not. It changes
  shutdown semantics and is not needed once the startup reset exists.

## Git workflow

- Branch: `advisor/012-recover-stranded-imports`.
- One commit; present-tense message, no prefix — matching `git log` style
  (e.g. `Reset stale importing rows on startup`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Reset stale `importing` rows at startup

In `app/main.py`, inside `ensure_history_schema`, append one more `cx.execute`
**after** the existing `status_updated_at` backfill (i.e. as the last statement
in the `with engine.begin() as cx:` block, ending at `app/main.py:139`):

```python
        # A row can only be 'importing' if a previous process died mid-import;
        # reset it so the auto-import poller retries it.
        cx.execute(text("""
            UPDATE history
            SET
                torrent_status = 'added',
                status_detail = NULL,
                status_updated_at = datetime('now')
            WHERE torrent_status = 'importing'
        """))
```

Indentation: two levels (8 spaces) — it sits inside `def ensure_history_schema`
→ `with engine.begin() as cx:`, matching the statements above it.

Placement matters: it must come **after** the `ALTER TABLE` statements that add
`status_detail` and `status_updated_at` (`app/main.py:112-115`), otherwise those
columns may not exist yet on an old database.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "WHERE torrent_status = 'importing'" app/main.py` → exactly one match,
with a line number greater than the `ALTER TABLE ... status_updated_at` line.

### Step 2: Add a test

This is DB-touching code, not a pure helper, so it needs the temp database the
plan-001 harness configures (`app/conftest.py` points `HISTORY_DB_URL` at a
temp file before `main` is imported). That temp DB **persists between runs**, so
the test must clean up after itself.

In `app/tests/test_helpers.py`, add at the end:
```python
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
```
(`main` is already imported at the top of the file per plan 001; `text` is
imported locally here because the rest of the suite tests pure helpers and does
not need SQLAlchemy at module scope.)

`ensure_history_schema` is idempotent, so calling it again inside a test is safe.

**Verify**: `cd app && python -m pytest -q` → all pass, including the new test.

### Step 3: Confirm the reset end-to-end without the harness

Independent of the test suite, prove the statement does what it claims against a
throwaway database:
```bash
cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_012.db python -c "
import main
from sqlalchemy import text
with main.engine.begin() as cx:
    cx.execute(text(\"INSERT INTO history (title, author, torrent_status, torrent_hash) VALUES ('T','A','importing','H1')\"))
main.ensure_history_schema()
with main.engine.begin() as cx:
    print(cx.execute(text(\"SELECT torrent_status FROM history WHERE torrent_hash='H1'\")).scalar())
"; rm -f app/tmp_012.db
```

**Verify**: prints `added`.

(Requires plan 001's `HISTORY_DB_URL` hook. Skip this step if 001 has not landed
— Step 2 covers the same ground once it has.)

## Test plan

- New test in `app/tests/test_helpers.py`:
  `test_ensure_history_schema_resets_stale_importing` — inserts a row in
  `importing` with a stale `status_detail`, runs `ensure_history_schema()`,
  asserts the status became `added` and the detail was cleared, then deletes the
  row.
- Model after the existing helper tests in the same file (plan 001) for
  structure; this one differs in that it touches `main.engine` and must clean up.
- Not covered by unit tests (accept as manual): that a real crashed import is
  actually re-imported on restart. Verify by hand if you have a live setup —
  set a row to `importing` in the SQLite DB, restart the container, and confirm
  the row flips to `added` and then `imported` within one poll interval (30s).
- Verification: `cd app && python -m pytest -q` → all pass, including 1 new test.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "WHERE torrent_status = 'importing'" app/main.py` returns exactly one match
- [ ] that match's line number is **greater** than the line matched by
      `grep -n "ADD COLUMN status_updated_at" app/main.py`
- [ ] `grep -n "NOT IN ('imported', 'import_failed', 'importing')" app/main.py` still returns one match — the candidate query was **not** widened
- [ ] `grep -n "Only failed imports can be retried" app/main.py` still returns one match — the retry guard is intact
- [ ] `cd app && python -m pytest -q` exits 0 with the new test passing (if plan 001 landed)
- [ ] Step 3's one-liner prints `added` (if plan 001 landed)
- [ ] `git status` shows only `app/main.py` and `app/tests/test_helpers.py` modified
- [ ] `plans/README.md` status row for 012 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `ensure_history_schema` excerpt at `app/main.py:120-139` does not match the
  live code.
- Plan 001 has not landed (`app/tests/test_helpers.py` does not exist). Step 1 is
  still correct and safe on its own — apply it, verify with `py_compile`, and
  report that Steps 2–3 were deferred pending 001. Do **not** create a partial
  test harness of your own.
- The new test fails because the `history` table does not exist in the test
  database — that means `ensure_history_schema()` did not run at import; report
  it rather than creating the table by hand in the test.
- You find yourself wanting to change `get_auto_import_candidates`,
  `retry_history_import`, or `app.js` to make something pass. All three are
  explicitly out of scope; report what pushed you there.

## Maintenance notes

- **Single-instance assumption.** The reset is safe because exactly one app
  process owns the database (`docker-compose.yml` defines one service with a
  fixed `container_name`). If the app is ever run as multiple replicas against a
  shared `/data`, this `UPDATE` would clobber a sibling's in-flight import and
  must be replaced with an owner/heartbeat column.
- Reviewer should confirm the statement sits **after** the `ALTER TABLE` calls
  and that no other status-handling code changed — the diff should be one
  `cx.execute` block plus one test.
- Related but deliberately not fixed here: a row whose torrent was removed from
  Transmission stays `added` forever. That is benign (it simply never becomes a
  candidate) and needs a different mechanism — reconciliation against the live
  torrent list — to address.
- If a future change introduces a new non-terminal status alongside `importing`,
  it needs the same startup reset, and `get_auto_import_candidates`'s `NOT IN`
  list needs the same treatment.
