# Plan 008: qBittorrent is a selectable download client alongside Transmission

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 6543acd..HEAD -- app/main.py docker-compose.yml README.md AGENTS.md`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED
- **Depends on**: none (soft: plan 001 for the test harness; interacts with plan 006 — see Maintenance notes)
- **Category**: direction / feature
- **Planned at**: commit `6543acd`, 2026-07-22

## Why this matters

qBittorrent support existed until commit `66c30ef` ("drop qb, use transmission",
2026-04-23), which switched the app to Transmission. Everything built since —
freeleech wedges, ebook/`kindle-nosend` handling, hardlink imports, the import
`Retry` action, and the auto-import poller — is **client-agnostic** and must be
preserved. This plan brings qBittorrent back as a **selectable** backend behind
a `TORRENT_CLIENT` environment switch (default `transmission`), so existing
Transmission deployments are unaffected and qBittorrent users get first-class
support again.

Crucially, this is **not** a revert of `66c30ef`. Reverting would delete the
Transmission-era features. Instead, the three client-specific operations the app
performs are placed behind a tiny abstraction with two implementations:
Transmission (today's code, reused unchanged) and qBittorrent (reintroduced,
adapted to the current env-only architecture). The removed setup UI /
`config.json` / `QB_PATH_MAP` machinery is **not** revived — the author
deliberately removed it (commits `7e11918`, `762464b`, `b4a39d4`), and the app
is now env-configured with fixed in-container mount points.

## Current state

The app performs exactly **three** download-client-specific operations, all in
`app/main.py`. Everything else (MAM search, `.torrent` fetch with FL-wedge
logic, sanitize/hardlink/copy import, history DB, auto-import loop) is shared.

**Config** — `Settings.__init__` (`app/main.py:59-77`):
```python
class Settings:
    def __init__(self) -> None:
        self.MAM_BASE = DEFAULT_MAM_BASE
        self.MAM_COOKIE = build_mam_cookie(os.getenv("MAM_COOKIE", ""))
        if not self.MAM_COOKIE:
            raise RuntimeError("MAM_COOKIE environment variable is required and must be set to a non-empty value")
        self.TRANSMISSION_URL = os.getenv("TRANSMISSION_URL", "http://transmission:9091/transmission/rpc").rstrip("/")
        self.TRANSMISSION_USER = os.getenv("TRANSMISSION_USER", "")
        self.TRANSMISSION_PASS = os.getenv("TRANSMISSION_PASS", "")
        self.TRANSMISSION_LABEL = DEFAULT_TRANSMISSION_LABEL
        ...
```
Relevant constants near the top (`app/main.py:22-23`):
```python
DEFAULT_TRANSMISSION_LABEL = "mam-audiofinder"
TRANSMISSION_NOSEND_LABEL = "kindle-nosend"
```

**Operation 1 — add** (inside `/add`, `app/main.py:452-459`):
```python
        metainfo = base64.b64encode(resp.content).decode("ascii")
        args = await transmission_rpc(
            client,
            "torrent-add",
            torrent_add_arguments(mam_id, "metainfo", metainfo, media_type, send_to_kindle),
        )
        torrent_hash = torrent_hash_from_add_result(args)
        insert_history(mam_id, title, author, narrator, media_type, send_to_kindle, dl, torrent_hash)
```
The `resp.content` above is the raw `.torrent` bytes already fetched from MAM
(with FL-wedge handling) earlier in the same function — that fetch is shared and
does **not** change.

**Operation 2 — list completed** (`list_completed_torrents`, `app/main.py:545-589`),
consumed by `auto_import_cycle` (`app/main.py:825-826`):
```python
    completed = await list_completed_torrents()
    completed_hashes = {item.get("hash") for item in completed if item.get("hash")}
