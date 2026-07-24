# Plan 018: Freeleech wedges are not auto-spent below a reserve you set

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **IMPORTANT — which commit this applies to**: this plan targets branch
> `advisor/plans-001-012` (tip `57c0af6`), **not** `master` (`f8d3d32`). Base
> your work on that branch.
>
> **Drift check (run first)**: `git diff --stat 57c0af6..HEAD -- app/main.py docker-compose.yml README.md`
> If any changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (default value preserves current behavior exactly)
- **Depends on**: none
- **Category**: direction / behavior change (opt-in)
- **Planned at**: commit `57c0af6` (branch `advisor/plans-001-012`), 2026-07-24

## Why this matters

The app spends a freeleech wedge automatically on **every** audiobook add,
whenever you have at least one:

```python
use_fl = media_type == MEDIA_TYPE_AUDIOBOOK and bool(freeleech_wedges and freeleech_wedges > 0)
```

Wedges are a scarce MyAnonamouse resource — earned or bought — and the user gets
no say. Adding five audiobooks in an evening silently burns five wedges, and the
only signal is the counter in the header ticking down afterwards.

This plan adds `FL_WEDGE_MIN_RESERVE`: a floor below which the app stops
auto-spending. Set it to `5` and the app spends wedges freely until you are down
to five, then stops and adds normally. **The default is `0`, which reproduces
today's behavior exactly**, so existing deployments are unchanged until the user
opts in.

A per-add toggle was considered and rejected: it adds a decision to the common
case, whereas a reserve is set once and then invisible. See "Maintenance notes"
if that trade-off is ever revisited.

## Current state

`app/main.py`, inside `add_to_transmission` (the `/add` endpoint) — the whole
wedge decision and its consequence:

```python
    freeleech_wedges = None
    use_fl = False
    used_fl = False
    async with httpx.AsyncClient(timeout=30) as status_client:
        freeleech_wedges = await fetch_freeleech_wedge_count(status_client)
        use_fl = media_type == MEDIA_TYPE_AUDIOBOOK and bool(freeleech_wedges and freeleech_wedges > 0)

    async with httpx.AsyncClient(timeout=60) as client:
        candidate_urls = [f"{settings.MAM_BASE}/tor/download.php?tid={mam_id}"]
        if use_fl:
            candidate_urls.insert(0, f"{settings.MAM_BASE}/tor/download.php?tid={mam_id}&fl=1")
        ...
```

Facts you need:

- `media_type` is already normalised (`normalize_media_type`) earlier in the
  function, so it is exactly `"audiobook"` or `"ebook"` by this point. The helper
  you add can compare it directly and must **not** call `normalize_media_type`
  again.
- `fetch_freeleech_wedge_count` returns `int | None` — `None` when the count is
  unavailable or unparseable. The current expression handles that via
  `bool(freeleech_wedges and ...)`; preserve that.
- Freeleech is **audiobook-only** by deliberate decision (commit `92c95a3`,
  "Limit FL wedges to audiobooks"). Do not extend it to ebooks.
- `Settings.__init__` reads config with `os.getenv(...)` and **raises
  `RuntimeError` on invalid values** — see the existing `MAM_COOKIE` and
  `TORRENT_CLIENT` checks. Follow that pattern.
- Existing small coercion helpers to match in style: `is_truthy`,
  `normalize_perpage`, `validate_mam_id` — module-level, `snake_case`, defensive.
- Conventions: Python 4-space indent, helpers kept flat in `main.py`.

## Commands you will need

| Purpose      | Command                                | Expected on success |
|--------------|----------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile app/main.py`    | exit 0              |
| Run tests    | `cd app && python -m pytest -q`        | all pass, exit 0    |
| Compose YAML | `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"` | `yaml ok` |

No virtualenv exists in a fresh checkout. Create one **outside** the repo,
install `requirements.txt` + `requirements-dev.txt`, invoke it explicitly.

## Scope

**In scope**:
- `app/main.py` — one setting, one helper, one changed expression.
- `docker-compose.yml` — document the new env var.
- `README.md` — document the behavior.
- `app/tests/test_helpers.py` — add a unit test.

