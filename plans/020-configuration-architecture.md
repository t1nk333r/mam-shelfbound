# Plan 020 (DESIGN / ARCHITECTURE REVIEW): Runtime configuration strategy

> **This is a design deliverable, not an implementation plan.** It produces a
> recommendation and (if accepted) a follow-up ADR + scoped implementation
> plans. It ships no code. Per the request, nothing is implemented here.
>
> **Written against**: `master` @ commit `000a178`, 2026-07-25.
> **Depends on / composes with**: `docs/adr/0001-authentication.md` (plan 019),
> whose decision — *no in-app auth; single-user; reverse proxy for remote
> access* — is load-bearing for Part 2 and Part 4 below.

---

## 0. Two premises in the brief are false — read this first

The request is framed on two assumptions. Both are wrong against the code on
`master` (`000a178`), and correcting them is the highest-value output of this
review, because designing around them would cause real harm.

### Premise 1: "The application has already migrated from Transmission to qBittorrent."

**It has not.** qBittorrent was *added as a selectable alternative*, not migrated
to. Evidence (`app/main.py`):

```python
# app/main.py:105-107
self.TORRENT_CLIENT = os.getenv("TORRENT_CLIENT", "transmission").strip().lower()
if self.TORRENT_CLIENT not in ("transmission", "qbittorrent"):
    raise RuntimeError("TORRENT_CLIENT must be 'transmission' or 'qbittorrent'")
```

```python
# app/main.py:770-772
def get_torrent_client() -> TorrentClient:
    if settings.TORRENT_CLIENT == "qbittorrent":
        return QbittorrentClient()
    return TransmissionClient()
```

**Transmission is the default backend.** `TransmissionClient` is fully wired,
tested, and selected unless the operator explicitly sets
`TORRENT_CLIENT=qbittorrent`. The `TRANSMISSION_*` variables are **not obsolete**;
deleting them would break the default deployment and every existing Transmission
user. Any "migration" that removes Transmission config is a **behavior change**
(dropping a supported backend), not a documentation cleanup — and it is not what
the current code represents.

**Implication for this review:** wherever the brief says "obsolete Transmission
variables to remove," the correct finding is "Transmission variables are live and
must stay until a *separate, deliberate* decision drops the backend." That
decision is out of scope here; if the maintainer wants it, it is its own plan
(flip the default, deprecate over a release, keep it working meanwhile).

### Premise 2: "the new outbound proxy feature."

**No proxy feature exists** — no proxy code, config, or documentation anywhere
(`grep -niE "proxy|socks|https_proxy" app/main.py docker-compose.yml README.md`
→ nothing). It is prospective. More importantly:

**The app's HTTP clients already honor standard proxy environment variables.**
Every outbound call uses `httpx.AsyncClient(timeout=...)` with no `trust_env=False`
(confirmed at `app/main.py:292, 504, 508, 534, 612, 655, 668, 719, 734, 747`).
httpx defaults `trust_env=True`, which means it already reads `HTTP_PROXY` /
`HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY` from the environment. So the "new proxy
feature," for the outbound MAM calls that actually need it, is **largely already
implemented** — it needs a verifying test and a documentation line, not a
configuration subsystem. This reframes Part 2 entirely: the question is not
"how do we build proxy config," it is "how much, if anything, do we need beyond
what httpx already does."

### Also: the config table in the brief is stale

The brief pastes a 4-row table (MAM + 3 TRANSMISSION vars). The **actual**
`README.md` on `master` already documents 12 variables (it was updated by the
qBittorrent, notification, and wedge-reserve work). The maintainer is looking at
a pre-merge copy. The real current surface is enumerated in Part 1.

---

## Part 1 — The actual configuration surface (audited)

Every runtime configuration input on `master` `000a178`, from
`Settings.__init__` (`app/main.py:95-123`) and the module constants
(`app/main.py:16-30`).

### A. Environment variables (read via `os.getenv`)

