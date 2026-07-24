# Plan 001: A one-command test suite exists and CI runs it on every push/PR

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 92761c0..HEAD -- app/main.py .github/workflows/docker-publish.yml requirements.txt`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (this plan unblocks 003 and 004)
- **Category**: tests
- **Planned at**: commit `92761c0`, 2026-07-22

## Why this matters

This repo has **zero automated tests** and its CI only builds a Docker image —
it never imports or runs the app, so a syntax error or broken import in
`app/main.py` ships to `main` and only surfaces at container runtime.
`AGENTS.md` even states "There is no formal test suite yet" and tells
contributors to test by hand. Every other improvement plan (path-traversal
hardening, API modernization) is riskier to execute without a way to know the
code still works. This plan creates a fast, dependency-light `pytest` suite for
the pure helper functions and wires it into CI as a gate. After this lands,
`cd app && python -m pytest` is the one command that answers "did I break
anything."

## Current state

Facts the executor needs, inlined:

- `app/main.py` is a single-file FastAPI app (905 lines). It has **import-time
  side effects** that will break a naive `import main`:
  1. `Settings.__init__` **raises** if `MAM_COOKIE` is unset:
     ```python
     # app/main.py:59-64
     class Settings:
         def __init__(self) -> None:
             self.MAM_BASE = DEFAULT_MAM_BASE
             self.MAM_COOKIE = build_mam_cookie(os.getenv("MAM_COOKIE", ""))
             if not self.MAM_COOKIE:
                 raise RuntimeError("MAM_COOKIE environment variable is required and must be set to a non-empty value")
     ```
  2. The DB engine path is **hardcoded** to `/data/history.db`, and
     `ensure_history_schema()` runs at import — it needs a writable DB:
     ```python
     # app/main.py:87-89
     # /data should be a volume/bind mount
     engine = create_engine("sqlite:////data/history.db", future=True)
     ...
     # app/main.py:141
     ensure_history_schema()
     ```
  3. `StaticFiles`/`Jinja2Templates` use **relative** directories, so `main`
     can only be imported with the current working directory set to `app/`:
     ```python
     # app/main.py:184-185
     app.mount("/static", StaticFiles(directory="static"), name="static")
     templates = Jinja2Templates(directory="templates")
     ```
     (`StaticFiles` raises `RuntimeError: Directory 'static' does not exist` if
     the cwd is not `app/`.)

- The pure, side-effect-free helper functions this plan will test (all at
  module scope, importable once the two blockers above are handled):
  - `is_truthy(value)` — `app/main.py:34`
  - `build_mam_cookie(raw)` — `app/main.py:39`
  - `normalize_media_type(value)` — `app/main.py:51` (raises `HTTPException` on bad input)
  - `sanitize(name)` — `app/main.py:593`
  - `next_available(path)` — `app/main.py:597`
  - `validate_download_path(p)` — `app/main.py:736` (raises `HTTPException` when path escapes `/downloads`)
  - `transmission_labels(mam_id, media_type, send_to_kindle)` — `app/main.py:329`
  - `clean_status_detail(detail)` — `app/main.py:639`
  - `torrent_hash_from_add_result(args)` — `app/main.py:346`

- CI today is build-only:
  ```yaml
  # .github/workflows/docker-publish.yml:18-27 (abridged)
  jobs:
    docker:
      runs-on: ubuntu-latest
      permissions:
        contents: write
        packages: write
      steps:
        - name: Checkout repository
          uses: actions/checkout@v4
  ```

- Repo conventions (from `AGENTS.md`): Python 4-space indent, `snake_case`
  functions, `CamelCase` classes, "keep modules small and flat; prefer helpers
  in `main.py`". New dependencies must be justified — this plan adds `pytest`
  as a **dev-only** dependency in a **new** `requirements-dev.txt` so the
  runtime image (`Dockerfile` installs `requirements.txt` only) stays lean.
- Commit message style (from `git log`): short, present-tense, no
  conventional-commit prefixes — e.g. `Add retry action for failed imports`,
  `Limit FL wedges to audiobooks`.

## Commands you will need

| Purpose             | Command                                             | Expected on success            |
|---------------------|-----------------------------------------------------|--------------------------------|
| Syntax check        | `python3 -m py_compile app/main.py`                 | exit 0, no output              |
| Install dev deps    | `pip install -r requirements-dev.txt`               | exit 0                         |
| Run tests           | `cd app && python -m pytest -q`                     | all pass, exit 0               |
| (CI) install app    | `pip install -r requirements.txt`                   | exit 0                         |

Python is 3.11 locally and the Docker base image is `python:3.12-slim` — write
code compatible with both.

## Scope

**In scope** (the only files you should create or modify):
- `requirements-dev.txt` (create)
- `app/conftest.py` (create)
- `app/tests/__init__.py` (create, empty)
- `app/tests/test_helpers.py` (create)
- `app/main.py` (ONE line changed — the DB URL becomes env-configurable; see Step 1)
- `.github/workflows/docker-publish.yml` (add a `test` job)

**Out of scope** (do NOT touch, even though they look related):
- Any behavior change to endpoints, import logic, or the auto-import loop — this
  plan only *adds* tests and one backward-compatible config hook.
- Do NOT extract `flatten`/`detect_format` (nested inside `search`,
  `app/main.py:240-275`) — they are not importable; testing them is deferred to
  a future plan. Leave them where they are.
- Do NOT change the default DB path or any runtime default value.

## Git workflow

- Branch: `advisor/001-verification-baseline` (or the repo's convention if one is evident).
- Commit per logical unit; present-tense messages (e.g. `Add pytest suite for pure helpers`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Make the history DB URL env-configurable (backward-compatible)

In `app/main.py`, replace the hardcoded engine line so tests can point it at a
temp database. Default behavior is unchanged.

Current (`app/main.py:87-89`):
```python
# /data should be a volume/bind mount
engine = create_engine("sqlite:////data/history.db", future=True)
```

Change to:
```python
# /data should be a volume/bind mount. Override with HISTORY_DB_URL for tests.
HISTORY_DB_URL = os.getenv("HISTORY_DB_URL", "sqlite:////data/history.db")
engine = create_engine(HISTORY_DB_URL, future=True)
```

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 2: Add the dev requirements file

Create `requirements-dev.txt`:
```
pytest
```
(Pin it if plan 002 has already landed and pinned the runtime deps — match that
style, e.g. `pytest==8.*`. Otherwise leave unpinned to match the current
`requirements.txt`.)

**Verify**: `pip install -r requirements-dev.txt` → exit 0.

### Step 3: Add `app/conftest.py` to neutralize import-time side effects

Create `app/conftest.py`. It must set the two required env vars **before** any
test imports `main`. pytest imports `conftest.py` before collecting tests, so
this runs first.
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

### Step 4: Add the test package and tests

Create empty `app/tests/__init__.py`.

Create `app/tests/test_helpers.py`. Import `main` at module top (works because
pytest is run from `app/`, putting `app/` on `sys.path`, and conftest has set
the env). Cover happy paths, the specific behaviors, and the raising cases:
```python
import pytest
from fastapi import HTTPException

