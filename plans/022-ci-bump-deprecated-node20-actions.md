# Plan 022: CI actions run on a supported Node runtime (off deprecated Node 20)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. Touch
> only the file in scope. If any STOP condition occurs, stop and report — do not
> improvise. Commit on your current worktree branch. Do NOT update
> `plans/README.md` — the reviewer maintains it.
>
> **Written against**: `master` @ `000a178`, 2026-07-25.
> **Drift check (run first)**: `git diff --stat 000a178..HEAD -- .github/workflows/docker-publish.yml`
> If it changed since this plan was written, compare the "Current state" lines
> against the live file before editing; on a mismatch treat it as a STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW-MED — see "Honest risk note"
- **Depends on**: none
- **Category**: dx (CI maintenance)
- **Planned at**: commit `000a178`, 2026-07-25

## Why this matters

The v0.0.1 release build **succeeded**, but GitHub annotated the run: the pinned
actions target **Node 20**, which GitHub is deprecating, and were force-run on
Node 24. This is a warning today; it becomes a hard failure when GitHub removes
the Node 20 runner. Bumping each action to its current major (which ships on the
supported Node runtime) clears the warning and future-proofs the release
pipeline. This is preventive maintenance on a working pipeline, not a bug fix.

## Honest risk note (read before starting)

This is the **release pipeline** that publishes the GHCR image and cuts version
tags. Two consequences you must respect:

1. Several actions jump **multiple majors** (see table). Major bumps *can* carry
   breaking input changes. The workflow's usage is deliberately simple (see
   "Current state") and these inputs are stable across the bumps, but you must
   confirm rather than assume — see STOP conditions.
2. **This change cannot be fully validated in the worktree.** GitHub Actions only
   runs on GitHub. The real proof is the next push to `master`. Your job is to
   make the change *correct and low-risk*; final validation happens when the
   maintainer pushes. Do not claim the pipeline "works" — claim the pins are
   valid and resolve to real releases.

## Current state

`.github/workflows/docker-publish.yml` — the seven `uses:` lines and the
**only** inputs the workflow passes to each (verified; these are what must stay
compatible):

```yaml
# line 23 and 46:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # line 46 only; line 23 has no `with:`
# line 25:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
# line 120:
      - uses: docker/setup-buildx-action@v3      # no inputs
# line 124:
      - uses: docker/login-action@v3
        with: { registry, username, password }   # standard
# line 132:
      - uses: docker/metadata-action@v5
        with: { images, tags, labels }           # standard
# line 147:
      - uses: docker/build-push-action@v6
        with: { context, file, push, tags, labels, build-args, cache-from, cache-to }
```

All of these inputs (`fetch-depth`, `python-version`, `registry/username/password`,
`images/tags/labels`, `context/file/push/tags/labels/build-args/cache-from/cache-to`)
have been stable across the major versions involved. That is what makes a
multi-major bump low-risk *here* specifically.

### Target versions (authoritative, resolved from GitHub on 2026-07-25)

Do not trust these numbers blindly — **re-resolve them in Step 1** in case a new
major published since. They are the expected answer:

| Action | Current | Latest major | Jump |
|---|---|---|---|
| `actions/checkout` | `v4` | **`v7`** | +3 |
| `actions/setup-python` | `v5` | **`v7`** | +2 |
| `docker/setup-buildx-action` | `v3` | **`v4`** | +1 |
| `docker/login-action` | `v3` | **`v4`** | +1 |
| `docker/metadata-action` | `v5` | **`v6`** | +1 |
| `docker/build-push-action` | `v6` | **`v7`** | +1 |

Keep the **floating-major** style the workflow already uses (`@v7`, not
`@v7.0.1`, not a SHA). SHA-pinning is a *separate* supply-chain concern and is
explicitly out of scope here — do not introduce it.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Resolve latest major | `gh api repos/<owner>/<action>/releases/latest --jq .tag_name` | a `vN.x.y` tag |
| YAML validity | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml')); print('yaml ok')"` | `yaml ok` |
| Confirm no stale pins | `grep -nE "uses: (actions|docker)/" .github/workflows/docker-publish.yml` | all at the new majors |

(If `gh` is unauthenticated in your environment, `gh api` still works for public
release reads; if it fails entirely, report it rather than guessing versions.)

## Scope

**In scope** (the only file you may modify):
- `.github/workflows/docker-publish.yml` — bump the six action major versions
  (seven `uses:` lines; `actions/checkout` appears twice).

**Out of scope** (do NOT touch):
- Any `app/` file, `Dockerfile`, `docker-compose.yml`, `requirements*`. This is a
  CI-only change.