| Var | Default | Validation | Class | Documented? |
|---|---|---|---|---|
| `MAM_COOKIE` | — (required, raises if empty) | non-empty | **secret** | ✅ |
| `TORRENT_CLIENT` | `transmission` | enum {transmission, qbittorrent} | topology | ✅ |
| `TRANSMISSION_URL` | `http://transmission:9091/...` | `.rstrip("/")` | connection | ✅ |
| `TRANSMISSION_USER` | `""` | — | connection | ✅ |
| `TRANSMISSION_PASS` | `""` | — | **secret** | ✅ |
| `QB_URL` | `http://qbittorrent:8080` | `.rstrip("/")` | connection | ✅ |
| `QB_USER` | `""` | — | connection | ✅ |
| `QB_PASS` | `""` | — | **secret** | ✅ |
| `QB_CATEGORY` | `mam-audiofinder` | — | operational label | ✅ |
| `QB_TAGS` | `""` | — | operational label | ✅ |
| `FL_WEDGE_MIN_RESERVE` | `0` | non-negative int, raises otherwise | user preference | ✅ |
| `NOTIFY_WEBHOOK_URL` | `""` | `.strip()` | semi-secret (capability URL) | ✅ |
| `HISTORY_DB_URL` | `sqlite:////data/history.db` | — | infra | ❌ **undocumented** |

### B. Hardcoded values (on the `settings` object, but from constants — no env hook)

| Value | Constant | Was it ever env-configurable? |
|---|---|---|
| `MAM_BASE = "https://www.myanonamouse.net"` | `DEFAULT_MAM_BASE` | no — only varies for tests |
| `TRANSMISSION_LABEL = "mam-audiofinder"` | `DEFAULT_TRANSMISSION_LABEL` | no |
| `DOWNLOADS_DIR = "/downloads"` | constant | no — tied to volume mounts |
| `LIBRARY_DIR = "/library"` | constant | no — tied to volume mounts |
| `EBOOKS_DIR = "/ebooks"` | constant | no — tied to volume mounts |
| `EBOOKS_NOSEND_DIR = "/ebooks-nosend"` | constant | no — tied to volume mounts |
| `UMASK = "0002"` | `DEFAULT_UMASK` | **yes — deliberately de-parameterised** |
| `AUTO_IMPORT_POLL_INTERVAL = 30` | `DEFAULT_AUTO_IMPORT_POLL_INTERVAL` | **yes — deliberately de-parameterised** |
| `NOTIFY_TIMEOUT = 10` | `DEFAULT_NOTIFY_TIMEOUT` | no |

### C. Persistent state

- SQLite DB at `/data/history.db` (`HISTORY_DB_URL`). Schema: **one `history`
  table** (download records + import status). **No configuration is stored in
  the database today.** This matters for Part 3/4: the DB is an *available*
  config home with zero new dependencies.

### Findings against the brief's checklist

- **Obsolete variables** — **none.** `TRANSMISSION_*` is the default backend, not
  legacy. (Refutes the premise.)
- **Renamed variables** — none.
- **Missing documentation** — **`HISTORY_DB_URL`** is env-readable (added by the
  test-harness work) but appears in neither `README.md` nor `docker-compose.yml`.
  Minor: its default is correct for production and it exists mainly as a test
  seam. Worth one documented row so operators who bind-mount `/data` elsewhere
  know it exists.
