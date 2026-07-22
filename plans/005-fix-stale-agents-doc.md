# Plan 005: AGENTS.md testing guidance points at endpoints that actually exist

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 92761c0..HEAD -- AGENTS.md app/main.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `92761c0`, 2026-07-22

## Why this matters

`AGENTS.md` is the contributor/agent guide for this repo, and its testing
section tells the reader to "Hit `/health`, `/search`, `/add`, and `/history`
manually." The `/health` endpoint was **removed** (commit `fc9251e`, "remove
health") and no longer exists in `app/main.py`. An agent or contributor
following this guide hits `/health` and gets a 404, wasting time and eroding
trust in the doc. Docs that are actively wrong are worse than missing ones. This
plan corrects the endpoint list to what the app actually serves.

## Current state

- `AGENTS.md:30-35` — the stale section:
  ```markdown
  ## Testing Guidelines

  - There is no formal test suite yet.
  - When changing backend logic, at minimum:
    - Hit `/health`, `/search`, `/add`, and `/history` manually in a dev environment.
    - Verify auto-import behavior with a completed torrent in Transmission.
  ```
- The endpoints that **actually exist** in `app/main.py` (verified by their
  route decorators):
  - `GET /` — `app/main.py:187`
  - `POST /search` — `app/main.py:196`
  - `POST /add` — `app/main.py:416`
  - `GET /account` — `app/main.py:466`
  - `GET /history` — `app/main.py:473`
  - `POST /history/{history_id}/retry` — `app/main.py:498`
  - There is **no** `/health` route.

## Commands you will need

| Purpose                     | Command                              | Expected on success              |
|-----------------------------|--------------------------------------|----------------------------------|
| Confirm `/health` is gone   | `grep -rn "health" app/`             | no matches                       |
| Confirm real routes         | `grep -n "@app\." app/main.py`       | lists the routes named above     |

## Scope

**In scope** (the only file you should modify):
- `AGENTS.md`

**Out of scope** (do NOT touch):
- `app/main.py` — do NOT add a `/health` endpoint to make the doc true; the doc
  is what's wrong, not the code.
- `README.md` — its content is accurate; leave it.

## Git workflow

- Branch: `advisor/005-fix-agents-testing-doc`.
- Single commit; present-tense message (e.g. `Fix stale endpoint list in AGENTS.md`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Correct the manual-test endpoint list

Replace the `/health`-containing bullet in `AGENTS.md` so it lists endpoints
that exist. Rewrite the manual-check bullet to:
```markdown
    - Hit `/search`, `/add`, `/account`, and `/history` manually in a dev environment, and exercise the `Retry` action (`POST /history/{id}/retry`) on a failed row.
```

### Step 2 (conditional): Update the test-suite line if plan 001 has landed

Check whether the pytest suite from plan 001 exists:
```bash
test -f app/tests/test_helpers.py && echo "001 landed" || echo "001 not landed"
```
- If it prints `001 landed`, replace `There is no formal test suite yet.` with:
  ```markdown
  - Run the unit tests with `cd app && python -m pytest -q` before pushing.
  ```
- If it prints `001 not landed`, leave that line unchanged.

**Verify**: `grep -n "health" AGENTS.md` → no matches.

## Test plan

- No code tests (docs-only change).
- Verification is the two greps in "Commands you will need": `/health` appears
  nowhere in `app/` or `AGENTS.md`, and the routes named in the doc match the
  `@app.` decorators in `app/main.py`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -rn "health" AGENTS.md` returns no matches
- [ ] `AGENTS.md` names `/search`, `/add`, `/account`, `/history` and the retry action
- [ ] `git status` shows only `AGENTS.md` modified
- [ ] `plans/README.md` status row for 005 updated

## STOP conditions

Stop and report back (do not improvise) if:

- A `/health` route has reappeared in `app/main.py` (drift) — then the doc may
  be correct and this plan is moot; report it.
- The `AGENTS.md:30-35` excerpt no longer matches the live file.

## Maintenance notes

- When endpoints are added or removed in `app/main.py`, update this section of
  `AGENTS.md` in the same change.
- Reviewer should confirm every endpoint named in `AGENTS.md` has a matching
  route decorator in `app/main.py`.
