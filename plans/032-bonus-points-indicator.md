# Plan 032: Show MAM bonus points beside the freeleech-wedge indicator

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. Touch
> only the files listed as in scope. If any STOP condition occurs, stop and
> report — do not improvise. Commit on your worktree branch. When done, update
> the status row for this plan in `plans/README.md` unless a reviewer told you
> they maintain the index.
>
> **Drift check (run first)**: `git diff --stat 4caefc1..HEAD -- app/main.py app/static/app.js app/tests/`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before editing; on a mismatch, STOP.

## Status

- **Priority**: P3
- **Effort**: S-M
- **Risk**: LOW — display + pure value extraction; touches no torrent/freeleech business logic; degrades to "unknown" if the field is absent
- **Depends on**: none
- **Category**: feature (frontend UX)
- **Planned at**: commit `4caefc1`, 2026-08-03

## Why this matters

The account-status line shows only **freeleech wedges** ("Freeleech wedges: 249").
MyAnonamouse accounts also have **bonus points** (a separate currency earned by
seeding), returned in the *same* account-summary response the app already fetches.
This plan surfaces bonus points next to the wedge count — a small, useful
indicator — without any extra MAM request: it extracts a second value from the
summary that `fetch_account_summary` already returns, and displays it.

The bonus-points value is refreshed on page load (via `GET /account`) and kept on
screen across searches/adds. That's appropriate: unlike freeleech wedges (spent
per add), bonus points change slowly, so they don't need to re-fetch on every action.

## Current state

`app/main.py` — the account summary is fetched once and the wedge count pulled
from it (`app/main.py:285-306`):

```python
async def fetch_account_summary(client: httpx.AsyncClient) -> dict:
    resp = await client.get(f"{settings.MAM_BASE}/jsonLoad.php", headers=mam_headers())
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"MAM account summary failed: {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="MAM account summary returned non-JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="MAM account summary returned unexpected data")
    return data

async def fetch_freeleech_wedge_count(client: httpx.AsyncClient) -> int | None:
    data = await fetch_account_summary(client)
    wedges = data.get("wedges")
    if wedges is None:
        return None
    try:
        value = int(wedges)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None
```

The `/account` endpoint (`app/main.py:621-625`):

```python
@app.get("/account")
async def account_status():
    async with httpx.AsyncClient(timeout=30) as client:
        freeleech_wedges = await fetch_freeleech_wedge_count(client)
    return {"freeleech_wedges": freeleech_wedges}
```

`fetch_freeleech_wedge_count` is **also** called by `/search` (`app/main.py:396`)
and `/add` (`app/main.py:594`) for their freeleech logic — **leave those two paths
alone**; this plan does not change them (the frontend keeps the last-known bonus
value across search/add).

`app/static/app.js` — the display (`app/static/app.js:255-268`):

```javascript
function setAccountStatus(value) {
  if (!accountStatusEl) return;
  accountStatusEl.textContent = `Freeleech wedges: ${value ?? 'unknown'}`;
}

async function refreshAccountStatus() {
  if (!accountStatusEl) return;
  accountStatusEl.textContent = 'Freeleech wedges: loading...';
  try {
    const data = await fetchJson('/account');
    setAccountStatus(data?.freeleech_wedges);
  } catch (e) {
    console.error('account status failed', e);
    accountStatusEl.textContent = 'Freeleech wedges: unavailable';
  }
}
```

`setAccountStatus` is also called after `/search` (`app.js:124`) and `/add`
(`app.js:218`) as `setAccountStatus(data?.freeleech_wedges)` — a single argument.

**The MAM field for bonus points:** MyAnonamouse's `jsonLoad.php` returns bonus
points as **`seedbonus`**. This plan reads that, with defensive fallbacks
(`bonus`, `bonusPoints`, `points`) — matching how the codebase already tries
multiple keys (see `detect_format` and the `free`/`fl_vip` checks). This exact
field name **cannot be verified without a live MAM cookie**; if bonus shows
"unknown" in production, the maintainer confirms the real key (see Maintenance
notes). The feature degrades safely either way.

**Repo conventions:** flat helper functions in `main.py`; tests are plain pytest
`import main` functions — see `app/tests/test_helpers.py:1-27`. Vanilla-JS
frontend, no framework/build, no JS test runner.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Backend tests | `cd app && python -m pytest -q` | all pass incl. new tests |
| JS syntax | `node --check app/static/app.js` | exit 0 |
| Confirm extractors | `grep -n "def extract_bonus_points\|def extract_wedge_count\|def _nonneg_int" app/main.py` | 3 matches |
| Confirm `/account` returns bonus | `grep -n '"bonus_points"' app/main.py` | 1 match (in the `/account` return) |

