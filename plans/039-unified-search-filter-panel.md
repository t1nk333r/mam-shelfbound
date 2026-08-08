# Plan 039: Unify search and filter controls in one panel

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update this plan's status row in
> `plans/README.md` unless a reviewer explicitly owns the index update.
>
> **Drift check (run first)**:
> `git diff --stat 98e25d9..HEAD -- app/templates/index.html`
> If the in-scope template changed, compare the "Current state" excerpts with
> live code. Stop if the search/filter markup or responsive selectors no longer
> match this plan.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW — template/CSS-only layout change with stable element IDs and behavior
- **Depends on**: Plan 016 (DONE; introduced result filters)
- **Category**: bug
- **Planned at**: commit `98e25d9`, 2026-08-08

## Why this matters

Search and result filtering are one workflow, but the current UI presents them
as two independently bordered and shadowed cards. Once filters appear, the
duplicated chrome makes the controls look disconnected and consumes excessive
vertical space, especially on mobile. A single shared panel with a primary
search row and a quieter secondary filter row restores hierarchy without
changing how searches or filters work.

## Current state

- `app/templates/index.html:7-18` gives every `.row` a complete card surface:

  ```css
  .row {
    display:flex;
    gap:0.65rem;
    flex-wrap: wrap;
    align-items:center;
    padding:0.75rem;
    border:1px solid var(--border);
    border-radius:8px;
    background:var(--bg-elevated);
    box-shadow:0 12px 28px var(--shadow);
  }
  ```

- `app/templates/index.html:188-216` applies that class separately to the
  search form and filter container:

  ```html
  <form id="searchForm" class="row">
    <!-- query, media type, Kindle toggle, page size, Search -->
  </form>

  <div id="filterRow" class="row filter-row" hidden>
    <!-- format, minimum seeders, freeleech-only, Clear -->
  </div>
  ```

  The committed references
  `app/static/screenshots/finder_desktop.png` and
  `app/static/screenshots/finder_mobile.png` visibly show the resulting two
  stacked outlined/shadowed surfaces. They are evidence, not source assets for
  this plan; do not edit them.

- `app/templates/index.html:135-168` makes `.row` controls stack on narrow
  viewports, but the minimum-seeders field retains its desktop fixed basis:

  ```css
  @media (max-width: 720px) {
    .row { align-items:stretch; }
    /* text, media toggle, Kindle toggle, and buttons become full width */
    .row button { width:100%; }
  }
  .filter-row[hidden] { display: none; }
  .filter-row input[type="number"] { flex:0 0 8rem; min-width:0; padding:0.6rem 0.7rem; }
  ```

  That is why the mobile screenshot shows a narrow seeders field beside empty
  space while the other filter controls span the card.

- `app/static/app.js:94-105` attaches filter input and Clear handlers by ID.
  `runSearch` hides `#filterRow` for no results and reveals it before rendering
  successful results (`app/static/app.js:128-137`):

  ```javascript
  if (!lastResults.length) {
    filterRow.hidden = true;
    statusEl.textContent = 'No results.';
    return;
  }
  await loadHistory();
  filterRow.hidden = false;
  renderResults();
  ```

  Preserve every ID and the initial `hidden` attribute. The filter row must
  remain outside `#searchForm`; otherwise Enter in a filter input can submit a
  new server search instead of only filtering the existing results.

- Shared colors, borders, shadows, fields, and responsive table behavior live
  in `app/static/common.css`. The relevant tokens already exist:
  `--bg-elevated`, `--border`, `--border-subtle`, and `--shadow`. Reuse them;
  no new palette or common component is needed.

- The frontend is vanilla JavaScript with template-local page styles. There is
  no frontend framework, formatter, DOM test library, lint command, or package
  manifest. Match the compact CSS style already used in `index.html` and do not
  add a dependency for this layout change.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Python syntax | `python -m py_compile app/main.py` | exit 0 |
