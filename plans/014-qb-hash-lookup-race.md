# Plan 014: A qBittorrent add reliably records the new torrent's hash

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
> **Drift check (run first)**: `git diff --stat 57c0af6..HEAD -- app/main.py`
> If `app/main.py` changed since this plan was written, compare the "Current
> state" excerpt against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `57c0af6` (branch `advisor/plans-001-012`), 2026-07-24

## Why this matters

qBittorrent's `torrents/add` endpoint returns `Ok.` and **no infohash**. To learn
the hash of the torrent it just added, `QbittorrentClient.add_torrent` immediately
queries `torrents/info` filtered by the `mamid=<id>` tag and takes the first
element.

**The real defect is a race.** `torrents/add` is asynchronous — qBittorrent
accepts the request and registers the torrent shortly afterwards. The follow-up
query fires with no delay and no retry, so when it loses the race the array is
empty and the method returns `None`. Verified with a mocked qB returning `[]`:
the method returns `None`, so `insert_history(...)` stores a **NULL**
`torrent_hash`.

A NULL hash is permanently fatal to that row. The auto-import candidate query
requires a hash:

```sql
WHERE
    torrent_hash IS NOT NULL
    AND trim(torrent_hash) != ''
```

so the row is never a candidate. It sits in `added` forever, never imports, and
shows no Retry button (the UI only offers Retry for `import_failed`). This is the
same permanently-stranded-row class that plan 012 fixed, arriving through a door
plan 012's startup reset does not cover — that reset only rescues rows stuck in
`importing`.

**A second, lower-likelihood issue rides along.** `arr[0]` is an arbitrary pick
with no ordering guarantee. Verified with a mocked two-element response: the
method returned the *older* torrent's hash, not the one just added. In practice
this is rare — adding the same MAM id twice yields the same infohash, so
qBittorrent deduplicates to a single torrent and `arr[0]` is correct. Two
torrents could only share a `mamid` tag if MyAnonamouse served different
infohashes for one `tid`. Worth fixing while the code is open, but it is not the
motivating problem; do not let it drive the design.

One change — retry briefly, then select the newest — fixes both.

## Current state

`app/main.py:674-697` — the whole method, with the hash lookup at the end:

```python
    async def add_torrent(self, metainfo, mam_id, media_type, send_to_kindle):
        async with httpx.AsyncClient(timeout=60) as client:
            await self._login(client)
            data = {"category": settings.QB_CATEGORY}
            tags = qb_tags(mam_id, media_type, send_to_kindle)
            if tags:
                data["tags"] = ",".join(tags)
            files = {"torrents": ("mam.torrent", metainfo, "application/x-bittorrent")}
            r = await client.post(f"{settings.QB_URL}/api/v2/torrents/add", data=data, files=files)
            if r.status_code != 200 or "Ok" not in (r.text or ""):
                raise HTTPException(status_code=502, detail=f"qBittorrent add failed: {r.status_code} {r.text[:160]}")
            if not mam_id:
                return None
            info = await client.get(
                f"{settings.QB_URL}/api/v2/torrents/info",
                params={"tag": f"mamid={mam_id}", "filter": "all"},
            )
            try:
                arr = info.json()
            except ValueError:
                return None
            if isinstance(arr, list) and arr:
                return arr[0].get("hash")
            return None
```

Facts the executor needs:

- `asyncio` is **already imported** at `app/main.py:1`
  (`import os, json, re, base64, asyncio, logging, errno`). Do not add imports.
- qBittorrent's `/api/v2/torrents/info` returns objects containing an
  **`added_on`** field: an integer Unix epoch timestamp of when the torrent was
  added. That is the field to sort on.
- The caller is `/add` in `app/main.py`, which does
  `torrent_hash = await get_torrent_client().add_torrent(...)` and passes the
  result straight into `insert_history(...)`. It does not inspect the value, so
  returning `None` is silently accepted — the caller needs no change.
