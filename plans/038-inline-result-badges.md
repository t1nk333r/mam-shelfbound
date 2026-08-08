# Plan 038: Keep all result badges in one shared row

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update this plan's status row in
> `plans/README.md` unless a reviewer explicitly owns the index update.
>
> **Drift check (run first)**:
> `git diff --stat 09f76cb..HEAD -- app/static/app.js app/templates/index.html`
> If either file changed, compare the "Current state" excerpts with live code.
> Stop if the title-cell rendering or `.result-flags` contract no longer
> matches this plan.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — presentation-only DOM restructuring with unchanged data and actions
- **Depends on**: 036 (DONE; introduced `in_library` and its badge)
- **Category**: bug
- **Planned at**: commit `09f76cb`, 2026-08-08

## Why this matters

Search results can display Freeleech, VIP, history, and library state. The
title renderer puts Freeleech and VIP in one flex row, but the row builder
appends history and library as separate `.result-flags` blocks. Consequently,
"In library" starts another line instead of sitting beside the other tags.

All badges describe the same result and belong to one logical group. This plan
makes the title cell own that group, so badges share a row when space permits
and wrap together naturally on small screens.

## Current state

- `app/static/app.js:228-240` assembles each search result. The title `<td>`
  currently concatenates three independently rendered fragments:

  ```javascript
  tr.innerHTML = `
    <td>${renderResultTitleCell(it)}${renderInHistoryBadge(it)}${renderInLibraryBadge(it)}</td>
    <!-- remaining cells unchanged -->
  `;
  ```

- `app/static/app.js:248-258` gives each status badge its own block wrapper:

  ```javascript
  function renderInHistoryBadge(item) {
    const status = historyMamIds.get(String(item?.id ?? ''));
    if (!status) return '';
    const label = status === 'import_failed' ? 'In history (failed)' : 'In history';
    return `<div class="result-flags"><span class="result-badge result-badge-history">${escapeHtml(label)}</span></div>`;
  }

  function renderInLibraryBadge(item) {
    if (!item?.in_library) return '';
    return `<div class="result-flags"><span class="result-badge result-badge-library">In library</span></div>`;
  }
  ```

- `app/static/app.js:302-321` already collects Freeleech and VIP spans and
  conditionally renders one `.result-flags` inside `.result-title-cell`:

  ```javascript
  const badgesHtml = badges.length
    ? `<div class="result-flags">${badges.join('')}</div>`
    : '';
  ```

- `app/templates/index.html:101-104` already has the correct layout rules:

  ```css
  .result-title-cell { display:flex; flex-direction:column; gap:0.35rem; }
  .result-title-main { font-weight:600; }
  .result-flags { display:flex; gap:0.35rem; flex-wrap:wrap; }
  ```

  Do not change these rules. `flex-wrap: wrap` is intentional: "same row" means
  one logical flex container, not forced overflow on narrow displays.

There is no frontend test framework or DOM dependency in this repository.
Use the dependency-free Node contract probe in the test plan to exercise the
real rendering functions; do not add a framework for this fix.

## Scope

**In scope**:

- `app/static/app.js` — return status badge spans, collect them with Freeleech
  and VIP, and make the title cell render the sole `.result-flags` wrapper.
- `plans/README.md` — change plan 038's status only after implementation and
  verification.

**Out of scope**:

- `app/templates/index.html`, `app/static/common.css`, and all badge styling.
- Backend search/library/history logic, JSON fields, database schema, and API
  contracts.
- Badge text, colors, visibility rules, or semantic order beyond placing the
  existing badges together.
- Add-button behavior, filters, sorting, and History-table rendering.
- A frontend framework, DOM library, snapshot dependency, or permanent test
  harness.
- Committing generated screenshots. Capture a review screenshot or GIF as
  required by `AGENTS.md`, but commit it only if the maintainer asks.
- `app/static/logo-white.svg`; that separately requested asset is not needed to
  correct the badge DOM and must not be wired into the badge in this plan.

