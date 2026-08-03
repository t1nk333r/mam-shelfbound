# Plan 030: Client-side sortable columns on the search-results table

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat a8625c9..HEAD -- app/static/app.js app/templates/index.html`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before editing; on a mismatch, STOP.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW — client-side only; no API/backend change; degrades to today's behavior when no column is active
- **Depends on**: none
- **Category**: feature (frontend UX)
- **Planned at**: commit `a8625c9`, 2026-08-01

## Why this matters

The search-results table renders in the order MyAnonamouse returns. Users want to
reorder by any column (Title, Author, Narrator, Filetype, Size, Seeders,
Uploaded) without re-querying. This adds **client-side** header-click sorting with
a 3-state cycle (ascending → descending → back to API order) and an ▲/▼ indicator.

It is low-risk because the frontend already keeps the raw results in memory
(`lastResults`) and re-renders them through one function (`renderResults`), so
sorting is just "reorder the array, then re-render." Filters, the freeleech/VIP
badges, the "in history" badge, and the Add/Link buttons all keep working
untouched because they flow through the same render path.

## Current state

Vanilla-JS frontend (no framework, no build step, no bundler). Three relevant files:

**`app/static/app.js`** — results are cached and rendered here:
- Line 23: `let lastResults = [];` — the raw array from the last `/search`.
- `renderResults()` (lines 156-167) filters and renders:
  ```javascript
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
- Each item carries raw fields (from `/search`): `it.title`, `it.author_info`,
  `it.narrator_info`, `it.format`, `it.size`, `it.seeders`, `it.leechers`,
  `it.added`, `it.id`, `it.dl`, `it.is_freeleech`, `it.is_vip`.
- `formatSize(sz)` (lines 325-337): does `Number(sz)`; if finite it formats from
  **bytes**, else it returns the string unchanged. So `it.size` is **either a
  numeric byte count OR a preformatted string** like `"12.3 GiB"` / `"528.9 MiB"`
  / `"5.4 KiB"` (MAM sometimes sends the string) — the size sorter below handles both.
- `it.seeders` is the raw seeder **number** (the `"3216 / 9"` display is built as
  `` `${it.seeders} / ${it.leechers}` `` in `buildResultRow`, line 209) — sort the
  number, never the display string.
- `it.added` is the upload **date string** (e.g. `"2018-03-21 15:06:33"`), rendered
  as-is at `buildResultRow` line 210.
- `const table = document.getElementById('results');` (line 10),
  `const tbody = table.querySelector('tbody');` (line 11).

**`app/templates/index.html`** — the results table header (lines 212-227):
```html
  <table id="results" style="display:none">
    <thead>
      <tr>
        <th>Title</th>
        <th>Author</th>
        <th>Narrator</th>
        <th>Filetype</th>
        <th class="right">Size</th>
        <th class="right">Seeders</th>
        <th>Uploaded</th>
        <th class="center">Link</th>
        <th>Add</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
```
Results-specific CSS lives in this file's inline `<style>` block (e.g. `.right`,
`.center`, `.result-badge` around lines 96-168) — put the new sort-header CSS there.

**Convention:** flat helper functions in `app.js`, `const`/`let`, no framework
(`AGENTS.md`). Match that — do NOT add a build step, a JS test framework, npm, or
a "DataTable" abstraction.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| JS syntax check | `node --check app/static/app.js` | exit 0 (if `node` is unavailable, skip and note it) |
| Backend unaffected | `cd app && python -m pytest -q` | all pass (frontend change touches no Python) |
| Confirm sort wiring | `grep -n "data-sort-key" app/templates/index.html` | 7 matches |
| Confirm sort code | `grep -n "function sortResults\|sizeToBytes\|updateSortIndicators" app/static/app.js` | 3 matches |

There is **no JS test runner** in this repo (vanilla JS, no build). Behavioral
acceptance is a browser check — see Test plan; do not add jest/vitest/etc.

## Scope

**In scope** (only these files):
- `app/static/app.js` — sort state, value parsers, comparator, header wiring,
  indicator update, and one integration line in `renderResults`.
- `app/templates/index.html` — add `data-sort-key` to 7 header cells + sort-UI CSS
  in the existing inline `<style>`.

**Out of scope** (do NOT touch):
- `app/main.py` / any backend or the `/search` API — sorting is 100% client-side
  on the already-fetched `lastResults`. No new request, no response change.
- The **History** table (`#history`) — not part of this plan; leave it as-is.
- `app/static/common.css` — generic `table`/`th`/`td` styles stay.
- Do NOT add a JS framework, bundler, build step, npm, or a generic reusable
  table/component abstraction. Keep it vanilla and flat.
- The `Link` and `Add` columns must NOT become sortable.

## Git workflow

- Branch: `advisor/030-sortable-results-columns`
- Short imperative commit subject (e.g. `Add client-side sorting to results table`).
  Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Mark the sortable headers in `index.html`

Add a `data-sort-key` attribute to the seven data columns (NOT Link/Add). Keep the
existing `class` attributes. The header row becomes:

