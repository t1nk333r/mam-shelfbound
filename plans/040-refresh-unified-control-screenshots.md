# Plan 040: Refresh README screenshots after unified controls ship

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update this plan's status row in
> `plans/README.md` unless a reviewer explicitly owns the index update.
>
> **Drift check (run first)**:
> `git diff --stat 98e25d9..HEAD -- app/static/screenshots/finder_desktop.png app/static/screenshots/finder_mobile.png`
> Plan 039 may change the template after this plan's baseline, but it must not
> change these screenshot files. If either PNG drifted, stop and reconcile this
> plan before replacing it; do not overwrite another screenshot refresh.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW — documentation-only binary asset replacement
- **Depends on**: Plan 039 DONE, merged to the default branch, pushed, and available in a successful published/deployed build
- **Category**: docs
- **Planned at**: commit `98e25d9`, 2026-08-08

**Execution attempt 2026-08-08 — BLOCKED before dispatch:** Docker Publish run
`31275335337` completed successfully for `e06d66c`, but the operator-provided
deployment at `http://10.10.10.9:8090/` still returned
`<form id="searchForm" class="row">` and no `search-filter-panel` marker.
This matches the Step 1 STOP condition. No executor was dispatched and no
screenshot asset was changed. Redeploy/recreate the service from the newly
published image, then rerun this plan.

**Retry 2026-08-08 — gate cleared:** the same deployment now returns both the
`.search-filter-panel` style and unified-panel markup. Execution may proceed in
an isolated worktree.

**Executed and reviewed 2026-08-08 — verdict APPROVE:** Luna captured the live
published UI in isolated worktree `/tmp/mam-audiofinder-plan040-luna`, branch
`advisor/040-refresh-unified-control-screenshots`, commit `d5ec83b`. The commit
changes exactly the two intended PNGs. Desktop is 2400×1560 (362,062 bytes)
and mobile is 1290×2796 (248,556 bytes); both pass PNG signature, size,
metadata, chunk-structure, README-link, scope, and diff-hygiene checks.

Review required one revision because the first captures included Chromium's
vertical scrollbar gutter and arrow controls. Luna recaptured both viewports
with browser scrollbars hidden and amended the focused commit. Original-detail
inspection of the final images confirms the shared search/filter panel,
full-width mobile seeders field, sanitized account line, consistent live search
state, intact result badges, and absence of History, host details, credentials,
focus artifacts, DevTools, and browser chrome. The executor worktree is clean;
merging remains the maintainer's decision.

## Why this matters

The README is the project's first visual explanation, but its desktop and
mobile screenshots show the old search and filter controls as two heavy,
separate cards. After Plan 039 ships one unified control panel, retaining those
images advertises a UI that no longer exists. Refreshing both views from the
actual published build keeps documentation honest and provides visual proof
that the desktop and mobile layouts landed correctly.

## Current state

- `README.md:5-10` embeds two stable paths in a comparison table:

  ```markdown
  | Desktop | Mobile |
  | --- | --- |
  | ![Desktop screenshot](app/static/screenshots/finder_desktop.png) | ![Mobile screenshot](app/static/screenshots/finder_mobile.png) |
  ```

  Preserve these paths; the README itself does not need an edit.

- Current asset properties at commit `98e25d9`:

  | File | Pixels | Approx. size | Visible problem |
  |---|---:|---:|---|
  | `app/static/screenshots/finder_desktop.png` | 2400×1560 | 338 KB | search and filters have separate outer borders/shadows |
  | `app/static/screenshots/finder_mobile.png` | 1290×2796 | 253 KB | duplicated stacked cards; seeders field is partial width |

  Keep these exact pixel dimensions so the README comparison does not change
  aspect ratio or layout. Capture targets are therefore:

  - Desktop: 1200×780 CSS-pixel viewport at device scale factor 2.
  - Mobile: 430×932 CSS-pixel viewport at device scale factor 3.

- The images were last refreshed in commit `f587737`; no capture script or
  browser-automation dependency exists. This plan uses the browser/DevTools
  already available to the executor and does not add screenshot tooling to the
  repository.

- `.dockerignore` explicitly excludes `app/static/screenshots/`. The PNGs are
  documentation assets referenced by GitHub's README renderer, not files
  shipped in the application image. A screenshot-only commit therefore does
  not require another application image build.

- Plan 039's accepted DOM invariant is one `.search-filter-panel` containing
  sibling `#searchForm` and `#filterRow`. Its desktop result has one outer
  border/shadow and one internal divider. At mobile width all filter controls,
  including `#filterMinSeeders`, fill the panel content width.

### Privacy boundary

Never capture browser chrome, the address bar, cookies, developer tools,
History rows, local hostnames, credentials, or real account-specific balances.
The MAM cookie is not rendered by the page and must not be copied into commands,
the plan, image metadata, commit messages, or reports. Use the existing public
documentation sample values for the account line:

