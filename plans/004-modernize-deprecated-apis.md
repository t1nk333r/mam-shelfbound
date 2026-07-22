# Plan 004: The app uses FastAPI lifespan and timezone-aware UTC instead of deprecated APIs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 92761c0..HEAD -- app/main.py`
> If `app/main.py` changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW-MED
- **Depends on**: plans/001-establish-verification-baseline.md (recommended, for regression coverage)
- **Category**: migration
- **Planned at**: commit `92761c0`, 2026-07-22

## Why this matters

`app/main.py` uses two deprecated APIs:

1. **`@app.on_event("startup")` / `@app.on_event("shutdown")`**
   (`app/main.py:899,903`) — deprecated by FastAPI in favor of a `lifespan`
   context manager. Combined with unpinned dependencies (see plan 002), the day
   FastAPI removes `on_event` the auto-import poller **silently never starts**
   (no startup hook fires) — imports quietly stop happening.
2. **`datetime.utcnow()`** (`app/main.py:92`) — deprecated since Python 3.12
   (the Docker base image), emitting `DeprecationWarning` and scheduled for
   removal. Replace with timezone-aware `datetime.now(timezone.utc)`.

Both fixes are small and keep behavior identical (the stored timestamp string
format does not change). This removes the deprecation warnings and the latent
startup-crash risk.

## Current state

- Timestamp helper (`app/main.py:91-92`):
  ```python
  def utcnow_str() -> str:
      return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
  ```
  The import at the top is `from datetime import datetime` (`app/main.py:11`).
  The produced string has **no** timezone suffix; the frontend appends `'Z'`
  when parsing (`app/static/app.js:320`:
  `new Date(item.added_at.replace(' ', 'T') + 'Z')`). The output string must
  stay byte-for-byte the same.
- App construction and the two event hooks:
  ```python
  # app/main.py:180-182
  app = FastAPI(title="MAM Book Finder", version=APP_VERSION)
  app.state.auto_import_task = None
  app.state.auto_import_stop = None
  ```
  ```python
  # app/main.py:899-905
  @app.on_event("startup")
  async def startup_event():
      await reconcile_auto_import_task()

  @app.on_event("shutdown")
  async def shutdown_event():
      await stop_auto_import_task()
  ```
- The two coroutines the hooks call are defined earlier in the file:
  `reconcile_auto_import_task` (`app/main.py:892`) and `stop_auto_import_task`
  (`app/main.py:879`). They reference the module global `app`, so they must be
  *called* only at runtime (after the whole module has loaded) — which lifespan
  guarantees.
- `contextlib` is **not** currently imported.

## Commands you will need

| Purpose        | Command                                  | Expected on success       |
|----------------|------------------------------------------|---------------------------|
| Syntax check   | `python3 -m py_compile app/main.py`      | exit 0                    |
| Run tests      | `cd app && python -m pytest -q`          | all pass                  |
| Import smoke   | `cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_lifespan.db python -c "import main; print(type(main.app).__name__)"` | prints `FastAPI` |

(The smoke command uses the env-configurable DB URL introduced in plan 001. If
001 has not landed, the DB path is still hardcoded to `/data`; see STOP
conditions.)

## Scope

**In scope** (the only file you should modify):
- `app/main.py`

**Out of scope** (do NOT touch):
- The bodies of `reconcile_auto_import_task` / `stop_auto_import_task`
  (`app/main.py:879-897`) — reuse them as-is from lifespan; do not rewrite the
  task management.
- Any other `datetime` usage or timestamp format — only `utcnow_str` changes.
- Do NOT change the stored timestamp string format (no `+00:00`, no `Z`).

## Git workflow

- Branch: `advisor/004-modernize-deprecated-apis`.
- Two logical commits are fine (one per API), present-tense messages
  (e.g. `Use FastAPI lifespan for auto-import poller`, `Use timezone-aware UTC timestamps`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Timezone-aware UTC timestamp

Update the import and the helper.

Change `app/main.py:11` from:
```python
from datetime import datetime
```
to:
```python
from datetime import datetime, timezone
```
Change `utcnow_str` (`app/main.py:91-92`) to:
```python
def utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
```
The `strftime` format is unchanged, so the output string is identical (UTC wall
clock, no offset text).

**Verify**:
`cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_ts.db python -c "import main,re; s=main.utcnow_str(); print(s); assert re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', s)"`
→ prints a timestamp and exits 0 (format preserved). Delete `app/tmp_ts.db`
afterward.

### Step 2: Replace `on_event` hooks with a lifespan handler

Add `from contextlib import asynccontextmanager` to the imports near the top of
`app/main.py` (a good spot is beside the other stdlib imports).

Define a `lifespan` function **immediately above** the `app = FastAPI(...)` line
(`app/main.py:180`) and wire it in. Because `lifespan` only *calls*
`reconcile_auto_import_task` / `stop_auto_import_task` at runtime, referencing
those (defined later in the file) is fine:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await reconcile_auto_import_task()
    try:
        yield
    finally:
        await stop_auto_import_task()

app = FastAPI(title="MAM Book Finder", version=APP_VERSION, lifespan=lifespan)
app.state.auto_import_task = None
app.state.auto_import_stop = None
```
Then **delete** the two `@app.on_event` blocks at the bottom of the file
(`app/main.py:899-905`).

**Verify**:
- `grep -n "on_event" app/main.py` → no matches.
- `grep -n "lifespan=lifespan" app/main.py` → one match.
- `python3 -m py_compile app/main.py` → exit 0.

### Step 3: Smoke-test that the app object builds

```bash
cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_lifespan.db python -c "import main; print(type(main.app).__name__)"
```
Then remove the temp DB: `rm -f app/tmp_lifespan.db`.

**Verify**: prints `FastAPI`, exit 0.

## Test plan

- If plan 001 landed, run its suite to confirm no regression:
  `cd app && python -m pytest -q` → all pass. `utcnow_str` is not directly
  asserted there; optionally add a format assertion test mirroring Step 1's
  regex.
- Lifespan wiring is verified by the Step 3 import smoke test (the poller start
  itself hits Transmission and is not unit-tested here — see maintenance notes).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "utcnow(" app/main.py` returns no matches
- [ ] `grep -n "on_event" app/main.py` returns no matches
- [ ] `grep -n "lifespan=lifespan" app/main.py` returns exactly one match
- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] the Step 3 smoke command prints `FastAPI`
- [ ] `cd app && python -m pytest -q` exits 0 (if plan 001 landed)
- [ ] `git status` shows only `app/main.py` modified (and no stray `tmp_*.db`)
- [ ] `plans/README.md` status row for 004 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The DB path is still hardcoded (`sqlite:////data/history.db`) and the smoke
  commands fail with a database open error — plan 001 has not landed; either run
  001 Step 1 first or run the smoke test in an environment where `/data` is
  writable, and note it.
- The excerpts at `app/main.py:180-182` or `:899-905` do not match live code.
- After wiring lifespan, the import smoke test raises `NameError` for
  `reconcile_auto_import_task` — this means the call was moved to module load
  time instead of staying inside the async `lifespan` body; revert and keep the
  call inside `lifespan`.

## Maintenance notes

- Any future startup/shutdown work belongs inside the `lifespan` function now,
  not in new `on_event` hooks.
- Reviewer should confirm the poller still starts (check logs for
  "Auto-import poller started") and stops cleanly on shutdown, and that the
  history timestamp column values look identical to before (no `+00:00`/`Z`).
- Follow-up deferred: an integration test for lifespan (poller start/stop with a
  mocked Transmission) would be valuable but needs the HTTP layer mocked — out
  of scope here.
