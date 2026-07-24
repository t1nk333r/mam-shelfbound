# Plan 016: Search results can be filtered, and results already in history are marked

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
> **Drift check (run first)**: `git diff --stat 57c0af6..HEAD -- app/static/app.js app/templates/index.html`
> If either changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P3
- **Effort**: S-M
- **Risk**: LOW (frontend only; no API or backend change)
- **Depends on**: none
- **Category**: direction / feature
- **Planned at**: commit `57c0af6` (branch `advisor/plans-001-012`), 2026-07-24

## Why this matters

Two small gaps that compound, both fixable without touching the backend.

**1. Every result field is already returned, and none of it is actionable.**
`/search` returns `format`, `seeders`, `leechers`, `size`, `is_freeleech`, and
`is_vip` per result. The UI renders all of them as inert text —
`app/static/app.js` contains no `filter(` or `sort(` anywhere. On a 100-result
page, finding "the M4B with live seeders" means reading every row. Note the
backend already forces `tor["sortType"] = "seedersDesc"`, so results arrive
seeder-sorted; **sorting is not the gap, filtering is.**

**2. Nothing tells you a result is already in your history.** The app records
`mam_id` for everything ever added, and the frontend already fetches that list
after every search — but never cross-references it. Re-adding a title you
already have is silent, and it has a real consequence: the auto-import
candidate query de-duplicates by hash **within a single poll cycle only**, so a
second history row for the same torrent is picked up on a *later* cycle and
imported again, producing a duplicate library folder (`Title (2)` via
`next_available`).

Both changes are confined to `app/static/app.js` and
`app/templates/index.html`.

## Current state

### The render path (this is what you will refactor)

`app/static/app.js` — `runSearch()` fetches and renders in one pass, so there is
nothing to re-render against when a filter changes:

```javascript
async function runSearch() {
  const text = (q?.value || '').trim();
  const mediaType = getSelectedMediaType();
  const perpage = parseInt(perpageSel?.value || '25', 10);

  statusEl.textContent = 'Searching...';
  table.style.display = 'none';
  tbody.innerHTML = '';

  try {
    const data = await fetchJson('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ media_type: mediaType, tor: { text }, perpage })
    });

    setAccountStatus(data?.freeleech_wedges);

    const rows = data.results || [];
    if (!rows.length) {
      statusEl.textContent = 'No results.';
      return;
    }

    rows.forEach((it) => {
      // ...builds addBtn, then tr.innerHTML = `...`, then tbody.appendChild(tr)
    });

    table.style.display = '';
    statusEl.textContent = `${rows.length} results shown`;
    await loadHistory();
  } catch (e) {
    console.error(e);
    statusEl.textContent = 'Search failed.';
  }
}
```

The row markup inside that `forEach`:

```javascript
      tr.innerHTML = `
        <td>${renderResultTitleCell(it)}</td>
        <td>${escapeHtml(it.author_info || '')}</td>
        <td>${escapeHtml(it.narrator_info || '')}</td>
        <td>${escapeHtml(it.format || '')}</td>
        <td class="right">${formatSize(it.size)}</td>
        <td class="right">${escapeHtml(`${it.seeders ?? '-'} / ${it.leechers ?? '-'}`)}</td>
        <td>${escapeHtml(it.added || '')}</td>
        <td class="center">
          ${detailsURL ? `<a href="${detailsURL}" target="_blank" rel="noopener noreferrer" title="Open on MAM">🔗</a>` : ''}
        </td>
        <td></td>
      `;

      applyDataLabels(table, tr);
      const actionCell = tr.lastElementChild;
      actionCell.appendChild(addBtn);
      tbody.appendChild(tr);
```

### History load

`loadHistory()` fetches `/history` and renders the history table. Each item
carries `mam_id`, `torrent_status`, `title`. It is currently called at the **end**
of `runSearch()`, i.e. after results are already on screen.

### DOM lookups block

`app/static/app.js` begins with a block of `document.getElementById` constants
(`form`, `q`, `perpageSel`, `statusEl`, `table`, `tbody`, `historyBody`, …).
Add new element handles there, matching that style.

### The search form

`app/templates/index.html`:

```html
  <form id="searchForm" class="row">
    <input id="q" type="text" placeholder="Search title/author/narrator" />
    <div class="media-toggle" role="radiogroup" aria-label="Media type">
      <input id="mediaAudiobook" type="radio" name="mediaType" value="audiobook" checked />
      <label for="mediaAudiobook">Audiobooks</label>
      <input id="mediaEbook" type="radio" name="mediaType" value="ebook" />
      <label for="mediaEbook">Ebooks</label>
    </div>
    <label id="kindleToggle" class="kindle-toggle" for="sendToKindle" hidden>
      <input id="sendToKindle" type="checkbox" />
      <span>Send to Kindle</span>
    </label>
    <select id="perpage">
      <option>25</option>
      <option>50</option>
      <option>100</option>
    </select>
    <button id="searchBtn" type="submit">Search</button>
  </form>

  <div id="accountStatus" class="muted status-line">Freeleech wedges: loading...</div>
  <div id="status" class="muted status-line"></div>
```

Page-scoped CSS lives in the `{% block head %}<style>` block at the top of
`index.html` (classes like `.row`, `.kindle-toggle`, `.type-badge`,
`.result-badge`). Add new styles there — do **not** create a new stylesheet.

### Conventions

- Vanilla ES, no framework (`AGENTS.md`: "avoid frameworks; keep logic in
  `app/static/app.js`").
- All text interpolated into HTML goes through `escapeHtml(...)`. **Keep doing
  that.** Note `escapeHtml` does *not* escape quotes, so never place an escaped
  value inside an HTML attribute — use `textContent`/`encodeURIComponent` there,
  as the existing `detailsURL` code does.
- Existing badge markup to copy for the new badge: `renderMediaTypeBadge` uses
  `<span class="type-badge">`; `renderResultTitleCell` uses
  `<span class="result-badge result-badge-free">`.

## Commands you will need

| Purpose        | Command                              | Expected on success |
|----------------|--------------------------------------|---------------------|
| Python suite   | `cd app && python -m pytest -q`      | 19 pass (unchanged) |
| Syntax check   | `python3 -m py_compile app/main.py`  | exit 0              |
| JS syntax      | `node --check app/static/app.js`     | exit 0 (if node present) |

**There is no JavaScript test framework in this repo** and this plan does not add
one. The Python suite must still pass (proving you changed nothing server-side),
and the rest of verification is the manual checklist in "Test plan".

## Scope

**In scope** (the only files you should modify):
- `app/static/app.js`
- `app/templates/index.html`

**Out of scope** (do NOT touch):
- `app/main.py` and every endpoint — this is **frontend-only**. Do not add a
  server-side filter, do not change the `/search` request or response shape, and
  do not add fields to `/history`. Everything needed is already returned.
- The `perpage` `<select>` — do not change its options. Filtering narrows the
  page you already fetched; it is not a substitute for a larger page.
- `app/static/common.css` — page-scoped styles belong in `index.html`'s
  `<style>` block, matching the existing pattern.
- The Add button's behavior and the `/add` payload — unchanged.
- `escapeHtml` — do not "improve" it in this plan.

## Git workflow

- Work on a branch based on `advisor/plans-001-012`.
- One or two commits; present-tense messages with no prefix
  (e.g. `Add search result filters`, `Mark search results already in history`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the filter controls to the page

In `app/templates/index.html`, insert a filter row **immediately after** the
closing `</form>` tag and **before** the `accountStatus` div:

```html
  <div id="filterRow" class="row filter-row" hidden>
    <input id="filterFormat" type="text" placeholder="Filter format (e.g. M4B)" />
    <input id="filterMinSeeders" type="number" min="0" placeholder="Min seeders" />
    <label class="kindle-toggle" for="filterFreeleech">
      <input id="filterFreeleech" type="checkbox" />
      <span>Freeleech only</span>
    </label>
    <button id="clearFilters" type="button">Clear</button>
  </div>
```

It reuses the existing `.row` and `.kindle-toggle` classes so it matches the
search bar without new styling work. Add one rule to the `<style>` block in
`{% block head %}`:

```css
    .filter-row[hidden] { display: none; }
    .filter-row input[type="number"] { flex:0 0 8rem; min-width:0; padding:0.6rem 0.7rem; }
```

The `[hidden]` rule is required because `.row` sets `display:flex`, which
otherwise overrides the `hidden` attribute.

**Verify**: `grep -n 'id="filterRow"\|id="filterFormat"\|id="filterMinSeeders"\|id="filterFreeleech"\|id="clearFilters"' app/templates/index.html` → 5 matches.

### Step 2: Separate fetching from rendering

In `app/static/app.js`, add the new element handles to the DOM lookups block at
the top, matching the existing style:

```javascript
const filterRow = document.getElementById('filterRow');
const filterFormatInput = document.getElementById('filterFormat');
const filterMinSeedersInput = document.getElementById('filterMinSeeders');
const filterFreeleechInput = document.getElementById('filterFreeleech');
const clearFiltersBtn = document.getElementById('clearFilters');
```

Add two module-level state variables next to them:

```javascript
let lastResults = [];              // raw results from the most recent search
let historyMamIds = new Map();     // mam_id -> torrent_status, for the "in history" badge
```

Now split `runSearch`. Replace the whole `try { ... }` body of `runSearch` with:

```javascript
  try {
    const data = await fetchJson('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ media_type: mediaType, tor: { text }, perpage })
    });

    setAccountStatus(data?.freeleech_wedges);

    lastResults = data.results || [];
    if (!lastResults.length) {
      filterRow.hidden = true;
      statusEl.textContent = 'No results.';
      return;
    }

    // Load history first so the "in history" badge can be rendered in one pass.
    await loadHistory();

    filterRow.hidden = false;
    renderResults();
  } catch (e) {
    console.error(e);
    statusEl.textContent = 'Search failed.';
  }
```

Note the deliberate ordering change: `loadHistory()` now runs **before** results
are rendered rather than after, so the badge can be drawn in a single pass. Both
complete before the user can interact, so this is not a visible regression.

**Verify**: `node --check app/static/app.js` → exit 0 (skip if `node` is absent).

### Step 3: Add the filter + render functions

Add these functions to `app/static/app.js`, directly below `runSearch`:

```javascript
function currentFilters() {
  return {
    format: (filterFormatInput?.value || '').trim().toLowerCase(),
    minSeeders: parseInt(filterMinSeedersInput?.value || '', 10),
    freeleechOnly: !!filterFreeleechInput?.checked
  };
}

function matchesFilters(item, f) {
  if (f.format && !String(item.format || '').toLowerCase().includes(f.format)) return false;
  if (Number.isFinite(f.minSeeders) && Number(item.seeders ?? 0) < f.minSeeders) return false;
  if (f.freeleechOnly && !item.is_freeleech) return false;
  return true;
}

function renderResults() {
  const f = currentFilters();
  const shown = lastResults.filter((it) => matchesFilters(it, f));

  tbody.innerHTML = '';
  shown.forEach((it) => tbody.appendChild(buildResultRow(it)));

  table.style.display = shown.length ? '' : 'none';
  statusEl.textContent = shown.length === lastResults.length
    ? `${shown.length} results shown`
    : `${shown.length} of ${lastResults.length} results shown`;
}
```

Then move the existing per-row construction out of the old `forEach` into a
`buildResultRow(it)` function that **returns** the `<tr>`. Take the body of the
current `rows.forEach((it) => { ... })` verbatim — the `addBtn` creation, its
click handler, the `tr.innerHTML = \`...\`` template, `applyDataLabels`, and the
`actionCell.appendChild(addBtn)` — and change only the ending: instead of
`tbody.appendChild(tr)`, `return tr;`.

Two edits inside that moved code:

1. Add the history badge to the title cell. Change the first `<td>`:
   ```javascript
        <td>${renderResultTitleCell(it)}${renderInHistoryBadge(it)}</td>
   ```
2. Leave everything else exactly as it was.

Add the badge helper next to the other render helpers:

```javascript
function renderInHistoryBadge(item) {
  const status = historyMamIds.get(String(item?.id ?? ''));
  if (!status) return '';
  const label = status === 'import_failed' ? 'In history (failed)' : 'In history';
  return `<div class="result-flags"><span class="result-badge result-badge-history">${escapeHtml(label)}</span></div>`;
}
```

Add the badge style to the `<style>` block in `index.html`:

```css
    .result-badge-history {
      color:var(--text-soft);
      background:var(--bg-elevated);
      border-color:var(--border);
    }
```

**Do not disable the Add button for results already in history.** A previously
failed import is a legitimate reason to add again — the badge informs, it does
not block. This is deliberate; do not "improve" it.

**Verify**: `node --check app/static/app.js` → exit 0; and
`grep -n "buildResultRow\|renderInHistoryBadge\|matchesFilters" app/static/app.js`
shows each defined and used.

### Step 4: Populate the history lookup

In `loadHistory()`, after `const items = j.items || [];`, add:

```javascript
    historyMamIds = new Map(
      items
        .filter((it) => it.mam_id)
        .map((it) => [String(it.mam_id), it.torrent_status || 'added'])
    );
```

Leave the rest of `loadHistory` unchanged — it must still render the history
table exactly as before.

**Verify**: `grep -n "historyMamIds = new Map" app/static/app.js` → one match
inside `loadHistory`.

### Step 5: Wire the filter events

Add near the other event listeners (e.g. below the `form.addEventListener`
block):

```javascript
[filterFormatInput, filterMinSeedersInput, filterFreeleechInput].forEach((el) => {
  if (el) el.addEventListener('input', () => { if (lastResults.length) renderResults(); });
});

if (clearFiltersBtn) {
  clearFiltersBtn.addEventListener('click', () => {
    if (filterFormatInput) filterFormatInput.value = '';
    if (filterMinSeedersInput) filterMinSeedersInput.value = '';
    if (filterFreeleechInput) filterFreeleechInput.checked = false;
    if (lastResults.length) renderResults();
  });
}
```

Filters re-render from `lastResults` and never re-query the server.

**Verify**: `node --check app/static/app.js` → exit 0.

## Test plan

There is no JS test framework, so this is a **manual** checklist. Run the app
(`docker compose up -d --build`, or `cd app && uvicorn main:app --reload --port 8080`
with `MAM_COOKIE` set) and confirm:

1. **Baseline** — search for a common term. Results appear; the filter row
   becomes visible; status reads `N results shown`.
2. **Format filter** — type `m4b`. Only rows whose Filetype contains M4B remain;
   status reads `X of N results shown`. Clearing the box restores all rows.
   Confirm it is case-insensitive (`M4B` and `m4b` behave identically).
3. **Min seeders** — enter a number above the lowest seeder count. Low-seeder
   rows disappear. Blank means no seeder filtering (not zero).
4. **Freeleech only** — tick it; only rows carrying the Freeleech badge remain.
5. **Combined** — all three at once narrow cumulatively.
6. **Clear** — resets all three and restores the full list.
7. **History badge** — add something, then search for it again: the result shows
   an "In history" badge and the Add button is **still enabled**. Force a failed
   import and confirm that row's badge reads "In history (failed)".
8. **No results** — a nonsense query hides the filter row and shows `No results.`
9. **Regression** — Add still works from a filtered list, and the History table
   below renders exactly as before.

**Automated**: `cd app && python -m pytest -q` → 19 pass, proving no server-side
change crept in.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c 'id="filter' app/templates/index.html` returns 4 (`filterRow`, `filterFormat`, `filterMinSeeders`, `filterFreeleech`)
- [ ] `grep -n "buildResultRow" app/static/app.js` shows the definition and its use in `renderResults`
- [ ] `grep -n "renderInHistoryBadge\|historyMamIds" app/static/app.js` shows both defined and used
- [ ] `grep -c "tbody.appendChild" app/static/app.js` returns 1 (rendering happens in exactly one place)
- [ ] `node --check app/static/app.js` exits 0 (skip only if `node` is unavailable — say so in your report)
- [ ] `cd app && python -m pytest -q` exits 0 with 19 passing
- [ ] `git diff --stat` shows **no** changes to `app/main.py`
- [ ] `git status` shows only `app/static/app.js` and `app/templates/index.html` modified
- [ ] `plans/README.md` status row for 016 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any "Current state" excerpt does not match the live code.
- You find yourself needing a change in `app/main.py` to make a filter work.
  Everything required (`format`, `seeders`, `is_freeleech`, and `mam_id` on
  history) is already returned; needing more means the design drifted. Report it.
- The history badge shows on results you have **not** added. That means the
  `mam_id` ↔ `id` key comparison is mismatched (one side is a number, the other
  a string) — both sides are coerced with `String(...)` for exactly this reason;
  report what you observed rather than loosening the comparison.
- After the refactor, the Add button stops working. `buildResultRow` must return
  the `<tr>` **after** `actionCell.appendChild(addBtn)`; returning early drops
  the button.

## Maintenance notes

- **Filtering is client-side only**: it narrows the page already fetched, not the
  whole MAM result set. If users start expecting "all M4Bs", that needs a
  server-side change to the `tor` search parameters — a different, larger plan.
- `renderResults()` is now the single render path. Any future column or badge
  goes in `buildResultRow`, not in `runSearch`.
- The badge deliberately does not block re-adding. If duplicate adds ever need
  actually preventing, do it in `/add` (reject a duplicate `mam_id` with a
  non-terminal status), not in the UI — the API is the real boundary.
- Reviewer should confirm `app/main.py` is untouched, that every interpolated
  string still goes through `escapeHtml`, and that no escaped value was placed
  inside an HTML attribute.
