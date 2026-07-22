# Plan 003: Import refuses torrent file names that escape the source or destination root

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 92761c0..HEAD -- app/main.py`
> If `app/main.py` changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/001-establish-verification-baseline.md (for the test harness)
- **Category**: security
- **Planned at**: commit `92761c0`, 2026-07-22

## Why this matters

`import_torrent_to_library` builds source and destination filesystem paths by
joining directory roots with the **file names reported for the torrent**, which
originate from `.torrent` metadata (attacker-influenceable by whoever uploaded
the torrent). The only cleanup applied is `lstrip("/")`, which strips leading
slashes but **not** `..` path components. A torrent whose declared file names
contain `../` can therefore:

- **Read outward**: cause `os.link(src, ...)` to hardlink a file from *outside*
  the download directory (e.g. a config or system file the container can read)
  into the user-visible library — an information-disclosure vector.
- **Write outward**: cause the destination to resolve *outside* the library
  root, placing hardlinked/copied files in unintended locations in the
  container filesystem.

The blast radius is bounded by the container filesystem and by whatever
Transmission actually reports, so this is defense-in-depth hardening rather than
a proven remote exploit — but the containment check is cheap, and the code
currently has none. The fix rejects unsafe names before any filesystem
operation and preserves all behavior for legitimate torrents.

## Current state

- `app/main.py:787-812` — the file-name handling and path joins (no `..` or
  containment check anywhere):
  ```python
  names = [(f.get("name") or "").lstrip("/") for f in files if f.get("name")]
  roots = {name.split("/", 1)[0] for name in names if "/" in name}
  common_root = next(iter(roots)) if len(roots) == 1 and all(name == next(iter(roots)) or name.startswith(next(iter(roots)) + "/") for name in names) else ""

  import_one = hardlink_one if media_type == MEDIA_TYPE_AUDIOBOOK else copy_one

  # Import all files (skip .cue). Audiobooks hardlink; ebooks copy.
  imported = 0
  try:
      if len(names) == 1:
          src = source_dir / names[0]
          if src.suffix.lower() == ".cue":
              raise HTTPException(status_code=400, detail="Only .cue file found; nothing to import")
          import_one(src, dest_dir / src.name)
          imported += 1
      else:
          for name in names:
              src = source_dir / name
              if src.suffix.lower() == ".cue":
                  continue
              rel_name = name
              if common_root and name.startswith(common_root + "/"):
                  rel_name = name[len(common_root) + 1:]
              if not rel_name:
                  continue
              import_one(src, dest_dir / rel_name)
              imported += 1
  except Exception:
      if dest_dir.exists():
          shutil.rmtree(dest_dir, ignore_errors=True)
      raise
  ```
- `source_dir` is validated to live under `/downloads` (`validate_download_path`,
  `app/main.py:736`), and `dest_dir` is `next_available(author_dir / title)`
  (`app/main.py:785`) under `/library`, `/ebooks`, or `/ebooks-nosend`. The
  gap is only in the per-file `name` joins.
- There is an existing helper pattern for raising import errors as
  `HTTPException(status_code=400, ...)` — see `hardlink_one`/`copy_one`
  (`app/main.py:607-637`). Match that: containment violations should raise
  `HTTPException(status_code=400, detail=...)`.
- Convention: `snake_case` module-level helpers in `main.py` (`AGENTS.md:26`).

## Commands you will need

| Purpose        | Command                                  | Expected on success       |
|----------------|------------------------------------------|---------------------------|
| Syntax check   | `python3 -m py_compile app/main.py`      | exit 0                    |
| Run tests      | `cd app && python -m pytest -q`          | all pass (incl. new ones) |

(Test harness comes from plan 001. If 001 has not landed, STOP — see
Dependencies.)

## Scope

**In scope** (the only files you should modify):
- `app/main.py` — add one containment helper and call it in
  `import_torrent_to_library`.
- `app/tests/test_helpers.py` — add tests for the new helper (file created by
  plan 001).

**Out of scope** (do NOT touch):
- `validate_download_path` (`app/main.py:736`) — it already guards
  `source_dir`; leave it.
- The `list_completed_torrents` root computation (`app/main.py:573-578`) — that
  output is unused; do not rework it here (see plan 006).
- Destination-collision behavior (`next_available`) — unchanged.

## Git workflow

- Branch: `advisor/003-import-path-containment`.
- Commit per logical unit; present-tense message (e.g. `Reject unsafe torrent file paths on import`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a containment helper

Add a pure, importable module-level helper in `app/main.py`, placed just above
`import_torrent_to_library` (near `app/main.py:756`). It resolves a candidate
path against a root and raises if the candidate escapes the root. Target shape:
```python
def safe_child_path(root: Path, name: str) -> Path:
    """Join `name` onto `root` and confirm the result stays within `root`.

    Rejects absolute names and any that traverse outside `root` via '..'.
    Raises HTTPException(400) on violation.
    """
    if os.path.isabs(name) or ".." in Path(name).parts:
        raise HTTPException(status_code=400, detail=f"Unsafe path in torrent contents: {name!r}")
    candidate = root / name
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if root_resolved != candidate_resolved and root_resolved not in candidate_resolved.parents:
        raise HTTPException(status_code=400, detail=f"Unsafe path in torrent contents: {name!r}")
    return candidate
