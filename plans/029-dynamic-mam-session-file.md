# Plan 029: Optionally read the MAM cookie from a file (mamapi handoff)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 4ec80a1..HEAD -- app/main.py app/tests/ README.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S-M
- **Risk**: LOW — additive; defaults to today's behavior when the new env var is unset
- **Depends on**: none
- **Category**: dx / feature (deployment resilience)
- **Planned at**: commit `4ec80a1`, 2026-07-30

## Why this matters

The app reads the MAM session cookie **once at startup** from the `MAM_COOKIE`
env var. MyAnonamouse sessions are IP-locked, and deployments behind a rotating
VPN commonly run a helper (e.g. **mamapi**) that refreshes the current `mam_id`
and writes it to a file whenever the exit IP changes. Because this app holds a
static value, a refreshed session isn't picked up until the container is
restarted. This adds an optional `MAM_ID_FILE`: when set, the cookie is read from
that file **per request** (so an external updater's changes take effect live),
falling back to the static `MAM_COOKIE`. When `MAM_ID_FILE` is unset, behavior is
exactly as today.

## Current state

`app/main.py`, single-file FastAPI app. `from pathlib import Path` is already
imported at the top.

- Cookie normalization helper (`app/main.py:73-83`):
  ```python
  def build_mam_cookie(raw: str) -> str:
      raw = (raw or "").strip()
      if not raw:
          return ""
      if "mam_id=" in raw or "mam_session=" in raw:
          return raw
      if raw and "=" not in raw and ";" not in raw:
          return f"mam_id={raw}"
      return raw
  ```
  (Handles both a full cookie header and a bare token — reuse it for file contents.)

- `Settings.__init__` reads and requires the cookie (`app/main.py:100-102`):
  ```python
          self.MAM_COOKIE = build_mam_cookie(os.getenv("MAM_COOKIE", ""))
          if not self.MAM_COOKIE:
              raise RuntimeError("MAM_COOKIE environment variable is required and must be set to a non-empty value")
  ```

- `mam_headers()` uses the static cookie (`app/main.py:254-256`):
  ```python
  def mam_headers(*, torrent: bool = False) -> dict:
      headers = {
          "Cookie": settings.MAM_COOKIE,
          ...
  ```
  `settings = Settings()` is created at module scope (around `app/main.py:130`),
  so any helper referencing the global `settings` must be defined **after** that.

- **Test-safety fact:** `app/conftest.py` sets `MAM_COOKIE=test-cookie` and does
  **not** set `MAM_ID_FILE`, so the fallback path (static cookie) is what runs in
  tests unless a test explicitly sets `MAM_ID_FILE`.

- `README.md` has an environment-variable table; the current last row is the
  `PORT` row:
  ```markdown
  | `PORT` | Port the app listens on inside the container (default `8080`); set this to avoid a clash when sharing another container's network namespace |
  ```

**Repo conventions:** flat helpers in `main.py`; tests are plain pytest functions
(`import main`) — see `app/tests/test_helpers.py:1-27`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Syntax check | `python -m py_compile app/main.py` | exit 0 |
| Run tests | `cd app && python -m pytest -q` | all pass (incl. new tests) |
| Confirm helper + wiring | `grep -n "MAM_ID_FILE\|def current_mam_cookie" app/main.py` | Settings read + helper + used in mam_headers |

## Scope

**In scope** (only files you may modify):
- `app/main.py` — add `MAM_ID_FILE` to `Settings`, relax the required check, add
  `current_mam_cookie()`, use it in `mam_headers()`.
- `app/tests/test_mam_session.py` — **create**.
- `README.md` — add one env-table row for `MAM_ID_FILE`.

**Out of scope** (do NOT touch):
- `build_mam_cookie` itself — reuse it, don't change it.
- Any other request path or the torrent-client code.
- Do NOT add file watching, caching, or a background reload thread — a plain
  per-request read of a tiny file is intentional and sufficient.

## Git workflow

- Branch: `advisor/029-dynamic-mam-session-file`
- Short imperative commit subject. Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add `MAM_ID_FILE` to `Settings` and relax the required check

Replace the two lines at `app/main.py:100-102` with:

```python
        self.MAM_COOKIE = build_mam_cookie(os.getenv("MAM_COOKIE", ""))
        self.MAM_ID_FILE = os.getenv("MAM_ID_FILE", "").strip()
        if not self.MAM_COOKIE and not self.MAM_ID_FILE:
            raise RuntimeError(
                "Set MAM_COOKIE (a MAM session cookie) or MAM_ID_FILE (path to a "
                "file containing the current mam_id, e.g. written by mamapi)"
            )
```

**Verify**: `grep -n "MAM_ID_FILE" app/main.py` → the Settings read; `python -m py_compile app/main.py` → exit 0.

### Step 2: Add the `current_mam_cookie()` helper

Add this **after** `settings = Settings()` and before `mam_headers` (e.g.
directly above `def mam_headers`):

```python
def current_mam_cookie() -> str:
    """The MAM cookie for outgoing requests. If MAM_ID_FILE is set and readable,
    its contents (normalized via build_mam_cookie) are used, so an external
    updater like mamapi can refresh the session without restarting this app.
    Falls back to the static MAM_COOKIE."""
    if settings.MAM_ID_FILE:
        try:
            raw = Path(settings.MAM_ID_FILE).read_text().strip()
        except OSError:
            raw = ""
        if raw:
            return build_mam_cookie(raw)
    return settings.MAM_COOKIE
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 3: Use it in `mam_headers()`

In `mam_headers()` change the `Cookie` line only:

```python
        "Cookie": current_mam_cookie(),
```

**Verify**: `grep -n "current_mam_cookie()" app/main.py` → the definition + its use in `mam_headers`.

### Step 4: Document `MAM_ID_FILE` in the README

In `README.md`, add one row to the environment-variable table, immediately after
the `PORT` row:

```markdown
| `MAM_ID_FILE` | Optional path to a file holding the current `mam_id` (e.g. written by [mamapi](https://github.com/elforkhead/mamapi)); read per request so a rotating session stays valid without a restart. Falls back to `MAM_COOKIE`. |
```

**Verify**: `grep -n "MAM_ID_FILE" README.md` → one match in the table.

### Step 5: Tests

Create `app/tests/test_mam_session.py`:

```python
import pytest

import main


def test_current_mam_cookie_uses_static_when_no_file():
    # conftest sets MAM_COOKIE and no MAM_ID_FILE
    assert main.settings.MAM_ID_FILE == ""
    assert main.current_mam_cookie() == main.settings.MAM_COOKIE


def test_current_mam_cookie_reads_and_wraps_file(monkeypatch, tmp_path):
    f = tmp_path / "mamid"
    f.write_text("bareToken123\n")
    monkeypatch.setattr(main.settings, "MAM_ID_FILE", str(f))
    assert main.current_mam_cookie() == "mam_id=bareToken123"


def test_current_mam_cookie_falls_back_when_file_missing(monkeypatch):
    monkeypatch.setattr(main.settings, "MAM_ID_FILE", "/no/such/mamid-file")
    assert main.current_mam_cookie() == main.settings.MAM_COOKIE


def test_settings_accepts_file_without_cookie(monkeypatch):
    monkeypatch.setenv("MAM_COOKIE", "")
    monkeypatch.setenv("MAM_ID_FILE", "/some/path")
    s = main.Settings()          # must not raise
    assert s.MAM_ID_FILE == "/some/path"


def test_settings_requires_cookie_or_file(monkeypatch):
    monkeypatch.setenv("MAM_COOKIE", "")
    monkeypatch.delenv("MAM_ID_FILE", raising=False)
    with pytest.raises(RuntimeError):
        main.Settings()
```

**Verify**: `cd app && python -m pytest -q` → all pass, 5 new tests.

## Test plan

- New file `app/tests/test_mam_session.py`: static fallback (default), file read
  + wrap of a bare token, fallback when the file is missing, and the relaxed
  startup validation (accepts `MAM_ID_FILE` alone; still rejects neither).
- Structural pattern: `app/tests/test_helpers.py`.
- Verification: `cd app && python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "self.MAM_ID_FILE = os.getenv" app/main.py` → one match
- [ ] `grep -n "def current_mam_cookie" app/main.py` → one match; used in `mam_headers` (the `Cookie` value is `current_mam_cookie()`, not `settings.MAM_COOKIE`)
- [ ] `grep -n "MAM_ID_FILE" README.md` → one match (table row)
- [ ] `python -m py_compile app/main.py` → exit 0
- [ ] `cd app && python -m pytest -q` → all pass; `app/tests/test_mam_session.py` exists with 5 tests
- [ ] `git status --porcelain` shows only `app/main.py`, `README.md`, and new `app/tests/test_mam_session.py`
- [ ] `plans/README.md` row for 029 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `Settings.__init__` / `mam_headers` / `build_mam_cookie` don't match the
  "Current state" excerpts (drift).
- Any existing test fails after Step 3 — the static-fallback path must keep
  behaving exactly as before when `MAM_ID_FILE` is unset; if something breaks,
  stop and report.
- `Path` is somehow not imported at the top of `app/main.py` (the excerpt says it
  is) — report rather than adding an import outside the shown edits.

## Maintenance notes

- The file is read on every MAM request. It's tiny (one line), so this is
  negligible for a single-user app; do not add caching without a measured need.
- If MAM ever changes what mamapi writes (format), `build_mam_cookie` already
  handles both a bare token and a full `mam_id=…` header — keep that dual
  handling.
- Reviewer: confirm the unset-`MAM_ID_FILE` path is byte-identical in behavior to
  before (static cookie), and that a missing/unreadable file falls back rather
  than raising mid-request.
