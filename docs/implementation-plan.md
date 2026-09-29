# Auburn Map Browser Implementation Plan

> **For Hermes:** Use subagent-driven-development for task-by-task implementation if
> requested; an explicitly authorized Looper run may instead use these same contracts.
> This revision is planning only. Do not start implementation from a documentation edit.

**Goal:** let a reader page through four Auburn map editions while remaining at exactly
the same location and zoom, with unambiguous dates and source attribution.

**Architecture:** immutable local GeoTIFFs are verified and converted offline into
same-origin XYZ PNG rasters on a shared Web Mercator grid. A single MapLibre map changes
raster edition without recreating the map or moving its camera. A clean allowlisted
public build contains only the viewer, sanitized edition metadata and selected tiles.

**Tech stack:** existing uv-managed Python, GDAL CLI, vanilla TypeScript, Vite,
MapLibre GL JS; Vitest for UI state and Playwright for browser acceptance. Pin all added
dependencies and record GDAL/PROJ versions. No React, backend, external basemap or storage.

**Status:** approved product direction recorded 2026-09-28; D1–D4 below are proposed
implementation work, not completed milestones. Existing M0/M1 tooling is retained.

---

## A. Decisions workers must not reopen independently

### Product boundary

Four editions, one shared Auburn quadrangle area. Initial edition is 1953; display
order is 1953, 1973, 1975 aerial, 1981. Previous/Next stop at endpoints. Direct selection
is supported. Reset view is separate and is the only edition-control action allowed
to fit bounds. Normal pan/zoom remains available, with north-up bearing and no pitch.
No trails or synthetic fixtures are displayed. Showing a raster does not assert that
its roads are trails or establish present-day access.

The full original quadrangle may include El Dorado context. Do not crop to a county
boundary merely to match the deferred countywide vector program. Use the shared mapped
footprint of these four sources, excluding decorative scan margins. Keep nodata explicit.

### Fixed input set

| Edition ID | Exact topo/source ID | Kind | Base | Revision | Photography | Field check |
| --- | --- | --- | --- | --- | --- | --- |
| auburn-1953 | CA_Auburn_288101_1953_24000 | topo | 1953 | null | 1952 | 1953 |
| auburn-1973 | CA_Auburn_288103_1953_24000 | topo | 1953 | 1973 | 1973 (revision); 1952 (base) | 1953 (base); revision not checked |
| auburn-1975 | CA_Auburn_288104_1975_24000 | orthophotoquad | null | null | 1975-08-29 | null |
| auburn-1981 | CA_Auburn_288105_1953_24000 | topo | 1953 | 1981 | 1978 (revision); 1952 (base) | 1953 (base); revision not checked |

Use these exact scan variants, not every identically named/reprinted sheet. The 1975
product is already georeferenced and is not a raw aerial requiring GCPs. The 1981 sheet
also cites other source data; its imagery year must not be presented as universal.
Source card wording must distinguish base versus revision and say revisions were not
field checked where applicable. Preserve the existing legal-framing safeguards.

### Manifest contract (to implement, not an existing file)

Create `data/sources/demo-editions.json`, checked by
`schema/demo-editions.schema.json`. No additional properties at any level.

Top-level keys:
- `version`: integer 1.
- `area_id`: literal `auburn`.
- `edition_order`: the four edition IDs above in that exact order.
- `view_bounds_wgs84`: ordered `[west, south, east, north]` derived from the common
  mapped footprint after datum transformation; never guessed from file labels.
- `tile_zoom`: object `{ "min": 10, "max": 16 }`.
- `editions`: array of exactly four edition objects, unique IDs/source IDs.

Each edition carries `id`, `source_id`, `kind` (`topo` or `orthophotoquad`), `label`,
`citation`, `source_url`, `rights` (literal `public_domain`), `attribution`, `dates`,
`date_note`, and `crop_wgs84` (a valid closed Polygon footprint verified against the
source neatline). Crops exclude borders only; they must not erase white map content.

`dates` has only `map_year` (1953, 1953, 1975, 1953 in display order),
`base_year` (nullable), `revision_year` (nullable), `base_photography` (nullable
YYYY or YYYY-MM-DD), `revision_photography` (nullable YYYY or YYYY-MM-DD),
`photography` (nullable, used for the orthophotoquad), `base_field_check_year`
(nullable), and `revision_field_checked` (nullable boolean). For both photorevisions
`revision_field_checked=false`; for non-revised products it is null. Null means unknown
or not applicable as explained by `date_note`, not ongoing presence. Actual calendar
validity is required. No automatic trail dating or inferred continuous intervals.

Resolve source bytes through `retrievals.jsonl` by source ID and verify hash/byte count;
reuse existing archive helpers rather than assuming legacy filenames. Fail on missing,
ambiguous or corrupt selected receipts/bytes before producing output. Unselected local
files are not necessary for a fresh MVP build. Do not modify receipt timestamps.

