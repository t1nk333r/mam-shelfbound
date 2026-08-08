# Plan 037: Make audiobook imports support configurable hardlink-to-copy fallback

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 0db27f4..HEAD -- app/main.py app/tests/test_import_fallback.py app/tests/test_preflight.py docker-compose.yml README.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED — copying changes storage consumption; strict mode must remain backward-compatible
- **Depends on**: none (independent of TODO plans 031, 033, and 034)
- **Category**: bug
- **Planned at**: commit `0db27f4`, 2026-08-08

## Why this matters

Audiobook imports always call `os.link`, so an otherwise valid deployment fails
when `/downloads` and `/library` are on different filesystems or ZFS datasets.
The failure is stored as `import_failed`; neither the automatic importer nor the
History-row Retry action can complete until the mounts are changed. The
maintainer's `documrnted-bugs.md` explicitly requests a configurable copy
fallback for cross-filesystem or unsupported-hardlink storage layouts.

This plan adds one restart-required deployment setting with three explicit
policies: `hardlink` (strict and backward-compatible), `auto` (try a hardlink,
then copy only when the OS says linking is unsupported), and `copy` (copy
directly). The default stays `hardlink`: changing it silently would duplicate
potentially large audiobook files and surprise existing operators. Users with
separate filesystems set `auto`; users on filesystems known not to support links
can set `copy`.

## Current state

- `app/main.py` — the single-file FastAPI backend and shared import pipeline.
  Both the 30-second automatic importer (`auto_import_cycle`, lines 1284-1320)
  and `POST /history/{id}/retry` (lines 684-728) call the same
  `import_torrent_to_library` function, so the policy belongs in that shared
  path, not in either caller.

- Configuration is read once in `Settings.__init__` (`app/main.py:97-131`).
  Existing scalar options validate at startup, for example:

  ```python
  # app/main.py:111-113
  self.TORRENT_CLIENT = os.getenv("TORRENT_CLIENT", "transmission").strip().lower()
  if self.TORRENT_CLIENT not in ("transmission", "qbittorrent"):
      raise RuntimeError("TORRENT_CLIENT must be 'transmission' or 'qbittorrent'")
  ```

- The file-operation helpers distinguish hardlink errors but never recover
  (`app/main.py:1008-1038`):

  ```python
  def hardlink_one(src: Path, dst: Path):
      dst.parent.mkdir(parents=True, exist_ok=True)
      try:
          os.link(src, dst)
      except FileNotFoundError:
          raise HTTPException(status_code=400, detail=f"Import source file not found: {src}")
      except FileExistsError:
          raise HTTPException(status_code=400, detail=f"Import destination already exists: {dst}")
      except OSError as exc:
          if exc.errno == errno.EXDEV:
              detail = (
                  f"Could not hardlink '{src}' to '{dst}' because they are on different filesystems. "
                  "Mount downloads and library paths from one shared parent directory."
              )
          elif exc.errno in (errno.EPERM, errno.EACCES):
              detail = f"Could not hardlink '{src}' to '{dst}': permission denied."
          else:
              detail = f"Could not hardlink '{src}' to '{dst}': {exc.strerror or exc}"
          raise HTTPException(status_code=400, detail=detail)

  def copy_one(src: Path, dst: Path):
      dst.parent.mkdir(parents=True, exist_ok=True)
      try:
          shutil.copy2(src, dst)
      ...
  ```

- `import_torrent_to_library` selects hardlink for every audiobook and copy for
  every ebook (`app/main.py:1251-1273`):

  ```python
  import_one = hardlink_one if media_type == MEDIA_TYPE_AUDIOBOOK else copy_one

  # Import all files (skip .cue). Audiobooks hardlink; ebooks copy.
  ...
  import_one(src, safe_child_path(dest_dir, rel_name))
  ```

  Torrent-client-specific behavior ends before this point: Transmission and
  qBittorrent both implement `torrent_source`, and both feed the same list of
  names and download directory into this function. Do not duplicate policy in
  either client class.