- The workflow's **logic** — jobs, steps, `run:` blocks, `if:` conditions,
  version-computation, the release/tag steps. Change **only** the `@vN` suffix on
  the six `uses:` lines. Everything else stays byte-identical.
- Do NOT convert floating tags to SHAs.
- Do NOT add, remove, or reorder steps or actions.

## Steps

### Step 1: Re-resolve the latest major of each action

For each action, confirm the current latest major (guards against the plan's
table being stale):

```bash
for repo in actions/checkout actions/setup-python \
            docker/setup-buildx-action docker/login-action \
            docker/metadata-action docker/build-push-action; do
  echo "$repo -> $(gh api repos/$repo/releases/latest --jq .tag_name)"
done
```

Record the major (the `vN` part) for each. If any differs from the plan's table,
use the **freshly resolved** value and note the difference in your report.

### Step 2: Bump the six `uses:` lines

Edit `.github/workflows/docker-publish.yml`, changing only the version suffix:

- `actions/checkout@v4` → `@v7` — **both** occurrences (lines 23 and 46)
- `actions/setup-python@v5` → `@v7`
- `docker/setup-buildx-action@v3` → `@v4`
- `docker/login-action@v3` → `@v4`
- `docker/metadata-action@v5` → `@v6`
- `docker/build-push-action@v6` → `@v7`

(Use the majors you resolved in Step 1 if they differ.)

**Verify**:
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml')); print('yaml ok')"` → `yaml ok`
- `grep -nE "uses: (actions|docker)/" .github/workflows/docker-publish.yml` → every
  line shows the new major; no `@v4`/`@v5`/`@v3`/`@v6` stragglers from the old set.
- `git diff .github/workflows/docker-publish.yml` → shows **only** the six/seven
  `@vN` suffix changes, nothing else.

### Step 3: Confirm each new pin resolves to a real release

For each bumped action, confirm the major you pinned actually exists (so CI won't
fail on an unresolvable tag):

```bash
gh api repos/actions/checkout/git/refs/tags/v7 --jq .ref        # -> refs/tags/v7
# ...repeat for each: setup-python v7, setup-buildx-action v4,
#    login-action v4, metadata-action v6, build-push-action v7
```

Each must return a ref (the floating major tag exists). If any 404s, you pinned a
major that has no floating tag — STOP and report.

## Test plan

- There is no local way to run GitHub Actions. Verification is: YAML validity,
  every pin resolves to a published floating-major tag, and the diff is
  suffix-only.
- **The definitive test is the next push to `master`**, which triggers the
  workflow; the maintainer performs that, and confirms the run is green with no
  Node-20 deprecation annotation. State this explicitly in your report — do not
  represent the change as verified-working.
- The app test suite is unaffected (no `app/` change); you need not run it, but
  `git status` must show no `app/` modifications.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -nE "uses: (actions|docker)/" .github/workflows/docker-publish.yml`
      shows: checkout `@v7` (×2), setup-python `@v7`, setup-buildx-action `@v4`,
      login-action `@v4`, metadata-action `@v6`, build-push-action `@v7`
      (or the freshly-resolved majors if newer)
- [ ] `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-publish.yml')); print('yaml ok')"` → `yaml ok`
- [ ] Each pinned major resolves via `gh api .../git/refs/tags/vN` (Step 3)
- [ ] `git diff 000a178 HEAD --stat` shows **only** `.github/workflows/docker-publish.yml` changed
- [ ] `git diff 000a178 HEAD` contains only `@vN` suffix changes on `uses:` lines — no logic changes

## STOP conditions

Stop and report back (do not improvise) if:

- The `uses:` lines don't match the "Current state" list (the workflow drifted).
- `gh api` cannot resolve an action's latest release — report rather than guess a
  version number.
- Reading a new major's release notes reveals a **breaking change to an input the
  workflow uses** (`fetch-depth`, `python-version`, `registry/username/password`,
  `images/tags/labels`, `context/file/push/tags/labels/build-args/cache-from/cache-to`).
  Report the specific action, version, and breaking change — do not adapt the
  workflow logic to accommodate it (that would be out of scope and unreviewed).
- You find yourself changing anything other than the six `@vN` suffixes.

## Maintenance notes

- This is the maintenance a Dependabot/Renovate config would automate. Adding one
  (`.github/dependabot.yml` for the `github-actions` ecosystem) is a reasonable
  **separate** follow-up so these bumps arrive as reviewable PRs instead of
  drifting until deprecation — not in scope here.
- Reviewer should confirm the diff is suffix-only, that floating-major style was
  kept (no SHAs), and that no workflow logic changed. Final sign-off waits on the
  next `master` CI run being green with no Node-20 annotation.