Internal `build/rasters/demo-processing.json` records exact source hashes, crop geometry,
tool versions, reprojection/resampling parameters, output digests, zoom range and size.
Public `build/public/editions.json` exports only display metadata, bounds, zoom limits,
and relative tile templates `tiles/<edition-id>/{z}/{x}/{y}.png`. It omits receipt paths,
private notes and processing host details. Do not copy the internal manifest wholesale.

### Raster and display contract

- Reproject to EPSG:3857 using source CRS/datum metadata. Record the transformation;
  never silently assume an unknown CRS. Use one shared output extent/grid.
- Source nearest-neighbor sampling for topo scans; cubic for aerial imagery. Preserve
  alpha/nodata. MapLibre raster resampling uses nearest for topo, linear for imagery.
- Produce XYZ (not TMS) PNG tiles for zooms 10–16. Do not confuse flipped Y conventions.
  Encode transparent tiles for empty portions of the bounded pyramid so blank areas
  are distinct from network failures. Do not use white-color transparency heuristics.
- Keep EPSG:3857 COG intermediates under `build/rasters/`, tiles under `build/tiles/demo/`.
  GDAL version and chosen tiler invocation are pinned/documented in D2. No vector tiles,
  PMTiles dependency, tile service or new download pipeline.
- One MapLibre instance. Edition selection must not call `fitBounds`, `jumpTo`, recreate
  the map, or change center/zoom/bearing/pitch. Camera state equality is tested.
- Track requested versus displayed edition separately. Until visible-viewport tiles
  for the requested edition are loaded, retain the prior edition and its matching card
  with an explicit loading notice. On success switch visibility and card together.
- Use request-generation IDs so late loads/errors from older selections cannot replace
  the current selection. A failed edition leaves the last valid layer/card displayed,
  with an explicit error and retry. Camera movement while loading restarts readiness
  for the current viewport. Failures during later pan/zoom remain visible warnings.
- Never flash another edition under a new label. No silent fallback, invented map years,
  blank success screens, false trail-access assertions or browser persistence.

## B. D1 — Edition contract and selected-source verification

**Dependencies:** none of the deferred research issues. Existing validation must remain
passing; missing selected bytes or unresolved rights/CRS are genuine blockers.

**Files:** create the manifest/schema above, `scripts/demo.py`, `scripts/test_demo.py`;
modify `Makefile` and dependency locks only as necessary. Record scan-margin locators
and actual source-card checks in `docs/demo-source-review.md` (do not invent reviewers).

1. Write isolated failing tests: wrong/missing/duplicate edition, unknown field,
   invalid date, nonpublic rights, inverted bounds, crop outside source, missing or
   mismatched receipt, checksum mismatch, and source-kind mismatch for 1975.
2. Add `make demo-check` calling `scripts/demo.py check` and `make demo-test` for the
   explicit Python test module. Record the expected failing test output before coding.
3. Implement source preflight using existing index/receipt helpers. No network access,
   source writes, inventory refresh or fake historical observation records.
4. Populate only values verified from the four inputs; derive crop/bounds from their
   georeferencing and inspect neatlines. If ambiguous, record the precise gap.
5. Run `make demo-test`, `make demo-check`, `make validate`, `make lint`. Record actual
   results and selected hashes. Separate data-only commits from code/docs commits.

**Accept:** exactly four verified public inputs with traceable dates and crops; tests
reject every listed invalid case. No claim that the manifest dates individual features.

## C. D2 — Reproducible raster preparation

**Depends on D1. Files:** create `scripts/warp_raster.py`,
`scripts/test_demo_rasters.py`, `docs/demo-processing.md`; extend `scripts/demo.py`,
`Makefile` and explicit `demo-test` modules. Reuse existing dependencies where possible.

1. Write failing tests using small synthetic georeferenced rasters for CRS transformation,
   common grid, XYZ orientation, alpha/nodata, resampling dispatch, missing GDAL, corrupt
   input and idempotent reruns. Fixtures remain outside authoritative source data.
2. Add `make demo-rasters`: preflight → COGs → bounded XYZ tiles → processing record.
   Fail atomically; do not advertise incomplete outputs. Pin/document GDAL prerequisites.
3. Implement read-only source processing, nearest/cubic separation and content-aware
   reuse keyed to input hashes plus processing parameters. Never overwrite raw inputs.
4. Run tests and build the real four-layer set. Compare source hashes before/after.
5. Inspect at least three dispersed stable landmarks across the shared footprint in all
   editions. Record pixel/metre offsets at fixed zoom, locations and fit-for-comparison
   decision; unresolved datum/systematic shifts block acceptance. Historical source
   error must be disclosed, not silently corrected with arbitrary GCPs.
6. Record tile count, output size, processing time, max useful zoom and label legibility.
   Read a known north/south tile to rule out TMS-Y inversion. Repeat build and verify
   deterministic source/processing manifests and equivalent outputs.

**Accept:** correct four raster pyramids, usable readable comparisons, documented
registration limitations and unchanged source hashes. Raw aerial acquisition is not needed.