- Startup currently detects different devices and warns that imports will fail
  (`app/main.py:168-179`, called from `lifespan` at lines 334-337):

  ```python
  def hardlink_fs_warning(downloads: str, library: str) -> str | None:
      """Return a warning if downloads and library exist on different filesystems
      (audiobook imports hardlink between them and would fail with EXDEV), else None."""
      ...
  ```

  This message must become policy-aware: strict mode still warns about failure,
  `auto` warns about extra copy/storage use, and `copy` emits no hardlink warning.

- `docker-compose.yml:8-25` lists every user-facing runtime environment
  variable. `README.md:17`, `:44-46`, `:66-85`, and `:91` currently state that
  audiobook imports hardlink and that different filesystems always fail. These
  claims must be updated together with the code.

- Tests are plain pytest functions that import `main`, use `monkeypatch` and
  `tmp_path`, and run async code with `asyncio.run`. Match
  `app/tests/test_helpers.py:22-27` for validation tests,
  `app/tests/test_library_guard.py:4-27` for temporary filesystem settings, and
  `app/tests/test_qbittorrent.py:104-136` for synchronous tests of async
  functions. `app/conftest.py` forces the database into the system temp
  directory before importing `main`; do not weaken that isolation.

### Configuration decision to preserve

`docs/adr/0002-configuration-philosophy.md:29-37` makes deployment and storage
topology Tier-1 environment configuration, read once at startup. The import mode
controls whether the operator's mounted storage can hardlink and whether the
deployment pays the disk cost of copies, so classify it as deployment-owned
Tier 1. Do not add a database field or UI control. This also follows
`AGENTS.md`: runtime configuration must be exposed through an environment
variable in `docker-compose.yml`, with no host-specific path hard-coded.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install dependencies | `python -m pip install -r requirements.txt -r requirements-dev.txt` | exit 0 |
| Syntax check | `python -m py_compile app/main.py` | exit 0 |
| Focused tests | `cd app && python -m pytest -q tests/test_import_fallback.py tests/test_preflight.py` | 18 tests pass |
| Full tests | `cd app && python -m pytest -q` | all tests pass |

There is no configured lint or static-typecheck command. Do not add one in this
plan. The advisor could not run the existing suite locally because pytest is not
installed in the current environment; the executor must run the install command
before treating the test commands as verification gates.

## Scope

**In scope** (the only files you should modify):

- `app/main.py` — validate the mode, route audiobook file imports, implement the
  opt-in unsupported-link fallback, and make startup warnings policy-aware.
- `app/tests/test_import_fallback.py` — create focused policy and integration
  tests.
- `app/tests/test_preflight.py` — update existing calls and add mode-aware
  warning tests.
- `docker-compose.yml` — expose the new environment variable with safe comments.
- `README.md` — document modes, default, disk-use trade-off, startup/retry flow,
  and storage-layout behavior.
- `plans/README.md` — update plan status only after implementation.

**Out of scope** (do NOT touch):

- `documrnted-bugs.md` — it is the operator-provided input to this plan and was
  untracked when the plan was written; do not delete, rename, or rewrite it.
- `Dockerfile` and fixed in-container paths. Keep `/downloads`, `/library`, and
  the `/storage` symlink layout unchanged.
- Ebook behavior. Ebooks must continue to use `copy_one` regardless of the new
  audiobook setting.
- History schema/statuses, notification behavior, `mark_history_failed`,
  `mark_history_imported`, the Retry endpoint, and the auto-import loop. They
  already share the correct import chokepoint.
- Transmission/qBittorrent client methods. The policy is client-independent.
- A settings page, per-book UI toggle, database preference, or live reload.
- Fallback for arbitrary I/O failures. `EACCES`, `EROFS`, `ENOSPC`, `EIO`, and
  a missing source must remain errors; copying must not hide access errors,
  read-only storage, full disks, corrupt I/O, or path mistakes. Do not change
  the existing `copy_one` destination-overwrite semantics in this plan.
- New dependencies.

## Git workflow

- Branch: `advisor/037-configurable-hardlink-copy-fallback`
- Use one focused commit with a short present-tense subject, for example
  `Add configurable audiobook copy fallback`.
- Do not push or open a PR unless the operator explicitly instructs it.

## Steps

### Step 1: Add and validate the deployment policy

Near the other constants at `app/main.py:18-31`, add:

```python
DEFAULT_AUDIOBOOK_IMPORT_MODE = "hardlink"
AUDIOBOOK_IMPORT_MODES = ("hardlink", "auto", "copy")
```

In `Settings.__init__`, immediately after torrent-client validation and before
qBittorrent settings, read `AUDIOBOOK_IMPORT_MODE`, strip it, lowercase it, and
reject anything outside `AUDIOBOOK_IMPORT_MODES` with `RuntimeError`. Store the
validated value as `self.AUDIOBOOK_IMPORT_MODE`. The error must name the setting
and all three accepted values. The intended shape is:

```python
self.AUDIOBOOK_IMPORT_MODE = os.getenv(
    "AUDIOBOOK_IMPORT_MODE", DEFAULT_AUDIOBOOK_IMPORT_MODE
).strip().lower()
if self.AUDIOBOOK_IMPORT_MODE not in AUDIOBOOK_IMPORT_MODES:
    raise RuntimeError(
        "AUDIOBOOK_IMPORT_MODE must be 'hardlink', 'auto', or 'copy'"
    )
```

Do not use `is_truthy`; this is a three-state enum, not a boolean. Reading once
at startup is intentional and means changing the value requires a container
restart.

**Verify**:

- `python -m py_compile app/main.py` → exit 0.
- `rg -n "DEFAULT_AUDIOBOOK_IMPORT_MODE|AUDIOBOOK_IMPORT_MODES|self\.AUDIOBOOK_IMPORT_MODE" app/main.py` → the two constants, one assignment, and one validation reference are present.

### Step 2: Add the narrowly scoped fallback and policy router

Near `hardlink_one`/`copy_one`, define the OS errors that mean "hardlink is
unavailable but a copy may still be valid":

```python
HARDLINK_COPY_FALLBACK_ERRNOS = frozenset(
    getattr(errno, name)
    for name in ("EXDEV", "EPERM", "EOPNOTSUPP", "ENOTSUP", "ENOSYS")
    if hasattr(errno, name)
)
```

The set deliberately includes:

- `EXDEV` — different filesystems/datasets/pools.
- `EPERM`, `EOPNOTSUPP`/`ENOTSUP`, and `ENOSYS` — filesystems or mounts that
  reject/omit hardlink support while still potentially allowing reads/writes.

Do **not** include `EACCES`, `EROFS`, `ENOSPC`, `EIO`, or broad `Exception`.

Extend `hardlink_one` with one keyword-only flag, defaulting to strict behavior:

```python
def hardlink_one(src: Path, dst: Path, *, fallback_to_copy: bool = False):
```

Inside its existing `except OSError as exc`, before formatting the strict error,
check the flag and error set. When both match, log one warning containing the
source, destination, and OS error, call `copy_one(src, dst)`, and return. Calling
`copy_one`, which is defined later in the module, is valid because the function
is resolved when an import runs after module initialization. Preserve every
existing strict-mode error message and the dedicated `FileNotFoundError` /
`FileExistsError` branches.

After `copy_one`, add a flat helper matching repository style:

```python
def import_audiobook_one(src: Path, dst: Path):
    if settings.AUDIOBOOK_IMPORT_MODE == "copy":
        copy_one(src, dst)
        return
    hardlink_one(
        src,
        dst,
        fallback_to_copy=settings.AUDIOBOOK_IMPORT_MODE == "auto",
    )
```

Settings validation makes other values impossible in production. Do not add a
second default or silently coerce unexpected values in this helper.

**Verify**:

- `python -m py_compile app/main.py` → exit 0.
- `rg -n "HARDLINK_COPY_FALLBACK_ERRNOS|fallback_to_copy|def import_audiobook_one" app/main.py` → constant, hardlink flag/check, and router are present.

### Step 3: Wire the shared importer and make preflight truthful

In `import_torrent_to_library`, change only the operation selector:

```python
import_one = import_audiobook_one if media_type == MEDIA_TYPE_AUDIOBOOK else copy_one
```

Keep the single-file/multi-file loops and their cleanup exactly as they are.
This one line applies the setting to both torrent clients, automatic completion
imports, and History retries.

Change `hardlink_fs_warning` to accept `import_mode: str` as its third argument.
Its behavior on different devices must be:

- `hardlink`: retain an actionable warning that the import will fail with
  `EXDEV` and recommend a shared filesystem or `AUDIOBOOK_IMPORT_MODE=auto`.
- `auto`: warn that hardlinks are unavailable and audiobook files will be
  copied instead, with extra disk usage.
- `copy`: return `None`; the device difference is expected and harmless.

Preserve the current best-effort behavior for absent directories/stat errors.
Update `lifespan` to pass `settings.AUDIOBOOK_IMPORT_MODE`. Do not make any mode
fatal at preflight and do not modify database preflight.

**Verify**:

- `python -m py_compile app/main.py` → exit 0.
- `rg -n "import_one = import_audiobook_one|hardlink_fs_warning\(settings.DOWNLOADS_DIR, settings.LIBRARY_DIR, settings.AUDIOBOOK_IMPORT_MODE\)" app/main.py` → one match for each shared wiring point.
- `rg -n "import_one = hardlink_one" app/main.py` → no matches.

### Step 4: Add focused regression and integration tests

Create `app/tests/test_import_fallback.py`. Use `pytest`, `asyncio`, `errno`,
`os`, `Path`, FastAPI's `HTTPException`, and `import main` as needed. Add these
tests (ten pytest cases total; the fallback test is parameterized over three
errors):

1. `test_settings_defaults_to_hardlink_and_accepts_supported_modes` — delete the
   env variable, construct `main.Settings()`, and assert `hardlink`; then loop
   over `hardlink`, `auto`, and `copy` via `monkeypatch.setenv` and assert each
   normalized value is accepted. The safe test MAM cookie from `conftest.py`
   remains in the environment.
2. `test_settings_rejects_unknown_audiobook_import_mode` — set a clearly invalid
   value, construct `Settings`, and assert `RuntimeError` mentions the variable
   and accepted modes.
3. `test_hardlink_mode_creates_a_real_hardlink` — set the mode on
   `main.settings`, write a source under `tmp_path`, call
   `import_audiobook_one`, assert equal bytes and equal `(st_dev, st_ino)`.
4. `test_hardlink_mode_keeps_exdev_failure` — make `os.link` raise `EXDEV`,
   assert the existing status-400 cross-filesystem detail is preserved, and
   assert no destination copy exists.
5. `test_copy_mode_never_calls_os_link` — monkeypatch `main.os.link` to raise
   `AssertionError` if called, run the helper in `copy` mode, and assert equal
   bytes but different inode.
6. Parameterized `test_auto_mode_copies_when_hardlink_is_unsupported` over
   `errno.EXDEV`, `errno.EPERM`, and `errno.EOPNOTSUPP` — monkeypatch `os.link`
   to raise that `OSError`, assert the copy exists with the source bytes and a
   distinct inode. This produces three pytest cases.
7. `test_auto_mode_does_not_mask_unrelated_io_errors` — make `os.link` raise
   `OSError(errno.EIO, ...)`, assert `HTTPException` with status 400, and assert
   the destination does not exist.
8. `test_import_torrent_to_library_uses_auto_fallback` — integration-test the
   shared chokepoint:
   - create temporary `downloads/torrent/book.m4b` and `library` directories;
   - monkeypatch `settings.DOWNLOADS_DIR`, `settings.LIBRARY_DIR`, and mode
     `auto`;
   - replace `get_torrent_client` with a fake whose async `torrent_source`
     returns `(["book.m4b"], str(source_dir))`;
   - make `os.link` raise `EXDEV`;
   - call `asyncio.run(import_torrent_to_library("Author", "Title", "HASH"))`;
   - assert the returned destination contains the copied bytes and the source
     remains intact.

The integration test is the proof for **both** auto-import and Retry: both
callers delegate to this exact function. Do not create duplicate endpoint tests
or mock Transmission/qBittorrent HTTP here.

Update `app/tests/test_preflight.py`:

- Pass an explicit `"hardlink"` to the two existing
  `hardlink_fs_warning` tests.
- Add a small helper/monkeypatch arrangement that makes `downloads` and
  `library` appear as directories with distinct `st_dev` values.