```text
Freeleech wedges: 8 · Bonus points: 152,340
```

Search-result book metadata for the safe representative query below is allowed;
download history and operator-specific configuration are not.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Confirm README links | `rg -n "finder_desktop\.png|finder_mobile\.png" README.md` | exactly the two existing image references |
| Confirm Plan 039 source | `rg -n "search-filter-panel|control-row" app/templates/index.html` | unified-panel markup/styles present |
| Confirm deployed build | `curl -fsS "${SCREENSHOT_BASE_URL%/}/" \| rg -n "search-filter-panel"` | deployed HTML contains the unified panel |
| Inspect PNGs | use `view_image` on both final files at original detail | both visually pass Step 5 |
| Hygiene | `git diff --check` | exit 0 |

There is no need to install dependencies, rebuild the image, or run the Python
test suite for a two-PNG documentation-only replacement. The published build
is a prerequisite, not something this plan creates.

## Scope

**In scope**:

- `app/static/screenshots/finder_desktop.png` — replace with the verified
  desktop capture.
- `app/static/screenshots/finder_mobile.png` — replace with the verified mobile
  capture.
- `plans/README.md` — status update only after both images pass review.

**Out of scope**:

- `README.md` — filenames, table structure, and alt text remain correct.
- `app/templates/index.html`, `app/static/app.js`, `app/static/common.css`, and
  all application behavior/styles. If the published page looks wrong, fix or
  redeploy Plan 039 first; do not retouch the UI while capturing docs.
- Any screenshot under `app/static/screenshots/` other than the two named
  finder assets, including `search.png`.
- Browser automation scripts, new packages, fixture data, or committed capture
  tooling.
- Editing, mocking, or exposing secrets/configuration to make MAM search work.
- History screenshots, browser chrome, DevTools, or deployment dashboards.
- Changing image dimensions, file format, filenames, or README references.

## Git workflow

- Branch: `advisor/040-refresh-unified-control-screenshots`
- Use one documentation-only commit, for example
  `Refresh unified control screenshots [skip ci]`.
- `[skip ci]` is appropriate because `.dockerignore` excludes the assets and no
  application/test source changes.
- Do not push or open a PR unless the operator explicitly instructs it.

## Steps

### Step 1: Prove the new UI is merged, published, and reachable

Do not start capture merely because Plan 039's index row says DONE. Verify all
of the following:

1. The current branch contains Plan 039's merged implementation and
   `app/templates/index.html` contains `.search-filter-panel` and
   `.control-row`.
2. The Plan 039 commit has been pushed and its Docker Publish workflow
   completed successfully.
3. The operator provides the base URL of a reachable deployment running that
   build. Keep it in an ephemeral shell variable only:

   ```bash
   export SCREENSHOT_BASE_URL="<operator-provided deployed URL>"
   ```

   Do not commit the value. Do not put credentials in the URL.

4. The deployed HTML proves it is the new build:

   ```bash
   test -n "$SCREENSHOT_BASE_URL"
   curl -fsS "${SCREENSHOT_BASE_URL%/}/" | rg -n "search-filter-panel"
   ```

Expected: one or more matching lines from the deployed HTML. A successful
workflow alone is insufficient if the running service still serves the old
markup. STOP if the URL is unavailable, requires credentials in the URL, or
does not contain the unified panel.

### Step 2: Prepare one representative, privacy-safe page state

Open the deployed app at 100% browser zoom with its default dark theme. Use
these controls so the two screenshots show the same recognizable workflow as
the existing assets:

- Query: `watership down`
- Media type: Audiobooks
- Results per page: 25
- Format filter: empty
- Minimum seeders: empty
- Freeleech only: unchecked
- History panel: hidden
- Scroll position: top of page

Submit Search and wait until results, account refresh, history lookup, and
layout have settled. The visible filter row must be inside the unified panel.
If the external MAM search fails or returns no representative results, STOP;
do not fabricate a UI fixture because the user requested screenshots of the
published build.

Before capture, open DevTools only long enough to sanitize operator-specific
state and then close it. Run:

```javascript
document.getElementById('accountStatus').textContent =
  'Freeleech wedges: 8 · Bonus points: 152,340';
document.getElementById('historyCard').style.display = 'none';
window.scrollTo(0, 0);
```

Click a non-interactive blank area so no field has a focus ring, selection,
tooltip, or text caret. Wait one additional second. Do not alter result data,
badge state, or the unified control layout.

### Step 3: Capture and replace the desktop asset

Use browser device emulation (or equivalent headless settings) with:

- CSS viewport: 1200×780
- Device scale factor: 2
- Browser zoom: 100%
- Capture: visible viewport only, without browser chrome
- Output: temporary PNG outside the repository first

The temporary image must be exactly 2400×1560 pixels. Visually inspect it
before replacing the tracked asset, then copy/move the accepted PNG to:

`app/static/screenshots/finder_desktop.png`