## D. D3 — The edition browser

**Depends on D1/D2. Files:** `site/package.json`, lockfile, `site/index.html`,
`site/tsconfig.json`, `site/vite.config.ts`, `site/src/main.ts`, `site/src/style.css`,
`site/src/editions.ts`, `site/src/editions.test.ts`, `site/tests/editions.spec.ts`,
`site/playwright.config.ts`. No framework beyond Vite; self-host all dependencies.

1. Write failing unit tests for initial selection, fixed order, endpoint disabling,
   direct selection, loading/error state, stale response rejection and truthful cards.
2. Add the four sources/layers to one map. Use neutral empty background outside coverage,
   constrained pan bounds and zooms 10–16. Reset fits the shared area; switching does not.
3. Implement accessible native controls, loading/retry notices, source card and attribution.
   No gestures may be required to reveal essential dates. Small-screen card may collapse,
   but its toggle, selected edition and attribution remain reachable.
4. Add browser tests: zoom/pan, traverse all editions and back, direct jumps, fast clicks,
   pan during load, simulated tile errors, retry, endpoints, keyboard operation and
   narrow/desktop viewports. Assert camera equality within 1e-7 degrees and 1e-6 zoom
   units before/after settled switches with no concurrent user movement.
5. Add `make demo-dev` and integrate frontend unit/browser checks into `make demo-test`
   (small raster test fixtures for CI, never downloadable gigabyte production sources).
6. Run tests, then inspect real output at local static origin. Measure loading behavior;
   do not claim a speed guarantee without test-machine/network context.

**Accept:** actual source rasters, fixed camera, correct card/layer pairing, usable error
states and no network requests except same-origin app/tiles. Original citation links
navigate only when clicked. No localStorage, sessionStorage, IndexedDB or service worker.

## E. D4 — Public assembly, regression gate and local acceptance

**Depends on D1–D3. Files:** create `scripts/build_site.py`,
`scripts/test_demo_build.py`, `docs/demo-acceptance.md`; modify `Makefile`, CI and
`docs/mvp-runbook.md`. Extend `demo-test` explicitly to include all new test files.

1. Write failing build tests: missing layer, incomplete manifest, stale output injection,
   path traversal, extra unselected tiles and prohibited data copied into the build.
2. Implement `make demo-build`: selected preflight/raster preparation → Vite build into
   staging → copy only selected tile trees and sanitized public metadata → validate
   staged output and run restricted-value scanning → publish `build/public/` atomically.
   A stale build must never mask a failed build. No broad copy of `data/`, docs or raw files.
3. Add `make demo-accept`: `demo-test`, `demo-build`, then existing baseline validation
   against the newly built public tree. Keep CI's existing suites and add offline demo
   tests/build fixtures. The real four-source build/manual review is a separate recorded
   acceptance artifact, not falsely claimed by CI fixtures.
4. Replace `build-public`/`dev` placeholders with documented aliases to demo-build/demo-dev.
   Reorder default `make` so the public build exists before final validation. Preserve
   `tiles` and `build-restricted` as clearly deferred; update obsolete scaffold messages.
   Never remove or weaken `coverage-ready`; it remains the future countywide gate.
5. Run [the manual runbook](mvp-runbook.md) on actual output; record exact commit, source
   hashes, commands, browser versions, screenshots, sizes, registration and limitations.
6. Verify source restoration instructions: existing exact-ID downloader and real backup
   tools remain available. Independent-archive mount absence is documented, not relabeled
   as success. Do not make the entire countywide research archive an implicit demo gate.
7. Hand over a working localhost URL and build directory. Stop here: hosting/provider,
   quota, public URL and deployment are a separate approval, not part of acceptance.

**Accept:** functional static build and all source/privacy/browser checks pass. The owner
can page through all four actual editions. Manual approval is recorded by the actual
reviewer; test results alone do not manufacture approval. Nothing implies completed trails.

## F. Dispatch, rollback and old work

One focused PR per D-step, sequential. Split oversized steps into dependency-ordered
subtasks with explicit file ownership; do not parallelize edits to shared manifests,
Makefile or build state. TDD steps above are separate actions: test → observed failure →
minimal implementation → pass → review → commit. Never push main directly.

Rollback code/docs by reverting their commits. Rebuild derived output; never delete or
rewrite raw sources/receipts. No evidence ingestion or data-model migration is included.

Existing GitHub issues #1–#23 and their status are historical/independent of this plan.
No issue is closed, reassigned or claimed accepted by this rewrite. Countywide research
issues #15–#23 do not block D1–D4. Do not dispatch the old milestone to implement this
new scope. Create a separate demo issue set only when implementation is authorized.

Preserved references: [countywide roadmap](countywide-roadmap.md),
[old task index](countywide-implementation-plan.md),
[deferred human research runbook](m1-human-runbook.md). Their evidence and validation
contracts still apply if that work resumes; their former release scope does not gate
this edition-browser MVP.
