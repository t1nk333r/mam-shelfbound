# Plan 009: New ebook adds default to "no-send" (not sent to Kindle)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 7ec17a5..HEAD -- app/main.py app/static/app.js app/templates/index.html README.md`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (soft: plan 001 for the unit test; interacts with plan 008 — see Maintenance notes)
- **Category**: direction / behavior change
- **Planned at**: commit `7ec17a5`, 2026-07-22

## Why this matters

Commit `6773809` ("Add ebook no-send destination") added a `Send to Kindle`
toggle for ebook downloads: when **off**, the torrent is tagged `kindle-nosend`
in the download client and imported into `/ebooks-nosend` instead of `/ebooks`.
Today that toggle **defaults on** — new ebook adds are sent to Kindle unless the
user unchecks it. This plan flips the default so ebook adds are **no-send by
default**; the user opts *in* to Kindle by checking the toggle before adding.

This is a small, deliberate behavior change. It reuses the exact machinery
`6773809` built (the `kindle-nosend` label, the `EBOOKS_NOSEND_DIR` destination,
and the `send_to_kindle` history column) — nothing new is introduced. Only the
**default state for new adds** changes. Historical rows and the retry/auto-import
read paths are intentionally left untouched (see Scope).

## Current state

The `send_to_kindle` flag (1 = send to Kindle / import to `/ebooks`, 0 = no-send
/ import to `/ebooks-nosend`) is defaulted to "send" in three new-add
touchpoints. Audiobooks ignore the flag entirely — it only affects ebooks.

**1. Frontend toggle** — `app/templates/index.html:180-183`:
```html
    <label id="kindleToggle" class="kindle-toggle" for="sendToKindle" hidden>
      <input id="sendToKindle" type="checkbox" checked />
      <span>Send to Kindle</span>
    </label>
```
The `checked` attribute makes the toggle default on. (The label is `hidden`
until an ebook search is active; `app/static/app.js:54` toggles it.)

**2. Frontend fallback** — `app/static/app.js:35-37`:
```javascript
function getSendToKindle() {
  return sendToKindleInput ? sendToKindleInput.checked : true;
}
```
The add payload uses it (`app/static/app.js:127`):
```javascript
              send_to_kindle: normalizeMediaType(it.media_type || mediaType) !== 'ebook' || getSendToKindle()
```
(For audiobooks the left side is `true`, so `send_to_kindle` is always `true` and
irrelevant; only ebooks consult the toggle.)

**3. Backend default** — the `/add` endpoint coercion (`app/main.py:423`):
```python
    send_to_kindle = True if body.send_to_kindle is None else bool(body.send_to_kindle)
```
`AddBody.send_to_kindle` is `bool | None = None` (`app/main.py:414`), so an API
caller that omits the field currently defaults to "send".

**How the flag is consumed** (do NOT change — these already work):
- `transmission_labels` (`app/main.py:329-337`): appends `TRANSMISSION_NOSEND_LABEL`
  (`"kindle-nosend"`) only for ebooks with `send_to_kindle` false.
- `import_torrent_to_library` (`app/main.py:779-782`): picks
  `EBOOKS_NOSEND_DIR` vs `EBOOKS_DIR` for ebooks based on the flag.
- History badge (`app/static/app.js:325`): shows "No Kindle" for ebook rows with
  `send_to_kindle === 0`.

**Docs** — `README.md:18` and `README.md:62`:
```markdown
- Optionally import ebooks into `/ebooks-nosend` when `Send to Kindle` is unchecked
...
- The `Send to Kindle` ebook toggle defaults on. When unchecked, new ebook adds are tagged `kindle-nosend` in Transmission and imported into `/ebooks-nosend`.
```

**Conventions** (`AGENTS.md`): Python 4-space indent, `snake_case` helpers kept
flat in `main.py`; frontend is vanilla ES, no framework. Commit messages: short,
present-tense, no prefixes.

## Commands you will need

| Purpose        | Command                                  | Expected on success       |
|----------------|------------------------------------------|---------------------------|
| Syntax check   | `python3 -m py_compile app/main.py`      | exit 0                    |
| Run tests      | `cd app && python -m pytest -q`          | all pass (if plan 001 landed) |
| Confirm default flip (UI) | `grep -n 'id="sendToKindle"' app/templates/index.html` | line has NO `checked` attribute |