## Git workflow

- Branch: `advisor/038-inline-result-badges`
- Use one focused commit, for example `Group result badges in one row`.
- Do not push or open a PR unless the operator explicitly instructs it.

## Steps

### Step 1: Make the status helpers return spans

In `renderInHistoryBadge`, preserve the `historyMamIds` lookup, the
`import_failed` label, and HTML escaping. Change only the returned markup so the
helper returns its `<span class="result-badge result-badge-history">` without a
`.result-flags` wrapper.

In `renderInLibraryBadge`, preserve the `in_library` guard and label. Return
only `<span class="result-badge result-badge-library">In library</span>`.

Both helpers must still return `''` when their badge does not apply. Do not
rename the helpers or change their inputs.

### Step 2: Give `renderResultTitleCell` ownership of every badge

After its existing Freeleech and VIP checks, call both status helpers and append
each non-empty returned span to the same `badges` array. Preserve this display
order:

1. Freeleech
2. VIP
3. In history / In history (failed)
4. In library

Keep the existing conditional `badgesHtml` construction. It should emit one
`.result-flags` wrapper when at least one badge applies and no wrapper when no
badges apply.

Then change the result-row title cell to render only:

```javascript
<td>${renderResultTitleCell(it)}</td>
```

Do not add a second wrapper, move the title outside `.result-title-cell`, or
change any other table cell.

The resulting structure for an item with every badge must be equivalent to:

```html
<td data-label="Title">
  <div class="result-title-cell">
    <div class="result-title-main">Dungeon Crawler Carl</div>
    <div class="result-flags">
      <span class="result-badge result-badge-free">Freeleech</span>
      <span class="result-badge result-badge-vip">VIP</span>
      <span class="result-badge result-badge-history">In history</span>
      <span class="result-badge result-badge-library">In library</span>
    </div>
  </div>
</td>
```

### Step 3: Run static and rendering-contract checks

Run:

```bash
node --check app/static/app.js
```

Expected: exit 0 with no syntax error.

Then run this dependency-free probe against the actual functions in
`app/static/app.js`:

```bash
node <<'NODE'
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('app/static/app.js', 'utf8');

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notStrictEqual(start, -1, `missing ${name}`);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unterminated ${name}`);
}

const context = {
  historyMamIds: new Map([
    ['42', 'imported'],
    ['43', 'import_failed'],
  ]),
};
vm.createContext(context);
vm.runInContext([
  'escapeHtml',
  'renderInHistoryBadge',
  'renderInLibraryBadge',
  'renderResultTitleCell',
].map(extractFunction).join('\n'), context);

const allBadges = context.renderResultTitleCell({
  id: '42',
  title: 'Dungeon Crawler Carl',
  is_freeleech: true,
  is_vip: true,
  in_library: true,
});
assert.strictEqual((allBadges.match(/class="result-flags"/g) || []).length, 1);
const flags = allBadges.match(/<div class="result-flags">([\s\S]*?)<\/div>/)?.[1] || '';
for (const label of ['Freeleech', 'VIP', 'In history', 'In library']) {
  assert.ok(flags.includes(label), `${label} is outside the shared badge row`);
}
assert.ok(
  flags.indexOf('Freeleech') < flags.indexOf('VIP') &&
  flags.indexOf('VIP') < flags.indexOf('In history') &&
  flags.indexOf('In history') < flags.indexOf('In library'),
  'badge order changed',
);

const noBadges = context.renderResultTitleCell({ id: '44', title: 'Plain result' });
assert.strictEqual((noBadges.match(/class="result-flags"/g) || []).length, 0);

