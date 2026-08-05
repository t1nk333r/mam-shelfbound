# Plan 034: Send an optional notification when an import succeeds

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f587737..HEAD -- app/main.py app/tests/test_notifications.py README.md`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (touches the same function `mark_history_imported` as plan 033; if both land, expect a trivial merge — see Maintenance notes)
- **Category**: direction
- **Planned at**: commit `f587737`, 2026-08-04

## Why this matters

Plan 017 added webhook notifications for import **failures** only — nine failure
paths funnel through `mark_history_failed`, which calls
`schedule_failure_notification` (`app/main.py:1067`). There is no positive signal:
a user who wants "tell me when a book lands" has to keep opening the UI. This plan
adds an **opt-in success notification** over the same `NOTIFY_WEBHOOK_URL` channel,
gated by a new `NOTIFY_ON_SUCCESS` flag (default off, because success is far noisier
than failure). It also generalizes the two failure-notification helpers to
message-agnostic names so the success path reuses them cleanly instead of calling a
function named "failure".

## Current state

- `app/main.py` — single-file FastAPI app. Relevant regions:
  - **Config** (`app/main.py:123-124`), and the truthy parser `is_truthy` already
    exists (`app/main.py:39-42`) — use it for the new boolean flag:
    ```python
    self.NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    self.NOTIFY_TIMEOUT = DEFAULT_NOTIFY_TIMEOUT
    ```
  - **The notification helpers to rename** (`app/main.py:992-1026`). Bodies stay
    identical; only the names become generic:
    ```python
    async def send_failure_notification(message: str) -> None:   # -> send_notification
        url = settings.NOTIFY_WEBHOOK_URL
        if not url: return
        try:
            async with httpx.AsyncClient(timeout=settings.NOTIFY_TIMEOUT) as client:
                await client.post(url, content=message.encode("utf-8"),
                    headers={"Content-Type": "text/plain; charset=utf-8"})
        except Exception:
            logger.warning("Could not deliver failure notification", exc_info=True)

    def schedule_failure_notification(message: str) -> None:      # -> schedule_notification
        if not settings.NOTIFY_WEBHOOK_URL: return
        try: loop = asyncio.get_running_loop()
        except RuntimeError: return
        task = loop.create_task(send_failure_notification(message))
        _notification_tasks.add(task); task.add_done_callback(_notification_tasks.discard)
    ```
  - **The one existing caller** in `mark_history_failed` (`app/main.py:1067`):
    ```python
    schedule_failure_notification(format_failure_message(row, cleaned))
    ```
  - **The failure message formatter** — the exact model for the success one
    (`app/main.py:1029-1033`):
    ```python
    def format_failure_message(row, detail: str | None) -> str:
        title = ((row or {}).get("title") or "").strip() or "Unknown title"
        author = ((row or {}).get("author") or "").strip()
        label = f"{title} by {author}" if author else title
        return f"Import failed: {label}\n{detail or 'No detail recorded.'}"
    ```
  - **The success chokepoint** `mark_history_imported` (`app/main.py:965-987`) —
    called from the poller (`:1221`) and manual retry (`:712`). It has two branches
    (by `history_id`, else by `torrent_hash`) and currently sends nothing. The
    SELECT-after-write pattern to mirror is in `mark_history_failed`
    (`app/main.py:1050-1052` / `:1063-1065`).
- **`app/tests/test_notifications.py`** (whole file) — calls
  `main.send_failure_notification`; must be updated to the new name and still pass.
- **README.md** Configuration table (`README.md:65-80`) + Notes (`README.md:86-`).

**Conventions**: flat `snake_case` helpers in `main.py`; config once in `Settings`;
outbound effects best-effort, never raise into imports. Tests: `import main`,
`respx`, `monkeypatch.setattr(main.settings, …)`, and DB seeding via
`main.engine` + `main.ensure_history_schema()` (see `app/tests/test_migrations.py`).

## Commands you will need

| Purpose      | Command                                             | Expected on success |
|--------------|-----------------------------------------------------|---------------------|
| Install deps | `pip install -r requirements.txt -r requirements-dev.txt` | exit 0 |
| Syntax check | `python -m py_compile app/main.py`                  | exit 0              |
| Tests        | `cd app && python -m pytest -q`                     | all pass            |

## Scope

**In scope** (only these files):
- `app/main.py` — one `Settings` field; rename 2 functions + update 1 caller;
  add `format_success_message`; add a gated success hook in `mark_history_imported`.
- `app/tests/test_notifications.py` — update the renamed call; add success tests.
- `README.md` — one env row + one Notes bullet.
- `plans/README.md` — status row.

**Out of scope**:
- `send_library_scan` / `schedule_library_scan` if plan 033 has landed — leave them.
- The DB schema, the import pipeline, the failure message text/behavior.

## Git workflow

- Branch: `advisor/034-import-success-notifications`
- Commit style: short, present-tense, no prefix. One commit is fine.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add the `NOTIFY_ON_SUCCESS` flag

After `app/main.py:124` (`self.NOTIFY_TIMEOUT = DEFAULT_NOTIFY_TIMEOUT`):

```python
self.NOTIFY_ON_SUCCESS = is_truthy(os.getenv("NOTIFY_ON_SUCCESS", ""))
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 2: Generalize the notification helper names

Rename (bodies unchanged):
- `send_failure_notification` → `send_notification`
- `schedule_failure_notification` → `schedule_notification`
- Inside `schedule_notification`, update `loop.create_task(send_failure_notification(message))` → `loop.create_task(send_notification(message))`.
- Update the caller in `mark_history_failed` (`app/main.py:1067`) →
  `schedule_notification(format_failure_message(row, cleaned))`.