```html
      <tr>
        <th data-sort-key="title">Title</th>
        <th data-sort-key="author">Author</th>
        <th data-sort-key="narrator">Narrator</th>
        <th data-sort-key="format">Filetype</th>
        <th class="right" data-sort-key="size">Size</th>
        <th class="right" data-sort-key="seeders">Seeders</th>
        <th data-sort-key="added">Uploaded</th>
        <th class="center">Link</th>
        <th>Add</th>
      </tr>
```

**Verify**: `grep -n 'data-sort-key' app/templates/index.html` → exactly 7 matches.

### Step 2: Add sort-header CSS to the inline `<style>` in `index.html`

Inside the existing `<style>…</style>` block (near the other result-table rules,
e.g. right after the `.center { text-align: center; }` line), add:

```css
    th[data-sort-key] { cursor: pointer; user-select: none; white-space: nowrap; }
    th[data-sort-key]:hover { color: var(--text); }
    .sort-ind { color: var(--accent); font-size: 0.8em; }
```

Do not hardcode pixel widths anywhere. **Verify**: `grep -n 'sort-ind' app/templates/index.html` → 1 match.

### Step 3: Add sort state + value parsers in `app.js`

Just below `let lastResults = [];` (line 23), add the sort state:

```javascript
let sortKey = null;   // null = original API order; otherwise a data-sort-key value
let sortDir = null;   // 'asc' | 'desc'
```

Add these pure helpers near the other helpers (e.g. just above `formatSize`):

```javascript
// Parse a size value (numeric bytes, or a string like "12.3 GiB" / "528.9 MiB"
// / "5.4 KiB" / "800 B") to a comparable byte count. Blank/unparseable -> -Infinity.
function sizeToBytes(v) {
  if (v == null || v === '') return -Infinity;
  if (typeof v === 'number') return Number.isFinite(v) ? v : -Infinity;
  const s = String(v).trim();
  const asNum = Number(s);
  if (Number.isFinite(asNum)) return asNum;            // pure numeric string = bytes
  const m = s.match(/([\d.]+)\s*([KMGT])?i?B/i);
  if (!m) return -Infinity;
  const val = parseFloat(m[1]);
  if (!Number.isFinite(val)) return -Infinity;
  const mult = { '': 1, K: 1024, M: 1024 ** 2, G: 1024 ** 3, T: 1024 ** 4 };
  return val * (mult[(m[2] || '').toUpperCase()] ?? 1);
}

// Parse the "Uploaded" value to a timestamp. Blank/unparseable -> -Infinity.
function parseUploaded(v) {
  if (!v) return -Infinity;
  const t = new Date(String(v).replace(' ', 'T')).getTime();
  return Number.isFinite(t) ? t : -Infinity;
}
```

**Verify**: `node --check app/static/app.js` → exit 0 (or skip if no node).

### Step 4: Add the comparator + a stable sort in `app.js`

Add a value-extractor map and a stable sort function (near the helpers):

```javascript
const RESULT_SORTERS = {
  title:    { get: (it) => it.title || '',         type: 'str' },
  author:   { get: (it) => it.author_info || '',   type: 'str' },
  narrator: { get: (it) => it.narrator_info || '', type: 'str' },
  format:   { get: (it) => it.format || '',        type: 'str' },
  size:     { get: (it) => sizeToBytes(it.size),   type: 'num' },
  seeders:  { get: (it) => { const n = Number(it.seeders); return Number.isFinite(n) ? n : -Infinity; }, type: 'num' },
  added:    { get: (it) => parseUploaded(it.added), type: 'num' },
};

// Stable sort: decorate with original index and tie-break on it, so equal keys
// keep their filtered (API) order regardless of the engine's sort stability.
function sortResults(arr, key, dir) {
  const s = RESULT_SORTERS[key];
  if (!s) return arr;
  const sign = dir === 'desc' ? -1 : 1;
  return arr
    .map((it, i) => [it, i])
    .sort((a, b) => {
      const av = s.get(a[0]);
      const bv = s.get(b[0]);
      let c;
      if (s.type === 'str') c = String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' });
      else c = av < bv ? -1 : av > bv ? 1 : 0;
      return c !== 0 ? c * sign : a[1] - b[1];
    })
    .map((x) => x[0]);
}
```

**Verify**: `node --check app/static/app.js` → exit 0.

### Step 5: Wire header clicks + the indicator, and integrate into `renderResults`

Add the indicator updater and the header wiring (near the other helpers):

```javascript
function updateSortIndicators() {
  table.querySelectorAll('thead th[data-sort-key]').forEach((th) => {
    let ind = th.querySelector('.sort-ind');
    if (!ind) { ind = document.createElement('span'); ind.className = 'sort-ind'; th.appendChild(ind); }
    ind.textContent = th.dataset.sortKey === sortKey ? (sortDir === 'desc' ? ' ▼' : ' ▲') : '';
  });
}

function initSortHeaders() {
  table.querySelectorAll('thead th[data-sort-key]').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.sortKey;
      if (sortKey !== key) { sortKey = key; sortDir = 'asc'; }        // 1st click: asc
      else if (sortDir === 'asc') { sortDir = 'desc'; }               // 2nd click: desc
      else { sortKey = null; sortDir = null; }                        // 3rd click: reset to API order
      renderResults();
    });
  });
}
```

