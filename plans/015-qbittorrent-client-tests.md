# Plan 015: The qBittorrent client's three real methods are covered by tests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **IMPORTANT — which commit this applies to**: this plan targets the code on
> branch `advisor/plans-001-012` (tip `57c0af6`), **not** `master` (`f8d3d32`).
> `QbittorrentClient` does not exist on `master`. Base your work on that branch.
>
> **Drift check (run first)**: `git diff --stat 57c0af6..HEAD -- app/main.py requirements-dev.txt`
> If either changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW (adds tests only; no production code changes)
- **Depends on**: none. Interacts with plan 014 — see "Interaction with plan 014".
- **Category**: tests
- **Planned at**: commit `57c0af6` (branch `advisor/plans-001-012`), 2026-07-24

## Why this matters

The qBittorrent backend is roughly 130 lines of production code whose three
*real* operations — `add_torrent`, `completed_hashes`, `torrent_source` — have
**zero test coverage**. The existing suite only covers `get_torrent_client()`
selection and `qb_tags()` string building; neither exercises a single HTTP
interaction.

That means nothing verifies the parts most likely to be wrong: that the torrent
is uploaded as multipart under the right field name, that the category and tags
are actually attached, that a failed login or rejected add raises instead of
silently continuing, that `save_path` and file names are normalised the way
`import_torrent_to_library` expects, or that a malformed qB response is handled
rather than crashing the auto-import poller.

The whole backend is opt-in (`TORRENT_CLIENT` defaults to `transmission`), so
today the risk is latent rather than active. It becomes active the moment
anyone flips the switch — and at that point every one of those behaviours is
load-bearing and unverified.

## Current state

### The constraint that dictates the approach

Each qB method constructs its **own** client internally:

```python
    async def completed_hashes(self):
        async with httpx.AsyncClient(timeout=30) as c:
            await self._login(c)
            ...
```

There is no seam to inject a fake client through — `add_torrent`,
`completed_hashes`, and `torrent_source` each open `async with
httpx.AsyncClient(...)`. So mocking must happen at the **transport** layer.
That is exactly what `respx` does, and it is the reason this plan adds it.

(Contrast: `_login(self, client)` *does* take a client parameter, so it can be
driven directly — but it is only meaningful in combination with a real call, so
this plan exercises it through the public methods.)

### The code under test

`app/main.py` — `QbittorrentClient` begins at `class QbittorrentClient(TorrentClient):`.
The two methods whose normalisation behaviour the tests pin down:

```python
    async def completed_hashes(self):
        async with httpx.AsyncClient(timeout=30) as c:
            await self._login(c)
            r = await c.get(
                f"{settings.QB_URL}/api/v2/torrents/info",
                params={"category": settings.QB_CATEGORY, "filter": "completed"},
            )
            try:
                arr = r.json()
            except ValueError:
                arr = []
            return {t.get("hash") for t in arr if isinstance(t, dict) and t.get("hash")}

    async def torrent_source(self, torrent_hash):
        async with httpx.AsyncClient(timeout=30) as c:
            await self._login(c)
            info_r = await c.get(f"{settings.QB_URL}/api/v2/torrents/info", params={"hashes": torrent_hash})
            try:
                arr = info_r.json()
            except ValueError:
                arr = []
            info = arr[0] if isinstance(arr, list) and arr else {}
            save_path = (info.get("save_path") or "").rstrip("/")
            if not save_path:
                raise HTTPException(status_code=404, detail="Torrent save path not found")
            files_r = await c.get(f"{settings.QB_URL}/api/v2/torrents/files", params={"hash": torrent_hash})
            try:
                files = files_r.json()
            except ValueError:
                files = []
            if not files:
                raise HTTPException(status_code=404, detail="No files found for torrent")
            names = [(f.get("name") or "").lstrip("/") for f in files if isinstance(f, dict) and f.get("name")]
            return names, save_path
```

`_login` raises `HTTPException(status_code=502, ...)` unless the response is
HTTP 200 **and** its body contains `Ok`.

### Test-suite conventions to match

- `app/tests/test_helpers.py` starts with:
  ```python
  import pytest
  from fastapi import HTTPException

  import main
  ```
  and contains 19 plain `def test_*()` functions. Match that import style.
- `app/conftest.py` sets `MAM_COOKIE` and `HISTORY_DB_URL` before `main` is
  imported. It applies to every file under `app/`, so the new file needs no
  setup of its own.
