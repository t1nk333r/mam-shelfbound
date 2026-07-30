# Plan 024: Startup preflight replaces misconfig tracebacks with one-line diagnostics

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat a13593e..HEAD -- app/main.py app/tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED — runs at import; must not break the test suite (see STOP conditions)
- **Depends on**: none (independent of 023, but naturally lands alongside it)
- **Category**: dx (operability)
- **Planned at**: commit `a13593e`, 2026-07-27

## Why this matters

Every misconfiguration of this container currently surfaces as a raw Python
traceback, which an operator cannot act on. Two real examples from a live
deployment: (1) the `/data` volume not being writable by the container's user
produced a 30-line SQLAlchemy `OperationalError` stack trace instead of "your
data dir isn't writable"; (2) putting `/downloads` and `/library` on different
filesystems makes audiobook imports fail *mid-import* with a cross-device
(`EXDEV`) hardlink error, discovered only after an import silently failed.

A boot-time **preflight** turns these into actionable messages: a **fatal, clear
exit** when `/data` isn't writable (caught *before* the DB code runs), and
**startup warnings** when the hardlink filesystems differ or the library dirs
are missing. This is deliberately the maintainer-preferred shape: the project
**removed** its old `/health` endpoint (commit `fc9251e`, and `plans/005` says
do not re-add it), so this plan does **not** add an HTTP endpoint — it fails
fast at startup with a message and logs warnings, nothing to poll.

## Current state

- `app/main.py` is a single-file FastAPI app. Relevant anchors:
  - Hardcoded path constants (`app/main.py:17-20`):
    ```python
    DOWNLOADS_DIR = "/downloads"
    LIBRARY_DIR = "/library"
    EBOOKS_DIR = "/ebooks"
    EBOOKS_NOSEND_DIR = "/ebooks-nosend"
    ```
    mirrored onto `settings.DOWNLOADS_DIR` / `.LIBRARY_DIR` etc. (`app/main.py:119-122`).
  - DB URL + engine (`app/main.py:139-140`):
    ```python
    HISTORY_DB_URL = os.getenv("HISTORY_DB_URL", "sqlite:////data/history.db")
    engine = create_engine(HISTORY_DB_URL, future=True)
    ```
  - `ensure_history_schema()` runs **at import** (`app/main.py:202`) — this is
    where the `/data`-not-writable traceback originates.
  - The app uses a lifespan handler for startup/shutdown (`app/main.py:242-251`):
    ```python
    async def lifespan(app: FastAPI):
        await reconcile_auto_import_task()
        try:
            yield
        finally:
            await stop_auto_import_task()

    app = FastAPI(title="MAM Book Finder", version=APP_VERSION, lifespan=lifespan)
    ```
  - `import_torrent_to_library()` hardlinks from `/downloads` into `/library`
    (`app/main.py:1013+`), which is why they must be one filesystem.

- **Test-safety fact (critical):** `app/conftest.py` sets
  `os.environ["HISTORY_DB_URL"]` to a file under the system temp dir **before
  any test imports `main`**. That temp directory is writable, so an import-time
  "is the DB dir writable?" check **passes during tests** and does not exit.

**Repo conventions to match:**
- Flat module-level helper functions in `main.py` (see `AGENTS.md:26`). Add the
  new functions near the other helpers; do not create new modules.
- Tests are plain pytest functions doing `import main` — see
  `app/tests/test_helpers.py:1-27`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Syntax check | `python -m py_compile app/main.py` | exit 0 |
| Run tests | `cd app && python -m pytest -q` | all pass (import must NOT exit) |
| Confirm preflight is wired before schema | `grep -n "run_startup_preflight()\|ensure_history_schema()" app/main.py` | preflight call appears immediately before the schema call |

## Scope

**In scope** (the only files you should modify):
- `app/main.py` — add three functions + one call site + warnings in `lifespan`.
- `app/tests/test_preflight.py` — **create** this file.

