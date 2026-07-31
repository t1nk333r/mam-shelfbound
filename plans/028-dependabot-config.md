# Plan 028: Add a Dependabot config to automate dependency & action updates

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 4ec80a1..HEAD -- .github/`
> If `.github/dependabot.yml` already exists, STOP (see STOP conditions).

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW — additive config file; opens PRs, changes nothing else
- **Depends on**: none
- **Category**: dx (tooling / maintenance)
- **Planned at**: commit `4ec80a1`, 2026-07-30

## Why this matters

There is no `.github/dependabot.yml`, so dependency and GitHub-Actions updates
are entirely manual. Plan 022 had to bump six actions off the deprecated Node-20
runtime **by hand**, and its own note flagged that a Dependabot config would turn
these into reviewable PRs instead of drift-until-deprecation. This adds that
config for three ecosystems the repo actually uses: **GitHub Actions** (the
workflow), **Docker** (the base image in `Dockerfile`), and **pip** (`requirements*.txt`).

It is a no-code, no-runtime change — GitHub reads `dependabot.yml` from the
default branch and starts opening update PRs on the schedule.

## Current state

- No `.github/dependabot.yml` (confirmed absent at plan time).
- The repo has all three target ecosystems:
  - GitHub Actions: `.github/workflows/docker-publish.yml` pins several
    `actions/*` and `docker/*` actions.
  - Docker: `Dockerfile` uses `FROM python:3.12-slim`.
  - pip: `requirements.txt` and `requirements-dev.txt` in the repo root.

**Convention:** the repo is a single service at the root (no monorepo), so all
ecosystems use `directory: "/"`. Dependabot special-cases `github-actions` to
scan `.github/workflows/` regardless.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Confirm file is absent first | `ls .github/dependabot.yml 2>/dev/null` | no output (must not exist yet) |
| YAML validity | `python3 -c "import yaml; yaml.safe_load(open('.github/dependabot.yml')); print('yaml ok')"` | `yaml ok` |
| Confirm three ecosystems | `grep -c "package-ecosystem" .github/dependabot.yml` | `3` |

## Scope

**In scope** (the only file you create):
- `.github/dependabot.yml` — **create**.

**Out of scope** (do NOT touch):
- Any workflow file, `Dockerfile`, `requirements*.txt`, or `app/` code. Do not
  "pre-bump" any dependency — Dependabot will open those PRs itself.

## Git workflow

- Branch: `advisor/028-dependabot-config`
- Short imperative commit subject (e.g. `Add Dependabot config`). Do NOT push or
  open a PR unless instructed.

## Steps

### Step 1: Create `.github/dependabot.yml`

Write exactly this content:

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: "ci"

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

**Verify**:
- `python3 -c "import yaml; yaml.safe_load(open('.github/dependabot.yml')); print('yaml ok')"` → `yaml ok`
- `grep -c "package-ecosystem" .github/dependabot.yml` → `3`

## Test plan

- No unit tests (config only; app untouched).
- **Definitive check (maintainer, on GitHub):** after this lands on the default
  branch, the repo's **Insights → Dependency graph → Dependabot** tab shows the
  three ecosystems enabled, and update PRs begin appearing on schedule. State in
  your report that this GitHub-side behavior was not (and can't be) verified in
  the worktree.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.github/dependabot.yml` exists and `python3 -c "import yaml; yaml.safe_load(open('.github/dependabot.yml'))"` exits 0
- [ ] `grep -c "package-ecosystem" .github/dependabot.yml` → `3` (github-actions, docker, pip)
- [ ] `git status --porcelain` shows only the new `.github/dependabot.yml`
- [ ] `git diff 4ec80a1 HEAD -- app/ Dockerfile requirements.txt requirements-dev.txt .github/workflows/` → empty
- [ ] `plans/README.md` row for 028 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `.github/dependabot.yml` already exists — do not overwrite; report its contents.
- `requirements.txt` / `requirements-dev.txt` / `Dockerfile` are no longer at the
  repo root (the `directory: "/"` assumption would be wrong) — report the layout.

## Maintenance notes

- The `pip` ecosystem will open PRs against `requirements*.txt`; if that proves
  noisy, the maintainer can drop that one `- package-ecosystem: "pip"` block or
  add `open-pull-requests-limit` / `groups` to batch them. Left simple here on
  purpose.
- Dependabot respects the repo's existing floating-major action pins and will
  propose major bumps as PRs — review them like plan 022 did (check for breaking
  input changes before merging).
- Reviewer: confirm it's a pure addition and no dependency was hand-bumped in the
  same change.
