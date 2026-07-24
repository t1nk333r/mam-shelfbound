# Plan 017: A failed import notifies you instead of failing silently

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **IMPORTANT — which commit this applies to**: this plan targets branch
> `advisor/plans-001-012` (tip `57c0af6`), **not** `master` (`f8d3d32`). Base
> your work on that branch.
>
> **Drift check (run first)**: `git diff --stat 57c0af6..HEAD -- app/main.py docker-compose.yml README.md`
> If any changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW-MED (touches the failure path; a bug here must not break imports)
- **Depends on**: none. Soft: plan 015 adds `respx`, which makes the HTTP
  delivery test possible — see "Test plan".
- **Category**: direction / feature
- **Planned at**: commit `57c0af6` (branch `advisor/plans-001-012`), 2026-07-24

## Why this matters

When an import fails, nothing tells you. The failure is recorded in the database
and rendered as `Failure` in the History table — but **only if you happen to open
the UI**. The auto-import poller runs unattended every 30 seconds; a book can
fail to import and sit there for weeks.

There are nine call sites that funnel into `mark_history_failed`: five in
`retry_history_import` and four in `auto_import_cycle`. All of them currently
end in a database write plus, at most, a `logger.warning` into container logs
nobody reads.

This plan sends a notification when a row is marked failed. It posts a plain-text
message to a configured webhook URL — which works out of the box with **ntfy**
and Gotify, needs no new dependency (`httpx` is already required), and is off by
default (empty URL = disabled), so existing deployments are unaffected.

## Current state

### The funnel — one function, nine callers

Every failure path ends here (`app/main.py`):

```python
def mark_history_failed(history_id: int | None, torrent_hash: str, detail: str):
    with engine.begin() as cx:
        params = {"detail": clean_status_detail(detail)}
        if history_id is not None:
            params["id"] = history_id
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'import_failed',
                    status_detail = :detail,
                    status_updated_at = :ts
                WHERE id = :id
            """), {"ts": utcnow_str(), **params})
        else:
            params["torrent_hash"] = torrent_hash
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'import_failed',
                    status_detail = :detail,
                    status_updated_at = :ts
                WHERE torrent_hash = :torrent_hash
            """), {"ts": utcnow_str(), **params})
```

Hooking the notification **here** means one integration point instead of nine.
That is the whole design.

### The complication, and how this plan handles it

`mark_history_failed` is a **synchronous** `def`, but sending HTTP needs `async`.
It is always called from inside an async function (`retry_history_import` or
`auto_import_cycle`), so a running event loop exists — but the function itself
cannot `await`. The plan therefore schedules a fire-and-forget task via
`asyncio.get_running_loop().create_task(...)`, and **no-ops cleanly when there is
no loop** (which is what happens under pytest, so the test suite never sends
anything).

Fire-and-forget tasks can be garbage-collected mid-flight, so the plan keeps a
module-level reference set — this is a real hazard, not defensiveness.

### Facts you need

- `asyncio`, `httpx`, and `logging` are already imported at the top of
  `app/main.py` (`import os, json, re, base64, asyncio, logging, errno`).
  **Do not add imports.**
- `logger = logging.getLogger("mam_audiofinder")` already exists.
- `clean_status_detail(detail)` collapses whitespace and truncates to 500 chars —
  reuse it for the message body.
- Constants live near the top of the file (`DEFAULT_AUTO_IMPORT_POLL_INTERVAL = 30`,
  `DEFAULT_UMASK = "0002"`). Add new constants there.
- `Settings.__init__` reads every config value with `os.getenv(...)`. Add new
  settings there, following the existing style.
- `docker-compose.yml` documents every env var in its `environment:` block.
- Conventions: Python 4-space indent, `snake_case` module-level helpers kept flat
  in `main.py` (`AGENTS.md`). Commit messages short and present-tense, no prefix.

## Commands you will need

| Purpose      | Command                                | Expected on success |
|--------------|----------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile app/main.py`    | exit 0              |
| Run tests    | `cd app && python -m pytest -q`        | all pass, exit 0    |
| Compose YAML | `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"` | `yaml ok` |

