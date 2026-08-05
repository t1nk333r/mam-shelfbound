# Plan 036: Flag search results that already exist in the library ("In library" badge)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f587737..HEAD -- app/main.py app/static/app.js app/templates/index.html`
> If any changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (independent of plans 031, 033, 034, 035)
- **Category**: direction
- **Planned at**: commit `f587737`, 2026-08-04

## Why this matters

The results table shows an **"In history"** badge (plan 016) when a result matches
a row in the app's own history — but that only covers books this app added. A book
already sitting in the library from a **manual or pre-app import** shows no badge, so
the user can re-download something they already own, spending bandwidth and (on a
private tracker) ratio. When they do, `next_available` silently creates a
`Title (2)` folder (`app/main.py:900`) rather than warning. This plan adds a
read-only, best-effort **"In library"** badge: `/search` checks whether a folder for
each result already exists on disk (using the *same* `sanitize` naming the importer
uses), and the frontend renders a badge — a warning, never a block, matching plan
016's deliberate "don't disable Add" decision (a re-add is sometimes legitimate).

## Current state

- `app/main.py` — single-file FastAPI app. Relevant regions:
  - **`/search` builds each result dict** here; `media_type` is already known and
    each result already carries `title` + `author_info` (`app/main.py:450-469`):
    ```python
    out = []
    for item in raw.get("data", []):
        is_freeleech = is_truthy(item.get("free")) or is_truthy(item.get("fl_vip"))
        is_vip = is_truthy(item.get("vip")) or is_truthy(item.get("fl_vip"))
        out.append({
            "id": str(item.get("id") or item.get("tid") or ""),
            "title": item.get("title") or item.get("name"),
            "author_info": flatten(item.get("author_info")),
            ...
            "media_type": media_type,
            "is_freeleech": is_freeleech,
            "is_vip": is_vip,
        })
    ```
  - **The importer's folder naming** — the check must mirror this exactly
    (`app/main.py:893-908`, and the importer at `:1132-1148`):
    ```python
    def sanitize(name: str) -> str:
        s = name.strip().replace(":", " -").replace("\\", "﹨").replace("/", "﹨")
        s = re.sub(r"\s+", " ", s)[:200]
        if s in (".", ".."):
            return "Unknown"
        return s or "Unknown"
    ```
    `sanitize` already neutralises path separators and `.`/`..`, so
    `Path(base) / sanitize(author) / sanitize(title)` is always a safe two-level
    path. The importer creates `LIBRARY_DIR / sanitize(author) / sanitize(title)`
    for audiobooks, and `EBOOKS_DIR` / `EBOOKS_NOSEND_DIR` for ebooks
    (`app/main.py:1142-1148`).
  - **Library roots** live on `settings` (`app/main.py:125-128`):
    `settings.LIBRARY_DIR` (`/library`), `settings.EBOOKS_DIR` (`/ebooks`),
    `settings.EBOOKS_NOSEND_DIR` (`/ebooks-nosend`).
- `app/static/app.js` — the results row assembles badges. The **title cell** line
  and the **in-history badge** are the exact pattern to copy
  (`app/static/app.js:228-229` and `:248-253`):
  ```js
  tr.innerHTML = `
    <td>${renderResultTitleCell(it)}${renderInHistoryBadge(it)}</td>
    ...`;

  function renderInHistoryBadge(item) {
    const status = historyMamIds.get(String(item?.id ?? ''));
    if (!status) return '';
    const label = status === 'import_failed' ? 'In history (failed)' : 'In history';
    return `<div class="result-flags"><span class="result-badge result-badge-history">${escapeHtml(label)}</span></div>`;
  }
  ```
- `app/templates/index.html` — badge styles live in the `<style>` block; the
  neutral history badge is the model (`app/templates/index.html:167-171`):
  ```css
  .result-badge-history {
    color:var(--text-soft);
    background:var(--bg-elevated);
    border-color:var(--border);
  }
  ```
  Other badges use `var(--success)` / `var(--warning)`; `var(--accent)` is the
  blue accent (used by `.sort-ind` and the search-button glow
  `rgba(156, 211, 255, …)`).

**Conventions**: flat `snake_case` helpers in `main.py`; results are plain dicts;
frontend is vanilla JS, no build. Outbound/side effects best-effort. Tests use
`import main`, `monkeypatch.setattr(main.settings, …)`, and pytest's `tmp_path`
fixture for filesystem cases; JS is checked with `node --check`.

## Commands you will need

| Purpose      | Command                                             | Expected on success |
|--------------|-----------------------------------------------------|---------------------|
| Install deps | `pip install -r requirements.txt -r requirements-dev.txt` | exit 0 |
| Syntax check | `python -m py_compile app/main.py`                  | exit 0              |
| JS check     | `node --check app/static/app.js`                    | exit 0, no output   |
| Tests        | `cd app && python -m pytest -q`                     | all pass            |

