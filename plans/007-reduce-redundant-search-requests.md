# Plan 007: Search tolerates a failed wedge lookup and reuses one HTTP client

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 92761c0..HEAD -- app/main.py`
> If `app/main.py` changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW-MED
- **Depends on**: none (independent of plan 006, which touches a different function)
- **Category**: perf (with a robustness fix)
- **Planned at**: commit `92761c0`, 2026-07-22

## Why this matters

The `/search` endpoint opens **two** separate `httpx.AsyncClient` contexts and
makes **two sequential** upstream calls to MyAnonamouse: one for the search
results, then a second one for the freeleech-wedge count. Two problems:

1. **Robustness bug**: the wedge lookup (`fetch_freeleech_wedge_count` →
   `fetch_account_summary`) **raises `HTTPException(502)`** on any non-200 or
   non-JSON response. Because it runs *after* the search succeeded, a transient
   account-summary hiccup makes the **entire search fail** even though results
   were already in hand. The wedge count is a nice-to-have sidebar number; it
   should never sink a search.
2. **Latency**: results wait on a second round-trip that runs only after the
   first completes, inside a freshly-created client.

This plan makes the wedge lookup best-effort (failure → `None`, search still
returns) and reuses a single client. An optional step runs the two calls
concurrently.

## Current state

`app/main.py:223-238` (the two-client, two-request sequence):
```python
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{settings.MAM_BASE}/tor/js/loadSearchJSONbasic.php",
                                  headers=headers, params=params, json=body)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"MAM request failed: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"MAM HTTP {r.status_code}: {r.text[:300]}")
    try:
        raw = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"MAM returned non-JSON. Body: {r.text[:300]}")

    async with httpx.AsyncClient(timeout=30) as client:
        freeleech_wedges = await fetch_freeleech_wedge_count(client)
```
Relevant helpers:
- `fetch_freeleech_wedge_count(client)` — `app/main.py:168`; calls
  `fetch_account_summary`, which **raises** `HTTPException(502)` on failure
  (`app/main.py:156-166`).
- `asyncio` is already imported (`app/main.py:1`). `httpx` too.
- The `/account` endpoint (`app/main.py:466-470`) deliberately lets wedge
  failures surface; do **not** change it — only `/search` needs to be tolerant,
  because there the wedge number is secondary to the results.

## Commands you will need

| Purpose        | Command                                  | Expected on success       |
|----------------|------------------------------------------|---------------------------|
| Syntax check   | `python3 -m py_compile app/main.py`      | exit 0                    |
| Run tests      | `cd app && python -m pytest -q`          | all pass (if 001 landed)  |
| Import smoke   | `cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_s.db python -c "import main; print('ok')" && rm -f app/tmp_s.db` | prints `ok` |

## Scope

**In scope** (the only file you should modify):
- `app/main.py` — only the `search` function's client/request block
  (`app/main.py:223-238`).

**Out of scope** (do NOT touch):
- `fetch_freeleech_wedge_count` / `fetch_account_summary` — leave their
  raising behavior intact; other callers rely on it.
- `/account` and `/add` endpoints — their wedge handling is intentional.
- The result-flattening logic below line 240 — unchanged.

## Git workflow

- Branch: `advisor/007-search-wedge-tolerance`.
- One commit; present-tense message (e.g. `Make search tolerant of wedge lookup failures`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1 (required): Reuse one client and make the wedge lookup best-effort

Replace the block at `app/main.py:223-238` with a single-client version where
the wedge lookup cannot fail the search:
```python
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(f"{settings.MAM_BASE}/tor/js/loadSearchJSONbasic.php",
                                  headers=headers, params=params, json=body)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"MAM request failed: {e}")

        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"MAM HTTP {r.status_code}: {r.text[:300]}")
        try:
            raw = r.json()
        except ValueError:
            raise HTTPException(status_code=502, detail=f"MAM returned non-JSON. Body: {r.text[:300]}")

        try:
            freeleech_wedges = await fetch_freeleech_wedge_count(client)
        except HTTPException:
            freeleech_wedges = None
```
Behavior change: a failed wedge lookup now yields `freeleech_wedges = None`
(the frontend already renders `None` as "unknown", see
`app/static/app.js:171`) instead of a 502 for the whole search. Everything else
is identical.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and the import smoke
command prints `ok`.

### Step 2 (optional — only if you are confident): Run the two calls concurrently

If you want the latency win too, replace the sequential search+wedge with a
concurrent gather **inside the same client block**:
```python
    async with httpx.AsyncClient(timeout=30) as client:
        async def _fetch_wedges():
            try:
                return await fetch_freeleech_wedge_count(client)
            except HTTPException:
                return None
        try:
            search_task = client.post(f"{settings.MAM_BASE}/tor/js/loadSearchJSONbasic.php",
                                      headers=headers, params=params, json=body)
            r, freeleech_wedges = await asyncio.gather(search_task, _fetch_wedges())
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"MAM request failed: {e}")

        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"MAM HTTP {r.status_code}: {r.text[:300]}")
        try:
            raw = r.json()
        except ValueError:
            raise HTTPException(status_code=502, detail=f"MAM returned non-JSON. Body: {r.text[:300]}")
```
If anything about the concurrent version is unclear, **skip Step 2** — Step 1
alone delivers the robustness fix and the single-client reuse, which is the
important part.

**Verify**: `python3 -m py_compile app/main.py` → exit 0; import smoke prints `ok`.

## Test plan

- `search` calls out over HTTP and is not unit-tested by the plan-001 suite;
  verification here is `py_compile` + the import smoke test.
- If plan 001 landed, `cd app && python -m pytest -q` must still pass (no helper
  behavior changed).
- Manual (recommended): run a real search and confirm results render; then
  simulate a wedge failure (e.g. temporarily point `MAM_BASE` at an endpoint
  that 500s for `jsonLoad.php`) and confirm the search **still returns results**
  with the wedge count showing "unknown" rather than erroring.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "httpx.AsyncClient" app/main.py` shows the `search` function now
      opens **one** client (previously two in that function)
- [ ] the import smoke command prints `ok`
- [ ] `cd app && python -m pytest -q` exits 0 (if plan 001 landed)
- [ ] `git status` shows only `app/main.py` modified
- [ ] `plans/README.md` status row for 007 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `app/main.py:223-238` excerpt does not match live code.
- After the change, a search against a working MAM returns no results when it
  previously did — the `raw`/`r` variable wiring is wrong; revert to Step 1's
  sequential form.
- You attempted Step 2 and the gather form behaves differently (e.g. `r` is not
  the response object) — fall back to Step 1 and report.

## Maintenance notes

- The wedge count is now explicitly a best-effort UI hint on `/search`. If a
  future change makes it load-bearing (e.g. gating an action on wedge
  availability), revisit this tolerance.
- Reviewer should confirm `/account` and `/add` still surface wedge errors
  (only `/search` was made tolerant) and that search results are unaffected.