- **Duplicated configuration** — the literal `"mam-audiofinder"` is defined
  **twice**: `DEFAULT_TRANSMISSION_LABEL` and `DEFAULT_QB_CATEGORY`
  (`app/main.py:23, 27`). Cosmetic; they are conceptually the same "this app's
  tag/category" and could share one constant. Also `TRANSMISSION_NOSEND_LABEL =
  "kindle-nosend"` is reused as a *qBittorrent tag* — correct value, misleading
  name (a naming smell already recorded in the index, not a defect).
- **Hardcoded defaults that arguably should be configurable** — `UMASK` and
  `AUTO_IMPORT_POLL_INTERVAL` were env vars historically and were **deliberately**
  frozen into constants as a simplification (recorded in the deep-sweep notes).
  Re-exposing them is a judgment call, not a bug. `MAM_BASE` and the library
  paths are correctly hardcoded (paths are bound to container mount points; see
  `AGENTS.md`: "Storage paths are static inside the app container").
- **Settings that should no longer exist** — **none.** The brief implies
  `TRANSMISSION_*` should go; it should not.

**Is the configuration architecture still appropriate?** **Yes, for what the app
is.** Flat environment variables read once into a `settings` singleton is the
right model for a single-user, single-process, Docker-deployed tool. The only
real tension the qBittorrent addition introduced is **conditional relevance**:
half the client vars (`TRANSMISSION_*` or `QB_*`) are inert depending on
`TORRENT_CLIENT`. That is mild noise, not a design flaw — every switchable-backend
app has it. It does **not** justify a settings page, a config file, or a
database-backed config layer. See Parts 2–4.

---

## Part 2 — Proxy configuration architecture

**Reframed by the finding above:** httpx already reads `HTTPS_PROXY` et al. from
the environment for every outbound call. So the realistic question is *"what, if
anything, do we add beyond the zero-code behavior httpx already gives us?"* The
four options are evaluated as *ways to configure the proxy*, but the baseline to
beat is "document the standard env vars and write one test."

### Comparison matrix

Legend: ✅ good · ◐ acceptable · ✗ poor.

| Criterion | A: Env vars only | B: In-app settings page | C: Hybrid (env default + UI override) | D: Config file |
|---|---|---|---|---|
| Usability (this app's single-user operator) | ✅ one line in compose | ◐ nice UI, but see security | ◐ two places to look | ◐ edit a file, restart |
| Docker | ✅ native | ✗ needs writable volume for state | ◐ | ◐ needs mounted file |
| Portainer | ✅ env fields in stack UI | ✗ can't set via Portainer | ◐ env part yes | ✗ must exec/edit file |
| TrueNAS SCALE (app catalog) | ✅ env in the app config form | ✗ | ◐ | ✗ awkward on k3s |
| Kubernetes | ✅ env / envFrom / Secret | ✗ needs PVC + in-cluster mutation | ◐ | ◐ ConfigMap, but then why not env |
| Bare-metal | ✅ shell/systemd `Environment=` | ◐ | ◐ | ✅ familiar |
| Runtime changes (no restart) | ✗ needs restart | ✅ live | ✅ live for the UI-owned subset | ✗ (unless a watcher is built) |
| Security | ✅ nothing new exposed | ✗ **unauthenticated mutable endpoint** (see 019) | ✗ same exposure for the UI part | ◐ file perms |
| Secret management | ✅ env / Docker/K8s secrets | ✗ **secrets typed into a browser, stored where?** | ◐ if UI part excludes secrets | ✗ plaintext on disk |
| Maintainability | ✅ ~0 code (httpx) | ✗ form + persistence + validation + auth | ◐ | ◐ parser + precedence |
| Backup implications | ✅ config lives in compose/IaC | ✗ new mutable state to back up | ◐ | ◐ another file to back up |
| Future scalability | ◐ fine to ~dozens of settings | ◐ | ✅ clean split as settings grow | ◐ |

### Advantages / disadvantages, in prose

- **A — Environment variables only.** *Advantage:* for the proxy specifically it
  is nearly free — httpx already honors `HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`, so
  "support a proxy" collapses to a README row and a `respx`/monkeypatch test that
  proves the outbound client routes through a set proxy. Native to every
  deployment target (Portainer/TrueNAS/K8s all have first-class env fields).
  *Disadvantage:* changing it needs a container restart, and it cannot express
  per-user preference (irrelevant here — single user).
- **B — In-app settings page.** *Advantage:* live changes, friendly UX, no
  redeploy. *Disadvantage, and it is decisive:* **this app deliberately has no
  authentication** (plan 019 / `docs/adr/0001-authentication.md`). A settings
  page that can rewrite the proxy, the MAM cookie, or the qB password is an
  **unauthenticated, mutable, secret-bearing control plane** on an app whose own
  README says "do not expose it directly to the public internet." It re-opens
  the exact question 019 just closed, and answers it the wrong way. It also
  raises "where are secrets stored, and encrypted how?" — for which this app has
  no answer today.
- **C — Hybrid (env default + UI override).** *Advantage:* the correct *shape*
  for the long term — deployment config in env, a **small, non-secret** slice
  editable live. *Disadvantage:* only safe if the UI slice rigidly **excludes
  secrets and connection/topology config**, and only after the 019 auth question
  is resolved (reverse proxy). Proxy config sits awkwardly here: a proxy URL can
  itself embed credentials (`http://user:pass@host`), so it leans "secret,"
  which pushes proxy specifically toward env, not the UI.
