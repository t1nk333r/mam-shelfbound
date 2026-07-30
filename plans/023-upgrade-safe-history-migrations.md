# Plan 023: History-schema migrations upgrade any pre-existing DB without crashing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat a13593e..HEAD -- app/main.py app/tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpt against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (migration robustness)
- **Planned at**: commit `a13593e`, 2026-07-27

## Why this matters

`ensure_history_schema()` **crash-loops the container at startup** whenever the
SQLite DB at `/data/history.db` already contains a `history` table that lacks
this fork's `torrent_status` / `torrent_hash` columns — for example a database
left behind by the upstream project, or by an older build. This is not
hypothetical: it happened in a real deployment. The function creates those
columns **only** via `CREATE TABLE IF NOT EXISTS` (which is a no-op when the
table already exists) and never adds them with `ALTER TABLE`, so the later
`UPDATE history SET torrent_status = 'added' ...` throws
`sqlite3.OperationalError: no such column: torrent_status` and uvicorn exits 1.

The function *already* adds four other columns defensively with guarded
`ALTER TABLE` statements (`status_detail`, `status_updated_at`, `media_type`,
`send_to_kindle`). This plan extends that exact same pattern to the two columns
it forgot, so any older/foreign `history` table upgrades cleanly instead of
crashing. It also records a `PRAGMA user_version` so future schema changes have
an ordered ledger.

## Current state

- `app/main.py` — single-file FastAPI app. `ensure_history_schema()` is the DB
  migration function; it runs **at import time** (module scope, line 202), so a
  failure here happens before the server can even start.

Excerpt as it exists today (`app/main.py:145-201`):

```python
def ensure_history_schema() -> None:
    with engine.begin() as cx:
        cx.execute(text("""
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY,
              mam_id   TEXT,
              title    TEXT,
              author   TEXT,
              narrator TEXT,
              media_type TEXT,
              dl       TEXT,
              added_at TEXT DEFAULT (datetime('now')),
              imported_at TEXT,
              torrent_status TEXT,          # <-- defined only on a BRAND-NEW table
              torrent_hash   TEXT           # <-- defined only on a BRAND-NEW table
            )
        """))
        cols = {row["name"] for row in cx.execute(text("PRAGMA table_info(history)")).mappings()}
        if "status_detail" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN status_detail TEXT"))
        if "status_updated_at" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN status_updated_at TEXT"))
        if "media_type" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN media_type TEXT"))
        if "send_to_kindle" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN send_to_kindle INTEGER DEFAULT 1"))
        # ... UPDATE statements follow. The one below is what crashes on an old table:
        cx.execute(text("""
            UPDATE history
            SET torrent_status = 'added'
            WHERE torrent_status IS NULL OR trim(torrent_status) = ''
        """))
        # ... more UPDATEs, including one resetting stale 'importing' rows ...
```

The bug: `torrent_status` and `torrent_hash` appear in the `CREATE TABLE` but
have **no** guarded `ALTER TABLE` like the four columns above them. `torrent_hash`
is also read by `/history` and `/add` queries elsewhere in the file, so a legacy
table missing it would crash at request time even if startup survived.

**Repo conventions to match:**
- Migrations live inline in `ensure_history_schema()`. Add columns with the
  existing `if "<col>" not in cols:` / `ALTER TABLE history ADD COLUMN` idiom —
  copy it verbatim, do not invent a new mechanism.
- Tests are plain pytest functions in `app/tests/test_*.py` that do `import main`
  and assert on module symbols. See `app/tests/test_helpers.py:1-27` for the
  structure (`import main`, `def test_...()`, direct asserts). `app/conftest.py`
  already points `HISTORY_DB_URL` at a writable temp file, so `main.engine` is
  safe to use in tests.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Syntax check | `python -m py_compile app/main.py` | exit 0, no output |
| Run tests | `cd app && python -m pytest -q` | all pass (incl. the new test) |
| Confirm the two new ALTERs exist | `grep -n "ADD COLUMN torrent_status\|ADD COLUMN torrent_hash" app/main.py` | two matches |

(`pytest` and `respx` are the only dev deps — `requirements-dev.txt`. Tests must
be run from the `app/` directory so `import main` resolves.)

## Scope

**In scope** (the only files you should modify):
- `app/main.py` — inside `ensure_history_schema()` only.
- `app/tests/test_migrations.py` — **create** this file.

**Out of scope** (do NOT touch, even though they look related):
- The `CREATE TABLE` column list — leave it exactly as-is; new DBs already work.
- The existing four guarded `ALTER`s and every `UPDATE` statement — do not
  reorder or modify them.
- Any other function, route, or the `history()` / `/add` query code.
- `app/conftest.py`.