No virtualenv exists in a fresh checkout. Create one **outside** the repo,
install `requirements.txt` + `requirements-dev.txt`, invoke it explicitly.

## Scope

**In scope**:
- `app/main.py` — two new settings, one constant, two new helpers, and one call
  added at the end of `mark_history_failed`.
- `docker-compose.yml` — document the new env vars.
- `README.md` — document the feature and the new variables.
- `app/tests/test_helpers.py` — add tests.

**Out of scope** (do NOT touch):
- The nine `mark_history_failed` **call sites** — do not add notify calls there.
  The whole point is a single integration point. If you find yourself editing
  `retry_history_import` or `auto_import_cycle`, stop.
- `mark_history_imported` and success paths — this plan notifies on **failure
  only**. Success notifications are a separate decision (see Maintenance notes).
- The `UPDATE` statements inside `mark_history_failed` — unchanged.
- Do **not** add a notification library (Apprise, etc.). `httpx` is already a
  dependency and a plain POST is sufficient; a new runtime dependency needs
  justification per `AGENTS.md` and is not warranted here.
- Do **not** make `mark_history_failed` async. That would force changes at all
  nine call sites and is exactly what this design avoids.

## Git workflow

- Work on a branch based on `advisor/plans-001-012`.
- One or two commits; present-tense message, no prefix
  (e.g. `Notify a configured webhook when an import fails`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add configuration

Near the other constants at the top of `app/main.py` (beside `DEFAULT_UMASK`),
add:

```python
DEFAULT_NOTIFY_TIMEOUT = 10
```

In `Settings.__init__`, after the `self.QB_TAGS` line, add:

```python
        self.NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
        self.NOTIFY_TIMEOUT = DEFAULT_NOTIFY_TIMEOUT
```

An empty `NOTIFY_WEBHOOK_URL` means notifications are **off**. There is no
enable/disable flag — presence of a URL is the switch.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "NOTIFY_WEBHOOK_URL" app/main.py` → one match in `Settings`.

### Step 2: Add the send + schedule helpers

Add both helpers immediately **above** `def mark_history_failed(` in
`app/main.py`:

```python
_notification_tasks: set = set()


async def send_failure_notification(message: str) -> None:
    """POST a plain-text failure message to the configured webhook.

    Never raises: a notification problem must not affect an import.
    """
    url = settings.NOTIFY_WEBHOOK_URL
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=settings.NOTIFY_TIMEOUT) as client:
            await client.post(
                url,
                content=message.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
            )
    except Exception:
        logger.warning("Could not deliver failure notification", exc_info=True)


def schedule_failure_notification(message: str) -> None:
    """Fire-and-forget the notification from synchronous code.

    No-ops when notifications are unconfigured or no event loop is running
    (e.g. under pytest), so callers never need to care.
    """
    if not settings.NOTIFY_WEBHOOK_URL:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(send_failure_notification(message))
    # Hold a reference: bare tasks can be garbage-collected before they finish.
    _notification_tasks.add(task)
    task.add_done_callback(_notification_tasks.discard)
```

Notes for the executor:
- `send_failure_notification` swallows **every** exception deliberately. A dead
  webhook must never turn a recoverable import failure into an unhandled error
  inside the poller.
- The `except RuntimeError` around `get_running_loop()` is what makes the test
  suite silent — do not remove it.

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 3: Hook it into the failure funnel

Modify `mark_history_failed` so it looks up the title/author (for a readable
message) inside the existing transaction, then schedules the notification
**after** the transaction commits. Replace the whole function with:

```python
def mark_history_failed(history_id: int | None, torrent_hash: str, detail: str):
    cleaned = clean_status_detail(detail)
    with engine.begin() as cx:
        params = {"detail": cleaned}
        if history_id is not None:
            params["id"] = history_id
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'import_failed',
                    status_detail = :detail,
                    status_updated_at = :ts
                WHERE id = :id
            """), {"ts": utcnow_str(), **params})
            row = cx.execute(text(
                "SELECT title, author FROM history WHERE id = :id"
            ), {"id": history_id}).mappings().first()
        else:
            params["torrent_hash"] = torrent_hash
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'import_failed',
                    status_detail = :detail,
                    status_updated_at = :ts
                WHERE torrent_hash = :torrent_hash
            """), {"ts": utcnow_str(), **params})
            row = cx.execute(text(
                "SELECT title, author FROM history WHERE torrent_hash = :torrent_hash"
            ), {"torrent_hash": torrent_hash}).mappings().first()

    schedule_failure_notification(format_failure_message(row, cleaned))
