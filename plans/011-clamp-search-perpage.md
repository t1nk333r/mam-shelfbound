# Plan 011: Values forwarded to MyAnonamouse are validated — `perpage` on `/search` and `id` on `/add`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 635d2f9..HEAD -- app/main.py`
> If `app/main.py` changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (soft: plan 001 for the unit test)
- **Category**: security (input hardening)
- **Planned at**: commit `635d2f9`, 2026-07-22
- **Amended at**: commit `f8d3d32`, 2026-07-23 — added the `/add` `mam_id`
  vector (Step 3 and its tests). `app/main.py` was unchanged between the two
  commits, so every excerpt below is still current.

## Why this matters

The `/search` endpoint reads `perpage` straight from the request body and
forwards it to MyAnonamouse unchanged:
```python
perpage = payload.get("perpage", 25)
body = {"tor": tor, "perpage": perpage}
```
The UI only ever sends one of `25`, `50`, or `100` (`app/templates/index.html:184-188`),
but a direct API caller can send any value — a huge number (asking MAM for an
enormous result page), a negative, or a non-integer string. MAM likely caps it,
but the app should not forward unvalidated pagination input to an upstream
service. Clamping to the known-good set is a one-helper hardening with no
behavior change for the UI.

**Second value, same class (added 2026-07-23): `mam_id` on `/add`.** The torrent
id from the request body is interpolated **raw** into the MAM download URL, with
only a non-empty check guarding it. Because the injection point sits *after* the
`?`, a crafted id adds query parameters to the upstream request. Verified by
parsing the exact URL the code builds:

```
id="12345"        -> ...download.php?tid=12345         parsed: {'tid': ['12345']}
id="12345&fl=1"   -> ...download.php?tid=12345&fl=1    parsed: {'tid': ['12345'], 'fl': ['1']}
```

Two concrete consequences:

1. **It bypasses the audiobook-only freeleech policy.** Commit `92c95a3` ("Limit
   FL wedges to audiobooks") deliberately keeps `use_fl` false for ebooks, so the
   app never appends `&fl=1` on an ebook add. An id of `12345&fl=1` puts it there
   anyway, and MAM spends a freeleech wedge — a scarce user resource — on a
   media type the maintainer decided should never consume one.
2. **It corrupts the wedge counter.** `used_fl = candidate_url.endswith("&fl=1")`
   (`app/main.py:445`) becomes true for the *non*-FL candidate, so `/add`
   decrements and returns a wedge count that doesn't match reality.

**This is not SSRF** — the host is fixed (`www.myanonamouse.net`) because the
injection lands in the query string, and no probe (`@evil.com`, `#`, `../`)
moves it. Scope it as input validation, not as an outbound-request
vulnerability.

Honest severity note for the reviewer: the app ships with **no authentication by
design** (`README.md:64` — "do not expose it directly to the public internet"),
so anyone who can reach `/add` to exploit this could also just add an audiobook
with a wedge through the normal UI. A browser-based CSRF is largely blocked
because an `application/json` POST triggers a CORS preflight the app doesn't
answer. So the value here is correctness and policy integrity, not a broken
security boundary — which is why it is a small hardening step folded into this
plan rather than a P1 of its own.

## Current state

- `app/main.py:196-211` — the search handler start and the `perpage` handling:
  ```python
  @app.post("/search")
  async def search(payload: dict):
      media_type = normalize_media_type(payload.get("media_type"))
      tor = payload.get("tor", {}) or {}
      ...
      perpage = payload.get("perpage", 25)
      body = {"tor": tor, "perpage": perpage}
  ```
- The UI's only options (`app/templates/index.html:184-188`):
  ```html
      <select id="perpage">
        <option>25</option>
        <option>50</option>
        <option>100</option>
      </select>
  ```
- Existing small coercion helpers to match in style (module-level, `snake_case`,
  defensive): `is_truthy` (`app/main.py:34`), `normalize_media_type`
  (`app/main.py:51`). Follow that pattern.

For the `/add` vector:

- `app/main.py:418` — where `mam_id` is read (no format check):
  ```python
      mam_id = ("" if body.id is None else str(body.id)).strip()
  ```
  `AddBody.id` is `str | int | None = None` (`app/main.py:408`), so a caller can
  send any string.
- `app/main.py:426-427` — the **only** existing guard:
  ```python
      if not mam_id:
          raise HTTPException(status_code=400, detail="Missing MAM id")
  ```
- `app/main.py:437-445` — where it reaches the URL:
  ```python
          candidate_urls = [f"{settings.MAM_BASE}/tor/download.php?tid={mam_id}"]
          if use_fl:
              candidate_urls.insert(0, f"{settings.MAM_BASE}/tor/download.php?tid={mam_id}&fl=1")

          resp = None
          for candidate_url in candidate_urls:
              resp = await client.get(candidate_url, headers=mam_headers(torrent=True))
              if resp.status_code == 200 and resp.content:
                  used_fl = candidate_url.endswith("&fl=1")
  ```
- `use_fl` is audiobook-only (`app/main.py:434`) — this is the policy the crafted
  id bypasses:
  ```python
          use_fl = media_type == MEDIA_TYPE_AUDIOBOOK and bool(freeleech_wedges and freeleech_wedges > 0)
  ```
- `re` is already imported at `app/main.py:1`. Do **not** add an import.
- MAM torrent ids are numeric — the frontend only ever sends `String(it.id)` from
  a MAM search result (`app/static/app.js:121`), so an allowlist of digits is the
  correct contract and changes nothing for the UI.

## Commands you will need

| Purpose        | Command                                  | Expected on success       |
|----------------|------------------------------------------|---------------------------|
| Syntax check   | `python3 -m py_compile app/main.py`      | exit 0                    |
| Run tests      | `cd app && python -m pytest -q`          | all pass (if plan 001 landed) |

## Scope

**In scope** (the only file you should modify):
- `app/main.py` — add a `normalize_perpage` helper and use it in `/search`; add a
  `validate_mam_id` helper and use it in `/add`.
- `app/tests/test_helpers.py` — add unit tests (only if plan 001 has landed).

**Out of scope** (do NOT touch):
- The `tor` search-parameter assembly (`app/main.py:199-208`) — unrelated.
- The frontend `<select>` — it already emits only valid values; no change.
- Do NOT make `perpage` a free-form min/max range; the UI offers a fixed set, so
  an allowlist is the correct contract (see Maintenance notes if that changes).
- The FL-wedge logic itself (`use_fl` / `used_fl`, `app/main.py:429-462`) — do
  **not** "fix" the `endswith("&fl=1")` check or restructure the candidate-URL
  loop. Once `mam_id` is digits-only, `endswith` is exact again. Changing the
  wedge flow is a behavior change this plan does not authorize.
- `AddBody` (`app/main.py:407-414`) — do **not** retype `id` to `int`. It is
  `str | int | None` and the frontend sends a string; retyping changes the API
  contract and the 422-vs-400 error shape.
- The existing empty-id check and its "Missing MAM id" message
  (`app/main.py:426-427`) — keep it exactly as is; the new check is additive.

## Git workflow

- Branch: `advisor/011-clamp-perpage`.
- Single commit; present-tense message (e.g. `Clamp search perpage to allowed values`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the `normalize_perpage` helper

Add near the other coercion helpers (e.g. just after `is_truthy`, around
`app/main.py:37`), including a module-level constant for the allowed set:
```python
ALLOWED_PERPAGE = (25, 50, 100)

def normalize_perpage(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 25
    return n if n in ALLOWED_PERPAGE else 25
```

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 2: Use the helper in `/search`

Replace the raw read at `app/main.py:210`. Before:
```python
    perpage = payload.get("perpage", 25)
```
After:
```python
    perpage = normalize_perpage(payload.get("perpage"))
```
(`normalize_perpage(None)` returns `25`, preserving the previous default when the
field is absent.)

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "normalize_perpage" app/main.py` shows the definition plus the call site.

### Step 3: Validate `mam_id` before it reaches the MAM URL

**3a — add the validator.** Put it next to `normalize_perpage` from Step 1:
```python
def validate_mam_id(mam_id: str) -> str:
    # MAM torrent ids are numeric. Anything else could inject extra query
    # parameters into the download URL (e.g. "&fl=1" spends a freeleech wedge).
    if not re.fullmatch(r"[0-9]+", mam_id):
        raise HTTPException(status_code=400, detail="Invalid MAM id")
    return mam_id
```

**Do not use `str.isdigit()` here.** It returns `True` for non-ASCII digits —
`"²".isdigit()` is `True` but `int("²")` raises, and `"١٢٣".isdigit()` is `True`
for Arabic-Indic digits MAM will not accept. Only `re.fullmatch(r"[0-9]+", ...)`
restricts to ASCII digits. `re` is already imported (`app/main.py:1`).

**3b — call it in `/add`.** Insert immediately **after** the existing empty check
(`app/main.py:426-427`), so the "Missing MAM id" message is preserved for the
empty case and validation order is unchanged:
```python
    if not mam_id:
        raise HTTPException(status_code=400, detail="Missing MAM id")
    mam_id = validate_mam_id(mam_id)
```
Do **not** move the check up to line 418 — that would run it before
`normalize_media_type` (`app/main.py:422`) and change which error a request with
two bad fields returns.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "validate_mam_id" app/main.py` shows the definition plus one call site.

### Step 4: Add unit tests (only if plan 001 has landed)

Check: `test -f app/tests/test_helpers.py && echo present || echo absent`.
- If **absent**, skip (note the deferred tests in the status row).
- If **present**, add to `app/tests/test_helpers.py`:
```python
def test_normalize_perpage():
    assert main.normalize_perpage(50) == 50
    assert main.normalize_perpage("100") == 100
    assert main.normalize_perpage(None) == 25      # missing -> default
    assert main.normalize_perpage(999) == 25       # out of allowed set -> default
    assert main.normalize_perpage("abc") == 25     # non-int -> default
    assert main.normalize_perpage(-1) == 25


def test_validate_mam_id_accepts_numeric():
    assert main.validate_mam_id("12345") == "12345"
    assert main.validate_mam_id("0") == "0"


def test_validate_mam_id_rejects_query_injection():
    # "&fl=1" would spend a freeleech wedge on an ebook add.
    with pytest.raises(HTTPException):
        main.validate_mam_id("12345&fl=1")
    for bad in ["abc", "-1", "1.5", "1 2", "", "²", "١٢٣"]:
        with pytest.raises(HTTPException):
            main.validate_mam_id(bad)
```
(`main`, `pytest`, and `HTTPException` are already imported at the top of the
file per plan 001.)

**Verify**: `cd app && python -m pytest -q` → all pass, including the three new
tests.

## Test plan

- **Unit (required if plan 001 landed)**: `normalize_perpage` returns the value
  for allowed ints (including numeric strings), and `25` for missing, out-of-set,
  negative, or non-numeric input. `validate_mam_id` passes plain digit strings
  through and raises `HTTPException` for query injection (`12345&fl=1`),
  non-numeric text, negatives, decimals, empty input, and non-ASCII digits
  (`²`, `١٢٣`) — the last two are the cases a naive `isdigit()` check would let
  through. Model after the existing helper tests.
- **Manual (optional)**: a normal UI search with each of 25/50/100 still returns
  the expected page size, and a normal Add from search results still works
  (the UI always sends a numeric id).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -n "normalize_perpage\|ALLOWED_PERPAGE" app/main.py` shows the constant, the helper, and the call site
- [ ] `grep -n 'payload.get("perpage", 25)' app/main.py` returns no matches (the raw read is gone)
- [ ] `grep -n "validate_mam_id" app/main.py` shows the definition plus exactly one call site
- [ ] `grep -n "isdigit" app/main.py` returns **no** matches (the regex check was used, not `isdigit()`)
- [ ] `grep -n "Missing MAM id" app/main.py` still returns one match (the original empty-id guard is intact)
- [ ] This one-liner prints `ok` (validator behavior in isolation):
      `cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp_011.db python -c "
      import main
      from fastapi import HTTPException
      assert main.validate_mam_id('12345') == '12345'
      for bad in ['12345&fl=1', 'abc', '', '²']:
          try: main.validate_mam_id(bad); raise SystemExit('ACCEPTED ' + bad)
          except HTTPException: pass
      print('ok')"; rm -f app/tmp_011.db`
- [ ] `cd app && python -m pytest -q` exits 0 (if plan 001 landed)
- [ ] `git status` shows only `app/main.py` (and `app/tests/test_helpers.py` if 001 landed) modified
- [ ] `plans/README.md` status row for 011 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `app/main.py:210` excerpt does not match live code.
- A UI search with a valid selection (25/50/100) returns a different page size
  than before — the helper is rejecting a value it should allow; report it.
- The `app/main.py:418` / `:426-427` / `:437-445` excerpts do not match live code.
- A normal Add from the UI starts returning "Invalid MAM id" — the id MAM
  returns is not purely numeric for some result type. Report the exact id rather
  than loosening the pattern to allow separators, because separators are the
  whole attack surface.

## Maintenance notes

- If the UI later offers a free-form or larger `perpage`, change
  `normalize_perpage` from an allowlist to a bounded clamp (e.g.
  `max(1, min(n, 100))`) and update `ALLOWED_PERPAGE`/the `<select>` together.
- Reviewer should confirm the default-on-missing behavior (`None -> 25`) matches
  the previous `payload.get("perpage", 25)` default.
- Reviewer should confirm `validate_mam_id` is called **before** the first
  `client.get(candidate_url, ...)` in `/add`, and that the FL-wedge logic was not
  otherwise touched.
- The `mam_id` check protects two downstream consumers, not just the URL: the
  Transmission label `f"mamid={mam_id}"` (`app/main.py:334`) and the stored
  history value. Digits-only keeps all three clean.
- If a future MAM endpoint takes a non-numeric identifier (a slug or hash), do
  not relax `validate_mam_id` — add a separate validator for that field. This one
  encodes "this value goes into a URL query and must not contain separators."