## Scope

**In scope**:
- `app/templates/index.html` — remove `checked` from the toggle.
- `app/static/app.js` — flip the defensive fallback default.
- `app/main.py` — flip the `/add` default (via a small testable helper).
- `README.md` — update the two lines describing the default.
- `app/tests/test_helpers.py` — add a unit test (only if plan 001 has landed).

**Out of scope** (do NOT touch — these concern historical data or unreached defaults, not the new-add default):
- The schema migration default and backfill: `ADD COLUMN send_to_kindle INTEGER DEFAULT 1` (`app/main.py:119`) and `SET send_to_kindle = 1 WHERE send_to_kindle IS NULL` (`app/main.py:127`) — these classify **pre-existing** rows; changing them would rewrite history semantics.
- The retry/auto-import read defaults `bool(row.get("send_to_kindle", 1))` (`app/main.py:531,846`) — these default **existing** rows missing the value; leave as 1 to preserve prior behavior for old data.
- The function-signature defaults `send_to_kindle: bool = True` in `transmission_labels` (`app/main.py:329`) and `import_torrent_to_library` (`app/main.py:756`) — the add/import/retry call graph always passes the flag explicitly, so these defaults are never hit; leave them to keep the diff minimal.
- The `send_to_kindle` column name and meaning, and the toggle label text `Send to Kindle` — keep both; only the default *state* flips (user opts in).

## Git workflow