- **D — Configuration file.** *Advantage:* familiar on bare-metal; supports
  comments. *Disadvantage:* introduces a **third** configuration source (env +
  file + the existing DB), with precedence rules, a parser, a mounted writable
  path, and its own backup story — for no capability env doesn't already provide.
  Strictly worse than env for this app.

### Part 2 recommendation

**For the proxy feature: Option A, and mostly for free.** Document
`HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY`; add a test asserting the outbound MAM
client honors a configured proxy (proving `trust_env` is not disabled and stays
that way); add the rows to `README.md` and `docker-compose.yml`. Do **not** build
a proxy settings page or a proxy config file. If a future need arises to proxy
*only* MAM but not the LAN-local torrent client, that is a small code change
(pass `proxy=` explicitly on the MAM client only) still driven by an env var —
still Option A.

---

## Part 3 — Where each existing (and near-future) setting belongs

The brief's instruction "do not assume they should all be treated the same" is
correct. Four homes: **env** (deployment), **app settings/DB** (live user prefs),
**config file** (rejected — see Part 2), **database** (persistent app state /
the storage layer *behind* app settings). Config file is deliberately absent
below because it earns a place for nothing here.

| Setting | Home | Secret? | Why |
|---|---|---|---|
| `MAM_COOKIE` | **env** | yes | Rotating credential; belongs with deployment secrets (Docker/K8s secret). Never typed into an unauthenticated browser or stored unencrypted in the DB. |
| `TRANSMISSION_PASS`, `QB_PASS` | **env** | yes | Same. |
| `TORRENT_CLIENT` | **env** | no | Selects which backend the *stack* provides; a deployment-topology fact fixed when you compose the services. Not a runtime toggle. |
| `TRANSMISSION_URL` / `QB_URL` | **env** | no | Points at sibling services on the Docker network; part of the deployment wiring. |
| `TRANSMISSION_USER` / `QB_USER` | **env** | no (but paired with a secret) | Kept with its password for coherence. |
| Download dirs (`/downloads`, `/library`, `/ebooks`, `/ebooks-nosend`) | **env-adjacent / immutable (volume mounts)** | no | Bound to container mount points and to the hardlink-same-filesystem invariant. **Must never be user-editable** — a UI-writable library path is a path-traversal / data-loss footgun, and these values must match the actual mounts, which the app cannot change from inside. |
| `HISTORY_DB_URL` | **env** | no | Infra (where state lives). Document it; keep it env. |
| Proxy settings | **env** | leans yes (may embed creds) | Per Part 2. httpx already reads it from env. |
| `AUTO_IMPORT_POLL_INTERVAL` (scan interval) | **env default → optional UI override (C)** | no | Non-secret operational tuning. Safe first candidate for a live, DB-backed override *if* a settings page is ever built. Env sets the deployment default. |
| `FL_WEDGE_MIN_RESERVE` | **env now; good UI-override candidate** | no | Pure behavioral preference; exactly the kind of thing a user might tune live. |
| `QB_CATEGORY` / `QB_TAGS` | **env** | no | Rarely changed; tied to how the torrent client is organized. Env is fine; low value as a UI setting. |
| `NOTIFY_WEBHOOK_URL` (notification settings) | **env now; UI-override candidate, with care** | semi (capability URL) | An ntfy/Gotify URL is a bearer capability — treat as semi-secret. Env is the safe home; if surfaced in a UI later, mask it and gate behind auth. |
| Search preferences (perpage, default media type) | **app settings (DB) or client-side** | no | Per-user UX. The natural first content of a real settings page. Already partly client-side (the frontend `<select>`); could persist in the DB. |
| UI preferences (theme, column layout) | **browser `localStorage`** | no | Pure presentation; never needs the server. The frontend already uses `localStorage`-style patterns. Don't put these in env, DB, or a file. |
| Logging level | **env** | no | Standard 12-factor env knob (`LOG_LEVEL`); read at startup. Not worth a UI. |

**The through-line:** *secrets and topology are deployment facts → env; behavioral
and UX preferences are user facts → DB/localStorage behind auth; paths are
immutable infrastructure → never user-editable.* Nothing here wants a config file.

---

## Part 4 — Five-year configuration strategy

### The model: two tiers, one storage each, minimal overlap