- Convention: `snake_case` methods, 4-space indent, private helpers prefixed
  with `_` (see `_login` at `app/main.py:666`). Errors raised as
  `HTTPException(status_code=502, ...)` — see `_login` for the pattern.

## Commands you will need

| Purpose      | Command                              | Expected on success |
|--------------|--------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile app/main.py`  | exit 0              |
| Run tests    | `cd app && python -m pytest -q`      | all pass, exit 0    |

No virtualenv exists in a fresh checkout. Create one **outside** the repo,
install `requirements.txt` + `requirements-dev.txt`, invoke it explicitly.

## Scope

**In scope** (the only files you should modify):
- `app/main.py` — add one private helper to `QbittorrentClient` and call it from
  `add_torrent`.
- `app/tests/test_helpers.py` — add tests for the new helper.

**Out of scope** (do NOT touch):
- `TransmissionClient` — its hash comes back directly from the `torrent-add`
  response; it has no race and needs no retry.
- `QbittorrentClient.completed_hashes` / `torrent_source` — different endpoints,
  not affected by this defect.
- `get_auto_import_candidates` — do **not** relax the `torrent_hash IS NOT NULL`
  guard to accommodate null hashes. A row without a hash genuinely cannot be
  matched to a torrent; the fix is to record the hash, not to weaken the query.
- `/add` and `insert_history` — the caller needs no change.
- Do **not** add a bencode parser or compute the infohash from the `.torrent`
  bytes. That is the robust long-term answer but needs a new dependency, which
  `AGENTS.md` forbids without justification. Noted as deferred below.

## Git workflow

- Work on a branch based on `advisor/plans-001-012`.
- Single commit; present-tense message with no prefix
  (e.g. `Retry qBittorrent hash lookup after add`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a retrying, newest-first hash lookup

Add this private helper to `QbittorrentClient`, immediately after `_login`
(after `app/main.py:672`):

```python
    async def _find_added_hash(self, client: httpx.AsyncClient, mam_id: str,
                               attempts: int = 5, delay: float = 0.5) -> str | None:
        """Find the hash of a just-added torrent by its mamid tag.

        qBittorrent's torrents/add returns no infohash and registers the torrent
        asynchronously, so poll briefly. When several torrents share the tag,
        prefer the most recently added one.
        """
        for attempt in range(attempts):
            r = await client.get(
                f"{settings.QB_URL}/api/v2/torrents/info",
                params={"tag": f"mamid={mam_id}", "filter": "all"},
            )
            try:
                arr = r.json()
            except ValueError:
                arr = []
            if isinstance(arr, list) and arr:
                newest = max(arr, key=lambda t: t.get("added_on") or 0)
                return newest.get("hash")
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
        return None