- Branch: `advisor/009-ebook-nosend-default`.
- One commit (or split backend/frontend/docs); present-tense message
  (e.g. `Default ebook adds to no-send`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Flip the UI toggle default

In `app/templates/index.html:181`, remove the `checked` attribute. Before:
```html
      <input id="sendToKindle" type="checkbox" checked />
```
After:
```html
      <input id="sendToKindle" type="checkbox" />
```

**Verify**: `grep -n 'id="sendToKindle"' app/templates/index.html` shows the line
without `checked`.

### Step 2: Flip the frontend defensive fallback

In `app/static/app.js:36`, change the fallback (used only if the checkbox
element is absent) from `true` to `false`. Before:
```javascript
  return sendToKindleInput ? sendToKindleInput.checked : true;
```
After:
```javascript
  return sendToKindleInput ? sendToKindleInput.checked : false;
```
Do **not** change line 127 (the payload expression) — with the checkbox now
defaulting unchecked, `getSendToKindle()` already returns `false` for ebooks by
default, and audiobooks still short-circuit to `true`.

**Verify**: `grep -n "sendToKindleInput.checked : false" app/static/app.js`
returns one match.

### Step 3: Flip the backend default via a testable helper

In `app/main.py`, add a small module-level helper next to the other coercion
helpers (a good spot is just after `normalize_media_type`, around
`app/main.py:57`):
```python
def default_send_to_kindle(value: bool | None) -> bool:
    # Ebooks default to no-send; the user opts in by enabling "Send to Kindle".
    return False if value is None else bool(value)
```
Then replace the inline coercion at `app/main.py:423`. Before:
```python
    send_to_kindle = True if body.send_to_kindle is None else bool(body.send_to_kindle)
```
After:
```python
    send_to_kindle = default_send_to_kindle(body.send_to_kindle)
```

**Verify**: `python3 -m py_compile app/main.py` → exit 0; and
`grep -n "default_send_to_kindle" app/main.py` shows the definition plus the call
site.

### Step 4: Update the docs

In `README.md`, update the two lines to describe no-send as the default.
- Line 18 (feature list) — before:
  ```markdown
  - Optionally import ebooks into `/ebooks-nosend` when `Send to Kindle` is unchecked
  ```
  after:
  ```markdown
  - Import ebooks into `/ebooks-nosend` by default; check `Send to Kindle` before adding to import into `/ebooks` instead
  ```
- Line 62 (Notes) — before:
  ```markdown
  - The `Send to Kindle` ebook toggle defaults on. When unchecked, new ebook adds are tagged `kindle-nosend` in Transmission and imported into `/ebooks-nosend`.
  ```
  after:
  ```markdown
  - The `Send to Kindle` ebook toggle defaults **off**: new ebook adds are tagged `kindle-nosend` in Transmission and imported into `/ebooks-nosend`. Check `Send to Kindle` before adding to send the ebook to Kindle and import it into `/ebooks` instead.
  ```
Also update `README.md:17` if it implies `/ebooks` is the default destination —
before:
```markdown
- Auto-import completed ebooks into `/ebooks` using copies
```
after:
```markdown
- Auto-import completed ebooks into `/ebooks-nosend` (default) or `/ebooks` (when `Send to Kindle` is checked) using copies
```

**Verify**: `grep -n "defaults \*\*off\*\*\|by default" README.md` shows the
updated wording; `grep -n "defaults on" README.md` returns no matches.

### Step 5: Add a unit test (only if plan 001 has landed)

Check: `test -f app/tests/test_helpers.py && echo present || echo absent`.
- If **absent**, skip (note in the status row that the unit test is deferred
  pending plan 001; Steps 1–4 are verified by grep + manual UI check).
- If **present**, add to `app/tests/test_helpers.py`:
```python
def test_default_send_to_kindle_defaults_to_nosend():
    assert main.default_send_to_kindle(None) is False   # new default: no-send
    assert main.default_send_to_kindle(True) is True
    assert main.default_send_to_kindle(False) is False
```

**Verify**: `cd app && python -m pytest -q` → all pass, including the new test.

## Test plan

- **Unit (required if plan 001 landed)**: `default_send_to_kindle(None)` returns
  `False` (the new default), `True`/`False` pass through. Model after the
  existing helper tests in `app/tests/test_helpers.py`.
- **Manual (recommended)**: load the UI, switch to an **Ebooks** search — the
  `Send to Kindle` toggle appears **unchecked**. Add an ebook without checking
  it and confirm the History row shows the "No Kindle" badge; on completion,
  confirm it imports into `/ebooks-nosend`. Then add another ebook with the
  toggle **checked** and confirm it imports into `/ebooks`.
- **Regression**: audiobook adds are unaffected (the flag is ignored for
  audiobooks) — confirm an audiobook add still imports into `/library`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'id="sendToKindle"' app/templates/index.html` shows the input with **no** `checked` attribute
- [ ] `grep -n "sendToKindleInput.checked : false" app/static/app.js` returns one match
- [ ] `grep -n "default_send_to_kindle" app/main.py` shows the helper definition and its use in `/add`
- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "defaults on" README.md` returns no matches
- [ ] `grep -n "send_to_kindle INTEGER DEFAULT 1\|SET send_to_kindle = 1\|row.get(\"send_to_kindle\", 1)" app/main.py` is **unchanged** (migration/read-path defaults untouched)
- [ ] `cd app && python -m pytest -q` exits 0 (if plan 001 landed)
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row for 009 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any "Current state" excerpt does not match live code (drift since this plan).
- You find the intended behavior is actually to *invert the control's meaning*
  (e.g. relabel it "Keep off Kindle" checked-by-default) rather than default the
  existing `Send to Kindle` control to off — that is a larger change touching the
  `send_to_kindle` column semantics and is NOT what this plan specifies; report
  and confirm before proceeding.
- Removing `checked` appears to break the toggle's initial rendering or the
  `kindleToggle.hidden` show/hide logic (`app/static/app.js:54`) — report rather
  than adding JS to force state.

## Maintenance notes

- **Interaction with plan 008** (qBittorrent client): plan 008 edits the
  `torrent-add` call inside the same `/add` function (`app/main.py:452-458`),
  while this plan edits the `send_to_kindle` coercion earlier in that function
  (`app/main.py:423`) and adds a helper near line 57. Different regions — no
  textual overlap — but if both land, rebase and re-run `py_compile` + tests.
  The `send_to_kindle` flag flows into both `transmission_labels` (Transmission)
  and `qb_tags` (qBittorrent) unchanged, so the no-send default applies to both
  clients automatically.
- This is a user-facing default change; note it in any release notes so existing
  users know ebooks now default to `/ebooks-nosend`.
- Reviewer should confirm the migration/backfill and retry read-path defaults
  (`DEFAULT 1`, `SET ... = 1`, `row.get(..., 1)`) were **not** changed — only the
  new-add default flipped.
