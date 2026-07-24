# Plan 006: Remove unused computed fields and the empty common.js request

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 92761c0..HEAD -- app/main.py app/templates/base.html app/static/common.js`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `92761c0`, 2026-07-22

## Why this matters

Two small pieces of dead weight:

1. `list_completed_torrents` fetches the **`files`** list for *every* torrent
   from Transmission and computes `root`, `single_file`, `name`, `download_dir`,
   `size`, and `added_on` for each — but its only caller uses **`hash`** and
   nothing else. Every 30-second poll pulls per-file metadata for the whole
   torrent list and throws it away.
2. `app/templates/base.html` loads `/static/common.js` on every page render, but
   `app/static/common.js` is a **0-byte file** — a wasted HTTP request on every
   page load and a confusing "is this used?" for the next reader.

Removing both makes the auto-import poll cheaper and the frontend request list
honest, with no behavior change.

## Current state

- `list_completed_torrents` (`app/main.py:545-589`):
  ```python
  async def list_completed_torrents() -> list[dict]:
      async with httpx.AsyncClient(timeout=30) as c:
          args = await transmission_rpc(c, "torrent-get", {
              "fields": [
                  "id", "hashString", "name", "percentDone",
                  "downloadDir", "totalSize", "addedDate", "labels", "files",
              ],
          })
          infos = args.get("torrents") or []
          out = []
          for t in infos:
              if settings.TRANSMISSION_LABEL and settings.TRANSMISSION_LABEL not in (t.get("labels") or []):
                  continue
              if float(t.get("percentDone") or 0) < 1:
                  continue
              h = t.get("hashString")
              if not h:
                  continue
              files = t.get("files") or []
              roots = set()
              for f in files:
                  name = (f.get("name") or "").lstrip("/")
                  roots.add(name.split("/", 1)[0])
              root = (list(roots)[0] if roots else t.get("name") or "")
              single_file = len(files) == 1 and "/" not in (files[0].get("name") or "")
              out.append({
                  "hash": h, "name": t.get("name"), "download_dir": t.get("downloadDir"),
                  "root": root, "single_file": single_file,
                  "size": t.get("totalSize"), "added_on": t.get("addedDate"),
              })
          return out
  ```
- Its **only** caller (`app/main.py:824-826`) uses only `hash`:
  ```python
  completed = await list_completed_torrents()
  completed_hashes = {item.get("hash") for item in completed if item.get("hash")}
  ```
  (Confirmed: `grep -rn "single_file\|download_dir\|added_on\|\.root\b" app/`
  finds no other consumer, in Python or frontend.)
- `app/templates/base.html:18`:
  ```html
    <script src="/static/common.js" defer></script>
  ```
  `app/static/common.js` is 0 bytes. Only `base.html` references it
  (`grep -rn "common.js" app/` → one hit).

## Commands you will need

| Purpose        | Command                                     | Expected on success  |
|----------------|---------------------------------------------|----------------------|
| Syntax check   | `python3 -m py_compile app/main.py`         | exit 0               |
| Run tests      | `cd app && python -m pytest -q`             | all pass (if 001 landed) |
| Confirm no refs| `grep -rn "common.js" app/`                 | no matches           |

## Scope

**In scope** (the only files you should modify/delete):
- `app/main.py` — simplify `list_completed_torrents`.
- `app/templates/base.html` — remove the `common.js` `<script>` tag.
- `app/static/common.js` — delete the empty file.

**Out of scope** (do NOT touch):
- `auto_import_cycle` (`app/main.py:824+`) — it already uses only `hash`; leave it.
- `import_torrent_to_library` (`app/main.py:756+`) — it does its **own**
  `torrent-get` with `files` (`app/main.py:762-765`); that call is required and
  stays. Only the **bulk** query in `list_completed_torrents` loses `files`.
- `app/static/app.js` and `index.html`'s own `<script>` block — unrelated.

## Git workflow

- Branch: `advisor/006-remove-dead-code`.
- One or two commits; present-tense messages
  (e.g. `Slim list_completed_torrents to hash-only`, `Drop empty common.js`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Slim `list_completed_torrents`

Replace the whole function body with a version that requests only the fields
needed for filtering (`labels`, `percentDone`) and identity (`hashString`), and
returns only `hash`:
```python
async def list_completed_torrents() -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as c:
        args = await transmission_rpc(c, "torrent-get", {
            "fields": ["hashString", "percentDone", "labels"],
        })
        infos = args.get("torrents") or []

        out = []
        for t in infos:
            if settings.TRANSMISSION_LABEL and settings.TRANSMISSION_LABEL not in (t.get("labels") or []):
                continue
            if float(t.get("percentDone") or 0) < 1:
                continue
            h = t.get("hashString")
            if not h:
                continue
            out.append({"hash": h})
        return out
```
The label filter and `percentDone >= 1` completeness check are preserved
exactly — only the discarded computation and fields are removed.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "single_file\|added_on\|\"files\"" app/main.py` shows `"files"` only in
`import_torrent_to_library` (around `app/main.py:764`), not in
`list_completed_torrents`.

### Step 2: Remove the empty common.js load

Delete line `app/templates/base.html:18`:
```html
  <script src="/static/common.js" defer></script>
```
Then delete the empty file:
```bash
git rm app/static/common.js
```

**Verify**: `grep -rn "common.js" app/` → no matches.

## Test plan

- If plan 001 landed, run `cd app && python -m pytest -q` → all pass (the helper
  suite still imports and passes; `list_completed_torrents` is not unit-tested
  but must still compile and import cleanly).
- Manual (optional): start the app and confirm the page loads with no request to
  `/static/common.js` and no 404 in the browser network panel.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n 'single_file\|added_on\|"download_dir"' app/main.py` returns no matches
      (**note**: match the *quoted dict key* `"download_dir"`, not the bare word.
      `import_torrent_to_library` has an unrelated local variable also called
      `download_dir` which is explicitly out of scope and must survive — an
      earlier revision of this criterion used the bare word and wrongly implied
      that code should be deleted.)
- [ ] `grep -rn "common.js" app/` returns no matches
- [ ] `app/static/common.js` no longer exists
- [ ] `cd app && python -m pytest -q` exits 0 (if plan 001 landed)
- [ ] `git status` shows only `app/main.py`, `app/templates/base.html`, and the deleted `app/static/common.js`
- [ ] `plans/README.md` status row for 006 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `grep -rn "single_file\|download_dir\|added_on\|common.js" app/` shows a
  consumer you did not expect (e.g. a new caller added since this plan) — the
  fields may no longer be dead; report it.
- The `list_completed_torrents` or `base.html` excerpts don't match live code.

## Maintenance notes

- If auto-import later needs per-torrent metadata (name, size) for display, add
  those fields back **and** a consumer in the same change — don't reintroduce
  compute-and-discard.
- Reviewer should confirm `import_torrent_to_library`'s own `torrent-get`
  (which still needs `files`) was not touched.