Call `initSortHeaders();` once at load — put it next to the other top-level init
calls (e.g. right after `updateSearchPlaceholder();` on line 66).

Then modify `renderResults` (lines 156-167) to sort the filtered copy and refresh
indicators. Change the filter/sort lines and add the indicator call — the rest of
the function stays identical:

```javascript
function renderResults() {
  const f = currentFilters();
  let shown = lastResults.filter((it) => matchesFilters(it, f));
  if (sortKey) shown = sortResults(shown, sortKey, sortDir);
  tbody.innerHTML = '';
  shown.forEach((it) => tbody.appendChild(buildResultRow(it)));
  table.style.display = shown.length ? '' : 'none';
  statusEl.textContent = shown.length === lastResults.length
    ? `${shown.length} results shown`
    : `${shown.length} of ${lastResults.length} results shown`;
  updateSortIndicators();
}
```

Why this satisfies the requirements:
- **No API call** — operates only on the in-memory `lastResults`.
- **Filters/pagination preserved** — sort runs on the already-filtered `shown`;
  `lastResults` is never mutated, so the perpage-limited result set is intact.
- **Badges + Add/Link preserved** — rows are still built by the unchanged
  `buildResultRow`.
- **Reset works** — `sortKey = null` re-filters from the pristine `lastResults`,
  which is in API order.
- **Stable** — the decorate/tie-break in `sortResults`.

**Verify**: `node --check app/static/app.js` → exit 0; `grep -n "initSortHeaders()" app/static/app.js` → definition + one call.

## Test plan

There is **no JS test framework** in this repo and adding one is out of scope.
Verification is:

1. **Syntax + backend**: `node --check app/static/app.js` (exit 0) and
   `cd app && python -m pytest -q` (unchanged, all pass — no Python touched).
2. **Browser acceptance** (the reviewer/maintainer runs the app —
   `cd app && MAM_COOKIE=x HISTORY_DB_URL=sqlite:///tmp/t.db uvicorn main:app --port 8099`
   — then loads `http://localhost:8099`, runs a search, and checks). State in your
   report that you could not perform the browser checks headlessly if that is the
   case; do not claim they pass unless you actually ran them. The checklist:
   - Click each of the 7 headers → sorts ascending; ▲ appears on that header only.
   - Click again → descending; ▼.
   - Third click → returns to the original API order; indicator clears.
   - **Size** sorts by real magnitude (a `5.4 MiB` row sorts below a `12.3 GiB` row),
     not lexically.
   - **Seeders** sorts by the number (`198 / 0` uses 198), not the display string.
   - **Uploaded** sorts chronologically, not as text.
   - Applying a format/min-seeders/freeleech filter then sorting keeps the filter;
     sorting then filtering keeps the sort.
   - Add and Link buttons still work after sorting.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c 'data-sort-key' app/templates/index.html` → `7`
- [ ] `grep -n 'sort-ind' app/templates/index.html` → the CSS rule exists
- [ ] `grep -n 'function sortResults\|function sizeToBytes\|function parseUploaded\|function updateSortIndicators\|function initSortHeaders' app/static/app.js` → 5 matches
- [ ] `renderResults` calls `sortResults` and `updateSortIndicators` (`grep -n 'sortResults(shown\|updateSortIndicators()' app/static/app.js`)
- [ ] `initSortHeaders()` is called once at top level
- [ ] `node --check app/static/app.js` → exit 0 (or report node unavailable)
- [ ] `cd app && python -m pytest -q` → all pass
- [ ] `git status --porcelain` shows only `app/static/app.js` and `app/templates/index.html`
- [ ] `plans/README.md` row for 030 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `renderResults`, `buildResultRow`, `lastResults`, or the results `<thead>` don't
  match the "Current state" excerpts (the code drifted).
- You find yourself needing to change `app/main.py` or the `/search` response — you
  don't; all sort inputs (`size`, `seeders`, `added`, etc.) are already on each item.
- The only way you can make Size/Seeders/Uploaded sort correctly seems to be
  parsing the rendered DOM text — it isn't; sort the raw item fields.
- A requirement seems to need a JS framework or build step — it doesn't; stop and report.

## Maintenance notes

- Sorting reads raw item fields, not DOM text, so display formatting (`formatSize`,
  the `seeders / leechers` string) can change without breaking sort.
- If the `/search` response ever stops sending a raw `seeders` number or `added`
  string, the corresponding sorter degrades to blanks-last — revisit the parser.
- Per-row parse cost is trivial at `perpage ≤ 100`; do not add a value cache
  unless a real perf problem is measured.
- Reviewer: confirm no `/search` request fires on header clicks (Network tab),
  that `lastResults` is never mutated, and that the third click restores API order.
- The History table was intentionally left non-sortable and untouched.