- Tests run as `cd app && python -m pytest -q` (19 currently pass).
- `requirements-dev.txt` currently contains exactly one line: `pytest`.
- **There is no async test plugin** (no `pytest-asyncio`, no `anyio`), and this
  plan deliberately does not add one. Tests stay **synchronous** and call
  `asyncio.run(...)`. This matches the style already used elsewhere in the suite
  and avoids a second new dependency plus its config.

### About the new dependency

`AGENTS.md` says: "Do not add new dependencies without updating
`requirements.txt` and explaining why." This plan adds **`respx`** — the standard
mocking library for `httpx`, which the app already depends on — to
`requirements-dev.txt` only. Justification: the methods build their own clients,
so transport-level interception is the only way to test them without a live
qBittorrent. It is **dev-only**: `Dockerfile` installs `requirements.txt` alone,
so the runtime image is unaffected, and `.dockerignore` already excludes
`requirements-dev.txt` and `app/tests/` from the build context.

Compatibility is confirmed: `respx` 0.23.1 resolves and runs against the pinned
`httpx==0.28.*`, and `@respx.mock` on a synchronous test intercepts calls made
inside `asyncio.run(...)`.

## Commands you will need

| Purpose        | Command                                        | Expected on success |
|----------------|------------------------------------------------|---------------------|
| Install dev deps | `pip install -r requirements-dev.txt`        | exit 0              |
| Run new tests  | `cd app && python -m pytest tests/test_qbittorrent.py -q` | 10 pass  |
| Run full suite | `cd app && python -m pytest -q`                | 29 pass, exit 0     |
| Syntax check   | `python3 -m py_compile app/main.py`            | exit 0              |

No virtualenv exists in a fresh checkout. Create one **outside** the repo,
install `requirements.txt` + `requirements-dev.txt`, and invoke its interpreter
explicitly.

## Scope

**In scope** (the only files you should create or modify):
- `requirements-dev.txt` — add `respx`.
- `app/tests/test_qbittorrent.py` — **create**; the new test module.

**Out of scope** (do NOT touch):
- `app/main.py` — this plan adds **tests only**. If a test reveals a bug, do
  **not** fix it here; report it (see STOP conditions). Changing production code
  to make a test pass defeats the purpose of writing the test.
- `app/tests/test_helpers.py` — leave it alone; the new tests get their own
  module, matching the repo's "keep modules small and flat" convention.
- `app/conftest.py` — no changes needed; it already provides the env this module
  depends on.
- `requirements.txt`, `Dockerfile` — `respx` is dev-only and must not reach the
  runtime image.
- Do **not** add `pytest-asyncio`, `anyio`, or a `pytest.ini`/`pyproject.toml`
  pytest config. Synchronous tests calling `asyncio.run(...)` are sufficient.
- `TransmissionClient` — out of scope here.

## Interaction with plan 014

Plan 014 (if it lands) rewrites `add_torrent`'s hash lookup to retry and to
select the newest torrent by `added_on`. These tests are written to survive that
change, and you must keep them that way:

- **Do not assert which element is chosen** from a multi-element `torrents/info`
  response. Today the code takes `arr[0]`; after 014 it takes the newest by
  `added_on`. Every happy-path test below therefore returns a **single-element**
  array, where both implementations agree.
- `test_add_torrent_returns_none_when_qb_never_lists_the_torrent` passes under
  both. Note that **after 014 it takes roughly 2 seconds** instead of being
  instant, because `add_torrent` now retries ~5 times. That is expected, not a
  failure. Do **not** reduce production retry defaults to speed up a test.

Neither plan blocks the other; they can land in either order.

## Git workflow