**Verify**: `grep -n "failure_notification" app/main.py` → **0 matches**;
`python -m py_compile app/main.py` → exit 0.

### Step 3: Add `format_success_message`

Directly below `format_failure_message` (after `app/main.py:1033`):

```python
def format_success_message(row) -> str:
    title = ((row or {}).get("title") or "").strip() or "Unknown title"
    author = ((row or {}).get("author") or "").strip()
    label = f"{title} by {author}" if author else title
    return f"Imported: {label}"
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 4: Fire the success notification from `mark_history_imported`

At the end of `mark_history_imported` (after its `with engine.begin()` block, which
currently ends at `app/main.py:987`), add a gated SELECT + schedule that mirrors
`mark_history_failed`'s follow-up SELECT:

```python
    if settings.NOTIFY_ON_SUCCESS:
        with engine.begin() as cx:
            if history_id is not None:
                row = cx.execute(text(
                    "SELECT title, author FROM history WHERE id = :id"
                ), {"id": history_id}).mappings().first()
            else:
                row = cx.execute(text(
                    "SELECT title, author FROM history WHERE torrent_hash = :torrent_hash"
                ), {"torrent_hash": torrent_hash}).mappings().first()
        schedule_notification(format_success_message(row))
```

**Verify**: `python -m py_compile app/main.py` → exit 0;
`grep -n "schedule_notification(format_success_message" app/main.py` → 1 match.

### Step 5: Update + extend tests

In `app/tests/test_notifications.py`: change `main.send_failure_notification` to
`main.send_notification` in the existing test. Then append:

```python
def test_format_success_message_with_author():
    assert main.format_success_message({"title": "Dune", "author": "Herbert"}) == "Imported: Dune by Herbert"


def test_format_success_message_without_author():
    assert main.format_success_message({"title": "Dune"}) == "Imported: Dune"


def test_mark_history_imported_success_notify_does_not_raise(monkeypatch):
    # With NOTIFY_ON_SUCCESS on and no running loop, the schedule must no-op
    # cleanly while the row still transitions to 'imported'.
    monkeypatch.setattr(main.settings, "NOTIFY_ON_SUCCESS", True)
    with main.engine.begin() as cx:
        cx.exec_driver_sql("DROP TABLE IF EXISTS history")
    main.ensure_history_schema()
    with main.engine.begin() as cx:
        cx.exec_driver_sql(
            "INSERT INTO history (id, title, author, torrent_hash, torrent_status) "
            "VALUES (1, 'Dune', 'Herbert', 'abc', 'importing')"
        )
    main.mark_history_imported(1, "abc")
    with main.engine.begin() as cx:
        status = cx.exec_driver_sql("SELECT torrent_status FROM history WHERE id = 1").scalar()
    assert status == "imported"
```

**Verify**: `cd app && python -m pytest -q test_notifications.py` → all pass
(1 renamed + 3 new).

### Step 6: Document the flag

Add to the README Configuration table (after `NOTIFY_WEBHOOK_URL`, `README.md:78`):

```
| `NOTIFY_ON_SUCCESS` | Also POST a notification to `NOTIFY_WEBHOOK_URL` on each **successful** import (`1`/`true` to enable; default off). |
```

And a Notes bullet (after the `NOTIFY_WEBHOOK_URL` note):

```
- Set `NOTIFY_ON_SUCCESS=1` to also get a message on each successful import (e.g. "Imported: Dune by Herbert") through the same `NOTIFY_WEBHOOK_URL`. Off by default, since successes are more frequent than failures.
```

**Verify**: `grep -c "NOTIFY_ON_SUCCESS" README.md` → 2.

## Test plan

- `app/tests/test_notifications.py`: rename the existing sender call; add
  `format_success_message` cases (with/without author) and a DB-backed
  `mark_history_imported` success test that proves the row transitions and the
  no-loop schedule no-ops. Model: `test_notifications.py` + `test_migrations.py`.
- Full suite passes unchanged otherwise.
- Verification: `cd app && python -m pytest -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `python -m py_compile app/main.py` exits 0
- [ ] `grep -n "failure_notification" app/main.py` → 0 matches
- [ ] `cd app && python -m pytest -q` exits 0; new success tests pass
- [ ] `grep -c "NOTIFY_ON_SUCCESS" README.md` → 2
- [ ] `git status` shows only: `app/main.py`, `app/tests/test_notifications.py`, `README.md`, `plans/README.md`
- [ ] `plans/README.md` status row for 034 updated to DONE

## STOP conditions

Stop and report if:

- The "Current state" excerpts don't match live code (drift since `f587737`) —
  in particular if `schedule_failure_notification` is already renamed or a success
  path already exists.
- A verification fails twice after a reasonable fix.
- Renaming the helpers breaks a test you cannot fix by updating the call name
  (something else depends on the old names).

## Maintenance notes

- **Shared function with plan 033**: both append to the end of
  `mark_history_imported`. Trivial merge; re-run the suite after merging.
- Success and failure now share `send_notification`/`schedule_notification`. If a
  future change needs different transport/formatting per event type, split them
  again — but today they are genuinely the same POST.
- Reviewer should confirm the success SELECT only runs when `NOTIFY_ON_SUCCESS`
  is true (no extra query on the common path) and that the message contains no
  secret/pathy data (title + author only).