import main


def test_is_truthy():
    assert main.is_truthy(True) is True
    assert main.is_truthy("yes") is True
    assert main.is_truthy("ON") is True
    assert main.is_truthy("0") is False
    assert main.is_truthy("no") is False
    assert main.is_truthy(None) is False


def test_build_mam_cookie_passthrough_and_wrap():
    assert main.build_mam_cookie("mam_id=abc; other=1") == "mam_id=abc; other=1"
    assert main.build_mam_cookie("bareToken") == "mam_id=bareToken"
    assert main.build_mam_cookie("  ") == ""


def test_normalize_media_type():
    assert main.normalize_media_type("audiobooks") == main.MEDIA_TYPE_AUDIOBOOK
    assert main.normalize_media_type("E-Book") == main.MEDIA_TYPE_EBOOK
    assert main.normalize_media_type(None) == main.MEDIA_TYPE_AUDIOBOOK
    with pytest.raises(HTTPException):
        main.normalize_media_type("magazine")


def test_sanitize_strips_separators():
    assert "/" not in main.sanitize("a/b")
    assert "\\" not in main.sanitize("a\\b")
    assert main.sanitize("  ") == "Unknown"
    assert main.sanitize("Title: Subtitle") == "Title - Subtitle"


def test_next_available(tmp_path):
    p = tmp_path / "Book"
    assert main.next_available(p) == p  # does not exist yet
    p.mkdir()
    assert main.next_available(p) == tmp_path / "Book (2)"