**Out of scope** (do NOT touch):
- `ensure_history_schema()` and the DB block (that is plan 023's territory).
- **Any torrent-client network/reachability check** — deferred (see Maintenance
  notes). Do not add httpx calls, client logins, or `get_torrent_client()` pings.
- The path constants (`DOWNLOADS_DIR` etc.) and `Settings`.
- Do NOT add an HTTP `/health` (or any) route — see "Why this matters".

## Git workflow

- Branch: `advisor/024-startup-preflight-diagnostics`
- Short imperative commit subject (e.g. `Add startup preflight diagnostics`).
  Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Ensure `import sys` is present

At the top of `app/main.py`, confirm `import sys` is among the imports; if it is
not, add it (it is used for `sys.stderr`).

**Verify**: `grep -n "^import sys" app/main.py` → one match.

### Step 2: Add the two pure checker functions

Add these near the other module-level helpers (e.g. just above
`def ensure_history_schema`). They **only compute and return** — no printing, no
exiting — which is what makes them unit-testable:

```python
from sqlalchemy.engine import make_url  # add to the existing sqlalchemy imports

def db_dir_writable(db_url: str) -> str | None:
    """Return an error message if the SQLite DB's directory is missing or not
    writable, else None. Non-file URLs (e.g. :memory:) return None."""
    try:
        path = make_url(db_url).database
    except Exception:
        return None
    if not path or path == ":memory:":
        return None
    directory = os.path.dirname(path) or "."
    if not os.path.isdir(directory):
        return f"database directory {directory!r} does not exist — mount it and make it writable"
    if not os.access(directory, os.W_OK):
        return (f"database directory {directory!r} is not writable by uid {os.getuid()} "
                f"— chown it to the container's user")
    return None

def hardlink_fs_warning(downloads: str, library: str) -> str | None:
    """Return a warning if downloads and library exist on different filesystems
    (audiobook imports hardlink between them and would fail with EXDEV), else None."""
    try:
        if os.path.isdir(downloads) and os.path.isdir(library):
            if os.stat(downloads).st_dev != os.stat(library).st_dev:
                return (f"{downloads!r} and {library!r} are on different filesystems; "
                        f"audiobook imports hardlink between them and will fail (EXDEV) — "
                        f"put both on one filesystem")
    except OSError:
        return None
    return None
```

If `make_url` is already imported at the top, do not import it twice.

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 3: Add the import-time fatal check and wire it before the schema call

Add this function (right after the checkers):

```python
def run_startup_preflight() -> None:
    """Fatal, actionable checks that must pass before the DB is touched."""
    err = db_dir_writable(HISTORY_DB_URL)
    if err:
        print(f"[preflight] FATAL: {err}", file=sys.stderr)
        raise SystemExit(1)
```

Then, at module scope, change the existing schema call site (`app/main.py:202`)
from:

```python
ensure_history_schema()
```

to:

```python
run_startup_preflight()
ensure_history_schema()
```

Why this is test-safe: in tests, `HISTORY_DB_URL` points at a **writable** temp
dir (conftest), so `db_dir_writable` returns `None` and `run_startup_preflight`
does **not** exit. In production with an unwritable `/data`, it prints one line
and exits 1 *before* the SQLAlchemy traceback.

**Verify**:
- `grep -n "run_startup_preflight()" app/main.py` → the call sits immediately
  before `ensure_history_schema()`.
- `cd app && python -m pytest -q` → still collects and passes (import did not exit).

### Step 4: Add non-fatal filesystem warnings to `lifespan`

The hardlink/library checks are **warnings, never fatal**, and belong in the
lifespan startup (which only runs when the ASGI server actually boots — so it
never fires during the unit tests, which import symbols without starting the
server). Edit `lifespan` (`app/main.py:242`) to add the warnings before
`reconcile_auto_import_task()`:

```python
async def lifespan(app: FastAPI):
    warn = hardlink_fs_warning(settings.DOWNLOADS_DIR, settings.LIBRARY_DIR)
    if warn:
        print(f"[preflight] WARNING: {warn}", file=sys.stderr)
    for d in (settings.LIBRARY_DIR, settings.EBOOKS_DIR, settings.EBOOKS_NOSEND_DIR):
        if not os.path.isdir(d):
            print(f"[preflight] WARNING: library directory {d!r} does not exist yet "
                  f"— imports there will fail until it is mounted/created", file=sys.stderr)
    await reconcile_auto_import_task()
    try:
        yield
    finally:
        await stop_auto_import_task()
```

Keep the existing `yield` / `finally` body exactly as-is; only prepend the
warning block.

**Verify**: `python -m py_compile app/main.py` → exit 0; `cd app && python -m pytest -q` → all pass.

## Test plan

Create `app/tests/test_preflight.py`. Test only the **pure** functions — never
call `run_startup_preflight()` in a way that could `SystemExit` the test process.

```python
import os

import main


def test_db_dir_writable_ok_for_temp(tmp_path):
    url = f"sqlite:///{tmp_path}/history.db"
    assert main.db_dir_writable(url) is None


def test_db_dir_writable_flags_missing_dir():
    url = "sqlite:////nonexistent-xyz/history.db"
    msg = main.db_dir_writable(url)
    assert msg and "does not exist" in msg


def test_db_dir_writable_ignores_memory():
    assert main.db_dir_writable("sqlite://") is None


def test_hardlink_fs_warning_none_when_same_dir(tmp_path):
    d = str(tmp_path)
    assert main.hardlink_fs_warning(d, d) is None


def test_hardlink_fs_warning_none_when_dirs_absent():
    assert main.hardlink_fs_warning("/no/such/a", "/no/such/b") is None
```

- Structural pattern: `app/tests/test_helpers.py`.
- Verification: `cd app && python -m pytest -q` → all pass, 5 new tests.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "def db_dir_writable\|def hardlink_fs_warning\|def run_startup_preflight" app/main.py` → three matches
- [ ] `run_startup_preflight()` is called immediately before `ensure_history_schema()` at module scope
- [ ] `lifespan` prints the hardlink/library warnings before `reconcile_auto_import_task()`
- [ ] `python -m py_compile app/main.py` → exit 0
- [ ] `cd app && python -m pytest -q` → all pass; `app/tests/test_preflight.py` exists with 5 tests; **the test run does not exit early** (proves the import-time preflight is test-safe)
- [ ] `git status --porcelain` shows only `app/main.py` and new `app/tests/test_preflight.py`
- [ ] `plans/README.md` status row for 024 updated

## STOP conditions

Stop and report back (do not improvise) if:

- After wiring Step 3, `cd app && python -m pytest -q` fails to **collect** or
  the process exits with code 1 during import — that means the import-time
  preflight is exiting during tests (it must not). Report before touching
  conftest or the checkers.
- `lifespan` no longer matches the excerpt (e.g. it was converted away from an
  async generator) — the codebase drifted; report it.
- You find yourself needing to add a torrent-client network check to satisfy a
  criterion — that is explicitly out of scope; stop.
- `make_url` cannot be imported from `sqlalchemy.engine` in this SQLAlchemy
  version — report the version; do not hand-parse the URL.

## Maintenance notes

- **Deferred follow-up (intentionally not in this plan):** a torrent-client
  reachability check (ping Transmission's session RPC / qBittorrent's
  `/api/v2/app/version` at startup and warn if unreachable). It needs per-client
  async health calls and belongs in its own plan; this one stays synchronous and
  dependency-free.
- If new required host paths are added later, extend the `lifespan` warning loop.
- A reviewer should confirm: the only **fatal** check is DB-dir writability;
  everything else warns; and nothing here adds an HTTP endpoint (the `/health`
  route was deliberately removed — see `plans/005`).
- If plan 023 (guarded migrations) also lands, order does not matter, but both
  edit the module-scope region around line 202 — expect a trivial merge there.