```
Notes for the executor:
- Both `os` and `Path` are already imported at the top of `app/main.py`
  (`import os, ...` and `from pathlib import Path`). Do not add imports.
- `Path.resolve()` here uses the default non-strict mode, so it works whether or
  not the file exists yet (needed for destination paths).

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 2: Use the helper for every source and destination join

In `import_torrent_to_library`, replace the raw `source_dir / name` and
`dest_dir / rel_name` joins with `safe_child_path(...)`. Concretely:

- Single-file branch (`app/main.py:797`):
  ```python
  src = safe_child_path(source_dir, names[0])
  ...
  import_one(src, safe_child_path(dest_dir, src.name))
  ```
- Multi-file branch (`app/main.py:804-812`):
  ```python
  for name in names:
      src = safe_child_path(source_dir, name)
      if src.suffix.lower() == ".cue":
          continue
      rel_name = name
      if common_root and name.startswith(common_root + "/"):
          rel_name = name[len(common_root) + 1:]
      if not rel_name:
          continue
      import_one(src, safe_child_path(dest_dir, rel_name))
      imported += 1
  ```
Keep the `.cue` skipping, `common_root` stripping, and the surrounding
`try/except` cleanup exactly as they are — only the path joins change.

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 3: Add unit tests for the helper

In `app/tests/test_helpers.py`, add:
```python
def test_safe_child_path_allows_normal_names(tmp_path):
    root = tmp_path
    assert main.safe_child_path(root, "book.m4b") == root / "book.m4b"
    assert main.safe_child_path(root, "Author/book.m4b") == root / "Author/book.m4b"


def test_safe_child_path_rejects_traversal(tmp_path):
    with pytest.raises(HTTPException):
        main.safe_child_path(tmp_path, "../evil")
    with pytest.raises(HTTPException):
        main.safe_child_path(tmp_path, "a/../../evil")
    with pytest.raises(HTTPException):
        main.safe_child_path(tmp_path, "/etc/passwd")
```
(`main`, `pytest`, and `HTTPException` are already imported at the top of the
file per plan 001.)

**Verify**: `cd app && python -m pytest -q` → all pass, including the two new tests.

## Test plan

- New tests in `app/tests/test_helpers.py`: normal names (single and nested)
  pass through unchanged; `../`, nested `a/../../`, and absolute paths raise
  `HTTPException`.
- Model after the existing helper tests in the same file (plan 001).
- Verification: `cd app && python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "safe_child_path" app/main.py` shows the definition plus at least 3 call sites (single-file src, single-file dst, multi-file loop src+dst)
- [ ] `grep -n "source_dir / name\|dest_dir / rel_name\|source_dir / names\[0\]" app/main.py` returns **no** raw-join matches inside `import_torrent_to_library`
- [ ] `cd app && python -m pytest -q` exits 0 with the two new traversal tests passing
- [ ] `git status` shows only `app/main.py` and `app/tests/test_helpers.py` modified
- [ ] `plans/README.md` status row for 003 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 001 has not landed (`app/tests/test_helpers.py` does not exist) — this
  plan's tests depend on it. Report and request 001 first, or (if instructed to
  proceed standalone) create the harness per plan 001 Steps 3–4 before adding
  tests here.
- The `app/main.py:787-812` excerpt does not match the live code.
- A legitimate multi-file torrent test starts failing after the change — the
  `common_root` stripping may produce a `rel_name` the helper rejects; report
  the exact name rather than loosening the check.

## Maintenance notes

- If a future change lets users configure destination libraries or supports
  nested collections, re-verify `safe_child_path` still contains every join.
- Reviewer should confirm **every** `source_dir /` and `dest_dir /` join in
  `import_torrent_to_library` now goes through `safe_child_path`, and that the
  `.cue` skip and `common_root` logic are unchanged.
- Follow-up deferred: symlink handling in `hardlink_one`/`copy_one` (an in-tree
  symlink could still point outward) is a separate, lower-severity concern; not
  in scope here.
