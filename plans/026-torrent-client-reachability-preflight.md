# Plan 026: Startup preflight warns when the torrent client is unreachable

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 4ec80a1..HEAD -- app/main.py app/tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW — warn-only; never fatal; async check runs only when the ASGI server starts
- **Depends on**: none (plan 024's preflight is already merged on `master`)
- **Category**: dx (operability)
- **Planned at**: commit `4ec80a1`, 2026-07-30

## Why this matters

The app's startup preflight (added in plan 024) validates the DB directory and
warns about filesystem/hardlink problems, but it has **no check that the
configured torrent client is reachable**. Today, a wrong `QB_URL`, bad
qBittorrent credentials, or a Transmission that isn't up surfaces only when the
user clicks **Add** and the request fails — not at boot. This adds a **warn-only**
reachability check to the existing lifespan startup so a misconfigured/unreachable
client is flagged in the logs immediately (`[preflight] WARNING: qbittorrent is
not reachable …`). Plan 024's maintenance note explicitly deferred this as its
own plan; this is it.

## Current state

`app/main.py` is a single-file FastAPI app.

- The torrent-client abstraction (`app/main.py:697-829`):
  - Base `class TorrentClient` — `add_torrent` / `completed_hashes` /
    `torrent_source` all `raise NotImplementedError`.
  - `class TransmissionClient(TorrentClient)` (`:710`) — talks to Transmission
    via `transmission_rpc(client, method, arguments)` (`:439`). A `session-get`
    RPC is the standard "is it alive + authed?" call.
  - `class QbittorrentClient(TorrentClient)` (`:742`) — `_login(client)` (`:743`)
    POSTs to `{settings.QB_URL}/api/v2/auth/login` and raises `HTTPException(502)`
    on failure; a successful login proves reachability **and** valid credentials.
  - `get_torrent_client()` (`:826`):
    ```python
    def get_torrent_client() -> TorrentClient:
        if settings.TORRENT_CLIENT == "qbittorrent":
            return QbittorrentClient()
        return TransmissionClient()
    ```
- The startup lifespan already warns about filesystem issues (`app/main.py:291-304`):
  ```python
  @asynccontextmanager
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
  Note the existing `[preflight] WARNING: …` shape and `file=sys.stderr` — match it.

- **Test-safety fact:** the lifespan runs only when the ASGI server actually
  starts. The unit tests (`app/tests/test_*.py`) `import main` and call functions
  directly — they do **not** start the server, so this async network check never
  fires during them. Network in tests is exercised only via **respx** mocks (see
  `app/tests/test_qbittorrent.py`).

**Repo conventions to match:**
- Flat helper functions in `main.py` (`AGENTS.md:26`).
- The "return a warning message or `None`" pattern already used by
  `hardlink_fs_warning` — mirror it for consistency.
- Tests: plain pytest functions, `@respx.mock` + `asyncio.run(...)` (no
  pytest-asyncio). See `app/tests/test_qbittorrent.py`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Syntax check | `python -m py_compile app/main.py` | exit 0 |
| Run tests | `cd app && python -m pytest -q` | all pass (incl. new tests) |
| Confirm new symbols | `grep -n "async def reachable\|def torrent_client_warning" app/main.py` | 3 `reachable` + 1 helper |

(`pytest` and `respx` are the dev deps in `requirements-dev.txt`. Run tests from
`app/`.)

## Scope

**In scope** (only files you may modify):
- `app/main.py` — add `reachable()` to the client classes, a
  `torrent_client_warning()` helper, and one call in `lifespan`.
- `app/tests/test_reachability.py` — **create**.

**Out of scope** (do NOT touch):
- `db_dir_writable` / `hardlink_fs_warning` / `run_startup_preflight` / the
  import-time `run_startup_preflight()` call — leave plan 024's code alone.
- The clients' `add_torrent` / `completed_hashes` / `torrent_source` bodies.
- Do NOT make the reachability check fatal — it must only warn. Do NOT add it to
  `run_startup_preflight()` (that runs at import and would make network calls
  during tests). It goes in `lifespan` only.

## Git workflow

- Branch: `advisor/026-torrent-client-reachability-preflight`
- Short imperative commit subject. Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add `reachable()` to the base and both clients

In the base `class TorrentClient`, add alongside the other abstract methods:

```python
    async def reachable(self) -> None:
        """Raise if the client is unreachable / misconfigured; return None if OK."""
        raise NotImplementedError
```

In `class TransmissionClient`, add:

```python
    async def reachable(self):
        async with httpx.AsyncClient(timeout=5) as c:
            await transmission_rpc(c, "session-get")
```

In `class QbittorrentClient`, add (a successful login proves reachability + creds):

```python
    async def reachable(self):
        async with httpx.AsyncClient(timeout=5) as c:
            await self._login(c)
```

**Verify**: `grep -n "async def reachable" app/main.py` → three matches; `python -m py_compile app/main.py` → exit 0.

### Step 2: Add the warning helper

Add near the other module-level helpers (e.g. just above `lifespan`):

```python
async def torrent_client_warning() -> str | None:
    """Return a warning if the configured torrent client is unreachable at
    startup, else None. Never raises."""
    try:
        await get_torrent_client().reachable()
        return None
    except Exception as exc:
        return (f"{settings.TORRENT_CLIENT} is not reachable at startup ({exc!s}) "
                f"— check its URL and credentials; torrent adds and imports will "
                f"fail until it is up")
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 3: Call it from `lifespan` (warn-only)

In `lifespan`, immediately after the existing filesystem warning block and
**before** `await reconcile_auto_import_task()`, add:

```python
    client_warn = await torrent_client_warning()
    if client_warn:
        print(f"[preflight] WARNING: {client_warn}", file=sys.stderr)
```

Keep everything else in `lifespan` unchanged.

**Verify**:
- `grep -n "torrent_client_warning()" app/main.py` → definition + one call in `lifespan`.
- `cd app && python -m pytest -q` → still all pass (lifespan didn't run in unit tests).

### Step 4: Tests

Create `app/tests/test_reachability.py`, modeled on `app/tests/test_qbittorrent.py`
(respx transport mocks + `asyncio.run`):

```python
import asyncio

import httpx
import respx

import main


@respx.mock
def test_warning_none_when_qb_reachable(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "qbittorrent")
    respx.post(f"{main.settings.QB_URL}/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    assert asyncio.run(main.torrent_client_warning()) is None


@respx.mock
def test_warning_flags_qb_unreachable(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "qbittorrent")
    respx.post(f"{main.settings.QB_URL}/api/v2/auth/login").mock(
        side_effect=httpx.ConnectError("refused")
    )
    msg = asyncio.run(main.torrent_client_warning())
    assert msg and "qbittorrent" in msg and "not reachable" in msg
```

**Verify**: `cd app && python -m pytest -q` → all pass, 2 new tests.

## Test plan

- New file `app/tests/test_reachability.py`: qB reachable → `None`; qB
  unreachable (ConnectError) → a warning mentioning the client and "not
  reachable". Structural pattern: `app/tests/test_qbittorrent.py`.
- Verification: `cd app && python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "async def reachable" app/main.py` → exactly three matches
- [ ] `grep -n "def torrent_client_warning" app/main.py` → one match; it is called once inside `lifespan` before `reconcile_auto_import_task()`
- [ ] The reachability check is **not** referenced inside `run_startup_preflight` (`grep -n "reachable\|torrent_client_warning" app/main.py` shows no hit inside that function)
- [ ] `python -m py_compile app/main.py` → exit 0
- [ ] `cd app && python -m pytest -q` → all pass; `app/tests/test_reachability.py` exists with 2 tests
- [ ] `git status --porcelain` shows only `app/main.py` and new `app/tests/test_reachability.py`
- [ ] `plans/README.md` row for 026 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The client classes or `lifespan` don't match the "Current state" excerpts (drift).
- Adding the check makes any existing test start doing real network I/O (it must
  not — the check lives in `lifespan`, which unit tests don't trigger; tests use
  respx). If a test hangs or hits the network, stop.
- You find yourself tempted to make the check fatal or move it into
  `run_startup_preflight` — both are out of scope; stop.

## Maintenance notes

- If a third torrent client is ever added, give it a `reachable()` too.
- Reviewer: confirm warn-only (no `SystemExit`/`raise` escaping into startup),
  the 5s timeouts, and that the check sits in `lifespan`, not at import.
- The check adds one lightweight request at server start; it does not run per
  request.
