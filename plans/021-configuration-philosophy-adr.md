# Plan 021 (DESIGN → ADR): Author `docs/adr/0002-configuration-philosophy.md`

> **This plan produces an ADR, not code.** Its deliverable is the file
> `docs/adr/0002-configuration-philosophy.md`, whose complete final text is
> inlined below in the block marked **BEGIN ADR TEXT … END ADR TEXT**. An
> executor creates that file verbatim; the advisor (who wrote the text) reviews
> placement. No application code changes.
>
> **Written against**: `master` @ `000a178`, 2026-07-25.
> **Depends on**: `docs/adr/0001-authentication.md` (plan 019, already on master)
> and `plans/020-configuration-architecture.md` (the first review). This ADR
> challenges and, where warranted, sharpens both — it does not rubber-stamp them.

## Why an ADR beyond plan 020

Plan 020 answered *today's* placement questions. The maintainer asked a harder,
second-order question: **what rule governs where every *future* setting goes,
and where do the prior conclusions break under 3–5 years of growth?** That
deserves a durable, authoritative record the whole project defers to — an ADR —
not another review doc. The value is a **reusable decision framework**, not a
static table.

The brief instructed: "Challenge these conclusions. Do not assume they are
correct simply because they exist." The ADR below does. Three prior conclusions
survive; two are **sharpened at the point where growth breaks them**:

1. **"Environment variables for deployment config" holds — but flat env
   genuinely breaks on *collections*.** Multiple indexers, plugin support, and
   any "N of a thing, each with its own settings" cannot be expressed as flat
   env without the `INDEXER_1_URL`, `INDEXER_2_URL` numbering anti-pattern. That
   is the real architectural breakpoint, and it forces structured storage (the
   DB) at that growth stage — not as a "nice to have," but as a necessity.
2. **"Secrets never in the database" holds for *deployment* secrets — but
   *per-integration user secrets* force one sanctioned exception.** If a user
   adds five indexers each with its own API key, those keys cannot be env vars
   (same numbering problem) and are inherently runtime/user-managed. The honest
   resolution is envelope encryption: such secrets live in the DB **encrypted at
   rest with a key supplied from env**, behind auth — not in plaintext, and only
   once multi-item integrations exist. This refines the principle rather than
   discarding it.
3. **"Reverse proxy is the security boundary" holds now — but the ADR names the
   trigger that would reopen it** (mutable server-side settings arriving, or any
   move toward multiple identities), rather than foreclosing in-app auth forever.

Everything else in 020 and ADR-0001 stands, and the ADR says so plainly instead
of re-deriving it.

## Scope

**In scope**: create `docs/adr/0002-configuration-philosophy.md` with the exact
text below. Create the `docs/adr/` directory if needed (it already exists —
`0001-authentication.md` is there).

**Out of scope**: any change to `app/`, `docker-compose.yml`, `README.md`,
`requirements*.txt`, or `plans/`. No settings table, no code, no doc edits
beyond creating the one ADR file. This ADR *describes* a future; it does not
build any of it.

## Steps

### Step 1: Create the ADR file

Create `docs/adr/0002-configuration-philosophy.md` containing **exactly** the
text between the BEGIN/END markers below (do not include the markers themselves).

### Step 2: Verify

- `test -f docs/adr/0002-configuration-philosophy.md` → exists.
- `grep -c "^## " docs/adr/0002-configuration-philosophy.md` → ≥ 10 (all sections present).
- `cd app && python -m pytest -q` → unchanged (38 passed) — proves no code was touched.
- `git status --porcelain` → only `docs/adr/0002-configuration-philosophy.md` added.

## Done criteria

- [ ] `docs/adr/0002-configuration-philosophy.md` exists and matches the inlined text
- [ ] The decision matrix lists every current configuration item from `app/main.py`
- [ ] `git status` shows only that one new file
- [ ] `cd app && python -m pytest -q` still reports 38 passed (no code touched)
- [ ] `plans/README.md` row for 021 updated