def test_validate_download_path():
    assert main.validate_download_path("/downloads/x") == "/downloads/x"
    assert main.validate_download_path("") == ""
    with pytest.raises(HTTPException):
        main.validate_download_path("/etc")


def test_transmission_labels():
    labels = main.transmission_labels("123", main.MEDIA_TYPE_EBOOK, send_to_kindle=False)
    assert main.settings.TRANSMISSION_LABEL in labels
    assert "mamid=123" in labels
    assert main.TRANSMISSION_NOSEND_LABEL in labels
    # audiobook never gets the nosend label
    assert main.TRANSMISSION_NOSEND_LABEL not in main.transmission_labels("1", main.MEDIA_TYPE_AUDIOBOOK, False)


def test_clean_status_detail():
    assert main.clean_status_detail("  a\n\n b ") == "a b"
    assert main.clean_status_detail("") is None
    assert len(main.clean_status_detail("x" * 999)) == 500


def test_torrent_hash_from_add_result():
    assert main.torrent_hash_from_add_result({"torrent-added": {"hashString": "AB"}}) == "AB"
    assert main.torrent_hash_from_add_result({"torrent-duplicate": {"hashString": "CD"}}) == "CD"
    assert main.torrent_hash_from_add_result({}) is None
```

**Verify**: `cd app && python -m pytest -q` → all tests pass (9 tests), exit 0.

### Step 5: Add a `test` job to CI

Edit `.github/workflows/docker-publish.yml`. Add a new job **above** `docker`
and make `docker` depend on it so a red test blocks publishing. Insert this
under `jobs:` (before the existing `docker:` job):
```yaml
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      - name: Syntax check
        run: python -m py_compile app/main.py
      - name: Run tests
        run: cd app && python -m pytest -q
```
Then add `needs: test` to the `docker` job (as the first key under `docker:`,
alongside `runs-on`):
```yaml
  docker:
    needs: test
    runs-on: ubuntu-latest
```

**Verify**: the file is valid YAML —
`python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docker-publish.yml')); print('yaml ok')"`
→ prints `yaml ok`. (If PyYAML is not installed, `pip install pyyaml` first; it
is not a project dependency, only a local check.)

## Test plan

- New file `app/tests/test_helpers.py` with the 9 tests above: happy paths plus
  the two `HTTPException`-raising cases (`normalize_media_type`,
  `validate_download_path`) and the 500-char truncation edge in
  `clean_status_detail`.
- There is no existing test to model after (this is the first suite); follow the
  structure shown in Step 4.
- Verification: `cd app && python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `cd app && python -m pytest -q` exits 0 with all tests passing
- [ ] `requirements-dev.txt`, `app/conftest.py`, `app/tests/__init__.py`, `app/tests/test_helpers.py` exist
- [ ] `.github/workflows/docker-publish.yml` contains a `test:` job and the `docker:` job has `needs: test`
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row for 001 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `cd app && python -m pytest -q` fails at **collection/import** with
  `RuntimeError: Directory 'static' does not exist` or a `MAM_COOKIE` /
  database error — this means the cwd or `conftest.py` env setup is wrong; do
  not "fix" it by editing endpoint or settings code.
- The `app/main.py:87-89` excerpt does not match the live code (the DB line was
  already changed) — reconcile before editing.
- A test assertion fails because a helper behaves differently than documented
  here — the code may have drifted; report the actual behavior rather than
  rewriting the assertion to pass.

## Maintenance notes

- When new pure helpers are added to `main.py`, add tests here — this suite is
  the regression net that plans 003 and 004 rely on.
- Follow-up deferred: `flatten` and `detect_format` (nested inside `search`)
  and the DB-touching / HTTP-calling paths (`import_torrent_to_library`,
  Transmission RPC) are untested. Testing them well needs either extraction to
  module scope or FastAPI `TestClient` with mocked `httpx` — out of scope here
  to keep this plan low-risk.
- Reviewer should confirm the CI `test` job actually gates `docker`
  (`needs: test`) and that `requirements-dev.txt` is not accidentally added to
  the Docker image build.