**Tier 1 — Deployment configuration (env vars).** Secrets, connections,
topology, paths, infra. Read **once** at startup into the `settings` singleton.
**Immutable at runtime; restart-required.** This is where everything lives today
and where it should stay. Owned by whoever deploys the stack (compose file,
Portainer stack, K8s manifest, systemd unit).

**Tier 2 — User preferences (SQLite, behind auth).** A **small, explicitly
enumerated, non-secret** set of behavioral/UX settings, stored in the existing
`/data/history.db` (a new `settings` key/value table — **zero new dependency**),
editable **live** through a settings UI. This tier **does not exist yet** and
should be built **only when there is real demand** and **only after** the reverse
proxy from ADR-0001 provides the authentication a mutable control plane requires.

Nothing else. No config file (Tier-3 sprawl for no gain). No secrets in Tier 2.

### The classification, made explicit (the brief asked for each)

- **Immutable deployment config (env, restart-required):** `MAM_COOKIE`,
  `TORRENT_CLIENT`, `TRANSMISSION_URL/USER/PASS`, `QB_URL/USER/PASS`,
  `HISTORY_DB_URL`, download paths, proxy, `LOG_LEVEL`, `UMASK`.
- **User-editable from the UI (Tier 2, live, DB, non-secret) — candidates only:**
  `AUTO_IMPORT_POLL_INTERVAL`, `FL_WEDGE_MIN_RESERVE`, search defaults (perpage,
  default media type), and *display* of notification config. UI-only presentation
  prefs go to `localStorage`, not the server.
- **Secrets (env only, never UI/DB/file unencrypted):** `MAM_COOKIE`,
  `TRANSMISSION_PASS`, `QB_PASS`, any proxy URL embedding credentials,
  `NOTIFY_WEBHOOK_URL` (semi).
- **Require restart:** everything in Tier 1 — because the `settings` singleton is
  built once at import (`settings = Settings()` at module load). Making any value
  live means reading it from the DB per-use, *not* from that frozen object.
- **Changeable live:** only Tier-2 values, and only once they are read
  per-request from the DB instead of the singleton.
- **Precedence (only where a setting has two sources):** keep the dual-source set
  as close to **empty** as possible — each setting should have exactly one home.
  For the few operational values you might want both a deployment default *and* a
  live override (poll interval, wedge reserve):
  **`env var (deployment default)` → overridden by → `DB value (user-set)` →
  falls back to → `hardcoded default`.** Env is the floor the operator sets;
  the UI can move within it; code constant is the last resort. Secrets and
  topology have **no** DB layer, so no precedence question arises for them.

### Why this minimizes operational complexity

- Every deployment target the brief named (Docker, Portainer, TrueNAS SCALE,
  Kubernetes, bare-metal) has **first-class env support**; Tier 1 needs no
  bespoke mechanism on any of them.
- The one piece of persistent state to back up stays **one file** (`/data`).
  Tier 2 rides inside the DB that is already there and already backed up.
- It **composes with the auth decision** already on record instead of quietly
  contradicting it.

---

## Deliverable: recommendation

**Adopt a deliberately narrow Hybrid (Option C), but ship it in that order and
only as far as demand justifies:**

1. **Now — stay Option A (env-only), and correct the docs.** Env is already the
   whole architecture and it is the right one for Tier 1. Immediate, code-free
   actions (each a small follow-up plan, not this document):
   - Document `HISTORY_DB_URL` (the one undocumented var).
   - Add the proxy env vars (`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`) to README +
     compose, plus a test proving the outbound MAM client honors them
     (verifying httpx `trust_env` stays enabled). This *is* the proxy feature.
   - De-duplicate the `"mam-audiofinder"` constant; optionally rename
     `TRANSMISSION_NOSEND_LABEL` to a client-neutral name.
   - **Do not** remove `TRANSMISSION_*`. Do not treat qB as a completed migration.
2. **Later, only on real demand, and only after ADR-0001's reverse proxy is in
   place — add Tier 2.** A `settings` key/value table in the existing SQLite DB,
   a settings UI, and per-request reads for the **enumerated non-secret** set
   (poll interval, wedge reserve, search defaults). Secrets and topology stay in
   env forever.

### Exact split (the brief asked for this, if hybrid)