## STOP conditions

- If `docs/adr/0002-configuration-philosophy.md` already exists with different
  content — do not overwrite; report the divergence.
- If creating the file appears to require touching any `app/` file — it does
  not; stop and report.

---

## BEGIN ADR TEXT

# 2. Configuration philosophy

## Status

Accepted — 2026-07-25. Supersedes nothing; **extends**
[ADR-0001 (authentication)](0001-authentication.md) and formalizes the review in
`plans/020-configuration-architecture.md` into project law.

## Context

This app is a single-user, single-process, Docker-first tool. Configuration
today is **environment variables read once at startup** into a `settings`
singleton (`app/main.py`), plus one SQLite table (`history`) that holds no
configuration. ADR-0001 decided the app carries **no built-in authentication**;
remote access goes behind a reverse proxy.

The project is expected to grow. Plausible future features: additional torrent
clients, **multiple indexers**, richer notifications and webhook integrations,
proxy support, scheduling, search presets, filtering, dashboards, statistics,
import policies, **plugin support**, and *optional* future authentication.

Two of those — multiple indexers and plugins — break the current model, because
they are **collections of configured things**, not scalars. This ADR defines a
rule that survives that growth, and states plainly where the earlier
conclusions bend.

## Decision

Adopt a **tiered configuration model** governed by a **classification rule** that
every future setting must pass through *before* it is implemented. The tiers:

- **Tier 1 — Deployment configuration: environment variables.** Secrets,
  service URLs, credentials, filesystem paths, networking, container topology,
  and the selection of which backends exist. Read once at startup. Immutable at
  runtime; **restart-required**. Owned by whoever deploys the stack. This is the
  whole model today and remains correct for all scalar deployment config
  indefinitely.
- **Tier 2 — Operational & user settings: SQLite, behind authentication.** A
  small, enumerated set of **non-secret** operational tunings and user
  preferences, editable live, read per-request from the existing database. Does
  not exist yet. Built only on demand and only after the ADR-0001 reverse proxy
  (or a future in-app auth decision) provides the authentication that a mutable
  server-side control plane requires.
- **Tier 3 — Client-only preferences: browser `localStorage`.** Pure
  presentation state (theme, column layout, last-used filter) that never needs
  to reach the server. No server storage, no backup, no auth surface.
- **Tier 0 — Immutable constants: code.** Protocol facts, fixed domains, and
  invariants that must never vary at runtime. Not configuration at all.

### The classification rule (the authoritative reference)

Before implementing any new configuration option, run it through these questions
**in order**. The first "yes" decides its home.

1. **Is it a deployment secret** (a credential the operator provisions:
   MAM cookie, torrent-client password, DB URL)? → **Tier 1, env, secret.**
   Never the DB, never the UI.
2. **Does it define infrastructure** — a service URL, path, port, network, or
   *which* backends the stack provides? → **Tier 1, env, restart-required.**
   Never editable from the UI (see Principle 4).