- Work on a branch based on `advisor/plans-001-012`.
- Single commit; present-tense message with no prefix, matching `git log`
  (e.g. `Add qBittorrent client tests`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the dev dependency

Append `respx` to `requirements-dev.txt` so it reads:

```
pytest
respx
```

Leave it unpinned to match the existing `pytest` line. (`requirements.txt` is
pinned; `requirements-dev.txt` is not. Do not "fix" that here — it is noted as a
separate follow-up.)

**Verify**: `pip install -r requirements-dev.txt` exits 0, and
`python -c "import respx, httpx; print(respx.__version__, httpx.__version__)"`
prints two versions without error.

### Step 2: Create the test module

Create `app/tests/test_qbittorrent.py` with exactly this content:

```python
"""qBittorrent client tests. The client builds its own httpx.AsyncClient
internally, so requests are intercepted at the transport layer with respx."""
import asyncio

import pytest
import respx
from fastapi import HTTPException
from httpx import Response

import main

QB = "http://qbittorrent:8080"


def _login_ok():
    return respx.post(f"{QB}/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))


# ---------------------------- _login ----------------------------

@respx.mock
def test_login_failure_raises_502():
    respx.post(f"{QB}/api/v2/auth/login").mock(return_value=Response(200, text="Fails."))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().completed_hashes())
    assert exc.value.status_code == 502


# ---------------------------- add_torrent ----------------------------

@respx.mock
def test_add_torrent_sends_torrent_category_and_tags():
    _login_ok()
    add = respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"hash": "ABC123", "added_on": 500}]))

    got = asyncio.run(main.QbittorrentClient().add_torrent(b"BYTES", "42", "ebook", False))

    assert got == "ABC123"
    body = add.calls.last.request.content
    assert b"mam.torrent" in body and b"BYTES" in body
    assert b"mamid=42" in body
    assert b"kindle-nosend" in body          # ebook + send_to_kindle False
    assert main.settings.QB_CATEGORY.encode() in body


@respx.mock
def test_add_torrent_audiobook_has_no_nosend_tag():
    _login_ok()
    add = respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"hash": "H", "added_on": 1}]))

    asyncio.run(main.QbittorrentClient().add_torrent(b"B", "7", "audiobook", True))

    assert b"kindle-nosend" not in add.calls.last.request.content


@respx.mock
def test_add_torrent_raises_502_when_add_rejected():
    _login_ok()
    respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Fails."))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().add_torrent(b"B", "1", "audiobook", True))
    assert exc.value.status_code == 502


@respx.mock
def test_add_torrent_returns_none_when_qb_never_lists_the_torrent():
    _login_ok()
    respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=Response(200, json=[]))

    got = asyncio.run(main.QbittorrentClient().add_torrent(b"B", "42", "audiobook", True))
    assert got is None


# ---------------------------- completed_hashes ----------------------------

@respx.mock
def test_completed_hashes_queries_category_and_returns_hashes():
    _login_ok()
    route = respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"hash": "H1"}, {"hash": "H2"}, {"no": "hash"}, "junk"]))

    got = asyncio.run(main.QbittorrentClient().completed_hashes())

    assert got == {"H1", "H2"}
    params = route.calls.last.request.url.params
    assert params["category"] == main.settings.QB_CATEGORY
    assert params["filter"] == "completed"


@respx.mock
def test_completed_hashes_tolerates_non_json():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=Response(200, text="<html>nope"))
    assert asyncio.run(main.QbittorrentClient().completed_hashes()) == set()


# ---------------------------- torrent_source ----------------------------

@respx.mock
def test_torrent_source_returns_names_and_save_path():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"save_path": "/downloads/", "hash": "H"}]))
    files = respx.get(f"{QB}/api/v2/torrents/files").mock(
        return_value=Response(200, json=[{"name": "Book/01.mp3"}, {"name": "/Book/02.mp3"}]))

    names, path = asyncio.run(main.QbittorrentClient().torrent_source("H"))

    assert path == "/downloads"                        # trailing slash stripped
    assert names == ["Book/01.mp3", "Book/02.mp3"]     # leading slash stripped
    assert files.calls.last.request.url.params["hash"] == "H"


@respx.mock
def test_torrent_source_raises_404_when_save_path_missing():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=Response(200, json=[]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().torrent_source("H"))
    assert exc.value.status_code == 404


@respx.mock
def test_torrent_source_raises_404_when_no_files():
    _login_ok()
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=Response(200, json=[{"save_path": "/downloads"}]))
    respx.get(f"{QB}/api/v2/torrents/files").mock(return_value=Response(200, json=[]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.QbittorrentClient().torrent_source("H"))
    assert exc.value.status_code == 404
```

Notes for the executor:
- `QB = "http://qbittorrent:8080"` is the **default** `QB_URL` from `Settings`.
  The tests rely on that default; they do not set `QB_URL`. If your environment
  exports `QB_URL`, unset it before running, or the routes will not match.
- `main.settings.QB_CATEGORY` is read rather than hardcoded, so the test does not
  break if the default category is renamed.
- The `"junk"` string in the `completed_hashes` payload is deliberate: it proves
  the `isinstance(t, dict)` guard actually filters non-dict entries.

**Verify**: `cd app && python -m pytest tests/test_qbittorrent.py -q` → **10 passed**.

### Step 3: Confirm the whole suite

**Verify**: `cd app && python -m pytest -q` → **29 passed** (19 inherited + 10 new),
exit 0.

## Test plan

The 10 tests, by method:

- **`_login`** (1): a non-`Ok` body raises `HTTPException(502)` — exercised
  through `completed_hashes`, since `_login` is only meaningful in combination.
- **`add_torrent`** (4): happy path returns the hash *and* the request carries
  the torrent bytes under the `mam.torrent` filename, the `mamid=` tag, the
  `kindle-nosend` tag, and the category; an audiobook gets **no** `kindle-nosend`
  tag; a rejected add raises 502; an empty listing yields `None`.
- **`completed_hashes`** (2): queries `category` + `filter=completed` and returns
  only entries that are dicts with a hash; a non-JSON body yields an empty set
  rather than raising (important — this runs in the auto-import poller, where an
  exception would be logged every 30 seconds).
- **`torrent_source`** (3): returns names with leading slashes stripped and
  `save_path` with the trailing slash stripped, and queries files by `hash`;
  raises 404 when `save_path` is missing; raises 404 when the file list is empty.

Model: `app/tests/test_helpers.py` for import style and plain `def test_*`
functions. This module differs by using the `@respx.mock` decorator and
`asyncio.run(...)`.

**Not covered, and deliberately so**: behaviour against a real qBittorrent
instance. These tests pin the contract this code *believes* qB implements; they
cannot detect that belief being wrong (e.g. a field renamed in a future qB API
version). Live verification remains a manual step.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c respx requirements-dev.txt` returns 1
- [ ] `grep -c respx requirements.txt` returns 0 — dev-only, not in the runtime image
- [ ] `app/tests/test_qbittorrent.py` exists and defines 10 `def test_*` functions
      (`grep -c "^def test_" app/tests/test_qbittorrent.py` → 10)
- [ ] `cd app && python -m pytest tests/test_qbittorrent.py -q` exits 0 with 10 passing
- [ ] `cd app && python -m pytest -q` exits 0 with 29 passing
- [ ] `git diff --stat` shows **no** changes to `app/main.py` (tests only)
- [ ] `git status` shows only `requirements-dev.txt` modified and
      `app/tests/test_qbittorrent.py` added
- [ ] `plans/README.md` status row for 015 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `QbittorrentClient` does not exist in `app/main.py` — you are on `master`, not
  `advisor/plans-001-012`. Re-base onto that branch.
- **A test fails against the current code.** That means you have found a real
  bug. Do **not** edit `app/main.py` to make it pass, and do **not** weaken the
  assertion. Report the failing test, the assertion, and the actual value.
- `respx` fails to install or errors at import — report the versions of `respx`
  and `httpx` you resolved. Do not switch to a different mocking approach or
  hand-roll transport patching without reporting first.
- Routes do not match and requests attempt to reach the network — almost always
  a `QB_URL` set in your environment overriding the default. Unset it; do not
  change the production default to match your environment.

## Maintenance notes

- **These tests encode assumptions about qBittorrent's Web API v2**, not
  verified facts about a running qB: form-login returning `Ok.`, `torrents/add`
  taking multipart under the `torrents` field, `torrents/info` accepting `tag` /
  `category` / `hashes`, and `torrents/files` accepting `hash`. If a qB upgrade
  changes any of these, these tests will keep passing while production breaks.
  That is the inherent limit of mock-based coverage — treat a live smoke test as
  still necessary before trusting qB support.
- When plan 014 lands, `test_add_torrent_returns_none_when_qb_never_lists_the_torrent`
  becomes slower (retries). Leave it; do not tune production retry defaults for
  test speed.
- If a fourth qB operation is added (pause, delete, recheck), add its tests here
  in the same style rather than growing `test_helpers.py`.
- Reviewer should confirm `app/main.py` is untouched, that `respx` landed in
  `requirements-dev.txt` and **not** `requirements.txt`, and that no async test
  plugin was introduced.
