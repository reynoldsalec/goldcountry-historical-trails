# Auburn Historical Map Browser

**Current MVP:** page through four historical map editions of the same Auburn area,
keeping the map position and zoom unchanged. Display original cartography and aerial
imagery with honest source dates—not reconstructed trail history.

**Scope decision: 2026-09-28.** The Nevada/Placer countywide trail atlas remains a
long-term direction, not this first-release gate. This is a planning revision, not a
claim that the raster pipeline, viewer or acceptance checks are implemented.

> **Success:** “I can zoom into one place, page through four source editions without
> losing my position, and see exactly which map I am viewing.”

## 1. User experience

Open to the Auburn quadrangle with the 1953 topo selected. Pan and zoom, then use
**Previous**, **Next**, or the **Map editions** selector. Preserve the camera when
switching; provide a separate **Reset view** button. Show a source card with base,
revision, photography and field-check dates, the source identifier, USGS attribution
and an original-source link. Disable Previous/Next at endpoints; do not wrap.

Order: **1953 base → 1973 revision → 1975 aerial → 1981 revision**. These are source
editions, not a continuous timeline. A revision year does not date every mapped feature.

## 2. Four existing sources

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

## 3. Required versus deferred

Required: four raster layers, one visible at a time; common projection; fixed-camera
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
four immutable, receipted GeoTIFFs + edition manifest
  → EPSG:3857 preparation, verified common mapped crop
  → static XYZ PNG tiles
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

D1–D4 are new plan identifiers, not GitHub issue numbers or renamed M0–M5 milestones.
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
claim an independent backup without verifying real archive storage. The new selected
preflight requires only the four MVP inputs.

**Planned, not yet available:** `make demo-check`, `make demo-rasters`, `make demo-test`,
`make demo-build`, `make demo-dev`, `make demo-accept`. Build output before leak checks;
fail if artifacts/tests are absent. Do not gate the demo on `coverage-ready`.

Bare `make`, `rasters`, `tiles`, `build-public`, `build-restricted` and `dev` still contain
older scaffold behavior/placeholders and milestone messages. They are not working demo
commands today. D4 aligns public/dev/default targets with the finished demo; vector and
restricted targets remain deferred.

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