3. **Is it a variable-length collection** — N indexers, N torrent clients, N
   plugins, each with its own sub-config? → **Tier 2, structured storage (DB).**
   Flat env cannot express repetition without the `THING_1_*`, `THING_2_*`
   anti-pattern. This is the growth breakpoint; when the app crosses it, the DB
   stops being optional. **If items in the collection carry secrets** (per-indexer
   API keys), those secrets live in the DB **encrypted at rest with a key from
   env** (Principle 3's sole exception), behind auth.
4. **Is it operational tuning** (poll interval, retry count, concurrency,
   schedule)? → **Tier 1 env default**, optionally **overridable in Tier 2**
   once a settings UI exists. Live where safe; otherwise restart.
5. **Is it a user preference that drives server behavior or must persist across
   devices** (default search filters, import policy defaults)? → **Tier 2, DB.**
6. **Is it a pure presentation preference** (theme, layout)? → **Tier 3,
   `localStorage`.**
7. **Is it a fixed protocol/domain constant** (MAM base URL, category codes)? →
   **Tier 0, code constant.**

This rule *is* the deliverable: every future feature's config decision is made by
walking it, not re-argued from scratch.

## Challenging the prior conclusions

Asked to challenge rather than assume:

- **"Env for deployment config" — upheld, with a named breakpoint.** Correct for
  every *scalar* today. It **fails for collections** (question 3). Multiple
  indexers and plugin support are the features that force Tier 2 structured
  storage; until they arrive, env-only remains right and a settings DB is
  premature.
- **"User preferences may belong in the DB" — upheld and sharpened.** Yes, but
  only non-secret prefs, only behind auth, and *distinct from* Tier 3
  presentation state that should never touch the server at all.
- **"No in-app auth; reverse proxy is the boundary" — upheld for now, with a
  revisit trigger.** ADR-0001 is right for the single-user shape and is a hard
  prerequisite for any Tier 2 UI. But it is **not foreclosed forever**: the
  trigger to reopen it is the arrival of **mutable server-side settings that
  need per-feature authorization**, or any move toward **multiple identities**.
  Reverse-proxy auth is all-or-nothing; the day the app needs "anyone may search,
  only an admin may change import policies," in-app auth returns to the table.
  Until then, the proxy is correct and cheaper.
- **"Secrets never in the DB" — upheld for deployment secrets, with one
  sanctioned exception.** Deployment secrets (MAM cookie, client passwords) stay
  in env, always. **Per-integration user secrets** created at runtime (each
  indexer's API key) are the one case the DB may hold a secret — encrypted at
  rest via envelope encryption (data key in the DB, master key in env), behind
  auth. This is not a loophole; it is the only correct home for a secret that is
  *user-created, per-item, and unknown at deploy time*.

## Classify every current setting

Using the tiers above, every configuration input on `master` `000a178`:

### Deployment configuration (Tier 1 — env, restart-required)

`MAM_COOKIE` (secret), `TORRENT_CLIENT`, `TRANSMISSION_URL`, `TRANSMISSION_USER`,
`TRANSMISSION_PASS` (secret), `QB_URL`, `QB_USER`, `QB_PASS` (secret),
`QB_CATEGORY`, `QB_TAGS`, `HISTORY_DB_URL`, and the download paths
(`/downloads`, `/library`, `/ebooks`, `/ebooks-nosend` — bound to volume
mounts). `NOTIFY_WEBHOOK_URL` sits here today as a semi-secret capability URL.
A future `LOG_LEVEL` and a re-exposed `UMASK` belong here too.

### Operational settings (Tier 1 default → Tier 2 override)

`AUTO_IMPORT_POLL_INTERVAL` and `FL_WEDGE_MIN_RESERVE` are the two live examples.
**Should they become editable?** Only once a Tier-2 UI exists and only as
overrides on top of an env default. **Should they require restart?** Today yes
(singleton read once at import). Making one live means reading it per-use from
the DB, not from the frozen `settings` object — a deliberate, per-setting choice,
not a blanket switch. Retry counts, queue limits, concurrency, and scheduler
values (all future) join this class.

### User preferences

Search defaults (per-page, default media type), sorting, and filters: **Tier 2
(DB)** if they must drive server-side behavior or persist across devices;
otherwise start in **Tier 3 (`localStorage`)**. Theme and UI layout: **Tier 3,
always** — they never need the server. Notification *routing* (where alerts go)
is operational/semi-secret and leans Tier 1; notification *preferences* (which
events, quiet hours) are Tier 2.

### Immutable constants (Tier 0 — never configurable)

`MAM_BASE` (the indexer's domain — only varies for tests), the MAM category
codes (`{audiobook: "13", ebook: "14"}`), `NOTIFY_TIMEOUT`, and internal labels.
**Why never configurable:** they are protocol/domain facts, not operator choices;
exposing them invites misconfiguration with zero legitimate use. The download
paths are a deliberate middle case — constants *inside* the container, but
effectively set by the operator's volume mounts, and **never** UI-editable
because a user-writable library path is a path-traversal and data-loss footgun.

## Future proxy support (revisited)

With the architecture defined, proxy configuration is **unambiguously Tier 1
(deployment), and a secret when the proxy URL embeds credentials.** It is never
an application setting. Reasoning, including the exotic cases:

- **The app already honors `HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY`** — its httpx
  clients leave `trust_env` at the default `True`. "Proxy support" is therefore
  a documentation task plus a test, not a subsystem.
- **VPN containers / Gluetun** — the dominant self-hosted pattern routes the
  whole container's traffic through a VPN sidecar via
  `network_mode: service:gluetun`. That is a **container-topology** decision made
  in compose/K8s, entirely outside the app — the app needs *zero* proxy config
  for it. This is the strongest reason proxy is deployment config: the most
  common real deployment doesn't touch the app at all.
- **Authenticated proxies** — the URL carries `user:pass`; that makes it a
  **secret**, which forces env (or an encrypted store), never a plaintext UI
  field.
- **Rotating proxies** — handled by a rotating-proxy *gateway* that presents one
  stable endpoint; the app still sees a single URL. Even here it is one env var.
- **Docker Compose / Kubernetes / Portainer / TrueNAS SCALE** — every one has
  first-class env (and `network_mode` / sidecar) support; none benefits from an
  in-app proxy setting.

Conclusion: proxy = **deployment configuration, env, secret when credentialed,
never an app setting.**

## Decision matrix (every current setting)

| Setting | Env | DB | LocalStorage | Constant | Requires restart | Secret |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `MAM_COOKIE` | ✅ | | | | ✅ | ✅ |
| `TORRENT_CLIENT` | ✅ | | | | ✅ | |
| `TRANSMISSION_URL` | ✅ | | | | ✅ | |
| `TRANSMISSION_USER` | ✅ | | | | ✅ | |
| `TRANSMISSION_PASS` | ✅ | | | | ✅ | ✅ |
| `QB_URL` | ✅ | | | | ✅ | |
| `QB_USER` | ✅ | | | | ✅ | |
| `QB_PASS` | ✅ | | | | ✅ | ✅ |
| `QB_CATEGORY` | ✅ | | | | ✅ | |
| `QB_TAGS` | ✅ | | | | ✅ | |
| `NOTIFY_WEBHOOK_URL` | ✅ | ◐ future | | | ✅ | ◐ semi |
| `FL_WEDGE_MIN_RESERVE` | ✅ default | ◐ future override | | | ✅ now | |
| `HISTORY_DB_URL` | ✅ | | | | ✅ | |
| `AUTO_IMPORT_POLL_INTERVAL` | ◐ re-expose | ◐ future override | | ✅ now | ✅ | |
| `UMASK` | ◐ re-expose | | | ✅ now | ✅ | |
| Download paths (`/downloads`, `/library`, `/ebooks`, `/ebooks-nosend`) | ✅ via mounts | | | ◐ in-container | ✅ | |
| `MAM_BASE` | | | | ✅ | ✅ | |
| MAM category codes | | | | ✅ | ✅ | |
| `NOTIFY_TIMEOUT` | | | | ✅ | ✅ | |
| Torrent labels/tags constants | | | | ✅ | ✅ | |
| Proxy (`HTTPS_PROXY` etc.) | ✅ | | | | ✅ | ◐ if credentialed |
| Search defaults (per-page, media type) | | ◐ | ✅ start here | | live | |
| Theme / UI layout | | | ✅ | | live | |
| `LOG_LEVEL` (proposed) | ✅ | | | | ✅ | |

Legend: ✅ = its home / applies · ◐ = conditional or future.

## Migration strategy (phased; no unnecessary work)

- **Phase 1 — Now (no work).** Env-only Tier 1. Correct and sufficient. The only
  defects are documentation, not architecture.
- **Phase 2 — Configuration cleanup (S, docs/constants only).** Document the
  undocumented `HISTORY_DB_URL`; document proxy env vars + add one test proving
  the outbound client honors them; de-duplicate the `"mam-audiofinder"` constant;
  correct any docs implying Transmission was removed (it is the default). No
  behavior change.
- **Phase 3 — Optional settings UI (M, gated).** *Only* if real demand appears
  **and** ADR-0001's reverse proxy is in place. A `settings` KV table in the
  existing SQLite DB; per-request reads for the enumerated **non-secret** Tier-2
  set (poll interval, wedge reserve, search defaults); precedence
  `env default → DB override → code fallback`. Not a roadmap commitment.
- **Phase 4 — Growth features that force structured storage (L, future).**
  Multiple indexers / plugins / multiple simultaneous clients. This is where the
  DB becomes **mandatory** (collections can't be flat env) and where the
  **encrypted per-integration secret** path is built (envelope encryption, master
  key from env). Revisit the auth decision here per the trigger above. Do not
  build any of this speculatively.

## Design principles (govern every future feature)

1. **Deployment owns infrastructure.** Service URLs, paths, topology, and backend
   selection are env-only and set by whoever deploys.
2. **Users own preferences.** Non-secret behavioral and UX settings may be
   user-editable; infrastructure never is.
3. **Secrets never enter the database — except per-integration user secrets,
   which are encrypted at rest with a key from env.** Deployment secrets are env,
   always.
4. **Infrastructure is never editable from the UI.** No path, URL, credential, or
   backend selector is ever a settings-page field.
5. **Authentication is a prerequisite for any mutable server-side setting.** No
   Tier-2 write path ships before ADR-0001's proxy (or a successor auth decision)
   is in place.
6. **One source of truth per setting.** A setting has exactly one home; the only
   sanctioned two-source case is an operational tuning with an env default and a
   DB override, resolved by fixed precedence.
7. **Avoid configuration duplication.** No value is defined in two constants or
   read from two places.
8. **Collections force structure.** The moment a setting becomes "N of a thing,"
   it leaves flat env for the DB — do not reach for `THING_1_*` numbering.
9. **Classify before you build.** Every new option is placed by the
   classification rule above *before* implementation, and this ADR is updated if
   a genuinely new category appears.

## Consequences

- **Every deployment target stays first-class.** Docker, Compose, Portainer,
  TrueNAS SCALE, and Kubernetes all drive Tier 1 through native env/secret
  mechanisms; Gluetun-style VPN routing needs no app config at all.
- **The backup story stays one file** (`/data`) until Phase 4, and even then
  everything persistent remains inside that database.
- **The ADR composes with ADR-0001** instead of contradicting it, and gives every
  future PR a single place to answer "where does this setting go?" before writing
  code.
- **Cost of getting it wrong is bounded:** the classification rule catches the
  two expensive mistakes early — a secret in a plaintext DB field, and an
  infrastructure value exposed in an unauthenticated UI.

## When to revisit

Reopen this ADR when any of these first occurs: (a) the first **collection**
feature (multiple indexers / plugins / clients) is scheduled — Phase 4 begins;
(b) **multiple identities** or **per-feature authorization** is required —
reopen ADR-0001 too; (c) a proposed setting genuinely fits none of the seven
classification questions — the framework has a gap to fix.

## END ADR TEXT

---

## Maintenance notes

- The ADR is deliberately a *decision framework*, not a build plan. It authorizes
  no code. Phases 2–4 each become their own `plans/` entries **only when the
  maintainer chooses to pursue them** — Phase 2 is the only one worth doing soon,
  and it is doc/test hygiene.
- If the executor finds `docs/adr/0002-configuration-philosophy.md` already
  exists, STOP — do not overwrite a hand-edited version.
- Reviewer (the ADR author) should confirm the created file matches the inlined
  text and that no `app/` file was touched (the pytest gate proves it).