const failedHistory = context.renderResultTitleCell({ id: '43', title: 'Retry me' });
assert.strictEqual((failedHistory.match(/class="result-flags"/g) || []).length, 1);
assert.ok(failedHistory.includes('In history (failed)'));
NODE
```

Expected: exit 0 with no output. Before this fix, the first label-group
assertion fails because history and library are outside the title renderer's
shared wrapper.

Do not commit this probe as a test file; it is a narrow verification substitute
for the frontend harness the project does not have.

### Step 4: Run the existing regression suite

From the repository root, run:

```bash
cd app && python -m pytest -q
```

Expected at the planning baseline: **79 passed**. This change is frontend-only,
but the existing backend suite must remain green.

If the host environment lacks pip or pytest, use the project's known-good
ephemeral Python 3.12 fallback from the repository root:

```bash
docker run --rm -v "$PWD":/repo -w /repo python:3.12-slim sh -lc '
set -e
python -m pip install -q -r requirements.txt -r requirements-dev.txt
cd app
python -m pytest -q
'
```

Do not add or upgrade dependencies to make this plan pass.

### Step 5: Verify visually at desktop and narrow widths

Start the app using the repository's normal development or Docker workflow and
load search results that exercise as many badge combinations as possible.

At desktop width, inspect the title `<td>` in browser developer tools and
confirm:

- `.result-title-cell` contains the title and exactly one `.result-flags` child.
- The title `<td>` has no direct-child `.result-flags` sibling.
- Freeleech, VIP, history, and library badges sit in the same visual row when
  available width permits.
- Items with no badges render no empty badge row.

At a narrow/mobile width, confirm the badges may wrap but stay within the same
flex container and do not overflow the table/card. Exercise an
`import_failed` history item and confirm its label is unchanged.

Capture one screenshot or short GIF showing the corrected layout for the
implementation review/PR description, per `AGENTS.md`. Do not commit the
artifact unless instructed.

### Step 6: Final checks and status update

Run from the repository root:

```bash
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors; only `app/static/app.js` plus the plan status
row are part of the implementation commit. Do not include unrelated or
pre-existing untracked files.

After every automated and visual check passes, change plan 038's status in
`plans/README.md` from `TODO` to `DONE`. If live visual verification is not
available, leave it `TODO` or mark it `BLOCKED` with that one-line reason; do
not claim completion from static checks alone.

## Test plan

- JavaScript syntax: `node --check app/static/app.js` exits 0.
- Rendering contract: the Node probe proves one wrapper for all badge types,
  zero wrappers for no badges, preserved ordering, and the failed-history
  label.
- Regression: the existing pytest suite passes (79 tests at plan time).
- Manual desktop: all applicable badges share one row when space permits.
- Manual narrow viewport: badges wrap within the same container without
  overflow.
- DOM inspection: no `.result-flags` exists as a direct sibling after
  `.result-title-cell`.
- Hygiene: `git diff --check` passes and no unrelated files enter the commit.

## Done criteria

- Freeleech, VIP, history, and library spans are rendered inside one shared
  `.result-flags` container owned by `renderResultTitleCell`.
- "In library" no longer creates a separate logical row.
- The existing badge conditions, text, classes, order, and responsive wrapping
  are preserved.
- No backend, CSS, template, dependency, or API change is introduced.
- All automated and visual checks pass and the index status is updated.

## STOP conditions

- `app/static/app.js` or `app/templates/index.html` has drifted so the current
  renderer/CSS excerpts no longer apply.
- Plan 036's `in_library` field or `renderInLibraryBadge` has been removed or
  materially redesigned.
- Correct placement would require changing backend data, badge semantics, or
  Add-button behavior.
- The Node probe or existing pytest suite fails for reasons not caused by this
  focused edit.
- The change requires a new runtime or test dependency.
- A pre-existing worktree change overlaps an in-scope line and its ownership
  cannot be established.

## Maintenance notes

- Future result badges should return a span (or another wrapper-free fragment)
  and be appended to `renderResultTitleCell`'s `badges` array. Do not create a
  sibling `.result-flags` block in `buildResultRow`.
- Keep `flex-wrap: wrap`; it is the responsive behavior, not the cause of this
  bug.
- If result markup later moves to a component/template system, preserve the
  invariant of one badge-group container per title cell and replace the
  temporary Node probe with a permanent DOM test in that system.