- Add three cases: strict warning says the import will fail; auto warning says
  it will copy and mentions disk use; copy mode returns `None`.

Avoid patching `Path` or changing the global test DB. Monkeypatches must be
scoped by pytest and restored automatically.

**Verify**:

- `cd app && python -m pytest -q tests/test_import_fallback.py tests/test_preflight.py` → 18 passed.
- Temporarily change the implementation's auto fallback check to always false,
  rerun `tests/test_import_fallback.py`, and confirm the EXDEV/EPERM/EOPNOTSUPP
  and end-to-end cases fail; restore the implementation immediately and rerun
  to green. This mutation check proves the regression tests exercise the fix
  rather than merely its surface shape.

### Step 5: Document configuration and storage consequences

In `docker-compose.yml`, add `AUDIOBOOK_IMPORT_MODE: "hardlink"` near
`TORRENT_CLIENT`, with comments naming all three values and explaining that
`auto` copies only when hardlinking is unavailable. Keep the shared `/storage`
mount as the recommended default; do not replace it with host-specific mounts.

Update `README.md` consistently:

- "What It Does": hardlinks by default, with opt-in auto/copy behavior.
- Quick Start/storage paragraph: one shared filesystem remains recommended for
  space-efficient hardlinks. Separate filesystems work only with `auto` or
  `copy`, and copies consume space independently from the torrent data.
- Configuration table: add `AUDIOBOOK_IMPORT_MODE` and define
  `hardlink` (default), `auto`, and `copy`.
- Download-client section: both clients share the same import policy because
  both resolve completed data under `/downloads`.
- Notes/retry guidance: after changing this restart-required env setting,
  restart the container and use Retry on the failed History row; no re-add is
  required.

Do not claim that `auto` falls back for every permission or I/O error. State the
named cross-device/unsupported-link cases (including `EPERM`, which some mounts
use for unsupported links) and make clear that access-denied `EACCES`, full
disk, read-only destination, corrupt I/O, and missing files remain failures.
State that `hardlink` remains the default to avoid unexpected duplicate storage.

**Verify**:

- `rg -n "AUDIOBOOK_IMPORT_MODE" docker-compose.yml README.md` → one Compose setting and README configuration/usage documentation are present.
- `rg -n "different filesystems.*fail|must live on the same filesystem" README.md` → no unconditional stale claim remains; any same-filesystem statement must be qualified as strict-mode/recommended behavior.
- `git diff --check` → exit 0, no whitespace errors.

### Step 6: Run the full gates and exercise the real workflow

Run the complete automated suite, then test the real behavior in a development
deployment because filesystem and torrent-client semantics cannot be fully
represented by tmp-path mocks.

1. With `AUDIOBOOK_IMPORT_MODE=hardlink` and `/downloads`/`/library` on separate
   devices, complete one audiobook torrent. Confirm `/history` shows
   `import_failed` with the existing actionable hardlink detail and no partial
   destination folder remains.
2. Change the setting to `auto`, restart the app, use
   `POST /history/{id}/retry` on that same row, and confirm it becomes
   `imported`, the destination bytes match the source, source data remains, and
   source/destination inodes differ.
3. With `hardlink` on a shared filesystem, import another small file and confirm
   source/destination `(device,inode)` pairs match.
4. Smoke-test `/search`, `/add`, `/account`, and `/history` with valid dev
   credentials. `/add` must still reach the configured Transmission or
   qBittorrent client and the completed item must auto-import.

Record which client was used. One configured client is sufficient because the
client-independent import chokepoint is covered by automated integration tests;
do not require two live torrent stacks.

**Verify**:

- `python -m py_compile app/main.py` → exit 0.
- `cd app && python -m pytest -q` → all tests pass.
- `git diff --check` → exit 0.
- `git status --short` → only the six in-scope implementation/index files are
  modified/created; the pre-existing untracked `documrnted-bugs.md` may also
  remain listed unchanged.

## Test plan

- New `app/tests/test_import_fallback.py`: ten pytest cases covering settings
  default/validation, actual hardlink semantics, forced copy, automatic fallback
  for three supported OS error classes, refusal to mask unrelated I/O failure,
  and the end-to-end shared import function.
