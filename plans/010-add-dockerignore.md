# Plan 010: A `.dockerignore` keeps non-runtime files out of the build context

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 635d2f9..HEAD -- Dockerfile docker-compose.yml .github/workflows/docker-publish.yml`
> If any changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `635d2f9`, 2026-07-22

## Why this matters

There is no `.dockerignore`, and the Docker build context is the repo root
(`docker-compose.yml` uses `build: .`; the CI workflow uses `context: .`). So
every build ships the entire working tree — `.git/` history, the `plans/`
directory, root docs, and the screenshot PNGs — to the Docker daemon / buildx,
even though the image only `COPY`s `requirements.txt` and `app/`. This bloats the
build context upload, and unrelated file changes (e.g. editing a plan) can
invalidate build cache layers. A `.dockerignore` fixes both at zero runtime risk.

## Current state

- `docker-compose.yml:3-4`:
  ```yaml
    # `up --build` uses the checked-out source; `pull` can use the published GHCR image.
    build: .
  ```
- `.github/workflows/docker-publish.yml` build step (`:127-138`) uses
  `context: .`.
- `Dockerfile` copies only two things into the image:
  ```dockerfile
  # Dockerfile:12-17
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  RUN mkdir -p /storage /ebooks /ebooks-nosend \
      && ln -s /storage/downloads /downloads \
      && ln -s /storage/audiobooks /library
  COPY app/ /app/
  ```
- Repo tree at root (for reference — what's currently in the context):
  `.git/`, `.github/`, `.gitignore`, `AGENTS.md`, `Dockerfile`, `README.md`,
  `app/`, `docker-compose.yml`, `icon.png`, `plans/`, `requirements.txt`.
- The screenshot PNGs at `app/static/screenshots/` are referenced **only** by
  `README.md` (rendered on GitHub via relative paths); the running app never
  serves them (the UI uses `logo.png` and the `favicon*` files). They are safe to
  exclude from the image.
- `.gitignore` already lists `__pycache__/`, `*.pyc`, `.env`, `/data/`, `*.db` —
  mirror the runtime-junk ones in `.dockerignore` too (`.dockerignore` is
  independent of `.gitignore`).

## Commands you will need

| Purpose                | Command                                  | Expected on success        |
|------------------------|------------------------------------------|----------------------------|
| Confirm file exists    | `cat .dockerignore`                       | prints the entries         |
| Build (optional; needs Docker) | `docker compose build`            | build succeeds             |
| Confirm app files NOT ignored | see Step 2                         | runtime paths still copy   |

(If Docker is unavailable in your environment, skip the build check and rely on
the content/negative-match checks — this change cannot break runtime code, only
what enters the context.)

## Scope

**In scope** (the only file you create):
- `.dockerignore` (create at repo root)

**Out of scope** (do NOT touch):
- `Dockerfile`, `docker-compose.yml`, the CI workflow — no changes needed.
- Do NOT exclude anything under `app/` that the running app needs:
  `app/main.py`, `app/templates/`, `app/static/app.js`, `app/static/common.css`,
  `app/static/common.js` (if still present), `app/static/logo.png`, and
  `app/static/favicon*` must remain in the context.
- Do NOT drop the unused `curl` from the Dockerfile here — that is a separate
  concern (see Maintenance notes); this plan only adds `.dockerignore`.

## Git workflow

- Branch: `advisor/010-dockerignore`.
- Single commit; present-tense message (e.g. `Add .dockerignore`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `.dockerignore`

Create `.dockerignore` at the repo root with these entries (patterns match from
the context root; `app/static/screenshots/` is a repo-doc asset not served at
runtime):
```
# VCS & CI
.git
.gitignore
.github/

# Advisor plans & docs (not needed in the image)
plans/
advisor-plans/
*.md
icon.png

# Compose file (image is built from Dockerfile, not compose)
docker-compose.yml

# Local runtime junk
__pycache__/
*.pyc
*.db
.env
/data/

# Screenshot assets referenced only by README, not served at runtime
app/static/screenshots/

# Test scaffolding (not needed at runtime; present only if plan 001 landed)
app/tests/
app/conftest.py
requirements-dev.txt
```

**Verify**: `cat .dockerignore` prints the entries.

### Step 2: Confirm no runtime file is excluded

Sanity-check that the patterns do not match files the app needs at runtime:
```bash
for f in app/main.py app/templates/base.html app/templates/index.html \
         app/static/app.js app/static/common.css app/static/logo.png \
         app/static/favicon.ico; do
  test -e "$f" && echo "PRESENT: $f"
done
```
None of these match any `.dockerignore` line (only `app/static/screenshots/`,
`app/tests/`, and `app/conftest.py` under `app/` are excluded).

**Verify**: all seven paths print `PRESENT:`.

### Step 3 (optional): Build to confirm

If Docker is available:
```bash
docker compose build
```

**Verify**: build completes successfully. (If Docker is unavailable, skip; this
change cannot affect the built application, only context transfer.)

## Test plan

- No code tests (no source changes). Verification is the file content (Step 1),
  the negative-match check (Step 2), and optionally a successful build (Step 3).
- If plan 001 landed, its suite is unaffected: `cd app && python -m pytest -q`
  still passes (nothing in `app/` runtime code changed).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.dockerignore` exists at the repo root and contains `.git`, `plans/`, and `app/static/screenshots/`
- [ ] The Step 2 loop prints `PRESENT:` for all seven runtime paths
- [ ] `git status` shows only the new `.dockerignore`
- [ ] `plans/README.md` status row for 010 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `docker compose build` (Step 3, if run) fails with a missing-file error during
  `COPY app/ /app/` — a `.dockerignore` pattern is excluding something the image
  needs; report which path.
- The build context or Dockerfile has changed such that files outside `app/` are
  now `COPY`'d into the image (the excerpt no longer matches) — reconcile the
  ignore list before finalizing.

## Maintenance notes

- If the Dockerfile later `COPY`s additional top-level files into the image, make
  sure they are not excluded here.
- Related deferred build-hygiene items found in the same audit, each a separate
  small change if desired: the Dockerfile installs `curl` (`Dockerfile:11`) which
  is unused since the healthcheck was removed, and the base image
  `python:3.12-slim` is a moving tag (not digest-pinned). Neither is in scope
  here.
- Reviewer should confirm nothing under `app/` that the app serves at runtime is
  excluded.