(`node` is available; the venv with deps is at `/tmp/exec030-venv` — reuse it, or make one from `requirements.txt` + `requirements-dev.txt`.)

## Scope

**In scope** (only these files):
- `app/main.py` — add three pure helpers, refactor `fetch_freeleech_wedge_count`
  to use one of them (behavior-preserving), and make `/account` return `bonus_points`.
- `app/static/app.js` — display both wedges and bonus, preserving bonus across
  search/add updates.
- `app/tests/test_account.py` — **create**; unit-test the pure extractors.

**Out of scope** (do NOT touch):
- `/search` and `/add` (`app/main.py` ~396 and ~588-619) and the freeleech
  spend/decrement logic — unchanged. Do NOT add a second MAM request there.
- `app/templates/index.html` — the `#accountStatus` element already exists and
  its initial "loading" text is overwritten on load; no markup change.
- Any torrent-client code.

## Git workflow

- Branch: `advisor/032-bonus-points-indicator`
- Short imperative commit subject (e.g. `Show MAM bonus points beside wedges`).
  Do NOT push or open a PR.

## Steps

### Step 1: Add pure value extractors in `app.js`'s backend (`app/main.py`)

Add these three helpers immediately **above** `fetch_freeleech_wedge_count`:

```python
def _nonneg_int(raw) -> int | None:
    """Coerce a MAM numeric field (int/float/str) to a non-negative int, else None."""
    if raw is None:
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None

def extract_wedge_count(data: dict) -> int | None:
    return _nonneg_int(data.get("wedges"))

def extract_bonus_points(data: dict) -> int | None:
    # MAM's jsonLoad.php returns bonus points as `seedbonus`; fallbacks for safety.
    for key in ("seedbonus", "bonus", "bonusPoints", "points"):
        if data.get(key) is not None:
            return _nonneg_int(data.get(key))
    return None
```

Then refactor `fetch_freeleech_wedge_count` (`app/main.py:297-306`) to reuse the
extractor — this preserves its exact behavior (so `/search` and `/add` are unaffected):

```python
async def fetch_freeleech_wedge_count(client: httpx.AsyncClient) -> int | None:
    data = await fetch_account_summary(client)
    return extract_wedge_count(data)
```

**Verify**: `grep -n "def extract_bonus_points\|def extract_wedge_count\|def _nonneg_int" app/main.py` → 3 matches; `python -m py_compile app/main.py` → exit 0.

### Step 2: Return `bonus_points` from `/account` (one fetch, both values)

Change the `/account` endpoint (`app/main.py:621-625`) to fetch the summary once
and extract both:

```python
@app.get("/account")
async def account_status():
    async with httpx.AsyncClient(timeout=30) as client:
        data = await fetch_account_summary(client)
    return {
        "freeleech_wedges": extract_wedge_count(data),
        "bonus_points": extract_bonus_points(data),
    }
```

**Verify**: `grep -n '"bonus_points"' app/main.py` → 1 match; `python -m py_compile app/main.py` → exit 0.

### Step 3: Display both values in `app/static/app.js` (preserve bonus across search/add)

Replace `setAccountStatus` (`app/static/app.js:255-258`) with a two-value version
backed by module state, so a search/add that only reports wedges keeps the
last-known bonus on screen:

```javascript
let lastWedges = null;
let lastBonus = null;

function renderAccountStatus() {
  if (!accountStatusEl) return;
  const w = lastWedges ?? 'unknown';
  const b = (lastBonus == null) ? 'unknown' : Number(lastBonus).toLocaleString();
  accountStatusEl.textContent = `Freeleech wedges: ${w} · Bonus points: ${b}`;
}

function setAccountStatus(wedges, bonus) {
  if (wedges !== undefined) lastWedges = wedges;
  if (bonus !== undefined) lastBonus = bonus;
  renderAccountStatus();
}
```

Then update `refreshAccountStatus` (`app/static/app.js:260-268`) to pass both and
to show both in its loading/unavailable states:

```javascript
async function refreshAccountStatus() {
  if (!accountStatusEl) return;
  accountStatusEl.textContent = 'Freeleech wedges: loading... · Bonus points: loading...';
  try {
    const data = await fetchJson('/account');
    setAccountStatus(data?.freeleech_wedges, data?.bonus_points);
  } catch (e) {
    console.error('account status failed', e);
    accountStatusEl.textContent = 'Freeleech wedges: unavailable · Bonus points: unavailable';
  }
}
```