## Git workflow

- Branch: `advisor/023-upgrade-safe-history-migrations`
- Commit message style matches the repo (short imperative subject, e.g.
  `Add guarded ALTERs for torrent_status/torrent_hash`). Do NOT push or open a
  PR unless the operator instructed it.

## Steps

### Step 1 (essential): Add guarded ALTERs for `torrent_status` and `torrent_hash`

In `ensure_history_schema()`, immediately **after** the existing
`if "send_to_kindle" not in cols:` block (the `ALTER TABLE history ADD COLUMN
send_to_kindle ...` line) and **before** the first `UPDATE` statement, insert:

```python
        if "torrent_status" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN torrent_status TEXT"))
        if "torrent_hash" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN torrent_hash TEXT"))
```

Placement is load-bearing: these must run before the `UPDATE ... SET
torrent_status` statement so the column exists when the UPDATE references it.

**Verify**:
- `grep -n "ADD COLUMN torrent_status\|ADD COLUMN torrent_hash" app/main.py` → two matches
- `python -m py_compile app/main.py` → exit 0

### Step 2 (additive, low-risk): Record a schema-version ledger

At the very end of the `with engine.begin() as cx:` block (after the last
`UPDATE`), record the current schema revision so future migrations have an
ordered home:

```python
        # Migration ledger. The block above is idempotent (CREATE IF NOT EXISTS +
        # guarded ALTERs), so it is safe to run on every boot; user_version exists
        # so a FUTURE, non-idempotent migration can be gated, e.g.:
        #   if cx.exec_driver_sql("PRAGMA user_version").scalar() < 2:
        #       cx.exec_driver_sql("<revision-2 migration>")
        cx.exec_driver_sql("PRAGMA user_version = 1")
```

Use `exec_driver_sql` (not `text(...)`) for the PRAGMA — PRAGMAs take no bound
parameters and this is the documented raw-SQL path.

**If `exec_driver_sql` raises or is unavailable, STOP and report** — Step 1 is
the actual crash fix and stands alone; do not block it on this ledger.

**Verify**: `python -m py_compile app/main.py` → exit 0

### Step 3 (essential): Regression test for the exact crash

Create `app/tests/test_migrations.py`:

```python
import sqlalchemy as sa

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
```

The test leaves a fully-migrated `history` table behind (the second call in the
first test recreates a valid schema), so it does not corrupt other tests.

**Verify**: `cd app && python -m pytest -q` → all pass, including the two new tests.

## Test plan

- New file `app/tests/test_migrations.py` with:
  - `test_ensure_history_schema_upgrades_legacy_table_without_torrent_columns`
    — the regression: legacy table without the two columns → migrates cleanly,
    both columns present. This is the case that crashed production.
  - `test_ensure_history_schema_is_idempotent_on_fresh_db` — running twice is safe.
- Structural pattern: model after `app/tests/test_helpers.py` (`import main`,
  plain `def test_...`).
- Verification: `cd app && python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "ADD COLUMN torrent_status\|ADD COLUMN torrent_hash" app/main.py` → exactly two matches
- [ ] `grep -n "PRAGMA user_version = 1" app/main.py` → one match (unless Step 2 was reported blocked)
- [ ] `python -m py_compile app/main.py` → exit 0
- [ ] `cd app && python -m pytest -q` → all pass, and `app/tests/test_migrations.py` exists with the two tests
- [ ] `git status --porcelain` shows only `app/main.py` and the new `app/tests/test_migrations.py` changed
- [ ] `plans/README.md` status row for 023 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `ensure_history_schema()` no longer matches the "Current state" excerpt (the
  code drifted since this plan was written).
- `torrent_status` / `torrent_hash` already have guarded `ALTER`s (someone fixed
  this already) — then only the tests are needed; report that.
- The regression test still raises `no such column` after Step 1 — the column
  set or UPDATE order differs from the excerpt; report the actual code.
- `PRAGMA user_version` via `exec_driver_sql` errors (Step 2) — deliver Step 1 +
  Step 3 and report Step 2 as skipped.

## Maintenance notes

- **This is now the one place schema evolves.** Any new `history` column must be
  added the same way: put it in `CREATE TABLE` (for new DBs) **and** add a
  guarded `if "<col>" not in cols: ALTER TABLE ...` (for existing DBs). Missing
  the second half is exactly the bug this plan fixed.
- If a future migration must transform existing data destructively, gate it on
  `PRAGMA user_version` and bump the version — see the comment added in Step 2.
- A reviewer should confirm the two new `ALTER`s sit before the first `UPDATE`
  and that no `UPDATE`/`CREATE` statement was altered.
