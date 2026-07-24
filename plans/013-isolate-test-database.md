# Plan 013: The test suite can never touch a real history database

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **IMPORTANT — which commit this applies to**: this plan targets the code on
> branch `advisor/plans-001-012` (tip `57c0af6`), **not** `master` (`f8d3d32`).
> The file it fixes, `app/conftest.py`, does not exist on `master`. Check out or
> base your work on that branch.
>
> **Drift check (run first)**: `git diff --stat 57c0af6..HEAD -- app/conftest.py app/main.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (plans 001 and 012 are already landed on the target branch)
- **Category**: bug
- **Planned at**: commit `57c0af6` (branch `advisor/plans-001-012`), 2026-07-24

## Why this matters

Running `pytest` can silently mutate a **real** history database.

`app/conftest.py` points the test suite at a temp SQLite file using
`os.environ.setdefault`. `setdefault` only assigns when the variable is *absent*.
`HISTORY_DB_URL` is a documented, first-class configuration knob, so a developer
who has it exported — pointing at their live `/data/history.db`, a bind-mounted
path, or a staging copy — gets **that** database when they run the tests.

That alone would be bad. It is worse because `app/main.py` calls
`ensure_history_schema()` at **module scope**, and that function now performs a
data-mutating `UPDATE`:

```sql
UPDATE history
SET torrent_status = 'added', status_detail = NULL, status_updated_at = datetime('now')
WHERE torrent_status = 'importing'
```

So merely **importing** `main` rewrites rows. This was demonstrated against a
seeded database: a row in `importing` was reset to `added` by

```
pytest --collect-only
```

with **no test body ever executing** — collection imports `main`, and that is
enough.

Consequence in a live deployment: an import that is genuinely in flight has its
row reset to `added` while the real import continues. The auto-import poller
then treats it as a fresh candidate and can import the same torrent a second
time, producing a duplicate library folder (`Title (2)`).

This is an *emergent* defect. Neither contributing change is wrong alone — one
introduced the env knob and the `setdefault`, the other made the schema function
mutate data. It only appears when both are present, which is why per-change
review did not surface it.

## Current state

- `app/conftest.py` — the complete file:
  ```python
  import os
  import tempfile
  import pathlib

  # main.py raises at import if MAM_COOKIE is unset, and opens a SQLite DB at
  # import time. Provide safe test values before any test imports `main`.
  os.environ.setdefault("MAM_COOKIE", "test-cookie")
  _test_db = pathlib.Path(tempfile.gettempdir()) / "mam_audiofinder_test_history.db"
  os.environ.setdefault("HISTORY_DB_URL", f"sqlite:///{_test_db}")
  ```
  The `HISTORY_DB_URL` line is the dangerous one.

- `app/main.py` — the engine reads that variable at import:
  ```python
  # /data should be a volume/bind mount. Override with HISTORY_DB_URL for tests.
  HISTORY_DB_URL = os.getenv("HISTORY_DB_URL", "sqlite:////data/history.db")
  engine = create_engine(HISTORY_DB_URL, future=True)
  ```

- `app/main.py` — `ensure_history_schema()` is invoked at module scope (a bare
  `ensure_history_schema()` call directly after the function definition), and its
  final statement is the mutating `UPDATE ... WHERE torrent_status = 'importing'`
  quoted above.

- Conventions: Python 4-space indent, `snake_case`. The test suite lives in
  `app/tests/test_helpers.py` and is run as `cd app && python -m pytest -q`
  (19 tests currently pass).

## Commands you will need

| Purpose       | Command                                       | Expected on success |
|---------------|-----------------------------------------------|---------------------|
| Run tests     | `cd app && python -m pytest -q`               | 19+ pass, exit 0    |
| Syntax check  | `python3 -m py_compile app/main.py`           | exit 0              |

There is no virtualenv in a fresh checkout. Create one **outside** the repo,
install `requirements.txt` + `requirements-dev.txt`, and invoke its interpreter
explicitly.

## Scope

**In scope** (the only files you should modify):
- `app/conftest.py` — force the test database instead of defaulting it.
- `app/tests/test_helpers.py` — add one guard test.

**Out of scope** (do NOT touch):
- `app/main.py` — do **not** change `ensure_history_schema`, the module-scope
  call, or the engine setup. The mutating `UPDATE` is intentional (it is how a
  crashed import recovers on restart); the defect is that tests can aim it at
  the wrong database, not the statement itself.
- The `MAM_COOKIE` line's `setdefault` — leave it. A real cookie in the
  environment is harmless here: no test performs network I/O.
- Do **not** add a pytest plugin, fixture framework, or `pytest.ini`. Keep the
  existing flat `conftest.py` approach.

## Git workflow

- Work on a branch based on `advisor/plans-001-012`.
- Single commit; present-tense message with no prefix, matching `git log`
  (e.g. `Force tests onto an isolated history database`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Force the test database

In `app/conftest.py`, change the `HISTORY_DB_URL` line from `setdefault` to an
unconditional assignment:

```python
import os
import tempfile
import pathlib

# main.py raises at import if MAM_COOKIE is unset, and opens a SQLite DB at
# import time. Provide safe test values before any test imports `main`.
os.environ.setdefault("MAM_COOKIE", "test-cookie")

