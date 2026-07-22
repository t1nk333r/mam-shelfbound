# Plan 011: The search endpoint clamps `perpage` to the allowed set

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 635d2f9..HEAD -- app/main.py`
> If `app/main.py` changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (soft: plan 001 for the unit test)
- **Category**: security (input hardening)
- **Planned at**: commit `635d2f9`, 2026-07-22

## Why this matters

The `/search` endpoint reads `perpage` straight from the request body and
forwards it to MyAnonamouse unchanged:
```python
perpage = payload.get("perpage", 25)
body = {"tor": tor, "perpage": perpage}
```
The UI only ever sends one of `25`, `50`, or `100` (`app/templates/index.html:184-188`),
but a direct API caller can send any value — a huge number (asking MAM for an
enormous result page), a negative, or a non-integer string. MAM likely caps it,
but the app should not forward unvalidated pagination input to an upstream
service. Clamping to the known-good set is a one-helper hardening with no
behavior change for the UI.

## Current state

- `app/main.py:196-211` — the search handler start and the `perpage` handling:
  ```python
  @app.post("/search")
  async def search(payload: dict):
      media_type = normalize_media_type(payload.get("media_type"))
      tor = payload.get("tor", {}) or {}
      ...
      perpage = payload.get("perpage", 25)
      body = {"tor": tor, "perpage": perpage}
  ```
- The UI's only options (`app/templates/index.html:184-188`):
  ```html
      <select id="perpage">
        <option>25</option>
        <option>50</option>
        <option>100</option>
      </select>
  ```
- Existing small coercion helpers to match in style (module-level, `snake_case`,
  defensive): `is_truthy` (`app/main.py:34`), `normalize_media_type`
  (`app/main.py:51`). Follow that pattern.

## Commands you will need

| Purpose        | Command                                  | Expected on success       |
|----------------|------------------------------------------|---------------------------|
| Syntax check   | `python3 -m py_compile app/main.py`      | exit 0                    |
| Run tests      | `cd app && python -m pytest -q`          | all pass (if plan 001 landed) |

## Scope

**In scope** (the only file you should modify):
- `app/main.py` — add a `normalize_perpage` helper and use it in `/search`.
- `app/tests/test_helpers.py` — add a unit test (only if plan 001 has landed).

**Out of scope** (do NOT touch):
- The `tor` search-parameter assembly (`app/main.py:199-208`) — unrelated.
- The frontend `<select>` — it already emits only valid values; no change.
- Do NOT make `perpage` a free-form min/max range; the UI offers a fixed set, so
  an allowlist is the correct contract (see Maintenance notes if that changes).

## Git workflow

- Branch: `advisor/011-clamp-perpage`.
- Single commit; present-tense message (e.g. `Clamp search perpage to allowed values`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the `normalize_perpage` helper

Add near the other coercion helpers (e.g. just after `is_truthy`, around
`app/main.py:37`), including a module-level constant for the allowed set:
```python
ALLOWED_PERPAGE = (25, 50, 100)

def normalize_perpage(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 25
    return n if n in ALLOWED_PERPAGE else 25
```

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 2: Use the helper in `/search`

Replace the raw read at `app/main.py:210`. Before:
```python
    perpage = payload.get("perpage", 25)
```
After:
```python
    perpage = normalize_perpage(payload.get("perpage"))
```
(`normalize_perpage(None)` returns `25`, preserving the previous default when the
field is absent.)

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "normalize_perpage" app/main.py` shows the definition plus the call site.

### Step 3: Add a unit test (only if plan 001 has landed)

Check: `test -f app/tests/test_helpers.py && echo present || echo absent`.
- If **absent**, skip (note the deferred test in the status row).
- If **present**, add to `app/tests/test_helpers.py`:
```python
def test_normalize_perpage():
    assert main.normalize_perpage(50) == 50
    assert main.normalize_perpage("100") == 100
    assert main.normalize_perpage(None) == 25      # missing -> default
    assert main.normalize_perpage(999) == 25       # out of allowed set -> default
    assert main.normalize_perpage("abc") == 25     # non-int -> default
    assert main.normalize_perpage(-1) == 25
```

**Verify**: `cd app && python -m pytest -q` → all pass, including the new test.

## Test plan

- **Unit (required if plan 001 landed)**: `normalize_perpage` returns the value
  for allowed ints (including numeric strings), and `25` for missing, out-of-set,
  negative, or non-numeric input. Model after the existing helper tests.
- **Manual (optional)**: a normal UI search with each of 25/50/100 still returns
  the expected page size (unchanged behavior).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "normalize_perpage\|ALLOWED_PERPAGE" app/main.py` shows the constant, the helper, and the call site
- [ ] `grep -n 'payload.get("perpage", 25)' app/main.py` returns no matches (the raw read is gone)
- [ ] `cd app && python -m pytest -q` exits 0 (if plan 001 landed)
- [ ] `git status` shows only `app/main.py` (and `app/tests/test_helpers.py` if 001 landed) modified
- [ ] `plans/README.md` status row for 011 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `app/main.py:210` excerpt does not match live code.
- A UI search with a valid selection (25/50/100) returns a different page size
  than before — the helper is rejecting a value it should allow; report it.

## Maintenance notes

- If the UI later offers a free-form or larger `perpage`, change
  `normalize_perpage` from an allowlist to a bounded clamp (e.g.
  `max(1, min(n, 100))`) and update `ALLOWED_PERPAGE`/the `<select>` together.
- Reviewer should confirm the default-on-missing behavior (`None -> 25`) matches
  the previous `payload.get("perpage", 25)` default.
