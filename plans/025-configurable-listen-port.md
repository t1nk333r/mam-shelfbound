# Plan 025: The container's listen port is configurable via a PORT env var

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat a13593e..HEAD -- Dockerfile README.md`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live files before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW-MED — see "Honest verification note"
- **Depends on**: none (fully independent of 023 and 024 — different files)
- **Category**: dx (deployment)
- **Planned at**: commit `a13593e`, 2026-07-27

## Why this matters

The image hardcodes `--port 8080` in its entrypoint. When the container runs in
a **shared network namespace** — the common VPN-sidecar pattern,
`network_mode: service:gluetun` — port 8080 collides with other services in that
namespace (SABnzbd's WebUI defaults to 8080), and two processes cannot bind the
same port in one namespace, so the container crash-loops with "address already
in use." A real deployment hit exactly this and had to override the compose
`command:` to relocate the port. Reading a `PORT` env var (default 8080) lets
operators move the listener with a one-line env var instead of overriding the
entrypoint — the same convention many self-hosted images follow.

The application code does not need to change: the port is bound by the uvicorn
entrypoint, not by the app. Only the `Dockerfile` CMD (and a docs line) change.

## Current state

`Dockerfile` (lines 18-19, the last two lines):

```dockerfile
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

This is exec-form `CMD` (a JSON array), which does **not** perform shell
variable expansion — so `${PORT}` written directly into the array would be
passed to uvicorn as the literal string `${PORT}`, not expanded. The fix must
use a shell so the variable expands.

`README.md` has an environment-variable table (lines 51-64); the last row today
is:

```markdown
| `NOTIFY_WEBHOOK_URL` | Optional webhook for import-failure notifications (empty = disabled) |
```

**Convention notes:**
- Keep `EXPOSE 8080` as-is — it is documentation of the default and does not
  publish or bind anything.
- The default must stay **8080** so existing deployments that set no `PORT` are
  unaffected.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Confirm CMD uses PORT with 8080 default | `grep -n "PORT" Dockerfile` | shows `${PORT:-8080}` in the CMD |
| App still compiles (sanity; unchanged) | `python -m py_compile app/main.py` | exit 0 |

**Honest verification note:** building/running the image requires Docker, which
is typically **not available in the executor's worktree**. Do **not** claim the
image "works." Your job is to make the entrypoint correct; the definitive test
(below) is run by the maintainer. If `docker` *is* available and you can run it,
do the manual check in the Test plan and report the result.

## Scope

**In scope** (the only files you should modify):
- `Dockerfile` — the `CMD` line only.
- `README.md` — add one row to the environment-variable table.

**Out of scope** (do NOT touch):
- `app/main.py` or any application code — the app does not read `PORT`; the
  entrypoint binds the port. Do **not** add a `PORT` read to `Settings`.
- `EXPOSE 8080` — leave it.
- `docker-compose.yml` — the compose file's `command:`/`ports:` are the
  operator's concern, not this image change.
- Do not convert the base image, add healthchecks, or touch any other Dockerfile
  line.

## Git workflow

- Branch: `advisor/025-configurable-listen-port`
- Short imperative commit subject (e.g. `Make container port configurable via PORT`).
  Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Make the CMD honor `$PORT` (default 8080)

Replace the exec-form `CMD` line in `Dockerfile` with a shell form that expands
the variable and still runs uvicorn as PID 1:

```dockerfile
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

- `sh -c` gives shell expansion of `${PORT:-8080}`.
- `exec` replaces the shell with uvicorn so it becomes PID 1 and receives
  container stop signals (graceful shutdown) — do not omit it.
- `${PORT:-8080}` means: use `$PORT` if set and non-empty, else `8080`.

Leave `EXPOSE 8080` on the line above unchanged.

**Verify**:
- `grep -n "PORT" Dockerfile` → the CMD line shows `${PORT:-8080}`.
- `grep -n "EXPOSE 8080" Dockerfile` → still present, unchanged.

### Step 2: Document `PORT` in the README env table

In `README.md`, add one row to the environment-variable table, immediately after
the `NOTIFY_WEBHOOK_URL` row (line 64):

```markdown
| `PORT` | Port the app listens on inside the container (default `8080`); set this to avoid a clash when sharing another container's network namespace |
```

**Verify**: `grep -n "\`PORT\`" README.md` → one match in the table.

## Test plan

- No unit tests apply (Dockerfile + docs change; the app is untouched).
- **Definitive test (maintainer, needs Docker):**
  ```
  docker build -t mam-af-porttest .
  docker run --rm -e PORT=9000 -e MAM_COOKIE=x mam-af-porttest
  ```
  Expected: the uvicorn startup log reads `Uvicorn running on http://0.0.0.0:9000`.
  Running without `-e PORT=...` must still log port `8080`.
  (The container will later error on the dummy cookie / missing DB dir — that is
  fine; you only need the "Uvicorn running on ... :PORT" line.)
- State explicitly in your report that image build/run was **not** performed in
  the worktree (unless you actually ran it).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'port ${PORT:-8080}' Dockerfile` → one match
- [ ] `grep -n "EXPOSE 8080" Dockerfile` → still present
- [ ] `grep -n "\`PORT\`" README.md` → one match (the new table row)
- [ ] `git diff a13593e HEAD -- app/` → empty (no application code changed)
- [ ] `git status --porcelain` shows only `Dockerfile` and `README.md` changed
- [ ] `plans/README.md` status row for 025 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `Dockerfile` CMD line does not match the "Current state" excerpt (it
  drifted, or already reads `$PORT`).
- You feel the need to make `app/main.py` read `PORT` — it must not; the
  entrypoint binds the port. Stop and report.
- The README env table structure differs from the excerpt (columns/headers
  changed) — add the row in the equivalent place and note the difference.

## Maintenance notes

- `EXPOSE 8080` is now only a documentation hint of the default; the actual bind
  port is `${PORT:-8080}`. If the default ever changes, update both the CMD
  default and `EXPOSE`.
- The compose file in this repo (and operators' own compose) may still pin a
  `command:` or `ports:` mapping; this change simply makes the `command:`
  override unnecessary for the port — it does not require anyone to change their
  compose.
- A reviewer should confirm `exec` is present (PID-1 signal handling) and that
  the default remained 8080 (no silent behavior change for existing users).
