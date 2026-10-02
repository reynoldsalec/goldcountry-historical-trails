# Auburn Map Browser — MVP Testing Runbook

**Status: acceptance instructions, not passed results.** This replaces the countywide
research checklist as the next MVP's release gate. Do not mark a check passed until you
have exercised it yourself.

D1–D4 and the nine-edition expansion (E1–E4, issues #55–#58) have landed, so the
commands below now run against nine editions. The automated half of this checklist has a
recorded result in [demo-acceptance.md](demo-acceptance.md); that record is machine
evidence, not a reviewer's decision, and it lists the checks here that a human still owes
(issue #38).

## 1. What you are testing

> Zoom into one place, page through nine map editions without losing your position,
> and see exactly which source you are viewing.

You are not deciding whether a road was a foot trail or whether public access exists.
You do not need to research both counties, digitize a trail, obtain new aerials, or pass
`coverage-ready` to evaluate this demo.

Expected sequence (approved 2026-09-29, issue #55). The viewer opens on the third, 1953:
1. Sacramento 1:125,000 sheet, 1891 — `CA_Sacramento_299588_1891_125000` (regional).
2. Auburn 1:62,500 sheet, 1944 — `CA_Auburn_296741_1944_62500` (15-minute).
3. 1953 topographic base map — `CA_Auburn_288101_1953_24000`.
4. 1973 photorevision — `CA_Auburn_288103_1953_24000`.
5. 1975 aerial orthophotoquad — `CA_Auburn_288104_1975_24000`.
6. 1981 photorevision — `CA_Auburn_288105_1953_24000`.
7. Sacramento 1:100,000 sheet, 1994 — `CA_Sacramento_299157_1994_100000` (regional).
8. Auburn 2018 US Topo map — ScienceBase `5d3aeb27e4b01d82ce8d133b`.
9. Auburn 2021 US Topo map — ScienceBase `61d7a9e2d34ed79294005276`.

The 1891 and 1994 editions are regional Sacramento sheets, not Auburn 7.5-minute maps.
They are tiled to zoom 14 and the 1944 sheet to zoom 15; the others to 16.

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
an excuse to change inventory states.

The demo needs the seven selected scans and the two US Topo PDFs. They are not in the
repository: point `DEMO_RAW_ROOT` at the directory holding them, or fetch them first with
`make fetch-topo-selected SELECTION=<file>` and `make expansion-fetch` (see
[demo-acceptance.md](demo-acceptance.md) §8). The pipeline only reads them.

```sh
export DEMO_RAW_ROOT=/path/to/data/raw   # unnecessary if data/raw is populated
make demo-accept     # demo-test, then demo-build, then validation of the built tree
```

`make demo-accept` is the whole gate: it runs the unit, browser, pipeline and expansion
suites, renders the two PDFs if needed, does the real nine-source build into
`build/public/`, and only then runs `make validate`, whose
restricted-value scan reads the tree that run just published. Bare `make` is the same
build and validation without the test suites. The single steps still exist for
diagnosis — `make demo-check`, `make demo-inspect`, `make demo-cogs`, `make demo-rasters`,
`make demo-test`, `make demo-build`, `make expansion-check`, `make expansion-pdf`.

Then serve the built output and open the URL you actually get:

```sh
cd build/public && python3 -m http.server 8317 --bind 127.0.0.1
```

A local HTTP server is required; opening the viewer with `file://` is not the acceptance
test. `make demo-dev` serves the source app on port 5173 instead, which is useful for
development but is not the published tree this checklist is about. Do not assume a port
is free; record the URL you used.

CI runs the same suites on synthetic fixtures only. It has no scans, so a green run says
nothing about the real editions.

## 3. Source and raster checks

- [ ] All nine selected inputs (seven TIFFs, two PDFs) match receipt hashes/byte counts;
  no raw file changed.
- [ ] Source IDs match the expected variants, not duplicate prints with different stamps.
- [ ] Dates and attribution match the scanned margins and source index.
- [ ] 1975 is labeled aerial/orthophotoquad, not a topographic line-map revision.
- [ ] The 1973 and 1981 labels disclose the 1953 base and non-field-checked revisions.
- [ ] 1981 card names 1978 photography and other source data; no universal 1981 claim.
- [ ] The 1891 and 1994 labels and cards name the Sacramento sheet and its scale
  (1:125,000, 1:100,000); the 1944 card names 1:62,500. None reads as an Auburn
  7.5-minute map.
- [ ] The 2018 and 2021 cards name the US Topo product, its publication date and the
  printed credit note verbatim; the hidden orthoimage layer is not shown.
- [ ] Common mapped crop excludes page decoration without erasing white map areas.
- [ ] Orientation is north-up, XYZ tile rows are not vertically flipped, and map labels
  are legible at useful zooms. Empty coverage has a deliberate no-data appearance.
- [ ] At least three dispersed stable landmarks have recorded inter-edition offsets
  and a fit-for-comparison decision. Unresolved datum errors fail; genuine source
  registration limitations are disclosed. No arbitrary warping to align changed features.
- [ ] Processing versions, selected hashes, tile counts and output bytes are recorded.
- [ ] Rerunning preparation preserves raw hashes and produces equivalent map outputs.

Expansion sources (E1). In a worktree, set `DEMO_RAW_ROOT` to the primary raw root.

- [ ] `make expansion-test` passes.
- [ ] `make expansion-fetch` run twice: the second run reports `present` for both PDFs
  and appends no receipt.
- [ ] `make expansion-check` reports all five as verified by full-file SHA-256. A range
  probe or response header is never enough.
- [ ] `retrievals.jsonl` is unchanged; the three reused TIFF receipts keep
  `retrieved_at: null`. Hashes of existing files under `data/raw/topo/` are unchanged.
- [ ] The printed credit note on each US Topo PDF matches `credit_note` in
  `data/sources/demo-pdf-sources.json` (a human confirms the agent transcription).
- [ ] Open processing blockers from `expansion-check` are listed in
  `docs/open-questions.md`, not hidden.
- [ ] PDF backup is not verified: `verify-backup` does not cover `data/raw/us-topo/`.

## 4. Main browser walkthrough

Use a desktop browser first. Repeat the essential sequence in a narrow viewport.

| Action | Expected behavior |
| --- | --- |
| Open a fresh page | Auburn shared footprint, 1953 layer, matching source card and attribution |
| Pan and zoom to a landmark | Readable detail; map stays usable within the selected footprint |
| Next through 1973 … 2021 | Same center, zoom, bearing and pitch; only edition changes |
| Previous back to 1891 | Same location throughout; expected reverse sequence |
| At zoom 15–16, choose 1891 or 1994 | Camera unchanged; sheet enlarged, not blank; card shows the detail-limit line |
| Choose 1981 then 1973 directly | Direct selection works without a camera reset |
| First/last edition | Previous disabled on 1891, Next on 2021; no wraparound |
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
  nine selected tile trees. No raw TIFFs or PDFs, authoritative fixtures, receipts,
  processing records, research inventory, private paths, restricted records, or broad
  copied data directories.
- [ ] Existing restricted-value scanner runs against actual build output. Allowlist
  tests also pass; neither an empty tree nor a missing build is a release-safety check.
- [ ] Output size and load behavior are measured with the test environment recorded.
  No assumed “free hosting” or unmeasured performance promise.

## 7. Pass, block and handoff

Pass only when all nine actual editions are usable, camera/state behavior is correct,
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

Fill only after doing the work; placeholders are not evidence. The technical half is
already filled in [demo-acceptance.md](demo-acceptance.md) §10 for one recorded run; the
reviewer, the review time and the decision are deliberately empty there.

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