Do **not** change the two existing `setAccountStatus(data?.freeleech_wedges)` calls
at `app.js:124` (after `/search`) and `app.js:218` (after `/add`) — with the new
signature their omitted second argument leaves `lastBonus` intact, which is the
intended behavior.

**Verify**: `node --check app/static/app.js` → exit 0; `grep -n "Bonus points" app/static/app.js` → present in `renderAccountStatus` + the loading/unavailable lines.

### Step 4: Unit-test the extractors

Create `app/tests/test_account.py` (model after `app/tests/test_helpers.py`):

```python
import main


def test_extract_wedge_count():
    assert main.extract_wedge_count({"wedges": 249}) == 249
    assert main.extract_wedge_count({"wedges": "249"}) == 249
    assert main.extract_wedge_count({}) is None
    assert main.extract_wedge_count({"wedges": -1}) is None


def test_extract_bonus_points_from_seedbonus():
    assert main.extract_bonus_points({"seedbonus": 123456}) == 123456
    assert main.extract_bonus_points({"seedbonus": "123456.7"}) == 123456


def test_extract_bonus_points_fallback_keys():
    assert main.extract_bonus_points({"bonus": 5}) == 5
    assert main.extract_bonus_points({"points": 7}) == 7


def test_extract_bonus_points_missing_returns_none():
    assert main.extract_bonus_points({"wedges": 10}) is None


def test_extract_bonus_points_negative_returns_none():
    assert main.extract_bonus_points({"seedbonus": -3}) is None
```

**Verify**: `cd app && python -m pytest -q` → all pass, 5 new tests.

## Test plan

- New file `app/tests/test_account.py` — unit tests for `extract_wedge_count` and
  `extract_bonus_points` (seedbonus, fallback keys, missing → None, negative →
  None, string/float coercion). Pattern: `app/tests/test_helpers.py`.
- No JS test framework exists; the display is verified in a browser by the
  reviewer/maintainer (load the app → the account line reads
  `Freeleech wedges: N · Bonus points: M`; on a MAM/network failure it reads
  `… unavailable`). State plainly that you did not run the browser check headlessly.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "def _nonneg_int\|def extract_wedge_count\|def extract_bonus_points" app/main.py` → 3 matches
- [ ] `grep -n '"bonus_points"' app/main.py` → 1 match (the `/account` return)
- [ ] `fetch_freeleech_wedge_count` now calls `extract_wedge_count` (`grep -n "extract_wedge_count" app/main.py` → ≥ 2)
- [ ] `grep -n "Bonus points" app/static/app.js` → present in the render + loading/unavailable text
- [ ] `node --check app/static/app.js` → exit 0
- [ ] `cd app && python -m pytest -q` → all pass; `app/tests/test_account.py` exists with 5 tests
- [ ] `git status --porcelain` shows only `app/main.py`, `app/static/app.js`, and new `app/tests/test_account.py`
- [ ] `plans/README.md` row for 032 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `fetch_account_summary` / `fetch_freeleech_wedge_count` / `/account` /
  `setAccountStatus` don't match the "Current state" excerpts (drift).
- Making bonus show up seems to require editing `/search` or `/add` or adding a
  second MAM request — it doesn't; the frontend preserves bonus across those.
- A test fails because the extractor coercion differs from the spec — report the
  actual behavior rather than loosening the test.

## Maintenance notes

- **Field-name verification (deferred, maintainer):** `seedbonus` is the expected
  MAM `jsonLoad.php` key for bonus points, but it can't be confirmed here without a
  live cookie. If the indicator shows `Bonus points: unknown` against a real
  account, temporarily log `sorted(data.keys())` inside `account_status` (or
  inspect the `/account` JSON) to find the actual key, then add it to the tuple in
  `extract_bonus_points`. The fallbacks (`bonus`, `bonusPoints`, `points`) cover
  the common alternatives.
- Bonus refreshes only on `/account` (page load), by design — it's a
  slowly-changing metric. If you ever want it to update after each add, add
  `bonus_points` to the `/add` response and pass it through `setAccountStatus`.
- Reviewer: confirm `/search` and `/add` and the freeleech decrement are untouched,
  that the extractors are pure and tested, and (render check) that the line shows
  both values and both degrade to "unavailable" together.