```

**Operation 3 — files + source dir for import** (inside `import_torrent_to_library`,
`app/main.py:760-787`):
```python
    # Query Transmission for files and download directory.
    async with httpx.AsyncClient(timeout=30) as c:
        args = await transmission_rpc(c, "torrent-get", {
            "ids": [h],
            "fields": ["id", "hashString", "name", "downloadDir", "labels", "files"],
        })
        torrents = args.get("torrents") or []
        info = torrents[0] if torrents else {}
        files = info.get("files") or []
        if not files:
            raise HTTPException(status_code=404, detail="No files found for torrent")

        download_dir = (info.get("downloadDir") or "").rstrip("/")
        if not download_dir:
            raise HTTPException(status_code=404, detail="Torrent download directory not found")

    source_dir = Path(validate_download_path(download_dir))
    ...
    names = [(f.get("name") or "").lstrip("/") for f in files if f.get("name")]
```
`validate_download_path` (`app/main.py:736`) requires the source directory to be
under `/downloads`. This constraint is preserved and applies to **both** clients
(see the path-mapping note in Scope).

**Existing Transmission helpers that will be REUSED unchanged** (do not modify):
- `transmission_rpc` (`app/main.py:311`), `transmission_auth` (`app/main.py:306`)
- `transmission_labels` (`app/main.py:329`), `torrent_add_arguments` (`app/main.py:339`)
- `torrent_hash_from_add_result` (`app/main.py:346`)
- `list_completed_torrents` (`app/main.py:545`)

**The historical qBittorrent Web API v2 surface** (from `66c30ef^:app/main.py`,
for reference — adapt, don't copy verbatim):
- Login: `POST {QB_URL}/api/v2/auth/login` with form `username`/`password`;
  success is HTTP 200 with body containing `Ok.`. The SID cookie is stored on
  the `httpx.AsyncClient` and reused for subsequent calls on that client.
- Add: `POST {QB_URL}/api/v2/torrents/add` — multipart with
  `files={"torrents": ("mam.torrent", <bytes>, "application/x-bittorrent")}` and
  `data={"category": ..., "tags": "a,b"}`. Success is HTTP 200 body `Ok.`.
  The response does **not** include the infohash.
- Find hash / list: `GET {QB_URL}/api/v2/torrents/info` with params like
  `{"tag": "mamid=<id>", "filter": "all"}` or
  `{"category": <cat>, "filter": "completed"}` → JSON array of
  `{hash, name, save_path, ...}`.
- Files: `GET {QB_URL}/api/v2/torrents/files?hash=<h>` → JSON array of `{name}`
  (names are relative to `save_path`, including the top folder for multi-file
  torrents — the same shape Transmission's `downloadDir` + `files[].name` use).

**Conventions** (`AGENTS.md`): 4-space indent, `snake_case` functions,
`CamelCase` classes (`Settings`, `AddBody` already exist — new client classes
fit), helpers kept flat in `main.py`, no new runtime dependencies. Commit
messages: short, present-tense, no prefixes.

The DB schema is already client-neutral (`torrent_status` / `torrent_hash`
columns — `app/main.py:94-140`); do **not** reintroduce the old `qb_status` /
`qb_hash` columns.

## Commands you will need

| Purpose        | Command                                                                                          | Expected on success        |
|----------------|--------------------------------------------------------------------------------------------------|----------------------------|
| Syntax check   | `python3 -m py_compile app/main.py`                                                               | exit 0                     |
| Import smoke (Transmission default) | `cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_t.db python -c "import main; print(type(main.get_torrent_client()).__name__)" && rm -f app/tmp_t.db` | prints `TransmissionClient` |
| Import smoke (qB)               | `cd app && MAM_COOKIE=x TORRENT_CLIENT=qbittorrent HISTORY_DB_URL=sqlite:///tmp_q.db python -c "import main; print(type(main.get_torrent_client()).__name__)" && rm -f app/tmp_q.db` | prints `QbittorrentClient` |
| Run tests      | `cd app && python -m pytest -q`                                                                   | all pass (if plan 001 landed) |