Do not resize a capture from another viewport; recapture at the correct device
metrics so text and responsive breakpoints remain genuine.

### Step 4: Capture and replace the mobile asset

Restore the same page state from Step 2, then use:

- CSS viewport: 430×932
- Device scale factor: 3
- Browser zoom: 100%
- Capture: visible viewport only, without browser chrome
- Output: temporary PNG outside the repository first

The temporary image must be exactly 1290×2796 pixels. Replace:

`app/static/screenshots/finder_mobile.png`

Do not crop a desktop capture. The mobile image must be rendered at the real
mobile breakpoint and visibly show the full-width minimum-seeders control.

### Step 5: Validate dimensions, metadata, content, and scope

Run this dependency-free PNG validator from the repository root:

```bash
python <<'PY'
from pathlib import Path
import struct

expected = {
    Path("app/static/screenshots/finder_desktop.png"): (2400, 1560),
    Path("app/static/screenshots/finder_mobile.png"): (1290, 2796),
}
for path, dimensions in expected.items():
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path}: not PNG"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == dimensions, (
        f"{path}: expected {dimensions}, got {(width, height)}"
    )
    assert 50_000 <= len(data) <= 2_000_000, f"{path}: implausible size"

    offset = 8
    text_chunks = []
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        if chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
            text_chunks.append(chunk_type.decode("ascii"))
        offset += 12 + length
    assert not text_chunks, f"{path}: textual metadata present: {text_chunks}"
PY
```

Expected: exit 0 with no output.

Then inspect both tracked files with `view_image` at original detail. Confirm:

- Both show the same safe query and representative results.
- Search and filters share one outer panel, with one subtle divider and no
  second card border/shadow.
- Desktop controls remain compact and aligned.
- Mobile search/filter controls are full width; minimum seeders is not a narrow
  partial row; there is no page-level horizontal overflow.
- The current result badge layout is intact.
- Account text exactly matches the sanitized sample.
- History, browser chrome, DevTools, hostnames/IPs, notifications, tooltips,
  focus rings, and credentials are absent.
- Text is crisp at original detail and neither capture is stretched/cropped.

If either image fails, recapture it; do not repair screenshots with image
editing or paint over sensitive content.

### Step 6: Verify documentation links and commit only the two PNGs

Run:

```bash
rg -n "finder_desktop\.png|finder_mobile\.png" README.md
git diff --check
git diff --stat
git status --short
```

Expected:

- README still contains the two existing paths.
- Exactly the two screenshot PNGs (plus the plan status row when executor-owned)
  are modified.
- Both binary files differ from `HEAD`; the diff stat reports binary changes.
- No temporary capture, browser profile, source file, secret, or unrelated
  untracked file is staged.

After all visual and machine checks pass, change Plan 040's index status from
TODO to DONE and commit with the documentation-only message from "Git workflow".

## Test plan

- No application tests are required because only two `.dockerignore`d PNG
  documentation assets change.
- Gate execution on the deployed HTML containing Plan 039's
  `search-filter-panel` marker.
- Validate exact PNG signature, dimensions, reasonable size, and absence of
  textual metadata with the Step 5 script.
- Visually inspect both images at original resolution against every listed
  privacy and layout invariant.
- Confirm README references resolve and only the two intended assets/status row
  changed.

## Done criteria

- Plan 039 is merged, pushed, successfully published, and the captured service
  proves it is serving unified-panel markup.
- Desktop PNG is a genuine 1200×780@2x viewport capture (2400×1560).
- Mobile PNG is a genuine 430×932@3x viewport capture (1290×2796).
- Both captures show one unified search/filter panel and the mobile seeders
  field at full width.
- Both use sanitized account values and contain no History, browser chrome,
  host details, credentials, or textual PNG metadata.
- README paths remain unchanged and valid.
- Only the two PNGs and the Plan 040 status row are modified.
- Machine validation, original-detail visual inspection, and diff hygiene pass.

## STOP conditions

- Plan 039 is not merged/pushed, its publish workflow failed, or the deployed
  HTML lacks `search-filter-panel`.
- No safe operator-provided deployment URL is available.
- The MAM search cannot produce a stable representative result state.
- Either screenshot asset drifted since `98e25d9`; another refresh may already
  own it.
- Exact viewport/DPR capture is unavailable or produces the wrong dimensions.
- Sensitive/operator-specific content cannot be removed before capture.
- The screenshots reveal a Plan 039 layout regression; fix/redeploy that plan
  instead of documenting the broken state.
- Capturing requires application source changes, new dependencies, committed
  automation, or editing files outside scope.

## Maintenance notes

- Keep these filenames stable because README links them directly.
- Repeat this workflow after future material UI changes; small backend-only
  releases do not require screenshot churn.
- Screenshot assets remain excluded from Docker context, so docs-only refreshes
  should use `[skip ci]` unless CI policy changes.
- Never normalize a bad capture with post-processing. Correct the browser state,
  viewport, or deployed UI and recapture.