```

The only changes are: `cleaned` hoisted to a local (so it is computed once and
reused in the message), a `SELECT` added to each branch, and the final
`schedule_failure_notification(...)` line. **The two `UPDATE` statements are
byte-for-byte unchanged.**

Add the message formatter next to the other helpers, above
`mark_history_failed`:

```python
def format_failure_message(row, detail: str | None) -> str:
    title = ((row or {}).get("title") or "").strip() or "Unknown title"
    author = ((row or {}).get("author") or "").strip()
    label = f"{title} by {author}" if author else title
    return f"Import failed: {label}\n{detail or 'No detail recorded.'}"
```

It tolerates `row` being `None` (the row could have been deleted between the
update and the select) — do not assume it is present.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -c "schedule_failure_notification" app/main.py` returns 2 (the definition
and the single call site).

### Step 4: Document the configuration

In `docker-compose.yml`, add to the `environment:` block after `QB_CATEGORY`:

```yaml
      # Optional: POST a plain-text message here when an import fails.
      # Works with ntfy (https://ntfy.sh/your-topic) and Gotify. Empty = disabled.
      NOTIFY_WEBHOOK_URL: ""
```

In `README.md`, add `NOTIFY_WEBHOOK_URL` to the Configuration table with the
purpose "Optional webhook for import-failure notifications (empty = disabled)",
and add one bullet under Notes:

```markdown
- Set `NOTIFY_WEBHOOK_URL` to receive a plain-text message whenever an import fails — for example an [ntfy](https://ntfy.sh) topic URL. Leave it empty to disable notifications. Delivery is best-effort: a webhook that is down is logged and ignored, never retried, and never affects the import itself.
```

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"` → `yaml ok`, and `grep -c NOTIFY_WEBHOOK_URL README.md docker-compose.yml` shows matches in both.

### Step 5: Add tests

Add to `app/tests/test_helpers.py`:

```python
def test_format_failure_message_with_and_without_author():
    msg = main.format_failure_message({"title": "Dune", "author": "Frank Herbert"}, "disk full")
    assert "Dune by Frank Herbert" in msg
    assert "disk full" in msg
    # missing author, and a completely absent row, must not raise
    assert "Dune" in main.format_failure_message({"title": "Dune", "author": ""}, "x")
    assert "Unknown title" in main.format_failure_message(None, None)


def test_schedule_failure_notification_is_a_noop_without_config(monkeypatch):
    # No webhook configured -> nothing scheduled, no error.
    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "")
    main.schedule_failure_notification("anything")
    assert not main._notification_tasks


def test_schedule_failure_notification_is_a_noop_without_event_loop(monkeypatch):
    # Configured, but called from sync test code with no running loop.
    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "http://example.invalid/hook")
    main.schedule_failure_notification("anything")
    assert not main._notification_tasks


def test_send_failure_notification_swallows_transport_errors(monkeypatch):
    # An unreachable webhook must never raise into the import path.
    import asyncio

    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "http://127.0.0.1:1/hook")
    monkeypatch.setattr(main.settings, "NOTIFY_TIMEOUT", 1)
    asyncio.run(main.send_failure_notification("boom"))  # must simply return
```

The last test deliberately targets port 1 on localhost, which refuses
connections fast; it asserts the swallow-everything contract without needing a
mock library.