**Out of scope** (do NOT touch):
- The audiobook-only restriction — freeleech must stay audiobook-only.
- `used_fl` and the post-add decrement
  (`freeleech_wedges = max(freeleech_wedges - 1, 0)`) — unchanged. This plan
  changes **whether** a wedge is spent, not the accounting afterwards.
- The candidate-URL loop and the `&fl=1` construction — unchanged.
- `fetch_freeleech_wedge_count` / `fetch_account_summary` / `/account` —
  unchanged.
- Do **not** add a per-add UI toggle. That is a different design, explicitly not
  chosen here.
- The frontend — no change; `/add`'s response shape is unaffected.

## Git workflow

- Work on a branch based on `advisor/plans-001-012`.
- Single commit; present-tense message, no prefix
  (e.g. `Add a freeleech wedge reserve`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the setting

In `Settings.__init__`, after the `self.QB_TAGS` line, add:

```python
        try:
            self.FL_WEDGE_MIN_RESERVE = max(0, int(os.getenv("FL_WEDGE_MIN_RESERVE", "0")))
        except ValueError:
            raise RuntimeError("FL_WEDGE_MIN_RESERVE must be a non-negative integer")
```

`max(0, ...)` clamps a negative value to `0`; a non-numeric value fails loudly at
startup, matching how `TORRENT_CLIENT` and `MAM_COOKIE` behave.

**Verify**: `python3 -m py_compile app/main.py` → exit 0. Then confirm both the
default and a bad value behave correctly:

```bash
cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///<scratch>/a.db python -c "import main; print(main.settings.FL_WEDGE_MIN_RESERVE)"
# -> 0
cd app && MAM_COOKIE=x FL_WEDGE_MIN_RESERVE=abc HISTORY_DB_URL=sqlite:///<scratch>/b.db python -c "import main" 2>&1 | tail -1
# -> RuntimeError: FL_WEDGE_MIN_RESERVE must be a non-negative integer
```

### Step 2: Add a testable decision helper

Add near the other coercion helpers (a good spot is just after
`validate_mam_id`):

```python
def should_use_freeleech(media_type: str, wedges: int | None, reserve: int) -> bool:
    """Decide whether to spend a freeleech wedge on this add.

    Freeleech is audiobook-only (commit 92c95a3). Above that, a wedge is spent
    only while the balance is strictly greater than the configured reserve, so
    a reserve of 0 keeps the historical "spend whenever you have one" behavior.
    """
    if media_type != MEDIA_TYPE_AUDIOBOOK:
        return False
    if not wedges:
        return False
    return wedges > reserve
```

`if not wedges` covers both `None` and `0` — matching the existing
`bool(freeleech_wedges and ...)` guard.

**Verify**: `python3 -m py_compile app/main.py` → exit 0.

### Step 3: Use it in `/add`

Replace the single decision line. Before:

```python
        use_fl = media_type == MEDIA_TYPE_AUDIOBOOK and bool(freeleech_wedges and freeleech_wedges > 0)
```

After:

```python
        use_fl = should_use_freeleech(media_type, freeleech_wedges, settings.FL_WEDGE_MIN_RESERVE)
```

Nothing else in `/add` changes.

**Verify**: `python3 -m py_compile app/main.py` → exit 0, and
`grep -n "should_use_freeleech" app/main.py` shows the definition plus exactly
one call site. Also confirm the old expression is gone:
`grep -n "freeleech_wedges > 0" app/main.py` → no matches.

### Step 4: Document it

In `docker-compose.yml`, add to the `environment:` block after `QB_CATEGORY`:

```yaml
      # Stop auto-spending freeleech wedges once the balance drops to this many.
      # 0 (default) = spend whenever any are available.
      FL_WEDGE_MIN_RESERVE: "0"
```

In `README.md`, add `FL_WEDGE_MIN_RESERVE` to the Configuration table with the
purpose "Keep this many freeleech wedges unspent (0 = spend freely)", and add one
bullet under Notes:

```markdown
- Freeleech wedges are spent automatically on audiobook adds. Set `FL_WEDGE_MIN_RESERVE` to keep a reserve — with `5`, the app stops using wedges once your balance reaches 5 and adds normally instead. The default `0` spends whenever any are available.
```

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"` → `yaml ok`.

### Step 5: Add a unit test

Add to `app/tests/test_helpers.py`:

```python
def test_should_use_freeleech_respects_reserve_and_media_type():
    AB = main.MEDIA_TYPE_AUDIOBOOK
    EB = main.MEDIA_TYPE_EBOOK

    # reserve 0 reproduces the historical behavior: spend whenever any exist
    assert main.should_use_freeleech(AB, 1, 0) is True
    assert main.should_use_freeleech(AB, 0, 0) is False
    assert main.should_use_freeleech(AB, None, 0) is False

    # a reserve holds the last N back
    assert main.should_use_freeleech(AB, 6, 5) is True
    assert main.should_use_freeleech(AB, 5, 5) is False   # at the reserve, stop
    assert main.should_use_freeleech(AB, 2, 5) is False   # below it, stop

    # ebooks never spend a wedge, whatever the balance
    assert main.should_use_freeleech(EB, 99, 0) is False
```

**Verify**: `cd app && python -m pytest -q` → all pass, including the new test.

## Test plan

- **Unit (required)**: the boundary is the whole feature — `wedges == reserve`
  must be `False` and `wedges == reserve + 1` must be `True`. The test above
  pins that, plus the `None`/`0` cases and the audiobook-only rule.
- **Regression (required)**: with `FL_WEDGE_MIN_RESERVE` unset, behavior is
  identical to before. `should_use_freeleech(AB, 1, 0) is True` is exactly the
  old `wedges > 0` condition.
- **Manual (recommended)**: set `FL_WEDGE_MIN_RESERVE` to one below your current
  balance, add an audiobook, and confirm the wedge count drops by one. Set it to
  your current balance, add another, and confirm the count does **not** drop and
  the torrent is still added successfully (just without freeleech).
- Not unit-testable: that MAM actually honours `&fl=1` — that is upstream
  behavior, unchanged by this plan.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile app/main.py` exits 0
- [ ] `grep -c "should_use_freeleech" app/main.py` returns 2 (definition + exactly one call site)
- [ ] `grep -n "freeleech_wedges > 0" app/main.py` returns **no** matches
- [ ] `grep -n "FL_WEDGE_MIN_RESERVE" app/main.py docker-compose.yml README.md` shows it in all three
- [ ] importing with `FL_WEDGE_MIN_RESERVE=abc` raises `RuntimeError` (Step 1's second command)
- [ ] `grep -n "max(freeleech_wedges - 1, 0)" app/main.py` still returns one match — the decrement was not touched
- [ ] `cd app && python -m pytest -q` exits 0 with the new test passing
- [ ] `git status` shows only `app/main.py`, `docker-compose.yml`, `README.md`, `app/tests/test_helpers.py` modified
- [ ] `plans/README.md` status row for 018 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `use_fl` excerpt does not match the live code.
- You find yourself changing the ebook branch, the `&fl=1` URL construction, or
  the post-add decrement. All are out of scope.
- A test asserts `should_use_freeleech(AB, 5, 5) is True`. The boundary is
  deliberately exclusive — at the reserve the app stops. If that reads wrong to
  you, report it rather than flipping the comparison; the semantics are "keep
  this many".

## Maintenance notes

- **The boundary is exclusive**: with `reserve = 5`, the app spends down to 5 and
  then stops, so you keep 5. Anyone changing `>` to `>=` changes what the setting
  means — the README wording ("keep this many") has to change with it.
- The rejected alternative was a **per-add toggle**. It gives exact control but
  adds a decision to every add; the reserve is configured once and then
  invisible. If precise per-add control is ever wanted, add it *alongside* the
  reserve (toggle overrides reserve) rather than replacing it.
- The wedge balance is fetched fresh on every `/add` before the decision, so the
  reserve is always evaluated against a current count — no caching concerns.
- Reviewer should confirm the audiobook-only rule survived, that the decrement
  logic is untouched, and that the default of `0` genuinely reproduces the old
  expression.
