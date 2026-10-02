# Auburn Historical Map Browser

**Current MVP:** page through historical map editions of the same Auburn area,
keeping the map position and zoom unchanged. Display original cartography and aerial
imagery with honest source dates—not reconstructed trail history.

**Expansion approved 2026-09-29 (issue #55):** the owner authorized growing the browser
from four to nine editions, including pre-1950 sheets as raster display context. Since E4
(issue #58) the active manifest, build and viewer hold all nine. The expansion changes no
evidence, privacy or legal-copy safeguard in AGENTS.md §2.

**Scope decision: 2026-09-28.** The Nevada/Placer countywide trail atlas remains a
long-term direction, not this first-release gate. This is a planning revision, not a
claim that the raster pipeline, viewer or acceptance checks are implemented.

> **Success:** “I can zoom into one place, page through nine source editions without
> losing my position, and see exactly which map I am viewing.”

## 1. User experience

Open to the Auburn quadrangle with the 1953 topo selected. Pan and zoom, then use
**Previous**, **Next**, or the **Map editions** selector. Preserve the camera when
switching; provide a separate **Reset view** button. Show a source card with product,
sheet name and scale, the dates the sheet records (publication, base, revision,
photography, field check, survey, edit, print; nulls omitted), the source identifier,
printed credits where transcribed, USGS attribution, the edition's detail limit and an
original-source link. Disable Previous/Next at endpoints; do not wrap.

Order: **sacramento-1891 → auburn-1944 → auburn-1953 → auburn-1973 → auburn-1975
(aerial) → auburn-1981 → sacramento-1994 → auburn-2018 → auburn-2021**. The 1953 edition
is the initial selection. These are source editions, not a continuous timeline. A
revision or publication year does not date every mapped feature. The 1891 and 1994
editions are regional Sacramento sheets at 1:125,000 and 1:100,000, not Auburn
7.5-minute maps; their labels and source cards show the original sheet name and scale.

Each edition is tiled only to its own native zoom (14 for the Sacramento sheets, 15 for
the 1944 sheet, 16 otherwise). A switch never moves the camera: past an edition's limit
the map enlarges its top level and the card says so.

## 2. The nine sources

The four 1:24,000 base editions:

| UI label | Exact source ID | Interpretation |
| --- | --- | --- |
| 1953 topo · base edition | `CA_Auburn_288101_1953_24000` | 1952 photography; 1953 field check. Later file stamps are not new observations. |
| 1973 topo · revision of 1953 base | `CA_Auburn_288103_1953_24000` | Purple revisions from 1973 photography; not field checked. |
| 1975 aerial · orthophotoquad | `CA_Auburn_288104_1975_24000` | Photography 1975-08-29 per scan margin. Already georeferenced, not a conventional topo. |
| 1981 topo · revision of 1953 base | `CA_Auburn_288105_1953_24000` | Purple revisions/woodland from 1978 photography and other data; edited 1981; not field checked. |

All four GeoTIFFs were found locally during assessment. Verify their bytes against
existing receipts before processing. The index records public-domain rights; check
cards against scan margins and preserve source URLs. Never use `content_year`, printing
dates or file stamps as universal feature dates.

**Area:** the shared mapped portion of the Auburn 7.5-minute quadrangle, nominally
121°07′30″W–121°00′W and 38°52′30″N–39°00′N in the source datum. Derive display bounds
from actual georeferencing; nominal NAD27 corners are not exact WGS84 values. The
original sheet includes context outside Placer County. Displaying it does not expand
future trail-data scope or claim countywide coverage. Colfax is deferred.

### Five added sources (E1, issue #55)

| Edition | Exact source ID | What it is |
| --- | --- | --- |
| sacramento-1891 | `CA_Sacramento_299588_1891_125000` | Regional Sacramento sheet, 1:125,000, 30′ × 30′. Reused local GeoTIFF. |
| auburn-1944 | `CA_Auburn_296741_1944_62500` | Auburn 15-minute sheet, 1:62,500. Reused local GeoTIFF. |
| sacramento-1994 | `CA_Sacramento_299157_1994_100000` | Regional Sacramento sheet, 1:100,000, 30′ × 60′. Reused local GeoTIFF. |
| auburn-2018 | ScienceBase `5d3aeb27e4b01d82ce8d133b` | US Topo 7.5-minute geospatial PDF, published 2018-09-24. |
| auburn-2021 | ScienceBase `61d7a9e2d34ed79294005276` | US Topo 7.5-minute geospatial PDF, published 2021-12-30. |

The three TIFFs already have `existing_file` receipts with `retrieved_at: null` in
`data/sources/retrievals.jsonl`; they are verified and reused, not downloaded again.
The two PDFs are cataloged in `data/sources/demo-pdf-sources.json` with their metadata
URL, verbatim use constraints and source statements, and printed credit note. Their
receipts are in `data/sources/demo-pdf-retrievals.jsonl`. All nine editions are in
`data/sources/demo-editions.json` (schema version 2) since #58. Crops, zoom limits and the
PDF rendering were derived in E2–E3; registration is machine-checked only and open items
are in `docs/open-questions.md`.

## 3. Required versus deferred

Required: nine raster layers, one visible at a time; common projection; fixed-camera
paging; source card and attribution; explicit loading, failure and no-data states;
keyboard and narrow-screen usability; reproducible local static build.

Deferred—not prerequisites:
- Trail identification, digitization, vectors and inferred trail states.
- Countywide completeness, four county/era batches and `coverage-ready` acceptance.
- New aerial acquisition, manual GCPs and re-georeferencing these inputs.
- Restricted data, authenticated deployment, parcels and owner information.
- Swipe, blending, animation, basemap services, geolocation and search.
- PMTiles, vector tiling, production hosting and coverage through the present.

Retain existing schemas, validators, research records and raw sources. Do not weaken
tests or fabricate review records to satisfy old gates. Publish neither
`data/authoritative/` nor `coverage.json` in this raster-only demo.

## 4. Architecture

Python/GDAL for offline preparation; vanilla TypeScript, Vite and MapLibre GL JS for
display; same-origin **static XYZ PNG tiles**, zooms **10–16**. No React, runtime API,
backend, tile server, external basemap, browser storage, analytics or external fonts.

```text
seven immutable, receipted GeoTIFFs + two receipted US Topo PDFs + edition manifest
  → PDF render with embedded georeferencing (expansion-pdf)
  → EPSG:3857 preparation, verified crop inside the common camera footprint
  → static XYZ PNG tiles, each edition up to its own native zoom
  → one map + edition controls + source card
  → build/public/ served over ordinary static HTTP
```

Use nearest-neighbor resampling for topo scans, cubic for the orthophotoquad. Preserve
source georeferencing. Check stable landmarks; never force changed features into
artificial agreement. Mask only verified borders/no-data, not legitimate white map
content. Preserve margin information in source cards and link the original sheets.
Measure output bytes, tile count and legibility before selecting hosting; no cost or
performance claim is made here. PMTiles is a separately approved optimization if needed.

## 5. Delivery sequence

| Step | Deliverable | Gate |
| --- | --- | --- |
| D1 | Four-edition manifest and preflight | IDs, source hashes, types, dates and rights checked |
| D2 | Raster/XYZ preparation | Common CRS/crop, readable tiles, registration review, unchanged raw bytes |
| D3 | Static edition browser | Four layers work; camera and source cards stay correct |
| D4 | Tests, public build and handoff | Automated checks and manual runbook pass on actual output |
| E1 | Acquire and catalog five expansion sources | Full-file hashes against receipts, verbatim rights evidence, no live-manifest change |
| E2 | Render the two US Topo PDFs | Embedded georeferencing, publisher-default layers, recorded render |
| E3 | Nine-edition manifest and added pyramids | Crops, native zooms and pyramids derived from the sources |
| E4 | Integrate nine editions into build and viewer | Baseline and expanded suites pass; real build coherent; preview refreshed |

D1–D4 are new plan identifiers, not GitHub issue numbers or renamed M0–M5 milestones.
E1 onward are the nine-edition expansion steps: E1 is issue #55, E4 is issue #58.
See [worker contracts](docs/implementation-plan.md) and
[the MVP testing runbook](docs/mvp-runbook.md). This document does not launch workers.

## 6. Commands: current versus planned

Existing regression commands:

```sh
make lint
make test-validation
make test-topo
make test-coverage
make validate
```

`make verify-sources` requires all receipted sources locally. Keep backup tooling; never
claim an independent backup without verifying real archive storage. The demo preflight
requires only the nine selected inputs.

The nine-edition demo:

```sh
make demo-check        # manifest, receipts, scans and PDF renders; reads only
make demo-rasters      # renders the PDFs, then all nine pyramids
make demo-test         # offline unit, raster, build, expansion and browser suites
make demo-build        # allowlisted build/public/ with exactly nine tile trees
make demo-accept       # demo-test, demo-build, then validate (local only)
make demo-dev          # vite dev server on http://127.0.0.1:5173/
```

Expansion source tools (E1–E3), still available on their own:

```sh
make expansion-test     # offline unit tests (also run by demo-test)
make expansion-fetch    # download the two US Topo PDFs once
make expansion-check    # source hashes, then the nine-edition manifest
make expansion-pdf      # the two PDFs -> georeferenced COGs (E2)
make expansion-rasters  # only the five added pyramids -> build/expansion/ (E3)
```

The four base pyramids are cut to `build/tiles/demo/`, the five added ones to
`build/expansion/tiles/`; `make demo-build` checks both against their processing records
and copies them to `build/public/tiles/`.

All demo and `expansion-*` source targets use `DEMO_RAW_ROOT` (default `data/raw`). A
worktree points it at the primary checkout's raw root. **PDF backup is not verified:**
`make backup-sources`, `restore-sources` and `verify-backup` read only
`retrievals.jsonl`, so they do not cover `data/raw/us-topo/`. The PDFs are
hash-pinned by their receipts and can be downloaded again, but no archive copy exists.

Bare `make` and `build-public` run the demo build, then validation; `dev` is
`demo-dev`. `rasters`, `tiles` and `build-restricted` stay deferred with the countywide
program. Do not gate the demo on `coverage-ready`.

## 7. Layout and preservation

- `data/raw/`: immutable gitignored bytes; retain paths and receipts.
- `data/working/`, `build/`: reproducible derived output, not source evidence.
- `data/sources/`, `schema/`, `scripts/`: existing machinery and proposed demo manifest,
  schema and focused raster scripts.
- `site/`: planned Vite/TypeScript viewer, not a completed application.
- `docs/implementation-plan.md`, `docs/mvp-runbook.md`: active plan and acceptance.
- `docs/countywide-roadmap.md`, `docs/countywide-implementation-plan.md`: archived
  larger plan, not the current dependency graph.
- `docs/m1-human-runbook.md`, `docs/m1-research-assessment.md`: deferred research work.
- `docs/data-model.md`, `docs/sources.md`, `docs/open-questions.md`: retained evidence
  contracts, source references and uncertainty records.

No new top-level directory or source-data edits are required by this revision.
GitHub issue states and Looper plans are not automatically migrated. Before new dispatch,
create a demo-scoped issue set rather than silently rewriting/closing old research
milestones. The future atlas remains in the [countywide roadmap](docs/countywide-roadmap.md).
