# Plan 019 (DESIGN/SPIKE): Decide how — and whether — this app should authenticate

> **This is a design plan, not an implementation plan.** Its deliverable is a
> written decision plus a throwaway spike, **not** shipped authentication. Do not
> implement production auth from this plan. If you finish the spike and the
> decision is "build it", the follow-up implementation plan gets written
> separately, informed by what you learned.
>
> **Executor instructions**: Work through the questions in order. Record every
> answer in the deliverable document. If a question cannot be answered from the
> codebase, say so explicitly in the document rather than guessing. If any STOP
> condition occurs, stop and report.
>
> **IMPORTANT — which commit this applies to**: branch `advisor/plans-001-012`
> (tip `57c0af6`), **not** `master` (`f8d3d32`).
>
> **Drift check (run first)**: `git diff --stat 57c0af6..HEAD -- app/main.py app/static/app.js README.md`

## Status

- **Priority**: P3
- **Effort**: M (mostly thinking and a small spike; not a shipping feature)
- **Risk**: LOW as specified (spike only). **HIGH if someone skips this and
  writes production auth directly** — which is the reason this plan exists.
- **Depends on**: none
- **Category**: direction / design
- **Planned at**: commit `57c0af6` (branch `advisor/plans-001-012`), 2026-07-24

## Why this matters

`README.md:73` states the limitation in the project's own words:

```markdown
- The app has no authentication, so do not expose it directly to the public internet.
```

That is an honest warning and a real constraint: the app can only be used on a
trusted LAN. Anyone wanting to reach it from a phone on mobile data has to solve
it themselves.

Authentication is also the single easiest thing on this project's roadmap to do
**badly**. A half-built token check is worse than none, because it converts a
clearly-understood limitation ("this is unprotected, keep it inside") into a
false belief that the app is safe to expose. The failure modes are unglamorous
and easy to miss: one endpoint left unguarded, a token compared with `==` instead
of a constant-time function, a token in a query string that lands in proxy logs,
or auth that protects the API while the app shell leaks.

So the deliverable here is a **decision**, evidence-backed, plus a spike that
proves the chosen mechanism actually works against this app's real shape — before
anyone writes middleware that everything else depends on.

**The design must seriously evaluate not building it.** See Question 1.

## Current state — the surface any design must cover

### Endpoints (`app/main.py`)

| Route | Method | Notes |
|---|---|---|
| `/` | GET | HTML shell, rendered from `templates/index.html` |
| `/search` | POST | proxies a query to MyAnonamouse using the user's cookie |
| `/add` | POST | **spends freeleech wedges**, adds torrents |
| `/account` | GET | returns the freeleech wedge balance |
| `/history` | GET | returns the last 200 rows of download history |
| `/history/{id}/retry` | POST | re-runs a failed import |

Note the asymmetry worth designing around: `/add` has **real-world cost** (it
spends a scarce paid resource and downloads content under the user's MAM
identity), while `/history` merely discloses. A design could reasonably protect
them differently — or reject that as needless complexity.

### Static assets

```python
app.mount("/static", StaticFiles(directory="static"), name="static")
```

Mounted before any route. Serves `app.js`, `common.css`, the logo, and favicons.
Nothing secret lives there, but a middleware that inspects every request will hit
these on every page load — a real consideration for both correctness and noise.

### Frontend call sites that would need a token

All requests funnel through one helper, `fetchJson` (`app/static/app.js:278`),
which is called from exactly five places:

- `/search` (line 93)
- `/add` (line 117)
- `/account` (line 178)
- `/history/{id}/retry` (line 255)
- `/history` (line 308)

**This is the single most important fact for the design**: because every call
goes through `fetchJson`, attaching a credential is a *one-function* change on
the frontend. That materially lowers the cost of a header-based scheme.

### Constraints from the project itself

- `AGENTS.md`: no new dependencies without justification; keep helpers flat in
  `main.py`; runtime config comes from environment variables in
  `docker-compose.yml`.
- The app is **single-user by design**. There is no user table, no session
  store, and no notion of identity anywhere in the schema.
- There is **no HTTPS** in the app or compose file. Any credential scheme is
  only as good as the transport in front of it.
- There is no `docs/` directory yet; this plan creates the first one.

