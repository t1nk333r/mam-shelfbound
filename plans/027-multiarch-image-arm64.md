# Plan 027: Release images build for arm64 as well as amd64

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 4ec80a1..HEAD -- .github/workflows/docker-publish.yml`
> If the workflow changed since this plan was written, compare the "Current
> state" excerpts against the live file before editing; on a mismatch, STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW-MED — changes the release pipeline; can't be fully verified without Actions (see note)
- **Depends on**: none
- **Category**: dx (deployment / reach)
- **Planned at**: commit `4ec80a1`, 2026-07-30

## Why this matters

The release workflow builds a **single architecture** — there is no `platforms:`
input on the build step, so images are `linux/amd64` only (the GitHub runner's
arch). Anyone on an **ARM** host (Raspberry Pi, many ARM NAS boxes, Apple-silicon
Docker) cannot pull and run the published image. Adding `linux/arm64` to the
build makes the image a multi-arch manifest so Docker automatically pulls the
right variant. The app is pure Python on `python:3.12-slim` (which is already
multi-arch) with dependencies that ship arm64 wheels, so this is a
build-configuration change, not a code change.

Cross-building arm64 on an amd64 runner requires **QEMU emulation**, which is
**not** currently set up in the workflow — so this plan adds the QEMU setup step
*and* the `platforms:` input. Missing the QEMU step is the usual reason a naive
"just add platforms" change fails.

## Honest verification note (read before starting)

This is the **release pipeline**. Two consequences:
1. **It cannot be fully validated in the worktree** — GitHub Actions runs only on
   GitHub. Your job is to make the change correct and minimal; the definitive
   test is the maintainer's next push to `master`, after which
   `docker manifest inspect ghcr.io/d7eeem/mam-audiofinder-transmission-qbit:<tag>`
   should list **both** `amd64` and `arm64`. Do not claim the multi-arch build
   "works" — claim the workflow edits are correct.
2. The arm64 build runs under emulation and will make the release build slower.
   That is expected, not a failure.

## Current state

`.github/workflows/docker-publish.yml`, the relevant steps in the build job:

```yaml
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v4
      ...
      - name: Build and push image
        uses: docker/build-push-action@v7
        with:
          context: .
          file: ./Dockerfile
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          build-args: |
            APP_VERSION=${{ steps.version.outputs.version }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

There is **no** `Set up QEMU` step and **no** `platforms:` input. Buildx is
already set up (good — buildx is required for multi-arch).

**Convention:** the repo pins actions to floating **majors** (`@v4`, `@v7`), not
SHAs. Keep that style for the new action.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Resolve QEMU action latest major | `gh api repos/docker/setup-qemu-action/releases/latest --jq .tag_name` | a `vN.x.y` tag (expect `v3`) |
| YAML validity | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml')); print('yaml ok')"` | `yaml ok` |
| Confirm platforms added | `grep -n "platforms:" .github/workflows/docker-publish.yml` | one match with amd64,arm64 |
| Confirm QEMU step added | `grep -n "setup-qemu-action" .github/workflows/docker-publish.yml` | one match |

(If `gh` is unavailable, use `@v3` for setup-qemu-action — the current major as of this plan — and note it.)

## Scope

**In scope** (only file you may modify):
- `.github/workflows/docker-publish.yml` — add one QEMU step, add one
  `platforms:` line. Nothing else.

**Out of scope** (do NOT touch):
- Any other workflow step, `Dockerfile`, `app/` code, or the version/tag/release
  logic.
- Do NOT convert action pins to SHAs, or bump any existing action version.
- Do NOT set `platforms:` to anything beyond `linux/amd64,linux/arm64` (more
  arches = much slower builds; out of scope).

## Git workflow

- Branch: `advisor/027-multiarch-image-arm64`
- Short imperative commit subject (e.g. `Build multi-arch (amd64+arm64) images`).
  Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Resolve the QEMU action major

`gh api repos/docker/setup-qemu-action/releases/latest --jq .tag_name` → expect
`v3.x.y`; use the major (`v3`). If `gh` fails, use `v3` and note it.

### Step 2: Add a "Set up QEMU" step before "Set up Docker Buildx"

Immediately **before** the `- name: Set up Docker Buildx` step, insert:

```yaml
      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3
```

(Match the surrounding indentation exactly — steps are indented 6 spaces for the
`- name:` line.)

**Verify**: `grep -n "setup-qemu-action" .github/workflows/docker-publish.yml` → one match, on the line just above the buildx step.

### Step 3: Add the `platforms:` input to the build step

In the `Build and push image` step's `with:` block, add a `platforms:` line
(placement within `with:` doesn't matter; put it right after `file:`):

```yaml
          platforms: linux/amd64,linux/arm64
```

**Verify**:
- `grep -n "platforms:" .github/workflows/docker-publish.yml` → one match reading `linux/amd64,linux/arm64`.
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml')); print('yaml ok')"` → `yaml ok`.
- `git diff .github/workflows/docker-publish.yml` → exactly two additions (the QEMU step and the platforms line); nothing else changed.

## Test plan

- No unit tests apply (CI config only; app untouched).
- **Definitive test (maintainer, needs a real release build):** after this lands
  and a release runs, `docker manifest inspect ghcr.io/d7eeem/mam-audiofinder-transmission-qbit:<newtag>`
  lists both `linux/amd64` and `linux/arm64`. State in your report that this was
  **not** run in the worktree.
- `git status` must show no `app/` changes.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "setup-qemu-action" .github/workflows/docker-publish.yml` → one match
- [ ] `grep -n "platforms:" .github/workflows/docker-publish.yml` → one match, `linux/amd64,linux/arm64`
- [ ] `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml')); print('yaml ok')"` → `yaml ok`
- [ ] `git diff 4ec80a1 HEAD -- .github/workflows/docker-publish.yml` shows only the two additions (QEMU step + platforms line)
- [ ] `git diff 4ec80a1 HEAD -- app/ Dockerfile` → empty
- [ ] `plans/README.md` row for 027 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The build step / buildx step don't match the "Current state" excerpt (drift).
- `gh api` can't resolve setup-qemu-action and you're unsure of the major —
  report rather than guessing beyond `v3`.
- You find the workflow already has a `platforms:` line or a QEMU step (someone
  did this already) — report it.

## Maintenance notes

- arm64 builds run under QEMU emulation and lengthen the release build; if that
  ever becomes painful, native arm64 runners are the upgrade path.
- If a future dependency lacks an arm64 wheel, the arm64 build may start
  compiling from source under emulation (slow) or fail — watch the first
  multi-arch release build.
- Reviewer: confirm only two additions, floating-major pin kept, and no other
  step touched.