```

Notes for the executor:
- Total worst-case wait is 4 × 0.5s = 2s (the sleep is skipped after the final
  attempt). `/add` already runs inside a 60-second client timeout, so this is
  comfortably within budget.
- `max(...)` with a `key` returns the first maximum on ties; a tie means two
  torrents were added in the same second, in which case either is acceptable.
- `t.get("added_on") or 0` guards against a missing or null field.

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 2: Call it from `add_torrent`

Replace the tail of `add_torrent` (`app/main.py:687-697`) — everything from
`info = await client.get(` through the final `return None` — with a single call:

```python
            return await self._find_added_hash(client, mam_id)
```

The method's tail becomes:

```python
            if not mam_id:
                return None
            return await self._find_added_hash(client, mam_id)
```

Leave everything above (`_login`, the category/tags assembly, the multipart
`files` payload, the status check) exactly as it is.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "arr\[0\].get(\"hash\")" app/main.py` returns **no** matches.

### Step 3: Add tests

Append to `app/tests/test_helpers.py`:

```python
def test_qb_find_added_hash_prefers_newest_and_retries():
    import asyncio

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        """Returns an empty list N times, then two torrents out of age order."""

        def __init__(self, empties):
            self.empties = empties
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            if self.calls <= self.empties:
                return _Resp([])
            return _Resp([
                {"hash": "OLDER", "added_on": 100},
                {"hash": "NEWEST", "added_on": 900},
            ])

    client = _Client(empties=2)
    got = asyncio.run(
        main.QbittorrentClient()._find_added_hash(client, "42", attempts=5, delay=0)
    )
    assert got == "NEWEST"      # newest wins, not arr[0]
    assert client.calls == 3    # retried past the two empty responses


def test_qb_find_added_hash_gives_up_and_returns_none():
    import asyncio

    class _Resp:
        def json(self):
            return []

    class _Client:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            return _Resp()

    client = _Client()
    got = asyncio.run(
        main.QbittorrentClient()._find_added_hash(client, "42", attempts=3, delay=0)
    )
    assert got is None
    assert client.calls == 3    # exhausted its attempts, no infinite loop
```

Both tests pass `delay=0` so they run instantly. They use a hand-rolled stub
client rather than mocking `httpx`, because the helper only needs an object with
an async `get`.

**Verify**: `cd app && python -m pytest -q` → all pass, including the two new
tests.

## Test plan

- New tests in `app/tests/test_helpers.py`:
  - `test_qb_find_added_hash_prefers_newest_and_retries` — the helper survives
    two empty responses (the race), then picks `added_on: 900` over the
    first-listed `added_on: 100`. This is the regression that the old `arr[0]`
    code fails.
  - `test_qb_find_added_hash_gives_up_and_returns_none` — bounded retries;
    returns `None` after exactly `attempts` calls rather than looping forever.
- Model after the existing helper tests in the same file.
- **Not covered, accept as manual**: behaviour against a real qBittorrent. Add a
  torrent with `TORRENT_CLIENT=qbittorrent` and confirm the History row shows a
  non-empty hash and the item later imports.
- Verification: `cd app && python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "_find_added_hash" app/main.py` shows the definition plus exactly one call site
- [ ] `grep -n 'arr\[0\].get("hash")' app/main.py` returns **no** matches
- [ ] `grep -n "added_on" app/main.py` returns one match (inside the new helper)
- [ ] `grep -c "torrent_hash IS NOT NULL" app/main.py` is 1 — the candidate query was **not** weakened
- [ ] `cd app && python -m pytest -q` exits 0 with the two new tests passing
- [ ] `git status` shows only `app/main.py` and `app/tests/test_helpers.py` modified
- [ ] `plans/README.md` status row for 014 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `QbittorrentClient` does not exist in `app/main.py` — you are on `master`, not
  `advisor/plans-001-012`. Re-base onto that branch.
- The `add_torrent` excerpt does not match the live code.
- A real qBittorrent still yields an empty array after all 5 attempts. Do **not**
  raise `attempts` past ~10 or `delay` past ~1s to force it; that points at a
  different cause (wrong tag, qB's "Automatic Torrent Management" relocating the
  torrent, or the tag not being applied on add). Report what you observed.
- You find yourself wanting to relax `torrent_hash IS NOT NULL` — explicitly out
  of scope; report what pushed you there.

## Maintenance notes

- **The robust fix is deferred deliberately.** Computing the v1 infohash
  (SHA-1 of the bencoded `info` dictionary) from the `.torrent` bytes would make
  the hash known *before* the add, eliminating both the race and the tag lookup
  entirely. It needs a bencode parser — a new dependency, which `AGENTS.md`
  forbids adding without justification. Revisit if qB support becomes
  load-bearing.
- The retry masks latency, it does not eliminate the race. A sufficiently slow
  qBittorrent can still exhaust the attempts and return `None`, producing the
  stranded row described above. If that is observed in practice, the infohash
  computation above is the answer — not a longer timeout.
- Reviewer should confirm `TransmissionClient` was left alone and that the
  auto-import candidate query still requires a non-null hash.
- A companion gap worth knowing: nothing currently surfaces a history row that
  has been sitting in `added` with a null hash. A future plan could flag those
  in the UI rather than leaving them silently inert.