## The questions to answer

Answer each in the deliverable, with a stated rationale. These are ordered so
that a "no" on Question 1 ends the exercise cheaply.

### Q1. Should this be solved in the app at all?

The strongest competing option is **not writing any application code**: put
HTTP Basic auth, or an SSO forward-auth (Authelia, Tinyauth, tailscale-serve),
in the reverse proxy that would already be terminating TLS for remote access.

Evaluate honestly:
- A reverse proxy is already required for HTTPS, and app-level tokens do not
  remove that requirement.
- Proxy auth protects `/static` and every future endpoint automatically, with no
  chance of missing one.
- It costs the project zero code, zero dependencies, and zero maintenance.
- Against that: it pushes setup complexity onto the user, and it cannot express
  per-endpoint rules (e.g. protect `/add` more strictly than `/history`).

**If the answer is "use a reverse proxy", the deliverable is a documented recipe
in the README plus a decision record — and no application code at all.** That is
a legitimate, and quite possibly the correct, outcome of this plan. Do not treat
it as a failure to deliver.

### Q2. What is the threat model?

State plainly what is being defended against and what is not. Suggested framing:
- Casual discovery by an internet scanner (realistic).
- A malicious device on the same LAN (plausible).
- A targeted attacker who already has the MAM cookie from the environment
  (out of scope — they have already lost).

The model determines whether a single shared secret is sufficient or whether
real sessions are needed. For a single-user app, a shared secret very likely is.

### Q3. Credential transport

Pick one and justify it:

- **`Authorization: Bearer <token>` header** — clean, never lands in logs or
  browser history, and cheap here because of the single `fetchJson` funnel. But
  the browser cannot send it on a plain navigation to `/`, so the HTML shell
  either stays open or needs a different mechanism.
- **Cookie** — sent automatically on navigation *and* fetch, so it protects `/`
  uniformly. Needs `HttpOnly`, `SameSite=Strict`, and `Secure` (which implies
  HTTPS), and needs a way to set it — i.e. a login form, which is more surface.
- **Query parameter** — reject this. It leaks into proxy logs, browser history,
  and `Referer` headers. Named here only so the decision record shows it was
  considered and why it lost.

### Q4. What does the token protect?

Decide, for each of: `/`, `/static/*`, the four data endpoints, and any future
endpoint. Specifically: is an unauthenticated `/` that renders a shell whose
every request then 401s acceptable? It is secure but confusing. Does `/static`
need protecting at all, given it contains no secrets?

### Q5. How does a browser acquire the token?

If Q3 chose a header: the token must be stored client-side (`localStorage`) and
attached in `fetchJson`. Specify how it gets there the first time — a prompt, a
settings field, a URL fragment on first visit — and what happens on 401
(clear it and re-prompt, presumably).

If Q3 chose a cookie: specify the login form, the endpoint that sets the cookie,
and the cookie's flags.

### Q6. Comparison and configuration

- Token compared with `hmac.compare_digest`, **not** `==`. `hmac` is in the
  standard library; no new dependency.
- Config: an env var (e.g. `AUTH_TOKEN`), **empty by default = auth disabled**,
  so existing deployments are untouched. Confirm this matches how
  `NOTIFY_WEBHOOK_URL` and `TORRENT_CLIENT` already behave.
- Decide whether an empty token should merely disable auth (consistent with the
  rest of the app) or hard-fail at startup when combined with some "expose me"
  flag.

### Q7. What must *not* be authenticated?

The auto-import poller runs **in-process** and calls no HTTP endpoint of its own,
so it needs no credential. Confirm that by reading `auto_import_cycle` — and
record the confirmation, because a future contributor adding an internal HTTP
call would break it.

## Deliverable

**1. A decision record** at `docs/adr/0001-authentication.md` (create the
directory). Keep it short — one page. Required sections:

```markdown
# 1. Application authentication

## Status
Accepted | Rejected  (pick one, dated)

## Context
(the constraint, the endpoint surface, the fetchJson funnel, the no-HTTPS reality)

## Decision
(what will be done — including, if applicable, "nothing in the app; use a reverse proxy")

## Consequences
(what this makes easy, what it makes hard, what remains unprotected)

## Considered and rejected
(each rejected option with one line on why — query-param tokens, full sessions, etc.)
```