| JavaScript syntax | `node --check app/static/app.js` | exit 0 |
| Tests | `cd app && python -m pytest -q` | 79 tests pass at the planning baseline |
| Whitespace | `git diff --check` | exit 0, no output |

If host Python lacks pytest, use the known-good repository-root fallback:

```bash
docker run --rm -v "$PWD":/repo -w /repo python:3.12-slim sh -lc '
set -e
python -m pip install -q -r requirements.txt -r requirements-dev.txt
cd app
python -m pytest -q
'
```

Do not install or add a frontend package solely for this plan.

## Scope

**In scope**:

- `app/templates/index.html` — add the shared panel wrapper, distinguish the
  two control rows, move card chrome to the wrapper, and correct responsive
  filter sizing.
- `plans/README.md` — update Plan 039's status only after implementation and
  verification.

**Out of scope**:

- `app/static/app.js` — IDs and current listeners already support the target
  markup. Do not rewrite filtering, searching, sorting, hidden-state logic, or
  form submission.
- `app/static/common.css` — this panel is page-specific and its styles already
  live in `index.html`; do not widen the change into the shared design system.
- `app/main.py`, API request/response shapes, database state, MAM requests, and
  torrent clients.
- Search/filter features, fields, defaults, labels, placeholder text, or
  persistence. Do not add saved filters, reset search state, or localStorage.
- Result table, badges, account/status lines, history panel, header, footer,
  theme palette, or global button/input styling.
- Moving `#filterRow` inside `#searchForm`, using `display:contents`, or removing
  the initial `hidden` attribute.
- Committed screenshot changes. Capture temporary desktop/mobile review images
  as required by `AGENTS.md`, but do not replace repository screenshots unless
  the maintainer separately requests it.
- New dependencies.

## Git workflow

- Branch: `advisor/039-unified-search-filter-panel`
- Use one focused commit, for example `Unify search and filter controls`.
- Do not push or open a PR unless the operator explicitly instructs it.

## Steps

### Step 1: Put both semantic rows inside one shared panel

In `app/templates/index.html`, wrap the existing search form and filter row in
one new container. Use this exact structural shape while preserving all current
children, order, IDs, input types, values, and the filter row's `hidden` state:

```html
<div class="search-filter-panel">
  <form id="searchForm" class="control-row search-row">
    <!-- existing search controls, unchanged -->
  </form>

  <div id="filterRow" class="control-row filter-row" hidden>
    <!-- existing filter controls, unchanged -->
  </div>
</div>
```

The two rows must be direct siblings under `.search-filter-panel`.
`#filterRow` must not become a descendant of `#searchForm`. Keep Search as
`type="submit"` and Clear as `type="button"`.

**Verify**:

```bash
node <<'NODE'
const fs = require('fs');
const assert = require('assert');
const html = fs.readFileSync('app/templates/index.html', 'utf8');
const panelStart = html.indexOf('<div class="search-filter-panel">');
const formStart = html.indexOf('<form id="searchForm" class="control-row search-row">');
const formEnd = html.indexOf('</form>', formStart);
const filterStart = html.indexOf('<div id="filterRow" class="control-row filter-row" hidden>');
const filterEnd = html.indexOf('</div>', filterStart);
const panelEnd = html.indexOf('</div>', filterEnd + 6);
assert.ok(panelStart >= 0, 'missing shared panel');
assert.ok(panelStart < formStart && formStart < formEnd, 'search form is not first in panel');
assert.ok(formEnd < filterStart && filterStart < filterEnd, 'filter row must follow and stay outside form');
assert.ok(filterEnd < panelEnd, 'shared panel does not close after filter row');
assert.ok(html.slice(formStart, formEnd).includes('id="searchBtn"'));
assert.ok(!html.slice(formStart, formEnd).includes('id="filterRow"'));
assert.ok(html.slice(filterStart, filterEnd).includes('id="clearFilters"'));
NODE
```

Expected: exit 0 with no output.

### Step 2: Move the card surface from each row to the shared parent

Replace the generic `.row` rule with two explicit responsibilities:

- `.search-filter-panel` owns the single border, 8px radius, elevated
  background, shadow, and clipped/hidden overflow needed to keep child
  backgrounds within the rounded edge.
- `.control-row` owns only flex layout, wrapping, alignment, gap, and padding.

Use the existing values from `.row` rather than inventing a new visual system:

```css
.search-filter-panel {
  border:1px solid var(--border);
  border-radius:8px;
  overflow:hidden;
  background:var(--bg-elevated);
  box-shadow:0 12px 28px var(--shadow);
}
.control-row {
  display:flex;
  gap:0.65rem;
  flex-wrap:wrap;
  align-items:center;
  padding:0.75rem;
}
.filter-row {
  border-top:1px solid var(--border-subtle);
}
```

Do not give `.search-row` or `.filter-row` another outer border, radius, or
shadow. Because `[hidden]` sets the entire filter row to `display:none`, the
divider must also disappear before results are available; do not implement the
divider with a panel pseudo-element that remains visible when filters are
hidden.

Remove every CSS/markup use of the old generic `.row` class from this template
and update its mobile selectors to `.control-row`. Do not change
`.actions-row`; it is unrelated despite the similar name.

**Verify**:

```bash
node <<'NODE'
const fs = require('fs');
const assert = require('assert');
const html = fs.readFileSync('app/templates/index.html', 'utf8');
assert.match(html, /\.search-filter-panel\s*\{[^}]*border:1px solid var\(--border\);[^}]*box-shadow:/);
assert.match(html, /\.control-row\s*\{[^}]*display:flex;[^}]*padding:0\.75rem;/);
assert.match(html, /\.filter-row\s*\{[^}]*border-top:1px solid var\(--border-subtle\);/);
assert.ok(!/(^|\n)\s*\.row(?:\s|\{|button)/.test(html), 'old .row selector remains');
assert.ok(!html.includes('class="row'), 'old row class remains in markup');
NODE
```

Expected: exit 0 with no output.

### Step 3: Make the secondary row coherent on mobile

Inside the existing `@media (max-width: 720px)` block:

- Change `.row { align-items:stretch; }` to `.control-row`.
- Change `.row button { width:100%; }` to `.control-row button`.
- Override `.filter-row input[type="number"]` to `flex:1 1 100%` and
  `width:100%` so minimum seeders aligns with the other full-width mobile
  controls.

Keep the existing full-width text input, media toggle, Kindle/freeleech toggle,
select, and button rules. Do not change the 720px/420px breakpoints. At desktop
width, retain the seeders field's compact `8rem` basis and allow the format
input to consume remaining space.

**Verify**:

```bash
node <<'NODE'
const fs = require('fs');
const assert = require('assert');
const html = fs.readFileSync('app/templates/index.html', 'utf8');
assert.ok(html.includes('.control-row { align-items:stretch; }'));
assert.ok(html.includes('.control-row button { width:100%; }'));
assert.match(html, /\.filter-row input\[type="number"\]\s*\{[^}]*flex:1 1 100%;[^}]*width:100%;/);
NODE
```

Expected: exit 0 with no output. Confirm these three declarations are inside
the existing 720px media block; do not move them into desktop styles merely to
satisfy the string probe.

### Step 4: Run syntax, regression, and hygiene checks

From the repository root, run:

```bash
python -m py_compile app/main.py
node --check app/static/app.js
cd app && python -m pytest -q
```

Expected: both syntax checks exit 0 and **79 tests pass** at the planning
baseline. Use the ephemeral Docker fallback from "Commands you will need" if
host pytest is unavailable.

Then return to the repository root and run:

```bash
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors; only `app/templates/index.html` plus the plan
status row are part of the implementation. Do not stage unrelated or
pre-existing untracked files.

### Step 5: Perform desktop, mobile, hidden-state, and behavior review

Start the app with the normal local or Docker workflow. The root page can be
reviewed even if MAM is unavailable. To expose the filter row without a live
search, use browser developer tools only for visual review:

```javascript
document.getElementById('filterRow').hidden = false
```

At approximately 1100px desktop width, confirm:

- Search and filters share exactly one outer border, radius, background, and
  shadow.
- A single subtle divider separates the filter row; there is no gap or second
  card shadow between them.
- Query input remains flexible, search controls retain their order, filter
  format fills remaining space, and minimum seeders remains compact.
- Hiding `#filterRow` removes the entire secondary row and divider, leaving a
  clean single-row panel.

At approximately 390px mobile width, confirm:

- The unified panel has one outer border/shadow around both stacked sections.
- Search and filter controls fill the available width consistently; minimum
  seeders no longer occupies a narrow partial row.
- No control overlaps, clips, or creates horizontal page scrolling.

If a configured search is available, also confirm Search still performs one
request, filter inputs re-render existing results without another request, and
Clear resets all three filters. If external MAM access is unavailable, do not
block solely on that service: the unchanged `app.js`, structural probe, and
manual hidden-attribute toggle cover the layout contract.

Capture temporary desktop and mobile screenshots for review/PR evidence per
`AGENTS.md`. Do not commit them unless the maintainer asks.

### Step 6: Update status only after acceptance gates pass

After all automated checks and both viewport reviews pass, change Plan 039's
status in `plans/README.md` from `TODO` to `DONE`. If either viewport still
looks like two cards, if the filter divider remains while hidden, or if the
mobile seeders field remains partial-width, do not mark DONE.

## Test plan

- No permanent test file is required for a template-local CSS restructure;
  adding a DOM framework would be disproportionate and violates scope.
- Run the Step 1 source contract to prove the two rows are siblings in one
  panel and filters remain outside the form.
- Run the Step 2 contract to prove one element owns card chrome and the old
  duplicated `.row` surface is gone.
- Run the Step 3 contract to prove mobile controls use the intended selectors
  and seeders becomes full width.
- Run existing syntax checks and all 79 pytest tests.
- Manually review hidden/visible states at desktop and mobile widths, with
  temporary screenshots.
- Where MAM is configured, smoke-test Search, all three filters, and Clear; do
  not require external service access solely for CSS acceptance.

## Done criteria

- Search and filters are direct sibling rows inside one `.search-filter-panel`.
- Only the shared parent owns border, radius, background, and shadow.
- The visible filter row uses one subtle internal divider and no second card
  chrome; the divider disappears with the hidden row.
- `#filterRow` remains outside `#searchForm`; all IDs, input types, control
  order, placeholders, and JavaScript behavior are unchanged.
- Desktop layout remains compact and mobile controls, including minimum
  seeders, fill the available width without page overflow.
- Structural contract probes, syntax checks, 79 tests, `git diff --check`, and
  both viewport reviews pass.
- Only in-scope files are modified and the Plan 039 index row is DONE.

## STOP conditions

- The drift check shows search/filter markup or responsive rules no longer
  match the excerpts.
- Achieving a unified visual panel requires moving filters inside the form or
  changing `app.js` submission/filter behavior.
- The target requires a new component framework, CSS dependency, or build step.
- A source-contract, syntax, or existing pytest check fails twice after a
  reasonable in-scope correction.
- A pre-existing worktree change overlaps `app/templates/index.html` and its
  ownership cannot be established.
- Desktop or mobile acceptance reveals that the single-wrapper approach needs
  a broader redesign of page structure or global styles; stop and report rather
  than editing `common.css` or unrelated UI.

## Maintenance notes

- Keep search and filter rows as siblings. Their shared panel is visual
  grouping, not permission to combine server-search submission with local
  result filtering.
- Future controls should be classified as search inputs (inside the form) or
  filters of already-loaded results (inside `#filterRow`) before placement.
- If these page-local control surfaces are reused on another page, that is the
  point to extract a shared component into `common.css`; doing so now would be
  premature.
- Repository screenshots remain intentionally unchanged by this plan. Refresh
  them in a separate documentation change when a configured representative
  dataset is available.