(The `HISTORY_DB_URL` override exists only if plan 001 has landed. If it hasn't,
the DB path is hardcoded to `/data`; run the smoke tests where `/data` is
writable, or land plan 001 Step 1 first. See STOP conditions.)

## Scope

**In scope**:
- `app/main.py` — add config, qB helpers, the client abstraction, and rewire the
  three call sites.
- `docker-compose.yml` — add the new env vars.
- `README.md`, `AGENTS.md` — document the `TORRENT_CLIENT` switch and qB vars.
- `app/tests/test_helpers.py` — add tests (only if plan 001 has landed).

**Out of scope** (do NOT touch):
- The existing `transmission_*` helpers and `list_completed_torrents` — reuse
  them from `TransmissionClient`; do not edit their bodies.
- The MAM `.torrent` fetch and FL-wedge logic in `/add` (`app/main.py:429-451`) —
  client-agnostic; unchanged.
- `sanitize`, `next_available`, `hardlink_one`, `copy_one`,
  `validate_download_path`, the history DB helpers — shared; unchanged.
- The frontend (`app/static/app.js`, templates) — `/add`, `/history`, `/account`
  response shapes do not change, so no UI change is needed.
- **Do NOT** revive the setup UI, `/setup`, `config.json`, `QB_PATH_MAP`,
  `QB_INNER_DL_PREFIX`, `QB_SAVEPATH`, or the old `qb_status`/`qb_hash` columns.
- **Path mapping is out of scope**: this plan requires qB's completed downloads
  to be visible at `/downloads` inside the app container (same shared-mount model
  the README already prescribes for Transmission). If a deployment's qB
  `save_path` is not under `/downloads`, that is a documented limitation, not a
  bug to fix here (see STOP conditions and Maintenance notes).

## Git workflow