## Scope

**In scope** (only these files):
- `app/main.py` — add two helpers; annotate each `/search` result with `in_library`.
- `app/static/app.js` — add `renderInLibraryBadge`; render it in the results row.
- `app/templates/index.html` — add one `.result-badge-library` CSS rule.
- `app/tests/test_library_guard.py` (create).
- `plans/README.md` — status row.

**Out of scope** (do NOT touch):
- The import pipeline, `next_available`, `sanitize`, `safe_child_path` — reuse, don't change.
- The Add button behavior — the badge must NOT disable or block Add (plan 016's rule).
- Fuzzy/duplicate detection across editions/narrators — this is an **exact**
  sanitized-folder match only (see Maintenance notes).
- Any new filter control (e.g. "hide in-library") — badge only this pass.

## Git workflow

- Branch: `advisor/036-pre-add-library-collision-guard`
- Commit style: short, present-tense, no prefix. One commit is fine.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add the on-disk existence helpers

Add near `sanitize` (after `next_available`, `app/main.py:908`):

```python
def library_check_dirs(media_type: str) -> list[str]:
    if normalize_media_type(media_type) == MEDIA_TYPE_EBOOK:
        return [settings.EBOOKS_DIR, settings.EBOOKS_NOSEND_DIR]
    return [settings.LIBRARY_DIR]


def title_in_library(author: str, title: str, media_type: str) -> bool:
    """True if a folder for this author/title already exists on disk.

    Mirrors the importer's naming (sanitize author + title), so it catches books
    already present — imported by this app OR manually. Best-effort: a missing or
    unreadable library yields False, never raises.
    """
    if not (title or "").strip():
        return False
    a = sanitize(author or "")
    t = sanitize(title or "")
    for base in library_check_dirs(media_type):
        try:
            if (Path(base) / a / t).is_dir():
                return True
        except OSError:
            continue
    return False
```

**Verify**: `python -m py_compile app/main.py` → exit 0.

### Step 2: Annotate `/search` results

In the result loop (`app/main.py:450-469`), compute `title`/`author_info` into
locals and add the `in_library` key. Replace the append block so it reads:

```python
    out = []
    for item in raw.get("data", []):
        is_freeleech = is_truthy(item.get("free")) or is_truthy(item.get("fl_vip"))
        is_vip = is_truthy(item.get("vip")) or is_truthy(item.get("fl_vip"))
        title = item.get("title") or item.get("name")
        author_info = flatten(item.get("author_info"))
        out.append({
            "id": str(item.get("id") or item.get("tid") or ""),
            "title": title,
            "author_info": author_info,
            "narrator_info": flatten(item.get("narrator_info")),
            "format": detect_format(item),
            "size": item.get("size"),
            "seeders": item.get("seeders"),
            "leechers": item.get("leechers"),
            "catname": item.get("catname"),
            "added": item.get("added"),
            "dl": item.get("dl"),
            "media_type": media_type,
            "is_freeleech": is_freeleech,
            "is_vip": is_vip,
            "in_library": title_in_library(author_info, title, media_type),
        })
```

Do not change any other key. `is_dir()` on a non-existent/unmounted path returns
False without raising, so this is safe when `/library` isn't present (e.g. tests).

**Verify**: `python -m py_compile app/main.py` → exit 0;
`grep -n '"in_library": title_in_library' app/main.py` → 1 match.

### Step 3: Render the badge in the frontend

In `app/static/app.js`, add a renderer next to `renderInHistoryBadge`
(after `app/static/app.js:253`):

```js
function renderInLibraryBadge(item) {
  if (!item?.in_library) return '';
  return `<div class="result-flags"><span class="result-badge result-badge-library">In library</span></div>`;
}
```

Then append it in the results row template (`app/static/app.js:229`):

```js
    <td>${renderResultTitleCell(it)}${renderInHistoryBadge(it)}${renderInLibraryBadge(it)}</td>
```

**Verify**: `node --check app/static/app.js` → exit 0;
`grep -n "renderInLibraryBadge" app/static/app.js` → 2 matches (definition + call).

### Step 4: Style the badge

In `app/templates/index.html`, add after the `.result-badge-history` rule
(`app/templates/index.html:171`):

```css
    .result-badge-library {
      color:var(--accent);
      background:rgba(156, 211, 255, 0.12);
      border-color:rgba(156, 211, 255, 0.30);
    }
```

**Verify**: `grep -n "result-badge-library" app/templates/index.html` → 1 match.

### Step 5: Write tests

Create `app/tests/test_library_guard.py`:

```python
import main


def test_title_in_library_true_when_folder_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    (tmp_path / main.sanitize("Matt Dinniman") / main.sanitize("Dungeon Crawler Carl")).mkdir(parents=True)
    assert main.title_in_library("Matt Dinniman", "Dungeon Crawler Carl", "audiobook") is True


def test_title_in_library_false_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    assert main.title_in_library("Nobody", "No Such Book", "audiobook") is False


def test_title_in_library_uses_sanitized_names(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    # A "/" in the title becomes the importer's replacement char, not a subdir.
    (tmp_path / main.sanitize("A") / main.sanitize("Book: One/Two")).mkdir(parents=True)
    assert main.title_in_library("A", "Book: One/Two", "audiobook") is True


def test_title_in_library_checks_both_ebook_dirs(monkeypatch, tmp_path):
    send = tmp_path / "send"; nosend = tmp_path / "nosend"
    send.mkdir(); nosend.mkdir()
    monkeypatch.setattr(main.settings, "EBOOKS_DIR", str(send))
    monkeypatch.setattr(main.settings, "EBOOKS_NOSEND_DIR", str(nosend))
    (nosend / main.sanitize("Herbert") / main.sanitize("Dune")).mkdir(parents=True)
    assert main.title_in_library("Herbert", "Dune", "ebook") is True


def test_title_in_library_empty_title_is_false(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    assert main.title_in_library("Someone", "", "audiobook") is False
```

**Verify**: `cd app && python -m pytest -q tests/test_library_guard.py` → 5 passed.

## Test plan

- New `app/tests/test_library_guard.py` (5 tests): folder exists → True; absent →
  False; sanitized-name match (a `/` in the title doesn't become a subdir); ebook
  checks both dirs; empty title → False. Uses `tmp_path` + `monkeypatch.setattr`
  on the library-dir settings. Model: `app/tests/test_migrations.py` for the
  `main.`-direct style.
- The `/search` wiring is a single dict key; it is covered by the helper tests plus
  the Step-2 grep. (Full `/search` endpoint mocking is out of scope — it would
  require respx-mocking the MAM search + wedge calls for one asserted key.)
- Full suite stays green; frontend `node --check` passes.
- Verification: `cd app && python -m pytest -q` → all pass, +5.

## Done criteria

ALL must hold:

- [ ] `python -m py_compile app/main.py` exits 0
- [ ] `node --check app/static/app.js` exits 0
- [ ] `cd app && python -m pytest -q` exits 0; `test_library_guard.py` (5) passes
- [ ] `grep -n '"in_library": title_in_library' app/main.py` → 1
- [ ] `grep -n "renderInLibraryBadge" app/static/app.js` → 2
- [ ] `grep -n "result-badge-library" app/templates/index.html` → 1
- [ ] `git status` shows only: `app/main.py`, `app/static/app.js`, `app/templates/index.html`, `app/tests/test_library_guard.py`, `plans/README.md`
- [ ] `plans/README.md` status row for 036 updated to DONE

## STOP conditions

Stop and report if:

- The "Current state" excerpts don't match live code (drift since `f587737`) — in
  particular if the `/search` result dict or `sanitize` has changed shape.
- A verification fails twice after a reasonable fix.
- You find yourself tempted to make the badge disable/gate the Add button, add a
  DB column, or add fuzzy matching — all out of scope; report instead.
- The per-result filesystem check appears to add noticeable latency to `/search`
  in the executor's environment (it should be ≤ ~200 cheap `is_dir` calls). If so,
  report — a batched or cached approach would be a follow-up, not this plan.

## Maintenance notes

- **Exact-match heuristic, by design**: this flags only a folder whose sanitized
  `Author/Title` matches what the importer would create. It will NOT catch the same
  book under a different edition/narrator/title spelling, nor a `Title (2)` variant.
  That's intentional — a cheap, false-positive-resistant "you already have this
  exact one" signal, not a dedup engine. If fuzzy matching is ever wanted, it's a
  separate, larger plan (normalize + index the library).
- The check runs synchronously inside the async `/search` handler (≤ perpage×2
  `is_dir` stats). Fine at single-user scale on a local library mount; if the
  library ever lives on a slow/remote filesystem, revisit (cache per author dir, or
  move to a separate lazy endpoint the frontend calls).
- A reviewer should confirm: Add is still enabled on in-library rows; a missing/
  unreadable `/library` yields no badge and no error (best-effort); and the badge
  reuses the existing `.result-flags` layout so no row-height regression.
- Interacts with the importer's naming: if `sanitize` or the
  `LIBRARY_DIR/Author/Title` layout changes, update `title_in_library` in lockstep.