- Extended `app/tests/test_preflight.py`: three new policy-aware different-device
  cases plus explicit mode arguments on the two existing hardlink warning tests.
- Regression mutation: disabling the fallback condition must make the fallback
  tests fail before the final green run.
- Full pytest suite guards history, path traversal, both client adapters, startup
  preflight, and existing ebook behavior.
- Manual cross-device test guards the real kernel/mount behavior and exercises
  the failed-row Retry workflow required by `AGENTS.md`.

## Done criteria

All must hold:

- [ ] `AUDIOBOOK_IMPORT_MODE` accepts exactly `hardlink`, `auto`, and `copy`, is
      read once at startup, and defaults to `hardlink`.
- [ ] Strict mode preserves current hardlink success/error behavior and creates
      no copy on `EXDEV`.
- [ ] Auto mode copies on `EXDEV`, `EPERM`, `EOPNOTSUPP`/`ENOTSUP`, or `ENOSYS`,
      but does not copy on `EACCES`, `EROFS`, `ENOSPC`, `EIO`, missing source, or
      an existing hardlink destination (`FileExistsError`). Direct `copy` mode
      retains `copy_one`'s current semantics.
- [ ] Copy mode never calls `os.link`.
- [ ] Ebooks still call `copy_one` and ignore the audiobook policy.
- [ ] Both automatic import and History Retry receive the behavior through
      `import_torrent_to_library`; no client/caller-specific policy exists.
- [ ] Different-filesystem startup warnings accurately distinguish strict,
      auto, and copy modes.
- [ ] `python -m py_compile app/main.py` exits 0.
- [ ] Focused tests report 18 passed, including a proven mutation-sensitive
      regression test.
- [ ] `cd app && python -m pytest -q` exits 0 with all tests passing.
- [ ] `git diff --check` exits 0.
- [ ] Compose and README document the setting, restart requirement, default,
      fallback limits, and duplicate-storage trade-off.
- [ ] Real cross-device auto-import/Retry and the required endpoint smoke tests
      are recorded in the implementation handoff.
- [ ] No dependency, schema, Dockerfile, fixed path, client adapter, UI, or
      untracked bug-report change is included.
- [ ] The plan 037 row in `plans/README.md` is updated to `DONE` only after every
      applicable automated and manual gate passes; use `BLOCKED` with a reason if
      a real cross-device dev environment is unavailable.

## STOP conditions

Stop and report back; do not improvise if:

- The drift check shows any in-scope file changed and the current-state excerpts
  or shared import chokepoint no longer match.
- The implementation would require a history schema change, per-book persisted
  mode, UI setting, torrent-client-specific branch, new dependency, or path
  configuration.
- `copy2` cannot preserve the expected media bytes in the target deployment, or
  the operator requires reflinks/deduplication instead of ordinary copies.
- The target platform reports the real unsupported-hardlink case with an errno
  outside the named allowlist. Capture the numeric errno and exact operation;
  do not broaden fallback to all `OSError` values without review.
- Satisfying the request appears to require changing `copy_one` overwrite
  semantics or the `next_available` destination policy; those are separate
  race/behavior questions and must be planned independently.
- Automated tests fail twice after a reasonable correction, or the full suite
  exposes a behavior change in ebooks, path safety, history, or either torrent
  client.
- Real cross-filesystem validation cannot be performed. Finish automated work
  only if directed, and mark the plan `BLOCKED`, not `DONE`.

## Maintenance notes

- Review future import changes at `import_torrent_to_library`; bypassing
  `import_audiobook_one` would silently bypass this policy for either auto-import
  or Retry.
- If reflink support is requested later, treat it as a separate storage-policy
  design. Do not silently substitute `cp --reflink` or shell commands here.
- `auto` is per-file. On a many-file audiobook, an unsupported filesystem may
  cause a failed link attempt before each copy. This is correct and simple for
  this plan; optimize/log-deduplicate only if measurements show it matters.
- Copy fallback preserves the torrent source, which is necessary for seeding,
  but consumes independent library space. Operators must account for both.
- Revisit whether this belongs in a future authenticated Tier-2 settings UI only
  if the project actually builds that control plane. Until then, environment
  configuration is the single source of truth.
