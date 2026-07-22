# Plan 002: Dependency versions are pinned so builds are reproducible

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 92761c0..HEAD -- requirements.txt Dockerfile`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: migration (dependencies)
- **Planned at**: commit `92761c0`, 2026-07-22

## Why this matters

`requirements.txt` pins nothing:
```
fastapi
uvicorn[standard]
jinja2
httpx
sqlalchemy
```
Every `docker compose build` resolves the latest release of each package at
build time, so two builds of the same commit can ship different dependency
trees, and a breaking major release lands with **zero warning**. This is not
hypothetical for this codebase: `app/main.py` uses the FastAPI
`@app.on_event(...)` API (`app/main.py:899,903`), which is deprecated and
scheduled for removal — the day an unpinned `fastapi` drops it, the container
crashes on startup. Pinning makes builds reproducible and turns dependency
upgrades into deliberate, reviewable changes.

## Current state

- `requirements.txt` (the full file):
  ```
  fastapi
  uvicorn[standard]
  jinja2
  httpx
  sqlalchemy
  ```
- `Dockerfile:12-13` installs exactly this file into the runtime image:
  ```dockerfile
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  ```
- Base image is `python:3.12-slim` (`Dockerfile:1`).
- Repo convention (`AGENTS.md`): "Do not add new dependencies without updating
  `requirements.txt` and explaining why." This plan does not add dependencies —
  it pins the existing five.

## Commands you will need

| Purpose                | Command                                                                 | Expected on success        |
|------------------------|-------------------------------------------------------------------------|----------------------------|
| Resolve current versions | `pip install fastapi "uvicorn[standard]" jinja2 httpx sqlalchemy && pip freeze` | prints resolved versions   |
| Syntax check           | `python3 -m py_compile app/main.py`                                     | exit 0                     |
| Build image (optional) | `docker compose build`                                                  | build succeeds             |

## Scope

**In scope** (the only file you should modify):
- `requirements.txt`

**Out of scope** (do NOT touch):
- `Dockerfile`, `docker-compose.yml` — no changes needed.
- `app/main.py` — do NOT migrate `on_event` here; that is plan 004. This plan
  only pins versions so the current code keeps working.
- Do NOT add a lockfile tool (pip-tools, Poetry) — out of scope; keep the plain
  `requirements.txt` format the repo already uses.

## Git workflow

- Branch: `advisor/002-pin-dependencies`.
- Single commit; present-tense message (e.g. `Pin runtime dependency versions`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Resolve the exact versions that currently work

In a clean environment (or a throwaway venv), install the five packages and
capture the resolved versions:
```bash
python3 -m venv /tmp/pinvenv && . /tmp/pinvenv/bin/activate
pip install fastapi "uvicorn[standard]" jinja2 httpx sqlalchemy
pip show fastapi uvicorn jinja2 httpx sqlalchemy | grep -E '^(Name|Version):'
deactivate
```
Record the five `Name`/`Version` pairs. These are the versions the app is known
to run against today.

**Verify**: you have a concrete version string for each of `fastapi`,
`uvicorn`, `jinja2`, `httpx`, `sqlalchemy`.

### Step 2: Write the pinned requirements

Rewrite `requirements.txt` pinning each package to a **compatible-release**
range on the minor line you resolved (this allows patch/minor security fixes
while forbidding surprise majors). Use the versions from Step 1. Example shape
(substitute the real resolved versions — do NOT copy these placeholder numbers
blindly):
```
fastapi==0.115.*
uvicorn[standard]==0.34.*
jinja2==3.1.*
httpx==0.28.*
sqlalchemy==2.0.*
```
Keep `uvicorn[standard]` with its extras marker exactly as written.

**Verify**:
`python3 -c "print(open('requirements.txt').read())"` shows all five lines
pinned with `==` and a `.*` patch wildcard, and `uvicorn[standard]` retains its
extras.

### Step 3: Confirm the pins install and the app still compiles

```bash
python3 -m venv /tmp/pinverify && . /tmp/pinverify/bin/activate
pip install -r requirements.txt
deactivate
python3 -m py_compile app/main.py
```

**Verify**: `pip install -r requirements.txt` exits 0 and resolves without
conflicts; `py_compile` exits 0.

## Test plan

- No new unit tests (this is a manifest change). If plan 001 has landed, run its
  suite against the pinned deps to confirm nothing regressed:
  `pip install -r requirements-dev.txt && cd app && python -m pytest -q` → all
  pass.
- Otherwise the verification is the clean `pip install -r requirements.txt` in
  Step 3.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `requirements.txt` pins all five packages with explicit `==` version constraints
- [ ] `pip install -r requirements.txt` in a clean venv exits 0
- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `git status` shows only `requirements.txt` modified
- [ ] `plans/README.md` status row for 002 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The current `requirements.txt` already contains version pins (drift — the
  excerpt above no longer matches); reconcile before rewriting.
- The resolved current version of `fastapi` is one that has **already removed**
  `on_event` and importing/compiling reveals the app is broken at the current
  commit — report this, because plan 004 (API modernization) then becomes a
  prerequisite rather than a follow-up.
- A dependency fails to resolve at the version you pinned.

## Maintenance notes

- Dependency upgrades are now explicit: bump the pin, rebuild, run the tests.
  Consider a Dependabot/Renovate config as a later DX plan (out of scope here).
- The `on_event` deprecation (plan 004) is the most urgent reason these pins
  matter — do not defer 004 indefinitely just because the version is pinned;
  pinning buys time, it doesn't remove the deprecation.
- Reviewer should confirm the pinned versions match what CI and the Docker image
  actually build with, and that `uvicorn[standard]` kept its extras marker.