**Docker environment variables (Tier 1 — always):**
`MAM_COOKIE`, `TORRENT_CLIENT`, `TRANSMISSION_URL`, `TRANSMISSION_USER`,
`TRANSMISSION_PASS`, `QB_URL`, `QB_USER`, `QB_PASS`, `QB_CATEGORY`, `QB_TAGS`,
`HISTORY_DB_URL`, `HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`, `LOG_LEVEL` (new),
`UMASK` (if re-exposed), download paths (via volume mounts).

**Application settings page (Tier 2 — later, non-secret, DB-backed, behind auth):**
`AUTO_IMPORT_POLL_INTERVAL`, `FL_WEDGE_MIN_RESERVE`, search defaults (perpage,
default media type), notification-URL *display/toggle* (value still set in env).
UI-only prefs (theme, layout) → `localStorage`, not the server.

**Never in the settings page:** any password/cookie/token, any URL that embeds
credentials, `TORRENT_CLIENT`, connection URLs, or download paths.

### Why the alternatives are rejected

- **Option B (settings page as the primary mechanism) — rejected.** It puts a
  mutable, secret-bearing control plane on an app with no authentication,
  directly contradicting `docs/adr/0001-authentication.md`. It also has no
  encrypted-at-rest answer for the secrets it would store. Good UX cannot buy
  back that exposure on a "don't expose to the internet" app.
- **Option D (config file) — rejected.** A third configuration source with a
  parser, a writable mount, and precedence rules, delivering nothing env doesn't
  already provide on every target platform. Pure added surface.
- **Pure Option A forever — rejected only as a *ceiling*, not as today's answer.**
  It is exactly right for Tier 1 and should remain so. It is "rejected" only in
  the sense that the five-year design leaves a *narrow, gated* door open to
  Tier 2 for genuine live-preference UX — a door that stays shut until demand and
  the auth prerequisite both exist.

---

## Migration plan from the current configuration

No migration is required for correctness — the current model is sound. The
"migration" is documentation hygiene plus optional, sequenced enhancement. Each
numbered item is a **candidate follow-up plan**, not work done here.

1. **Docs truth-up (S, no code):** add the `HISTORY_DB_URL` row to README +
   compose; state plainly that `TORRENT_CLIENT` defaults to `transmission` and
   both backends are supported (kill the "migrated away" misconception at the
   source).
2. **Proxy via env (S):** README + compose rows for `HTTPS_PROXY`/`ALL_PROXY`/
   `NO_PROXY`; one test asserting the MAM client routes through a configured
   proxy. Closes "the proxy feature" with near-zero code.
3. **Constant hygiene (S):** collapse the duplicated `"mam-audiofinder"`
   constant; optionally client-neutral-rename `TRANSMISSION_NOSEND_LABEL`.
4. **(Conditional) Re-expose `UMASK` / `AUTO_IMPORT_POLL_INTERVAL` as env (S):**
   only if an operator actually needs them; they were removed on purpose.
5. **(Conditional, gated on ADR-0001 reverse proxy) Tier 2 settings store (M):**
   `settings` KV table in SQLite, settings UI, per-request reads for the
   enumerated non-secret set, with the precedence rule above. Build only on
   demand.
6. **(Separate decision, NOT config work) If qBittorrent should become the
   default or Transmission should be dropped:** that is a behavior-change plan of
   its own — flip the default, keep both working, deprecate `TRANSMISSION_*` over
   a documented release window. Do not smuggle it into a "config cleanup."

## What this document is not

- Not code, not an ADR yet. If the maintainer accepts this direction, the natural
  next artifact is `docs/adr/0002-configuration-architecture.md` recording the
  two-tier decision, followed by the S-sized doc/proxy plans above. Those are
  separate, and each should be its own `plans/` entry.
- Not a mandate to build a settings page. The strong default is **env-only stays**;
  Tier 2 is a gated option, not a roadmap commitment.

## Confidence

- **HIGH** that the two premises are false (direct code evidence) and that
  env-only is the right Tier-1 model.
- **HIGH** that a settings page is unsafe *until* the auth question is resolved —
  it follows directly from the app's own ADR-0001.
- **MEDIUM** on the exact Tier-2 membership; that list is a starting point to
  refine against real user requests, not a fixed contract.
- **Not verified by execution:** that httpx honors the proxy env vars in *this*
  app end-to-end (it is httpx's documented default with `trust_env` unset, and no
  client disables it — but migration item 2's test is what would prove it here).
