# 1. Application authentication

## Status

Accepted — 2026-07-25

## Context

`README.md` states plainly: "The app has no authentication, so do not expose it
directly to the public internet" (README.md:75). That warning is accurate today.
This ADR decides whether, and how, that should change.

Endpoint surface (`app/main.py`, confirmed with `grep -n '@app\.' app/main.py`):

| Route | Method | Notes |
|---|---|---|
| `/` | GET | HTML shell (main.py:256) |
| `/search` | POST | proxies a query to MyAnonamouse using the user's cookie (main.py:265) |
| `/add` | POST | spends freeleech wedges, adds torrents (main.py:487) |
| `/account` | GET | returns the freeleech wedge balance (main.py:532) |
| `/history` | GET | returns the last 200 download-history rows (main.py:539) |
| `/history/{id}/retry` | POST | re-runs a failed import (main.py:564) |

`/static` is mounted separately (main.py:253) and serves `app.js`, `common.css`,
the logo, and favicons — no secrets.

All five data endpoints are called from exactly one frontend function,
`fetchJson` (app/static/app.js:339), from five call sites (app.js:115, 180,
239, 316, 369 — confirmed with `grep -n "fetchJson" app/static/app.js`).
Attaching a credential is a one-function change on the frontend. `/` itself
loads by plain browser navigation, not through `fetchJson`.

Governing constraints:

- No new dependencies without justification; keep helpers flat in `main.py`
  (AGENTS.md:26, 47).
- Single-user by design: `ensure_history_schema()` (main.py:145-200) defines
  only a `history` table — no users, no sessions, no notion of identity.
- **No HTTPS anywhere.** `Dockerfile:19` runs `uvicorn ... --port 8080` with no
  `--ssl-keyfile`/`--ssl-certfile`; `docker-compose.yml` maps `8080:8080` in
  plain HTTP with no TLS config; the documented local-dev command
  (`AGENTS.md:15`) is likewise plain HTTP. Confirmed by grepping both files
  for `ssl|tls|https|cert` — the only hits are an unrelated CA-certificates
  package (for this app's *outbound* calls to MAM) and a webhook URL example
  in a comment.
- No existing inbound auth mechanism: `grep -n 'Depends\|middleware\|Security\|
  HTTPBearer\|HTTPBasic\|APIKeyHeader' app/main.py` returns nothing. The only
  `login`/`session_id` hits in the codebase are this app's *outbound*
  credentials to Transmission/qBittorrent (main.py:386-388, 686-692, 720, 735,
  748), not anything guarding this app's own endpoints. No `hmac`/
  `compare_digest` usage exists anywhere yet either.
- The project already requires Docker Compose to run (README Quick Start) and
  already has a working config precedent for optional features:
  `NOTIFY_WEBHOOK_URL` defaults to `""` and is treated as disabled whenever
  empty (main.py:117, 880-882, 900-901).

## Decision

**Do not add authentication to the application.** Anyone who needs to reach
this app from outside a trusted LAN should put it behind a reverse proxy that
performs HTTP Basic auth or SSO forward-auth (e.g. Caddy/nginx with basic
auth, or Authelia/Tinyauth/`tailscale serve`) and terminates TLS there. No
application code, no new config, no new dependency. Full reasoning is in
"Analysis (Q1-Q7)" below — Q1 is the load-bearing question.

In one sentence: the app cannot offer HTTPS without a proxy in front of it
anyway, and once that proxy exists, doing auth there is strictly better than
doing it in the app — it costs zero code, cannot miss a route (including `/`
and `/static`, which an in-app header check structurally cannot cover), and
matches this project's existing "flat, minimal, no new dependencies" bias.

## Consequences

**Easy:** nothing changes in `app/main.py` or `app/static/app.js`; no new
config surface to document or misconfigure; no risk of the "half-built token
check" failure mode (a `==` comparison, a query-string token, one unguarded
route) that motivated this plan, because there is no in-app check to get
wrong.

**Hard / pushed onto the user:** anyone who wants to reach the app outside the
LAN must stand up and maintain a reverse proxy themselves. Per-endpoint policy
(e.g. protect `/add` more strictly than `/history`) is not expressible — proxy
auth is all-or-nothing for the app. That distinction was not meaningful to
enforce in-app anyway: this app has no read-only-vs-write identity concept, so
anyone who can reach one endpoint can already reach all of them.

**Remains unprotected:** exactly as much as today, until a user deploys a
proxy in front of the app. The README's warning (README.md:75) is left
unmodified by this ADR and stays accurate — consistent with the plan's
instruction not to change it until a decision is actually implemented.

## Considered and rejected

