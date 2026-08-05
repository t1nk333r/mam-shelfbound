# Plan 033: Trigger a media-server library scan after a successful import

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f587737..HEAD -- app/main.py README.md`
> If `app/main.py` or `README.md` changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (touches the same function `mark_history_imported` as plan 034; if both land, expect a trivial merge — see Maintenance notes)
- **Category**: direction
- **Planned at**: commit `f587737`, 2026-08-04

## Why this matters

When an audiobook/ebook finishes importing, the app hardlinks/copies it into
`/library` (or `/ebooks*`) and stops there — `mark_history_imported` just flips
the DB row to `imported` and logs (`app/main.py:965`, `:1221`). Nothing tells the
downstream media server (Audiobookshelf, Calibre-Web, Plex, …) that a new book
arrived, so it doesn't appear until that server's own scheduled scan runs — often
hours later. This plan adds an **optional, fire-and-forget scan trigger**: when an
import succeeds, POST to a user-configured URL (with an optional auth header) so
the media server rescans immediately. It reuses the exact fire-and-forget pattern
plan 017 built for failure notifications, adds no dependency, and is a no-op unless
the user sets the URL.

## Current state

- `app/main.py` — single-file FastAPI app. Relevant regions:
  - **`Settings.__init__`** parses all env config. The failure-notification knob
    is the model to copy (`app/main.py:123-124`):
    ```python
    self.NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    self.NOTIFY_TIMEOUT = DEFAULT_NOTIFY_TIMEOUT
    ```
    `DEFAULT_NOTIFY_TIMEOUT = 10` is defined at `app/main.py:29`.
  - **The fire-and-forget notification helpers** — copy this shape exactly
    (`app/main.py:989-1026`):
    ```python
    _notification_tasks: set = set()

    async def send_failure_notification(message: str) -> None:
        url = settings.NOTIFY_WEBHOOK_URL
        if not url:
            return
        try:
            async with httpx.AsyncClient(timeout=settings.NOTIFY_TIMEOUT) as client:
                await client.post(url, content=message.encode("utf-8"),
                    headers={"Content-Type": "text/plain; charset=utf-8"})
        except Exception:
            logger.warning("Could not deliver failure notification", exc_info=True)

    def schedule_failure_notification(message: str) -> None:
        if not settings.NOTIFY_WEBHOOK_URL:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(send_failure_notification(message))
        _notification_tasks.add(task)
        task.add_done_callback(_notification_tasks.discard)
    ```
  - **The success chokepoint** — `mark_history_imported` is the single function
    that marks a row imported, called from BOTH the auto-import poller
    (`app/main.py:1221`) and the manual retry endpoint (`app/main.py:712`). Hook
    the scan here so both paths trigger it (`app/main.py:965-987`):
    ```python
    def mark_history_imported(history_id: int | None, torrent_hash: str):
        ts = utcnow_str()
        with engine.begin() as cx:
            if history_id is not None:
                cx.execute(text(""" UPDATE history SET torrent_status='imported', ... WHERE id=:id """), {"ts": ts, "id": history_id})
            else:
                cx.execute(text(""" UPDATE history SET torrent_status='imported', ... WHERE torrent_hash=:torrent_hash """), {"ts": ts, "torrent_hash": torrent_hash})
    ```
- **README.md** documents runtime env in a table under `## Configuration`
  (`README.md:65-80`) and behavioral notes under `## Notes` (`README.md:86-`).
  The `NOTIFY_WEBHOOK_URL` row and note are the style to match.