**If plan 015 has landed** (`respx` is in `requirements-dev.txt`), also add a
delivery test to `app/tests/test_qbittorrent.py`'s sibling — create
`app/tests/test_notifications.py`:

```python
import asyncio

import respx
from httpx import Response

import main


@respx.mock
def test_send_failure_notification_posts_the_message(monkeypatch):
    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "http://hook.test/topic")
    route = respx.post("http://hook.test/topic").mock(return_value=Response(200))
    asyncio.run(main.send_failure_notification("Import failed: Dune"))
    assert route.called
    assert b"Import failed: Dune" in route.calls.last.request.content
```

If 015 has **not** landed, skip that file and note it in your report — do not
add `respx` yourself; that is 015's job.

**Verify**: `cd app && python -m pytest -q` → all pass.

## Test plan

- **Unit (required)**: message formatting with author, without author, and with
  a `None` row; `schedule_failure_notification` no-ops both when unconfigured and
  when no event loop is running; `send_failure_notification` swallows a
  connection failure rather than raising.
- **Unit (only if plan 015 landed)**: a respx-mocked webhook receives a POST
  whose body contains the message.
- **Manual (recommended)**: set `NOTIFY_WEBHOOK_URL` to an ntfy topic, force an
  import failure (e.g. point `/library` at a read-only path, or mark a history
  row `import_failed` via the Retry path), and confirm a phone notification
  arrives reading `Import failed: <title> by <author>` with the detail beneath.
- **Regression (required)**: with `NOTIFY_WEBHOOK_URL` unset, imports and
  failures behave exactly as before — `cd app && python -m pytest -q` all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -c "schedule_failure_notification" app/main.py` returns 2 (definition + exactly one call site)
- [ ] `grep -n "send_failure_notification\|format_failure_message\|_notification_tasks" app/main.py` shows each defined
- [ ] `grep -c "mark_history_failed" app/main.py` returns 10 (1 definition + the 9 pre-existing call sites — **no new call sites added**)
- [ ] `grep -n "NOTIFY_WEBHOOK_URL" docker-compose.yml README.md` shows it documented in both
- [ ] `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"` prints `yaml ok`
- [ ] `cd app && python -m pytest -q` exits 0, including the four new tests
- [ ] `git status` shows only `app/main.py`, `docker-compose.yml`, `README.md`, `app/tests/test_helpers.py` (and `app/tests/test_notifications.py` only if plan 015 landed)
- [ ] `plans/README.md` status row for 017 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `mark_history_failed` excerpt does not match the live code.
- `grep -c "mark_history_failed" app/main.py` is not 10 after your change — you
  added or removed a call site, which is out of scope.
- Any existing test fails. The notification path must be inert under pytest (no
  running loop); a failure means `schedule_failure_notification` is not no-oping
  as designed. Report it rather than adding skips.
- You find yourself wanting to make `mark_history_failed` async, or to add
  notify calls at the individual failure sites. Both are explicitly out of scope.
- The poller starts logging notification warnings every 30 seconds. That means
  something is scheduling a notification on a non-failure path; report where.

## Maintenance notes

- **Failure-only, by design.** Success notifications would fire on every import
  and turn the feature into noise. If they are ever wanted, add a separate
  opt-in variable rather than reusing this one.
- **Delivery is best-effort and unretried.** A webhook that is down loses that
  notification permanently. That is a deliberate trade: retry logic inside the
  failure path is a good way to make failures worse. If guaranteed delivery is
  ever needed, queue it in the database rather than retrying inline.
- The single integration point is the feature's main virtue. If a new failure
  path is added later, route it through `mark_history_failed` and it gets
  notifications for free.
- Related gap this does **not** cover: a history row that never reaches
  `import_failed` at all — for example the null-hash rows described in plan 014,
  which sit in `added` forever. Those produce no notification because they never
  fail. Fixing that is 014's job, not this plan's.
- Reviewer should confirm the two `UPDATE` statements are unchanged, that exactly
  one call site was added, and that `send_failure_notification` still catches
  bare `Exception`.