- **In-app `Authorization: Bearer` token.** Cheap to wire up given the
  `fetchJson` funnel, but a browser cannot attach a custom header to a plain
  navigation to `/`, so it can never cover the whole surface by itself; and
  without HTTPS (which this app doesn't have) a header secret is exposed in
  plaintext to exactly the "malicious LAN device" threat it would exist to
  stop. Rejected in favor of the proxy, which covers `/` and gets TLS for
  free.
- **In-app cookie + login form.** Would cover `/` uniformly, but needs a login
  endpoint/page (explicitly out of scope for this plan) and a `Secure` cookie
  flag that itself requires HTTPS the app doesn't have — it re-invents session
  infrastructure for an app that deliberately has none.
- **Query-parameter token.** Rejected outright: leaks into proxy access logs,
  browser history, and `Referer` headers. Named only so the record shows it
  was considered and why it lost.
- **Full session management / user accounts.** Rejected: the app is
  single-user by design — the schema has no users/sessions table at all
  (main.py:145-200). Accounts and roles would be an architecture-scale change
  with no corresponding requirement; nobody has asked this app to serve more
  than one identity.

## Analysis (Q1-Q7)

### Q1. Should this be solved in the app at all?

**No.** For the reverse proxy:

- The app has no HTTPS anywhere (`Dockerfile:19`, `docker-compose.yml`,
  `AGENTS.md:15` all confirm plain HTTP). Any in-app credential — header or
  cookie — travels in the clear between browser and server. Defending against
  the plan's own "plausible" threat (a malicious LAN device, Q2) requires
  TLS, and this app cannot terminate TLS itself without a new dependency (a
  cert/ACME library), which is out of scope. A reverse proxy is required for
  *meaningful* protection regardless of what the app does.
- Once that proxy exists, doing auth there is strictly better than
  duplicating it in-app: it protects `/`, `/static/*` (main.py:253, 256), and
  every future endpoint automatically, with no chance of a route being
  missed. That directly closes the failure mode this plan's own "Why this
  matters" section names: "one endpoint left unguarded ... auth that
  protects the API while the app shell leaks."
- It costs zero code, zero new config, and zero new dependency, matching this
  project's explicit "no new dependencies without justification, keep
  helpers flat" bias (AGENTS.md:26, 47). Even an in-app scheme using only
  `hmac`/`secrets` from the standard library still adds new code paths, new
  config surface (`AUTH_TOKEN`, docs, README rows), and an ongoing "did every
  new route remember the dependency?" maintenance burden that a proxy avoids
  entirely.
- This app is single-user with no identity model at all (main.py:145-200
  defines only a `history` table). A single shared credential checked by a
  reverse proxy (HTTP Basic auth) is the same operational shape as a single
  shared credential checked in-app — the proxy is a strict improvement at
  equal complexity, not a mismatch requiring new architecture.
- The realistic threat (casual internet scanner, Q2) is already fully handled
  today by "don't expose this to the public internet" (README.md:75). Auth
  starts to matter precisely when someone chooses to expose the app beyond
  the LAN — which is exactly the scenario that already requires TLS/a proxy.

Considered honestly, against the reverse proxy:

- It pushes setup work onto the user, who must add and maintain a second
  service. Real, but proportionate: the app already requires Docker Compose
  (README Quick Start), so one more Compose service is incremental, not a
  novel skill.
- It cannot express per-endpoint policy (e.g. `/add`, which spends a scarce
  resource, protected more strictly than `/history`, which merely
  discloses). Real, but this app has no read-only-vs-write concept anywhere
  else in its design — differential protection would be new complexity in
  service of a distinction the app doesn't otherwise make.

**Verdict:** use a reverse proxy; write no application code. This matches the
plan's own framing that this is "a legitimate, and quite possibly the correct,
outcome."

### Q2. What is the threat model?

- **Realistic, already defended, unaffected by this decision:** casual
  internet scanners / opportunistic bots. Mitigated today by "don't expose
  this to the public internet" (README.md:75).
- **Plausible — the actual live gap:** another device on the same LAN (a
  compromised IoT device, an untrusted guest, a shared/co-working network)
  making direct HTTP requests to the app's port. Nothing stops this today. A
  reverse proxy with Basic auth or forward-auth stops it once deployed. An
  in-app credential would only *partly* stop it — see below.
- **Out of scope — already lost:** an attacker who already has the
  `MAM_COOKIE` value or shell/env access to the host. They can already act as
  the user's MAM identity directly; no application-level check helps.
- **The reason Q1 favors the proxy:** a network-level eavesdropper on the same
  LAN (open/weak Wi-Fi, ARP spoofing, a compromised router). Because there is
  no HTTPS anywhere in this app, this attacker sees any in-app credential in
  plaintext. The plausible threat is a network threat, and only TLS (i.e., a
  proxy) addresses it — an in-app-only token stops someone who can reach the
  port but not someone who can also observe traffic on it.

### Q3. Credential transport

Not applicable to the accepted decision (no in-app credential is being
built). Recorded for a future implementer in case this ADR is revisited:

- **Bearer header** — the better of the two in-app options: cheap given the
  single `fetchJson` funnel (app.js:339, five call sites), never lands in
  logs by default. But a browser cannot attach a custom header to a plain
  navigation, so it structurally cannot protect `/` — even choosing this
  would leave the HTML shell (and `/static`) uncovered by the app alone,
  undercutting the premise that the app can solve this by itself.
- **Cookie** — covers `/` uniformly, but needs `HttpOnly` + `SameSite=Strict`
  + `Secure` (the last requires HTTPS the app doesn't have) and a login form,
  which is explicitly out of scope for this plan.
- **Query parameter** — rejected: leaks into proxy logs, browser history, and
  `Referer`. Named only so the record shows it was considered and why it
  lost.

### Q4. What does the token protect?

Not applicable (no token is being built). For the record, if a Bearer scheme
were ever built despite this ADR: `/add` (real-world cost — spends a wedge,
downloads under the user's identity) would be the highest-value target;
`/search`, `/account`, `/history`, `/history/{id}/retry` disclose data or
re-trigger imports and would reasonably get the same protection, since the
app has no notion of a lesser-privileged caller; `/static/*` (main.py:253)
holds no secrets and is not worth protecting; `/` cannot be protected by a
header check at all (Q3), so an unauthenticated shell whose data calls then
401 is the best an in-app scheme could do — acceptable as a fallback, but a
materially weaker guarantee ("protects data, not the fact that this tool
exists or its structure") than what the proxy gives for free.

### Q5. How does a browser acquire the token?

Not applicable (no token is being built). For the record: `localStorage`,
populated by a one-time prompt when the user first configures the app;
`fetchJson` (app.js:339) would need to attach the stored value and
specifically catch `401` to clear/re-prompt. This avoids a server-side login
endpoint (out of scope) but is real friction — every browser/device needs the
token pasted in by hand, versus a reverse-proxy Basic-auth prompt that
browsers and password managers already know how to save and offer.

### Q6. Comparison and configuration

Not applicable to what's being shipped (nothing), but the precedent is
confirmed for the record:

- This codebase already has a working "empty env var = feature disabled"
  precedent: `NOTIFY_WEBHOOK_URL` defaults to `""` (main.py:117), and both
  call sites that use it (`send_failure_notification` main.py:880-882,
  `schedule_failure_notification` main.py:900-901) treat empty as "do
  nothing." A future `AUTH_TOKEN` should follow that precedent, not
  `TORRENT_CLIENT`'s pattern (main.py:105-107), which defaults to a concrete
  value and validates against an allowed set — `TORRENT_CLIENT` is a
  selector, not an optional feature toggle, so it is the wrong analog.
- `hmac.compare_digest` (stdlib) instead of `==` is confirmed correct for any
  future token check — grep confirms zero existing uses of either in this
  codebase, so there is no precedent conflict to reconcile.
- Whether an empty token should hard-fail at startup: this codebase already
  has precedent for *required* config raising at startup — `MAM_COOKIE` does
  exactly that (main.py:98-100: `if not self.MAM_COOKIE: raise
  RuntimeError(...)`). A future implementer could mirror that under an
  explicit opt-in flag (e.g. `REQUIRE_AUTH=1`) without changing the default
  (empty `AUTH_TOKEN` = disabled, matching `NOTIFY_WEBHOOK_URL`). Not built
  now.

### Q7. What must *not* be authenticated?

Confirmed by reading `auto_import_cycle` (main.py:1069-1105) and its call
chain. It calls `get_torrent_client().completed_hashes()` (an outbound
`httpx` call to Transmission/qBittorrent, not to this app — main.py:663-665,
733-744), `get_auto_import_candidates()` (a direct SQLAlchemy query,
main.py:952-976), and — critically — `import_torrent_to_library(...)`
(main.py:1013-1067) as a **direct in-process function call**, the same
function `/history/{id}/retry` (main.py:564-608) calls directly rather than
via HTTP. The poller itself runs as an `asyncio.create_task` created inside
the FastAPI `lifespan` context (`reconcile_auto_import_task`,
main.py:1136-1141, invoked from `lifespan` at main.py:242-247) — same
process, same event loop as the web server, not a separate process or cron
job. There is no `httpx` call anywhere in this path directed at the app's own
host/port. **Confirmed: the poller needs no credential under any scheme,
app-level or proxy-level, because it never makes an HTTP request to itself at
all.**

## Follow-up recommendation

No application implementation plan is warranted — Q1 concluded the
reverse-proxy path, which needs no code in this repository. The only
follow-up worth planning is documentation: a short README recipe (one example
each for a Caddy/nginx Basic-auth sidecar and a forward-auth SSO option) that
shows how to put a proxy in front of the existing `docker-compose.yml`
service, plus updating the README's no-auth line once a user has actually
verified the recipe end-to-end. That follow-up should not touch
`app/main.py` or `app/static/app.js`.
