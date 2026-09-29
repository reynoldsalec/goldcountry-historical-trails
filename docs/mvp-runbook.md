# Auburn Map Browser — MVP Testing Runbook

**Status: acceptance instructions, not passed results.** This replaces the countywide
research checklist as the next MVP's release gate. The viewer and demo Make targets are
planned, not implemented by this document. Do not mark checks passed until exercised.

## 1. What you are testing

> Zoom into one place, page through four map editions without losing your position,
> and see exactly which source you are viewing.

You are not deciding whether a road was a foot trail or whether public access exists.
You do not need to research both counties, digitize a trail, obtain new aerials, or pass
`coverage-ready` to evaluate this demo.

Expected sequence:
1. 1953 topographic base map — `CA_Auburn_288101_1953_24000`.
2. 1973 photorevision — `CA_Auburn_288103_1953_24000`.
3. 1975 aerial orthophotoquad — `CA_Auburn_288104_1975_24000`.
4. 1981 photorevision — `CA_Auburn_288105_1953_24000`.

## 2. Preparation and honest status

From the repository root, the following existing baseline commands work today:

```sh
make lint
make test-validation
make test-topo
make test-coverage
make validate
```

Stop on a genuine validation failure. A documented research gap is allowed; it is not
an excuse to change inventory states. Current raster/viewer/public-build placeholders
are not evidence of a runnable demo.

**After D1–D4 implement the targets**, run:

```sh
make demo-check
make demo-rasters
make demo-test
make demo-build
make demo-accept
make demo-dev
```

These are future commands, not instructions to bypass today's missing implementation.
`demo-accept` must validate real built output, not an absent public directory. Record the
actual URL printed by the development server; do not assume a fixed port. A local HTTP
server is required; opening the viewer with `file://` is not the acceptance test.

## 3. Source and raster checks

- [ ] All four selected inputs match receipt hashes/byte counts; no raw file changed.
- [ ] Source IDs match the expected variants, not duplicate prints with different stamps.
- [ ] Dates and attribution match the scanned margins and source index.
- [ ] 1975 is labeled aerial/orthophotoquad, not a topographic line-map revision.
- [ ] The 1973 and 1981 labels disclose the 1953 base and non-field-checked revisions.
- [ ] 1981 card names 1978 photography and other source data; no universal 1981 claim.
- [ ] Common mapped crop excludes page decoration without erasing white map areas.
- [ ] Orientation is north-up, XYZ tile rows are not vertically flipped, and map labels
  are legible at useful zooms. Empty coverage has a deliberate no-data appearance.
- [ ] At least three dispersed stable landmarks have recorded inter-edition offsets
  and a fit-for-comparison decision. Unresolved datum errors fail; genuine source
  registration limitations are disclosed. No arbitrary warping to align changed features.
- [ ] Processing versions, selected hashes, tile counts and output bytes are recorded.
- [ ] Rerunning preparation preserves raw hashes and produces equivalent map outputs.

## 4. Main browser walkthrough

Use a desktop browser first. Repeat the essential sequence in a narrow viewport.

| Action | Expected behavior |
| --- | --- |
| Open a fresh page | Auburn shared footprint, 1953 layer, matching source card and attribution |
| Pan and zoom to a landmark | Readable detail; map stays usable within the selected footprint |
| Next through 1973, 1975, 1981 | Same center, zoom, bearing and pitch; only edition changes |
| Previous back to 1953 | Same location throughout; expected reverse sequence |
| Choose 1981 then 1973 directly | Direct selection works without a camera reset |
| First/last edition | Previous/Next disabled respectively; no wraparound |
| Reset view | Explicitly returns to shared Auburn extent, not triggered by edition changes |
| Open the source information | Correct title, identifier, dates, caveat, USGS attribution and original link |
| Reload | Predictable default 1953 view; no browser-storage persistence |

Automated tests compare settled switch camera state to its starting values within
1e-7 degrees / 1e-6 zoom units, excluding deliberate user movement. Manual comparison
still matters: geographic source misregistration and a moving camera are different bugs.

## 5. Slow, failed and rapid switching

Use browser network throttling and request blocking; do not damage real source files.

- [ ] Under throttling, the previous visible raster retains its matching card until the
  requested viewport is ready. The pending edition is explicitly labeled as loading.
- [ ] Block one edition's tile request. The UI reports failure and keeps the last valid
  edition/card; it never silently labels old pixels as the requested edition.
- [ ] Unblock and retry. The requested edition loads without resetting the camera.
- [ ] Rapidly switch among all editions. Late responses never override the final choice.
- [ ] Pan/zoom while an edition is loading. Readiness follows the new viewport; no stale
  completion swaps in an incompletely loaded or wrongly labeled layer.
- [ ] A failure while panning an already selected edition is visible, not mistaken for
  historical no-data. Transparent coverage and failed network requests remain distinct.
- [ ] At the mapped boundary, no-data is neutral; it is not explained as missing trails.

## 6. Accessibility, network and public-output checks

- [ ] Tab reaches every edition control, source-card toggle and Reset; focus is visible.
- [ ] Enter/Space activates controls. Screen-reader names and loading/error announcements
  are meaningful. No interaction requires a swipe or precise mouse gesture.
- [ ] At 390px width and desktop width, controls and source information remain usable;
  no horizontal page overflow. Record browsers and viewports actually tested.
- [ ] App loads only same-origin code/styles/tiles; no third-party basemap or fonts,
  analytics, API calls, localStorage, sessionStorage, IndexedDB or service worker.
- [ ] Original-source links work when clicked; these intentional navigations are separate
  from background requests made by the viewer.
- [ ] `build/public/` contains only the allowlisted app, public edition metadata and
  four selected tile trees. No raw TIFFs, authoritative fixtures, receipts, research
  inventory, private paths, restricted records, or broad copied data directories.
- [ ] Existing restricted-value scanner runs against actual build output. Allowlist
  tests also pass; neither an empty tree nor a missing build is a release-safety check.
- [ ] Output size and load behavior are measured with the test environment recorded.
  No assumed “free hosting” or unmeasured performance promise.

## 7. Pass, block and handoff

Pass only when all four actual editions are usable, camera/state behavior is correct,
source/date information is honest, raw bytes are preserved, and all relevant automated
and manual checks above have recorded results. If a check fails, describe the failure
and affected step; do not expand scope to unrelated countywide research.

The local MVP handoff includes:
- Exact code commit, source IDs/hashes and processing manifest.
- Local URL / static build directory and reproducible commands.
- Test outputs, browser versions, screenshots and registration limitations.
- Tile count, disk size and observed loading behavior.
- Actual reviewer, review time, pass/block decision and remaining limitations.

A local pass is not a deployed site. Production hosting and a public URL require a
separate decision and host verification. No trail-history or countywide completion
claim is made by accepting this map browser.

## 8. Blank acceptance worksheet

Fill only after doing the work; placeholders are not evidence.

```text
Code revision:
Selected source IDs / receipt hashes:
Processing manifest / tool versions / output size:
Build and test commands / exit results:
Browser versions / viewports / local URL:
Stable landmarks / measured registration offsets / decision:
Edition paging and camera tests:
Slow-load / error / retry / rapid-switch tests:
Accessibility / network / public-output checks:
Screenshots / logs:
Known limitations / failed checks:
Actual reviewer / UTC review time:
Decision: PASS or BLOCK
```

For future countywide trail research only, see the retained
[M1 human runbook](m1-human-runbook.md). Its four-batch/aerial gate is not this checklist.