- Branch: `advisor/008-qbittorrent-client`.
- Commit in logical units (config, abstraction, wiring, docs, tests); present-tense
  messages (e.g. `Add selectable qBittorrent download client`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add configuration

Near the top constants (`app/main.py:22-23`), add:
```python
DEFAULT_QB_CATEGORY = "mam-audiofinder"
```
In `Settings.__init__`, after the `TRANSMISSION_LABEL` line (`app/main.py:68`),
add:
```python
        self.TORRENT_CLIENT = os.getenv("TORRENT_CLIENT", "transmission").strip().lower()
        if self.TORRENT_CLIENT not in ("transmission", "qbittorrent"):
            raise RuntimeError("TORRENT_CLIENT must be 'transmission' or 'qbittorrent'")
        self.QB_URL = os.getenv("QB_URL", "http://qbittorrent:8080").rstrip("/")
        self.QB_USER = os.getenv("QB_USER", "")
        self.QB_PASS = os.getenv("QB_PASS", "")
        self.QB_CATEGORY = os.getenv("QB_CATEGORY", DEFAULT_QB_CATEGORY)
        self.QB_TAGS = os.getenv("QB_TAGS", "")
```

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 2: Add the client abstraction and qB helpers

Insert a new section in `app/main.py` immediately **after** the end of
`list_completed_torrents` (after `app/main.py:589`) and before the
`# ---- Perform Import ----` section. Paste the block below verbatim. Method
bodies resolve names (`transmission_rpc`, `list_completed_torrents`, `settings`,
etc.) at call time, so placement here is safe.
```python
# ---------------------------- Torrent client abstraction ----------------------------

def qb_tags(mam_id: str = "", media_type: str = MEDIA_TYPE_AUDIOBOOK, send_to_kindle: bool = True) -> list[str]:
    tags = [t.strip() for t in (settings.QB_TAGS or "").split(",") if t.strip()]
    if mam_id:
        tags.append(f"mamid={mam_id}")
    if normalize_media_type(media_type) == MEDIA_TYPE_EBOOK and not send_to_kindle:
        tags.append(TRANSMISSION_NOSEND_LABEL)
    return tags


class TorrentClient:
    async def add_torrent(self, metainfo: bytes, mam_id: str, media_type: str, send_to_kindle: bool) -> str | None:
        raise NotImplementedError

    async def completed_hashes(self) -> set[str]:
        raise NotImplementedError

    async def torrent_source(self, torrent_hash: str) -> tuple[list[str], str]:
        """Return (relative file names, source directory) for a completed torrent."""
        raise NotImplementedError


class TransmissionClient(TorrentClient):
    async def add_torrent(self, metainfo, mam_id, media_type, send_to_kindle):
        async with httpx.AsyncClient(timeout=60) as client:
            b64 = base64.b64encode(metainfo).decode("ascii")
            args = await transmission_rpc(
                client, "torrent-add",
                torrent_add_arguments(mam_id, "metainfo", b64, media_type, send_to_kindle),
            )
            return torrent_hash_from_add_result(args)

    async def completed_hashes(self):
        completed = await list_completed_torrents()
        return {item.get("hash") for item in completed if item.get("hash")}

    async def torrent_source(self, torrent_hash):
        async with httpx.AsyncClient(timeout=30) as c:
            args = await transmission_rpc(c, "torrent-get", {
                "ids": [torrent_hash],
                "fields": ["id", "hashString", "name", "downloadDir", "labels", "files"],
            })
            torrents = args.get("torrents") or []
            info = torrents[0] if torrents else {}
            files = info.get("files") or []
            if not files:
                raise HTTPException(status_code=404, detail="No files found for torrent")
            download_dir = (info.get("downloadDir") or "").rstrip("/")
            if not download_dir:
                raise HTTPException(status_code=404, detail="Torrent download directory not found")
            names = [(f.get("name") or "").lstrip("/") for f in files if f.get("name")]
            return names, download_dir


class QbittorrentClient(TorrentClient):
    async def _login(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            f"{settings.QB_URL}/api/v2/auth/login",
            data={"username": settings.QB_USER, "password": settings.QB_PASS},
        )
        if r.status_code != 200 or "Ok" not in (r.text or ""):
            raise HTTPException(status_code=502, detail=f"qBittorrent login failed: {r.status_code}")

    async def add_torrent(self, metainfo, mam_id, media_type, send_to_kindle):
        async with httpx.AsyncClient(timeout=60) as client:
            await self._login(client)
            data = {"category": settings.QB_CATEGORY}
            tags = qb_tags(mam_id, media_type, send_to_kindle)
            if tags:
                data["tags"] = ",".join(tags)
            files = {"torrents": ("mam.torrent", metainfo, "application/x-bittorrent")}
            r = await client.post(f"{settings.QB_URL}/api/v2/torrents/add", data=data, files=files)
            if r.status_code != 200 or "Ok" not in (r.text or ""):
                raise HTTPException(status_code=502, detail=f"qBittorrent add failed: {r.status_code} {r.text[:160]}")
            if not mam_id:
                return None
            info = await client.get(
                f"{settings.QB_URL}/api/v2/torrents/info",
                params={"tag": f"mamid={mam_id}", "filter": "all"},
            )
            try:
                arr = info.json()
            except ValueError:
                return None
            if isinstance(arr, list) and arr:
                return arr[0].get("hash")
            return None

    async def completed_hashes(self):
        async with httpx.AsyncClient(timeout=30) as c:
            await self._login(c)
            r = await c.get(
                f"{settings.QB_URL}/api/v2/torrents/info",
                params={"category": settings.QB_CATEGORY, "filter": "completed"},
            )
            try:
                arr = r.json()
            except ValueError:
                arr = []
            return {t.get("hash") for t in arr if isinstance(t, dict) and t.get("hash")}

    async def torrent_source(self, torrent_hash):
        async with httpx.AsyncClient(timeout=30) as c:
            await self._login(c)
            info_r = await c.get(f"{settings.QB_URL}/api/v2/torrents/info", params={"hashes": torrent_hash})
            try:
                arr = info_r.json()
            except ValueError:
                arr = []
            info = arr[0] if isinstance(arr, list) and arr else {}
            save_path = (info.get("save_path") or "").rstrip("/")
            if not save_path:
                raise HTTPException(status_code=404, detail="Torrent save path not found")
            files_r = await c.get(f"{settings.QB_URL}/api/v2/torrents/files", params={"hash": torrent_hash})
            try:
                files = files_r.json()
            except ValueError:
                files = []
            if not files:
                raise HTTPException(status_code=404, detail="No files found for torrent")
            names = [(f.get("name") or "").lstrip("/") for f in files if isinstance(f, dict) and f.get("name")]
            return names, save_path


def get_torrent_client() -> TorrentClient:
    if settings.TORRENT_CLIENT == "qbittorrent":
        return QbittorrentClient()
    return TransmissionClient()
```

**Verify**:
- `python3 -m py_compile app/main.py` → exit 0.
- The default smoke command prints `TransmissionClient`; the qB smoke command
  prints `QbittorrentClient` (see "Commands you will need").

### Step 3: Rewire the `/add` endpoint to the client factory

In `add_to_transmission` (`app/main.py`), replace the six lines at
`app/main.py:452-458` (the base64 + `transmission_rpc` + hash extraction) with a
single client call. Before:
```python
        metainfo = base64.b64encode(resp.content).decode("ascii")
        args = await transmission_rpc(
            client,
            "torrent-add",
            torrent_add_arguments(mam_id, "metainfo", metainfo, media_type, send_to_kindle),
        )
        torrent_hash = torrent_hash_from_add_result(args)
        insert_history(mam_id, title, author, narrator, media_type, send_to_kindle, dl, torrent_hash)
```
After:
```python
        torrent_hash = await get_torrent_client().add_torrent(resp.content, mam_id, media_type, send_to_kindle)
        insert_history(mam_id, title, author, narrator, media_type, send_to_kindle, dl, torrent_hash)
```
Leave the surrounding `async with httpx.AsyncClient(timeout=60) as client:` block
and the MAM fetch loop above it untouched (the `client` there is still used for
the MAM `.torrent` GETs).

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 4: Rewire the import file lookup

In `import_torrent_to_library`, replace the Transmission `torrent-get` block
(`app/main.py:760-776`) and remove the now-redundant `names = [...]` line
(`app/main.py:787`). Before (the block plus the later names line):
```python
    # Query Transmission for files and download directory.
    async with httpx.AsyncClient(timeout=30) as c:
        args = await transmission_rpc(c, "torrent-get", {
            "ids": [h],
            "fields": ["id", "hashString", "name", "downloadDir", "labels", "files"],
        })
        torrents = args.get("torrents") or []
        info = torrents[0] if torrents else {}
        files = info.get("files") or []
        if not files:
            raise HTTPException(status_code=404, detail="No files found for torrent")

        download_dir = (info.get("downloadDir") or "").rstrip("/")
        if not download_dir:
            raise HTTPException(status_code=404, detail="Torrent download directory not found")

    source_dir = Path(validate_download_path(download_dir))
```
After:
```python
    # Query the configured torrent client for files and source directory.
    names, download_dir = await get_torrent_client().torrent_source(h)
    if not names:
        raise HTTPException(status_code=404, detail="No files found for torrent")

    source_dir = Path(validate_download_path(download_dir))
```
Then delete the later duplicate assignment (`app/main.py:787`):
```python
    names = [(f.get("name") or "").lstrip("/") for f in files if f.get("name")]
```
Leave the `roots` / `common_root` computation that follows it (it uses `names`)
and everything below unchanged.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "info.get(\"files\")\|info.get(\"downloadDir\")" app/main.py` shows those
now only inside `TransmissionClient.torrent_source`, not in
`import_torrent_to_library`.

### Step 5: Rewire the auto-import completed-list lookup

In `auto_import_cycle`, replace `app/main.py:825-826`. Before:
```python
    completed = await list_completed_torrents()
    completed_hashes = {item.get("hash") for item in completed if item.get("hash")}
```
After:
```python
    completed_hashes = await get_torrent_client().completed_hashes()
```
Keep `list_completed_torrents` defined — `TransmissionClient.completed_hashes`
calls it.

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 6: Add the config surface + docs

In `docker-compose.yml`, add to the `environment:` block (after the
`TRANSMISSION_PASS` line):
```yaml
      # Download client: "transmission" (default) or "qbittorrent"
      TORRENT_CLIENT: "transmission"
      # qBittorrent settings (used when TORRENT_CLIENT=qbittorrent)
      QB_URL: "http://qbittorrent:8080"
      QB_USER: ""
      QB_PASS: ""
      QB_CATEGORY: "mam-audiofinder"
```
In `README.md`, add a short subsection under Configuration explaining:
- `TORRENT_CLIENT` selects `transmission` (default) or `qbittorrent`.
- When `qbittorrent`: set `QB_URL`, `QB_USER`, `QB_PASS`, and optionally
  `QB_CATEGORY` (default `mam-audiofinder`) / `QB_TAGS`.
- **qBittorrent's completed downloads must be visible at `/downloads` inside the
  app container** (same shared-mount requirement as Transmission), and downloads
  + the audiobook library must share one filesystem for hardlinks.
Add the four qB variables to the Configuration table.
In `AGENTS.md`, note in the Config & Storage section that the download client is
selected by `TORRENT_CLIENT` and both clients import from the same `/downloads`
mount.

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"` → `yaml ok`
(if PyYAML is missing, `pip install pyyaml` for this check only).

### Step 7: Add tests (only if plan 001 has landed)

Check: `test -f app/tests/test_helpers.py && echo present || echo absent`.
- If **absent**, skip this step (record in the status note that qB unit tests are
  deferred pending plan 001).
- If **present**, add to `app/tests/test_helpers.py`:
```python
def test_get_torrent_client_selects_backend(monkeypatch):
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "transmission")
    assert type(main.get_torrent_client()).__name__ == "TransmissionClient"
    monkeypatch.setattr(main.settings, "TORRENT_CLIENT", "qbittorrent")
    assert type(main.get_torrent_client()).__name__ == "QbittorrentClient"


def test_qb_tags():
    monkeypatch_tags = main.qb_tags("123", main.MEDIA_TYPE_EBOOK, send_to_kindle=False)
    assert "mamid=123" in monkeypatch_tags
    assert main.TRANSMISSION_NOSEND_LABEL in monkeypatch_tags
    # audiobook, kindle on -> just the mamid tag (no nosend)
    assert main.TRANSMISSION_NOSEND_LABEL not in main.qb_tags("1", main.MEDIA_TYPE_AUDIOBOOK, True)
```

**Verify**: `cd app && python -m pytest -q` → all pass, including the two new tests.

## Test plan

- **Unit (required if plan 001 landed)**: `get_torrent_client()` returns the
  right class per `settings.TORRENT_CLIENT`; `qb_tags` builds `mamid=` and
  `kindle-nosend` tags correctly. Model after the existing helper tests in
  `app/tests/test_helpers.py`.
- **Transmission regression (required)**: the default backend must be unchanged.
  `python3 -m py_compile app/main.py` + both import smoke commands + (if 001)
  the full pytest suite must pass. Because `TransmissionClient` reuses the
  untouched `transmission_*` helpers, behavior should be identical.
- **qBittorrent integration (manual — cannot be unit-tested without a live qB or
  HTTP mocks)**: with `TORRENT_CLIENT=qbittorrent` and a reachable qB instance,
  (1) add a torrent from the UI and confirm it appears in qB under category
  `mam-audiofinder` with a `mamid=<id>` tag and a `Added` history row with a
  hash; (2) let it complete and confirm the auto-import poller imports it into
  `/library` (audiobook) or `/ebooks` (ebook); (3) confirm the `Retry` action
  works on a deliberately-failed import.
- **Deferred (recommended follow-up, not required here)**: `respx`-based tests
  that mock the qB Web API for `add_torrent` / `completed_hashes` /
  `torrent_source`. Noted in Maintenance notes.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "TORRENT_CLIENT" app/main.py` shows the Settings field, the validation, and the factory
- [ ] `grep -n "class QbittorrentClient\|class TransmissionClient\|def get_torrent_client" app/main.py` shows all three
- [ ] Default import smoke prints `TransmissionClient`; qB smoke prints `QbittorrentClient`
- [ ] `grep -n "await get_torrent_client()" app/main.py` shows the three call sites (`/add`, `import_torrent_to_library`, `auto_import_cycle`)
- [ ] `grep -n "qb_status\|qb_hash\|QB_PATH_MAP\|/setup\|config.json" app/main.py` returns no matches (old architecture not revived)
- [ ] `docker-compose.yml` contains `TORRENT_CLIENT`, `QB_URL`, `QB_USER`, `QB_PASS`, `QB_CATEGORY`
- [ ] `cd app && python -m pytest -q` exits 0 (if plan 001 landed)
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row for 008 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any "Current state" excerpt does not match live code (the file drifted since
  this plan was written).
- Plan 001 has not landed and the smoke commands fail on a database open error
  (the `HISTORY_DB_URL` override doesn't exist yet) — run plan 001 Step 1 first,
  or run the smokes where `/data` is writable, and note it.
- During manual qB testing, `import_torrent_to_library` fails with the
  `validate_download_path` error ("expects completed downloads under
  /downloads") — this means the qB `save_path` is not under `/downloads` in the
  app container. Do **not** hack around `validate_download_path`; this is the
  documented path-mapping limitation. Report it as needing the deferred
  path-mapping follow-up (or the operator must mount qB's downloads at
  `/downloads`).
- qB `torrents/add` returns 200 but `torrents/info?tag=mamid=<id>` returns an
  empty array (no hash) — report it; the history row is still inserted with a
  null hash but auto-import can't match it. Consider whether qB's "Automatic
  Torrent Management" is relocating files (a deployment issue, not a code bug).

## Maintenance notes

- **Interaction with plan 006** (remove dead code): plan 006 slims
  `list_completed_torrents` to return `[{"hash": h}]`. `TransmissionClient.completed_hashes`
  here only reads `item.get("hash")`, so the two are compatible in either order;
  if both are applied, rebase and re-run the smoke tests.
- **Path mapping** is the known limitation of this plan. If users run qB with a
  `save_path` prefix that differs from the app's `/downloads` mount, a future
  plan can reintroduce a *narrow* env-based mapping (`QB_DOWNLOAD_PREFIX` →
  `/downloads`) applied inside `QbittorrentClient.torrent_source` — but keep it
  env-only; do not revive the old `config.json`/setup-UI machinery.
- **Hash reliability**: qB does not return the infohash on add, so this plan
  finds it by querying the `mamid=<id>` tag. A more robust approach computes the
  v1 infohash (SHA1 of the bencoded `info` dict) from the `.torrent` bytes — but
  that needs a bencode parser (a new dependency), deliberately avoided here.
- Reviewer should confirm the Transmission path is byte-for-byte behavior-identical
  (the `transmission_*` helpers were not edited, only wrapped), that no `qb_*` DB
  columns or setup-UI code were reintroduced, and that the three call sites all
  route through `get_torrent_client()`.