# Always OVERRIDE the database URL — never setdefault. `main` runs
# ensure_history_schema() at import, which mutates rows, so an inherited
# HISTORY_DB_URL would let a test run rewrite a real database.
_test_db = pathlib.Path(tempfile.gettempdir()) / "mam_audiofinder_test_history.db"
os.environ["HISTORY_DB_URL"] = f"sqlite:///{_test_db}"
```

Only that one line changes from `setdefault(...)` to `[...] = ...`; the comment
above it explains why, so a future reader does not "tidy" it back.

**Verify**: `grep -n "HISTORY_DB_URL" app/conftest.py` shows an assignment
(`os.environ["HISTORY_DB_URL"] =`), and **no** `setdefault` on that variable.

### Step 2: Add a guard test

Append to `app/tests/test_helpers.py`:

```python
def test_engine_is_pointed_at_a_temp_database():
    # conftest must FORCE the test DB. If this ever regresses to setdefault, a
    # developer with HISTORY_DB_URL exported would have the suite mutate their
    # real database at import time (ensure_history_schema rewrites rows).
    import tempfile

    url = str(main.engine.url)
    assert tempfile.gettempdir() in url
    assert "/data/history.db" not in url
```

(`main` is already imported at the top of the file.)

**Verify**: `cd app && python -m pytest -q` → all pass, including the new test.

### Step 3: Prove the fix against a hostile environment

This is the criterion that actually matters — it reproduces the original defect
and confirms it is gone. Run it from the repo root, substituting a scratch path
for `<TMP>`:

```bash
# 1. Build a "production" database with an in-flight import
cd app && MAM_COOKIE=x HISTORY_DB_URL="sqlite:///<TMP>/prod.db" python -c "
import main
from sqlalchemy import text
with main.engine.begin() as cx:
    cx.execute(text(\"INSERT INTO history (title,author,torrent_status,torrent_hash) VALUES ('T','A','importing','LIVE1')\"))
print('seeded')
"

# 2. Run the suite with that variable still exported
cd app && HISTORY_DB_URL="sqlite:///<TMP>/prod.db" MAM_COOKIE=x python -m pytest -q

# 3. The seeded row must still say 'importing'.
#    CRITICAL: this check must NOT import `main`. Importing it runs
#    ensure_history_schema() against this very database, which performs the
#    'importing' -> 'added' reset — i.e. the check would cause the mutation it
#    is testing for the absence of, and print 'added' even when the fix works.
#    Read the row with a bare engine instead:
python -c "
from sqlalchemy import create_engine, text
e = create_engine('sqlite:///<TMP>/prod.db')
with e.begin() as cx:
    print(cx.execute(text(\"SELECT torrent_status FROM history WHERE torrent_hash='LIVE1'\")).scalar())
"
# (equivalently, if the sqlite3 CLI is available:
#  sqlite3 <TMP>/prod.db "SELECT torrent_status FROM history WHERE torrent_hash='LIVE1'")
```

**Verify**: step 3 prints `importing`. Before this plan it printed `added`.

Two deliberate subtleties:

- Step 1 **does** import `main` — that is fine and necessary: it creates the
  schema, the reset is a no-op on a database with no `importing` rows yet, and
  the `INSERT` happens afterwards.
- Step 3 must **not** import `main`, for the reason in the comment above. This
  was found the hard way: an earlier revision of this plan used `import main` in
  step 3 and was structurally unable to ever print `importing`, in both the fixed
  and unfixed states.

If step 1 fails to seed the row, your command is wrong — not the fix.

## Test plan

- New test `test_engine_is_pointed_at_a_temp_database` in
  `app/tests/test_helpers.py`: asserts `main.engine.url` resolves inside the
  system temp directory and is not the production `/data/history.db` path.
  Model after the existing helper tests in that file.
- The Step 3 hostile-environment reproduction is the real regression gate; it
  cannot be expressed as a unit test because the danger occurs at interpreter
  start, before any test runs.
- Verification: `cd app && python -m pytest -q` → all pass (20 tests: 19
  inherited + 1 new).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'os.environ\["HISTORY_DB_URL"\]' app/conftest.py` returns one match
- [ ] `grep -n 'setdefault("HISTORY_DB_URL"' app/conftest.py` returns **no** matches
- [ ] `cd app && python -m pytest -q` exits 0 with 20 tests passing
- [ ] Step 3's reproduction prints `importing` (not `added`) — using the **bare-engine** reader, not one that imports `main`
- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `git status` shows only `app/conftest.py` and `app/tests/test_helpers.py` modified
- [ ] `plans/README.md` status row for 013 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `app/conftest.py` does not exist — you are on `master`, not
  `advisor/plans-001-012`. Re-base onto that branch.
- The `ensure_history_schema` mutating `UPDATE` is absent from `app/main.py` —
  the branch is not the one this plan was written against; reconcile first.
- Step 3 still prints `added` after the change. First confirm your reader does
  **not** import `main` (see Step 3's comment — importing it re-triggers the
  reset and invalidates the check). If the reader is bare and it still prints
  `added`, then `conftest.py` is not being loaded — pytest must run from `app/`.
  Report the directory you ran from rather than editing `main.py` to compensate.
- Any existing test fails after the change. The forced override should be
  invisible to them; a failure means something depended on inheriting the
  variable, which is exactly the coupling being removed. Report it.

## Maintenance notes

- The rule this encodes: **`conftest.py` must force every environment variable
  that selects a data store, never `setdefault` it.** If a future variable is
  added that picks a database, cache, or output directory, force it too.
- Reviewer should confirm `MAM_COOKIE` kept `setdefault` (deliberate) while
  `HISTORY_DB_URL` did not, and that `app/main.py` was not touched.
- Deferred, not required here: giving each test run a unique database file
  (`tempfile.mkdtemp()`) so concurrent or interrupted runs cannot share state.
  The current shared temp file is fine because the one DB-touching test cleans
  up in a `finally` block.