**2. If — and only if — Q1 concludes the app should do it: a spike.** On a
throwaway branch, implement the chosen mechanism for **one endpoint only**
(`/history` is the right choice: it discloses, it is a GET, and it is called from
the frontend, so it exercises both server and client sides). The spike must
demonstrate end to end:
- a request without the credential is rejected,
- a request with it succeeds,
- the frontend can actually attach it via `fetchJson`,
- `hmac.compare_digest` is used for the comparison.

The spike is **evidence, not a deliverable to merge**. Say so in your report and
do not extend it to the other endpoints.

**3. A recommendation** of what the follow-up implementation plan should contain,
in three or four sentences — or an explicit statement that no implementation plan
is warranted because Q1 chose the reverse proxy.

## Commands you will need

| Purpose      | Command                              | Expected |
|--------------|--------------------------------------|----------|
| Syntax check | `python3 -m py_compile app/main.py`  | exit 0   |
| Run tests    | `cd app && python -m pytest -q`      | all pass |

## Scope

**In scope**:
- `docs/adr/0001-authentication.md` — **create**; the primary deliverable.
- A throwaway spike branch touching `app/main.py` and `app/static/app.js`, only
  if Q1 says so, and only for `/history`.

**Out of scope** (do NOT do):
- **Do not ship production authentication from this plan.** No middleware
  covering all endpoints, no login page, no session store.
- Do not change any default so that auth becomes enabled.
- Do not add a dependency. `hmac` and `secrets` are standard library; anything
  needing `python-jose`, `passlib`, or `authlib` is out of scope by definition —
  if the design seems to require one, that is a finding to record, not to act on.
- Do not modify `README.md:73`'s warning until a decision is actually
  implemented. The warning is accurate today and must stay accurate.
- Do not add user accounts, roles, or a users table. The app is single-user.

## Done criteria

This plan is design work, so the criteria are about the artifact:

- [ ] `docs/adr/0001-authentication.md` exists and contains all five required
      sections (Status, Context, Decision, Consequences, Considered and rejected)
- [ ] Every question Q1–Q7 has an explicit answer in the document, including any
      answered "cannot determine from the codebase"
- [ ] The document names the **rejected** options and why — at minimum
      query-parameter tokens and full session management
- [ ] Q1 is answered with a genuine comparison against the reverse-proxy option,
      not a one-line dismissal
- [ ] If a spike was built: it covers exactly one endpoint, uses
      `hmac.compare_digest`, and lives on a branch that is **not** proposed for
      merge — state the branch name in your report
- [ ] `cd app && python -m pytest -q` passes on the main working branch (i.e. the
      spike did not leak into it)
- [ ] `git status` on the working branch shows only `docs/adr/0001-authentication.md` added
- [ ] `plans/README.md` status row for 019 updated

## STOP conditions

Stop and report back (do not improvise) if:

- You conclude the app genuinely needs multi-user accounts. That contradicts the
  single-user design and is a product decision far beyond this plan.
- The chosen design appears to require a new runtime dependency — record it as a
  finding and stop; do not add it.
- You find an existing authentication or authorization mechanism already in the
  codebase that this plan missed. Report it; the premise would be wrong.
- You find yourself implementing auth across all six endpoints. That is the
  failure mode this plan exists to prevent — stop at one.

## Maintenance notes

- **The most likely correct outcome is "use a reverse proxy."** For a
  single-user, self-hosted app that already needs a proxy for TLS, app-level
  tokens add code, surface, and maintenance for little marginal safety. A
  reviewer should be suspicious of a decision record that reaches for middleware
  without seriously engaging Q1.
- Whatever is decided, `README.md:73` must end up **accurate**. If auth ships,
  update it. If the decision is "reverse proxy", strengthen it into a documented
  recipe rather than deleting it.
- The `fetchJson` funnel is the design's biggest asset. If a future change starts
  calling `fetch()` directly, any header-based scheme silently develops a hole —
  worth a comment on `fetchJson` if that route is chosen.
- If auth ships, every future endpoint must be covered by default. Prefer
  middleware that protects everything with an explicit allow-list over
  per-route decorators that are easy to forget.