**Conventions to match** (from `AGENTS.md` and the file): flat helper functions in
`main.py` (no new modules/packages); `snake_case`; config read once in `Settings`;
outbound side-effects are best-effort and must **never** raise into the import path.
Tests use `import main`, `respx`, and `monkeypatch.setattr(main.settings, …)` — see
`app/tests/test_notifications.py` (the direct model for this plan's tests).

## Commands you will need

| Purpose      | Command                                             | Expected on success |
|--------------|-----------------------------------------------------|---------------------|
| Install deps | `pip install -r requirements.txt -r requirements-dev.txt` | exit 0 |
| Syntax check | `python -m py_compile app/main.py`                  | exit 0, no output   |
| Tests        | `cd app && python -m pytest -q`                     | all pass (57 today → 60+ after this plan) |

(Tests run from `app/` so `import main` resolves — this is exactly what CI does:
`.github/workflows/docker-publish.yml:35`.)

## Scope

**In scope** (the only files you may modify):
- `app/main.py` — add two `Settings` fields, two helper functions, one call site.
- `app/tests/test_library_scan.py` (create).
- `README.md` — one env-table row + one Notes bullet.
- `plans/README.md` — status row update.

**Out of scope** (do NOT touch):
- `send_failure_notification` / `schedule_failure_notification` / `mark_history_failed`
  and their tests — leave failure notifications exactly as they are.
- Any Audiobookshelf/Plex/Calibre-*specific* client code — v1 is a generic webhook
  only (see STOP conditions and Maintenance notes for why).
- The import logic in `import_torrent_to_library`, `auto_import_cycle`, the DB schema.

## Git workflow

- Branch: `advisor/033-post-import-library-scan-trigger`
- Commit message style: short, present-tense, no prefix (e.g. `git log` shows
  "Warn at startup when the configured torrent client is unreachable"). One commit
  is fine.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add config knobs to `Settings`

In `Settings.__init__` (immediately after the `NOTIFY_TIMEOUT` line at
`app/main.py:124`), add:

```python
self.LIBRARY_SCAN_WEBHOOK_URL = os.getenv("LIBRARY_SCAN_WEBHOOK_URL", "").strip()
# Optional raw Authorization header value, e.g. "Bearer <token>" for
# Audiobookshelf's POST /api/libraries/<id>/scan. Empty = send no auth header.
self.LIBRARY_SCAN_AUTH_HEADER = os.getenv("LIBRARY_SCAN_AUTH_HEADER", "").strip()
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 2: Add the fire-and-forget scan trigger

Directly below `schedule_failure_notification` (after `app/main.py:1026`), add a
generic scan sender + scheduler mirroring the failure pair. Use a **separate**
task-set so the two subsystems never interfere:

```python
_library_scan_tasks: set = set()


async def send_library_scan() -> None:
    """POST to the configured media-server scan webhook. Never raises."""
    url = settings.LIBRARY_SCAN_WEBHOOK_URL
    if not url:
        return
    headers = {}
    if settings.LIBRARY_SCAN_AUTH_HEADER:
        headers["Authorization"] = settings.LIBRARY_SCAN_AUTH_HEADER
    try:
        async with httpx.AsyncClient(timeout=settings.NOTIFY_TIMEOUT) as client:
            await client.post(url, headers=headers)
    except Exception:
        # Never log the auth header value.
        logger.warning("Could not trigger library scan", exc_info=True)


def schedule_library_scan() -> None:
    """Fire-and-forget a library scan from synchronous code.

    No-ops when unconfigured or no event loop is running (e.g. under pytest).
    """
    if not settings.LIBRARY_SCAN_WEBHOOK_URL:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(send_library_scan())
    _library_scan_tasks.add(task)
    task.add_done_callback(_library_scan_tasks.discard)
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 3: Trigger the scan on import success

At the very end of `mark_history_imported` (after the `with engine.begin()` block
closes, currently ending at `app/main.py:987`), add one line:

```python
    schedule_library_scan()
```

Do not change the UPDATE statements. This fires for both auto-import and manual
retry because both call `mark_history_imported`.

**Verify**: `python -m py_compile app/main.py` → exit 0, and
`grep -n "schedule_library_scan()" app/main.py` → exactly **2** matches (the
definition's call site is inside `schedule_library_scan`'s own body? no — the
definition line is `def schedule_library_scan()`, so grep for the *call* `schedule_library_scan()` returns 1 in the def body's `loop.create_task(send_library_scan())`? No). To avoid ambiguity, verify precisely:
`grep -n "    schedule_library_scan()" app/main.py` → exactly **1** match (the new
call in `mark_history_imported`, indented 4 spaces).

### Step 4: Write tests

Create `app/tests/test_library_scan.py`, modeled on
`app/tests/test_notifications.py`:

```python
import asyncio

import respx
from httpx import Response

import main


@respx.mock
def test_send_library_scan_posts_to_url(monkeypatch):
    monkeypatch.setattr(main.settings, "LIBRARY_SCAN_WEBHOOK_URL", "http://abs.test/scan")
    monkeypatch.setattr(main.settings, "LIBRARY_SCAN_AUTH_HEADER", "")
    route = respx.post("http://abs.test/scan").mock(return_value=Response(200))
    asyncio.run(main.send_library_scan())
    assert route.called


@respx.mock
def test_send_library_scan_sends_auth_header_when_set(monkeypatch):
    monkeypatch.setattr(main.settings, "LIBRARY_SCAN_WEBHOOK_URL", "http://abs.test/scan")
    monkeypatch.setattr(main.settings, "LIBRARY_SCAN_AUTH_HEADER", "Bearer tok")
    route = respx.post("http://abs.test/scan").mock(return_value=Response(200))
    asyncio.run(main.send_library_scan())
    assert route.called
    assert route.calls.last.request.headers.get("Authorization") == "Bearer tok"


def test_send_library_scan_noop_when_unset(monkeypatch):
    monkeypatch.setattr(main.settings, "LIBRARY_SCAN_WEBHOOK_URL", "")
    # Must return without raising and without any HTTP (no respx routes registered).
    asyncio.run(main.send_library_scan())


def test_schedule_library_scan_noop_without_loop(monkeypatch):
    monkeypatch.setattr(main.settings, "LIBRARY_SCAN_WEBHOOK_URL", "http://abs.test/scan")
    # No running loop under a plain sync test -> must no-op, not raise.
    main.schedule_library_scan()
```

**Verify**: `cd app && python -m pytest -q test_library_scan.py` → 4 passed.

### Step 5: Document the env vars

In `README.md`, add one row to the Configuration table (after the
`NOTIFY_WEBHOOK_URL` row, `README.md:78`):

```
| `LIBRARY_SCAN_WEBHOOK_URL` | Optional URL POSTed after each successful import to trigger a media-server rescan (e.g. Audiobookshelf `…/api/libraries/<id>/scan`). Empty = disabled. |
| `LIBRARY_SCAN_AUTH_HEADER` | Optional `Authorization` header value sent with the scan POST (e.g. `Bearer <token>`). |
```

And add one bullet under `## Notes` (after the `NOTIFY_WEBHOOK_URL` note):

```
- Set `LIBRARY_SCAN_WEBHOOK_URL` to have the app POST to your media server after each successful import so new books appear without waiting for its scheduled scan. Delivery is best-effort (a failure is logged and ignored, never retried, and never affects the import). Add `LIBRARY_SCAN_AUTH_HEADER` if the endpoint needs auth.
```

**Verify**: `grep -c "LIBRARY_SCAN_WEBHOOK_URL" README.md` → 2 (table row + note).

## Test plan

- New file `app/tests/test_library_scan.py` (4 tests): posts when configured;
  sends the auth header when set; no-ops when URL empty; `schedule_*` no-ops with
  no running loop. Model: `app/tests/test_notifications.py`.
- The full suite must still pass unchanged (no failure-notification test touched).
- Verification: `cd app && python -m pytest -q` → all pass, +4 new.

## Done criteria

ALL must hold:

- [ ] `python -m py_compile app/main.py` exits 0
- [ ] `cd app && python -m pytest -q` exits 0; `test_library_scan.py` (4 tests) passes
- [ ] `grep -n "    schedule_library_scan()" app/main.py` → exactly 1 (the call in `mark_history_imported`)
- [ ] `grep -c "LIBRARY_SCAN_WEBHOOK_URL" README.md` → 2
- [ ] `git status` shows only: `app/main.py`, `app/tests/test_library_scan.py`, `README.md`, `plans/README.md`
- [ ] `plans/README.md` status row for 033 updated to DONE

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts for `Settings`, the notification helpers, or
  `mark_history_imported` don't match live code (drift since `f587737`).
- A verification fails twice after a reasonable fix.
- You find yourself needing to add Audiobookshelf-/Plex-specific request shaping
  (library-id discovery, token refresh, JSON bodies) to make a test pass — v1 is
  deliberately a generic authless-or-single-header POST. Report instead.
- The change appears to require editing anything in the Out-of-scope list.

## Maintenance notes

- **Shared function with plan 034**: both this plan and plan 034 (success
  notifications) append a scheduled call to the end of `mark_history_imported`.
  If both land on separate branches, the merge is trivial (two adjacent
  one-line calls); re-run `cd app && python -m pytest -q` after merging.
- The auth header value is a secret — it is read from env and sent as a header;
  it must never be logged. The `except Exception` handler intentionally logs only
  a generic message.
- Deferred by design: a native Audiobookshelf integration (auto-discover the
  library id, use a typed client) was considered and left out — a generic
  URL+header POST covers ABS (`POST /api/libraries/<id>/scan` with a Bearer
  token), Plex (`/library/sections/<id>/refresh?X-Plex-Token=…` via the URL),
  Calibre-Web, and home-automation webhooks with zero server-specific code. Revisit
  only if users need library-id auto-discovery.
- Future: if a "manual scan now" button is ever added to the UI, have it call a
  thin endpoint that awaits `send_library_scan()` directly (not the scheduler).
