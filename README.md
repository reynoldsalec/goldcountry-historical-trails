# Nevada and Placer Historical Foot Trail Atlas

A temporal GIS dataset and static web viewer mapping historical foot trails throughout
Nevada and Placer Counties, California, decade by decade from 1950 to the present.

The full area of both counties is in scope for research and digitizing, including the
foothills, mountains, and eastern portions. Local collections, including those of the
Open Trails Community Alliance (OTCA), can contribute evidence to this countywide atlas.

> Agents: read `AGENTS.md` first. It contains the non-negotiable rules. This file
> contains the plan.

---

## 1. Why this exists

Build a traceable record of where foot trails are documented from 1950 onward, how
their alignments change, and where the historical record is incomplete. Combine dated
maps, aerial photographs, plans, field records, and accounts with explicit provenance
and uncertainty.

Coverage must extend across both counties. Bear River Canal, Meadow Vista, and other
individual localities are contributing work areas, with no special geographic priority.
The atlas supports historical research and trail stewardship; legal questions about
particular trails do not set its timeline or imply public access rights.

### Success criteria

1. Any rendered line can answer "what document supports this, and from what date?" in
   one click.
2. A decade stepper spans the 1950s through the present and distinguishes documented
   trails, inferred continuity, documented closures, and gaps in observation.
3. Coverage can be inspected by area and decade across both counties. Unexamined areas
   and incomplete evidence remain visible; missing observations do not count as loss.
4. The whole thing deploys as static files with no server and no recurring cost.
5. Public and restricted builds come from one dataset, with the split enforced by a
   failing test rather than by discipline.

### Non-goals

- Not a trail navigation or route-planning app.
- Not a legal claim. See `AGENTS.md` §2.6.
- Not a general historical atlas. Scope is trails and the corridors that carry them.
- No backend, no database, no user accounts in the public build.

---

## 2. Scope and coverage

| Dimension | Scope |
| --- | --- |
| Geography | The entire area of Nevada and Placer Counties, California |
| Time | 1950 to the present, with decade views and source dates retained |
| Subject | Historical foot trails, including changed alignments and documented closures |
| Detail | Segment-level digitizing wherever cited evidence supports it in either county |
| Source coverage | Maps, aerials, and other dated observations across both counties |

`data/sources/aoi_counties.geojson` defines the project boundary for acquisition,
clipping, and digitizing. It uses Census TIGERweb boundaries, Census 2020 vintage,
and is built by `make fetch-aoi`. A sheet or flight may extend beyond the boundary;
its full source extent does not expand the mapping scope.

Plan manageable work batches by quadrangle, locality, or source footprint and decade.
Maintain a countywide coverage inventory that distinguishes sources located, sources
examined, trails digitized, and unresolved gaps. Prioritize useful evidence and gaps
across both counties. Work anywhere in either county can proceed without finishing
another locality first. Countywide scope is a goal, not a claim of completed coverage.

Foot trails are the subject. A road, canal, or maintenance route is relevant only where
a source connects it to a foot trail or documented walking use. A modern route cannot
be projected backward in time without evidence. Pre-1950 material may provide context,
but does not establish presence after 1950 or require a separate earlier-era viewer.

### Legacy implementation

The former Tier 1/2/3 scope system is superseded. `aoi_tier1.geojson` remains an optional
Bear River Canal work-area reference derived from a dated OSM snapshot. It does not
limit digitizing. The trail schema no longer carries `tier`, and `corridor` is a free-text
grouping label rather than a locality enum. The topo index's `in_tier1` column and the
`--tier1` download option still exist as acquisition filters. They describe the earlier
implementation, not countywide priorities. Schema and tooling migration work
is recorded in `docs/open-questions.md`; this document does not imply it is complete.

---

## 3. Data model

Three entities plus a join. Full JSON Schemas live in `schema/`.

### `trails.json` — persistent trail concepts (a JSON array without geometry)

| Field | Type | Notes |
| --- | --- | --- |
| `trail_id` | string | stable slug; not tied to one locality |
| `name` | string | |
| `aka` | string[] | local/colloquial names |
| `corridor` | string | required, nonempty; free-text grouping label, `other` when no grouping is established; not a geographic constraint |
| `current_status` | enum | `secured` \| `unsecured` \| `threatened` \| `lost` \| `unknown` |
| `notes` | string | human-authored |

### `alignments.geojson` — dated geometry versions (the rendered unit)

| Field | Type | Sensitivity | Notes |
| --- | --- | --- | --- |
| `alignment_id` | string | public | |
| `trail_id` | string | public | FK → trails |
| `geometry` | LineString | public | EPSG:4326, 6dp |
| `earliest_known_open` | date \| null | public | ISO `YYYY` or `YYYY-MM-DD` |
| `latest_known_open` | date \| null | public | |
| `earliest_known_closed` | date \| null | public | |
| `latest_known_closed` | date \| null | public | |
| `positional_confidence` | enum | public | `surveyed` \| `digitized_topo` \| `interpreted_aerial` \| `sketched_testimony` |
| `side` | enum | public | `berm` \| `bank` \| `road` \| `na` |
| `superseded_by` | string \| null | public | alignment_id of a later reroute |
| `parcel_apns` | string[] | **restricted** | from county records only |

Any temporal field may be null. Null means unobserved, not absent. See `AGENTS.md` §2.3.

### `observations.geojson` — dated evidence

| Field | Type | Sensitivity | Notes |
| --- | --- | --- | --- |
| `observation_id` | string | public | |
| `obs_type` | enum | public | `topo_sheet` \| `aerial_frame` \| `county_plan` \| `recorded_map` \| `declaration` \| `photograph` \| `oral_account` \| `deed` |
| `date_start` | date | public | |
| `date_end` | date \| null | public | end of the evidence date range; never on its own authorizes presence across the intervening decades |
| `source_citation` | string | public | human-readable |
| `source_url` | string \| null | public | |
| `rights` | enum | public | `public_domain` \| `cc_by_nc_sa` \| `restricted` \| `unknown` |
| `sensitivity` | enum | public | `public` \| `restricted` |
| `geometry` | Polygon \| Point \| LineString | public | sheet footprint, photo point, or declared corridor |
| `declarant_name` | string \| null | **restricted** | |
| `document_path` | string \| null | **restricted** | path to unpublished scan |

### `support.csv` — the join

`alignment_id, observation_id, role, confidence, note`

- `role` ∈ `attests_existence` \| `attests_public_use` \| `attests_closure` \| `attests_alignment`
- `confidence` ∈ `high` \| `medium` \| `low`

Every alignment needs ≥1 support row. Enforced by `make validate`.

### Decade rendering logic

For decade `D` (e.g. 1970 = 1970-01-01 … 1979-12-31), an alignment renders in one of
four states. Nothing projects indefinitely: an observation dates the moment it records,
not every decade after it.

**Evidence roles.** Positive evidence is a support row with role `attests_existence` or
`attests_public_use`. Closure evidence is `attests_closure`. `attests_alignment`
supports geometry only and never sets a decade state.

**Dates.** `date_end` null means a dated event, not an ongoing interval. A bare `YYYY`
is uncertain within that year. An observation resolves to decade `D` when its whole date
range falls inside `D`. A range that crosses a decade boundary is unresolved for every
decade it touches until a reviewer supplies more precise evidence; it neither documents
nor brackets a decade.

| State | Condition for decade `D` | Reason |
| --- | --- | --- |
| `documented_closed` | closure evidence resolves to `D` and no positive evidence resolves to `D` | `documented_evidence` |
| `documented_open` | positive evidence resolves to `D` and no closure evidence resolves to `D` | `documented_evidence` |
| `unobserved` | both positive and closure evidence resolve to `D`; both citations are retained | `conflicting_evidence` |
| `inferred_open` | no evidence resolves to `D`, the same alignment has positive evidence before `D` and after `D`, and no closure or unresolved range lies between those bracketing observations | `inferred_between_observations` |
| `unobserved` | bracketing positives exist but a closure lies between them | `closure_in_bracket` |
| `unobserved` | the only candidate evidence is a date range crossing a decade boundary | `date_range_unresolved` |
| `unobserved` | anything else, including no observations at all | `no_resolving_evidence` |

**Rule precedence.** Evidence inside `D` outranks inference across `D`. Within `D`,
conflict outranks both documented states. Inference is evaluated only when nothing
resolves to `D`; a blocking closure or unresolved range inside the bracket defeats it.

`inferred_open` renders dashed. `unobserved` does not render but is listed in the panel.
Do not promote `inferred_open` to `documented_open` in exports.

#### Worked examples

`scripts/fixtures/temporal_cases.json` holds these same cases in machine-readable form
with fixture-only IDs and synthetic dates. They are documentation examples, not data.

| # | Observations | Decade | State | Reason |
| --- | --- | --- | --- | --- |
| 1 | 1954 positive | 1950 | `documented_open` | `documented_evidence` |
| 2 | 1954 positive | 1970 | `unobserved` | `no_resolving_evidence` |
| 3 | 1954 positive, 1978 positive | 1960 | `inferred_open` | `inferred_between_observations` |
| 4 | 1954 positive, 1978 positive, 1962 closure | 1960 | `documented_closed` | `documented_evidence` |
| 5 | 1954 positive, 1978 positive, 1958 closure | 1960 | `unobserved` | `closure_in_bracket` |
| 6 | 1962 closure | 1970 | `unobserved` | `no_resolving_evidence` |
| 7 | 1961 positive, 1962 closure | 1960 | `unobserved` | `conflicting_evidence` |
| 8 | 1963 `attests_alignment` only | 1960 | `unobserved` | `no_resolving_evidence` |
| 9 | 1968–1972 positive range | 1960 | `unobserved` | `date_range_unresolved` |
| 10 | 1962–1968 positive range | 1960 | `documented_open` | `documented_evidence` |
| 11 | none | 1960 | `unobserved` | `no_resolving_evidence` |
| 12 | 1947 positive | 1950 | `unobserved` | `no_resolving_evidence` |

The four temporal fields on an alignment are bounds. They never manufacture a decade
observation on their own. See `docs/data-model.md` for the longer discussion.

---

## 4. Architecture

Static site. No server, no database, no recurring cost.

```
data/raw/            immutable downloads (gitignored)
   │
   ├─ topoView GeoTIFFs ──────► already georeferenced ─┐
   ├─ EarthExplorer / FrameFinder aerials ─► manual GCPs ─┤
   └─ Rumsey / IIIF ──────────► Allmaps annotation ─────┤
                                                        │
                                              scripts/warp_raster.py
                                                        │
                                                 COG / raster PMTiles
                                                        │
data/authoritative/  committed GeoJSON + CSV ──► scripts/build_vector_tiles.py
   (edited in QGIS)                                  (tippecanoe)
                                                        │
                                                  vector PMTiles
                                                        │
                                              scripts/build_site.py
                                                        │
                                    build/public/  and  build/restricted/
                                                        │
                                        MapLibre GL JS + pmtiles protocol
                                                        │
                                          Cloudflare Pages / Netlify
```

Key choices and why:

- **PMTiles** — single-file tile archives served by HTTP range request. No tile server.
- **GeoJSON in git as source of truth** — free versioning and an audit trail of every
  edit, which matters more here than query convenience.
- **QGIS as the editor** — digitizing against warped rasters is the bulk of the labour
  and QGIS is the right tool. Felt (if adopted) is an editing/field surface that
  exports into this pipeline, not a destination.
- **Allmaps for IIIF sources** — georeferences Rumsey/Stanford scans in the browser with
  no GIS infrastructure, and its tile server exposes them as XYZ for QGIS and MapLibre.
- **Two builds from one dataset** — see `AGENTS.md` §2.5.

---

## 5. Layout

```
.
├── AGENTS.md
├── README.md
├── Makefile
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── validate.yml    # runs lint, validate and the tests on push and PR
├── data/
│   ├── raw/                    # gitignored, immutable
│   ├── working/                # gitignored intermediates
│   ├── sources/                # COMMITTED
│   │   ├── sources.yml         # source manifest: id, url, rights, sensitivity
│   │   ├── topo_index.csv      # per-sheet USGS topo index with lineage dates
│   │   ├── retrievals.jsonl    # source bytes: SHA-256, storage path, retrieval time
│   │   ├── coverage.json       # research bookkeeping: area/decade coverage inventory
│   │   ├── aoi_counties.geojson  # both counties: acquisition + digitizing boundary
│   │   ├── aoi_tier1.geojson     # optional legacy Bear River Canal work area (OSM)
│   │   └── gcp/                # *.points files from QGIS Georeferencer
│   └── authoritative/          # COMMITTED — source of truth
│       ├── trails.json
│       ├── alignments.geojson
│       ├── observations.geojson
│       └── support.csv
├── schema/
│   ├── trail.schema.json
│   ├── alignment.schema.json
│   ├── observation.schema.json
│   ├── retrieval.schema.json   # public USGS download receipts
│   ├── support.schema.json
│   ├── coverage.schema.json      # coverage.json
│   └── coverage_grid.schema.json # coverage_grid.geojson (built in a later M1 issue)
├── scripts/
│   ├── fetch_aoi.py            # TIGERweb + OSM → the two AOI files
│   ├── fetch_topoview.py       # TNM Access API → data/raw/topo/
│   ├── source_archive.py       # receipt catalog, checksum verification, backup/restore
│   ├── warp_raster.py          # GCPs + GDAL → COG
│   ├── ingest_gaia.py          # GPX → candidate alignments
│   ├── ingest_declarations.py  # structured declaration records → observations
│   ├── validate.py             # schema + integrity + leak tests
│   ├── build_vector_tiles.py   # tippecanoe → PMTiles
│   └── build_site.py           # assemble build/public and build/restricted
├── site/                       # MapLibre viewer (vite + TS)
├── build/                      # gitignored output
└── docs/
    ├── data-model.md
    ├── sources.md
    ├── topo-editions.md        # generated from topo_index.csv
    ├── georeferencing.md
    ├── implementation-plan.md # M0/M1 architecture and worker issue index
    └── open-questions.md
```

---

## 6. Commands

| Command | Does |
| --- | --- |
| `make setup` | `uv sync`, check for `gdal`, `tippecanoe`, `node` |
| `make fetch-aoi` | rebuild the countywide AOI (TIGERweb) and the legacy corridor work area (OSM) |
| `make fetch-topo` | index + pull quads covering both counties from TNM Access API into `data/raw/topo/` (current inventory: 615 sheets, 6.3 GB, including pre-1950 material) |
| `make topo-plan` | preview pending downloads from the current index without fetching rasters |
| `make topo-docs` | regenerate the countywide edition report from the current index |
| `make test-topo` | run offline acquisition regression tests and source-index integrity checks |
| `make catalog-sources` | record checksums of existing TIFFs with unknown retrieval dates; preserve their paths |
| `make verify-sources` | verify every receipted local source against SHA-256 and byte count |
| `make backup-sources` | copy verified raw TIFFs and a receipt snapshot to the separate archive |
| `make verify-backup` | verify archived TIFFs against the receipt ledger |
| `make restore-sources` | restore exact source bytes from the archive without overwriting existing files |
| `make test-validation` | run the offline validator regression suite (schema, provenance, temporal, leak) |
| `make test-coverage` | run the coverage inventory schema contract tests |
| `make rasters` | warp + COG everything with a GCP file, write to `build/rasters/` |
| `make validate` | schemas, referential integrity, temporal coherence, geometry, leak test |
| `make tiles` | tippecanoe → `build/tiles/alignments.pmtiles` |
| `make build-public` | assemble `build/public/` (restricted fields stripped) |
| `make build-restricted` | assemble `build/restricted/` |
| `make dev` | vite dev server against `build/public/` |
| `make` | `validate build-public` |

All targets idempotent and safe to re-run.

The optional `make fetch-topo TOPO=--tier1` downloads only the legacy corridor subset
(91 sheets, 1.0 GB in the current index). It is not the default project scope. The
current downloader does not enforce the 1950 start date; select evidence by its
documented content dates when mapping the study period.

### Retrieval records and storage

Raw TIFF bytes stay out of Git. Commit `data/sources/retrievals.jsonl`, which maps
each source to its SHA-256, byte count, original index URL, observed retrieval URL,
UTC retrieval time, and relative storage path. `recorded_at` is the time the receipt
was created. For files downloaded before receipts existed, `retrieved_at` and
`retrieval_url` are `null`; the index URL remains available without claiming it was
observed during retrieval. These timestamps do not date the map's ground content.

New downloads use `data/raw/topo/sha256/<first-two-hash-characters>/<sha256>.tif`.
The source ID and readable edition name remain in the index and receipts. The original
91 TIFFs retain their existing names. Before reuse, receipted files must match their
hashes. If a remote re-download differs from its recorded hash, use the preserved
archive or investigate the new source version; never silently replace recorded bytes.

The configured backup root is `/Volumes/T7 Shield/historical-trails-backup`.
It contains `objects/sha256/<first-two-hash-characters>/<sha256>.tif` and immutable
`manifests/<manifest-sha256>.jsonl` snapshots. Run `make backup-sources` after new
acquisitions, then `make verify-backup`. Repeated runs reuse verified copies and
never delete old objects. A successful source download does not itself mean a backup
exists. This workflow currently covers public USGS GeoTIFFs, not restricted documents
or other source types.

Set `TRAIL_ARCHIVE_ROOT` to use another dedicated directory; quote paths containing
spaces, for example `make backup-sources TRAIL_ARCHIVE_ROOT="/path/to/source archive"`.
The archive root may be a symlink to a mounted drive. The tool fails if its parent
directory is unavailable, rather than creating a replacement mount directory.
`make restore-sources` restores paths from the committed receipts. If recovering
without that ledger, a verified archive manifest snapshot can supply it.

`make validate` validates receipt structure and hashes of available local sources;
it permits missing local copies in fresh clones. `make verify-sources` requires every
receipted file locally. Tests cover backup, restoration, corruption, and filesystems
without hard links. Hashes establish byte identity from the first inventory onward;
they do not independently authenticate the original source or prove an earlier
retrieval date.

---

## 7. Milestones

The MVP is one published atlas with a verified initial dataset from both counties,
a decade viewer spanning 1950 to the present, visible evidence gaps, and enforced
public/restricted separation. Exhaustive countywide digitizing continues after release.

Each milestone has a completion gate. Complete them in order; do not start the next
until the current gate passes. Close a milestone only with links to its deliverables
and recorded acceptance results. Existing code or downloaded files alone do not prove
completion. Do not assign a delivery date until the remaining source-review and manual
GIS work has been estimated.

**Planning baseline, 2026-09-16:** schemas, validation, CI, county boundaries, topo
acquisition, and source-archive tooling exist. The refined M0 gate still needs
verification and countywide schema migration. M1 is partial: the countywide coverage
inventory and later-period/aerial research remain open. Authoritative trail records
are synthetic fixtures; raster processing, the viewer, and build assembly remain
unimplemented. These are implementation observations, not acceptance-test results.

M0 and M1 are decomposed into bounded worker tasks in
[the implementation handoff](docs/implementation-plan.md). Each child issue specifies
its dependencies, owned files, contract, and acceptance checks. Coding tasks are
separate from source research, GIS review, and milestone acceptance.

### M0 — Countywide data contracts and validation

Tracking issue: [#1](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/1).

**Outcome:** the data model can represent supported foot trails anywhere in either
county, and automated checks reject invalid evidence records before publication.

Build on the existing scaffold, schemas, validator, and CI. Remove the required legacy
geographic tiers and replace locality-specific constraints where needed, preserving
stable IDs and provenance. Update schema consumers and the data-model documentation
together. Preserve all four temporal fields and the distinction between an observation
gap and documented closure.

**Completion gate:**

- Countywide records can be represented without an obsolete tier assignment. README
  field tables, schemas, consumers, and `docs/data-model.md` agree.
- Document observation-dating and decade-state rules, including revised map sheets,
  bracketing observations, overlapping open/closed evidence, and unresolved dates.
  Rules must not assign every feature a sheet's latest lineage date or carry a single
  observation forward indefinitely as documented presence. Unresolved source dates
  remain explicit gaps requiring source inspection.
- `make validate` passes on the valid dataset. A Make target runs isolated regression
  cases that reject an orphan alignment, broken reference, invalid required field,
  invalid geometry, reversed temporal bounds, and a restricted value planted in a
  temporary public output. Fixtures must not alter raw evidence.
- CI runs validation and those regression cases. A leak test against a temporary
  output proves the scanner works; an absent `build/public/` is not a publication check.
- Synthetic records are clearly marked and cannot be mistaken for evidence. Their
  removal from authoritative data is a required M3 deliverable.

### M1 — Countywide coverage inventory and source acquisition

Tracking issue: [#2](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/2).

**Outcome:** we know what evidence is available, what has been examined, and which
source-backed batches will supply the initial release.

Inventory historical USGS editions, modern maps, candidate aerials, and local or agency
records across both counties. Extend the existing acquisition and archive scripts;
USGS historical topo downloads alone do not cover the full period through the present.

**Completion gate:**

- A committed, machine-readable inventory accounts for every quadrangle intersecting
  `aoi_counties.geojson` and every decade from the 1950s through the current decade.
  Each cell identifies verified source IDs or an explicit gap. Distinguish sources
  located, sources examined, trails digitized, and unexamined coverage. A located
  source does not mean its trails have been inspected.
- Search records include search date, collection, geographic/temporal extent, result,
  and unresolved access or evidence gaps. Modern maps, aerials, and local/agency
  records are represented by verified candidates or documented search gaps.
- Selected topo editions from both counties are acquired reproducibly. Record source
  IDs, dates and lineage dates, scale, rights, URLs, and retrieval receipts. New TIFFs
  use content-addressed paths; existing raw files remain unchanged.
- `make test-topo`, `make validate`, `make verify-sources`, `make backup-sources`, and
  `make verify-backup` pass for the receipted acquisition set. Record the receipt
  snapshot and verification results; do not commit raw rasters.
- Select at least four county/decade work batches: at least two distinct decades in
  each county, including one before 2000 and one from 2000 onward in each county.
  Each batch lists its footprint, source IDs, examined foot-trail evidence, review
  tasks, and remaining gaps. Select batches by evidence and coverage benefit, without
  making any locality a prerequisite. Do not invent alignments to meet the minimum.
- Identify at least one obtainable, dated aerial frame for M2, with verified frame ID,
  footprint, rights, and access method. If no suitable frame is obtainable, record the
  blocker; M1 remains incomplete unless the milestone requirement is explicitly revised.

A sheet's printed date does not resolve each feature's observation date. The current
index contains 615 sheets, including pre-1950 material; 149 have later lineage dates,
by up to 28 years. `fetch_topoview.py` preserves those dates in `topo_index.csv`.
See `docs/sources.md`, `docs/topo-editions.md`, and `docs/open-questions.md`.

### M2 — Reproducible raster pipeline

**Outcome:** the selected evidence can be inspected in GIS and supplied to the viewer
with traceable processing and correct attribution.

Implement `scripts/warp_raster.py` through `make rasters`. Already-georeferenced USGS
topos need reprojection and COG conversion only. Raw aerial scans require committed
manual GCPs. Viewer controls are delivered in M4, not required to complete this gate.

**Completion gate:**

- `make rasters` reproducibly produces valid COGs for selected topo editions from both
  counties and at least one manually georeferenced aerial frame from the M1 inventory.
- Commit GCP files and processing parameters. Log RMS error for each GCP set and
  record a visual alignment review and fitness decision before using the frame.
- Verify output CRS, bounds, internal overviews, and resampling: nearest for scanned
  maps, cubic for aerials. Re-running the target leaves raw sources unchanged.
- A raster manifest links outputs to source IDs, processing records, rights, and
  attribution. Imagery with unknown or restricted redistribution rights is excluded
  from public layer inputs; it may still support permitted internal inspection.

### M3 — Reviewed initial vector dataset

**Outcome:** real, source-supported trail geometry replaces the synthetic dataset.

Complete the M1-selected batches using the M0 dating rules and M2 source rasters.
Modern tracks support dated modern observations only. Local inventories can identify
candidates; declarations require supported geometry and restricted declarant fields.

**Completion gate:**

- At least four county/decade batches meet the M1 distribution requirement, with at
  least one reviewed, supported foot-trail alignment in each. Record examined sources,
  digitized extent, and unresolved or unexamined coverage for every batch.
- Every alignment has supporting observations and support rows. Record a human source
  review of geometry, feature identity, observation dates, confidence, and provenance.
  Roads and canals do not become trails without cited foot-trail evidence.
- Remove all synthetic records from authoritative data; retain test fixtures separately
  if needed. `make validate` and the M0 regression checks pass on the resulting setup.
- All four temporal fields are preserved. Unsupported dates remain null, and ambiguous
  evidence is recorded explicitly. Narrative fields remain human-authored.

Completing these batches does not establish complete coverage of either county or any
whole decade. The inventory must expose that limitation in M4.

### M4 — Viewer and public build

**Outcome:** a user can explore the initial dataset and trace every rendered line to
its dated evidence in a working local static build.

Implement the vanilla TypeScript MapLibre viewer, vector PMTiles, and public build
assembly. `make build-public` belongs here because viewer acceptance depends on it;
M5 adds restricted build assembly and verifies hosted release behavior.

**Completion gate:**

- `make tiles` and `make build-public` produce the static viewer and its data;
  `make dev` serves it. The initial map shows both counties, and the decade stepper
  reaches every decade from the 1950s through the present.
- Every rendered line opens its supporting citations, source dates, and available
  links in one click. Confidence and the M0 temporal states have distinct styles;
  gaps in observation cannot be presented as documented closures.
- The countywide inventory is inspectable by area and decade, including unexamined
  areas. Raster layers have attribution, opacity, and swipe comparison controls.
- The public build excludes restricted observations, fields, unpublished document
  links, and alignments without public supporting evidence. Derived dates and
  attributes cannot expose restricted-only evidence. Validate the assembled output.
- Exercise the temporal states with isolated test fixtures, even when the real seed
  dataset lacks a closure or reroute. Keep those fixtures out of release artifacts.
- Record browser checks for citations, decade changes, coverage states, and raster
  controls. Confirm no network calls beyond the static origin and basemap, no browser
  storage, and no analytics. Any change totals state their evidence and coverage limits.

### M5 — Restricted build and verified deployment

**Outcome:** the MVP is published, reproducible, and safe to access in each audience.

Implement `make build-restricted` from the same authoritative dataset. Deploy the public
site to Cloudflare Pages from `main`; protect the restricted site and all its artifacts
with host-level authentication.

**Completion gate:**

- A clean checkout with restored or retrieved sources can reproduce both builds
  through Make targets. Bare `make` succeeds; CI builds public output before running
  the public leak check, so the check scans actual release artifacts.
- CI fails when a restricted value is deliberately introduced into public output.
  Verify that restricted observations and their dependent data cannot leak through
  GeoJSON, PMTiles, manifests, citations, or other published assets.
- The deployed public viewer passes the M4 browser checks. Verify static asset and
  PMTiles range requests at the host, and record the deployed revision and URL.
- Unauthenticated requests cannot retrieve the restricted site or its data artifacts;
  authenticated access works. Public assets cannot link around that protection.
- Record the release's covered batches, known evidence gaps, source-license review,
  and recovery procedure. User-facing legal framing remains subject to the separate
  `copy:` commit requirement in AGENTS §2.6.

### Backlog (not scheduled)

Continue countywide digitizing and close coverage gaps after the initial release.
Optional later features include additional contextual layers and Felt round-trip
export. Pre-1950 reconstruction is outside the core mapping program.

---

## 8. Source inventory

| Source | Era | Georeferenced? | Rights |
| --- | --- | --- | --- |
| USGS Historical Topographic Map Collection (topoView / TNM Access API) | 1884–2006 | Yes, GeoTIFF w/ metadata | Public domain |
| USGS US Topo | 2009– | Yes | Public domain |
| USGS EarthExplorer single-frame aerials | 1930s– | No, manual GCPs | Public domain |
| UCSB FrameFinder (incl. Cartwright Aerial Surveys, late 1950s–early 1980s, strong for N. CA counties) | 1920s–2010 | No, manual GCPs | Varies — check per flight |
| Placer County Open Data (`gis-placercounty.opendata.arcgis.com`) | current | Yes | Public |
| Placer County Assessor historic parcel maps | varies | No | Public record |
| Placer County Clerk-Recorder subdivision maps (offers of dedication) | varies | No | Public record |
| Meadow Vista Community Plan, 1974 + amendments | 1974– | No | Public record |
| Nevada County GIS | current | Yes | Public |
| BLM GLO township plats + field notes (`glorecords.blm.gov`) | 1850s–1880s | No | Public domain |
| Hartwell, *Map of Nevada County*, 1880 (David Rumsey) | 1880 | Via Allmaps | CC-BY-NC-SA |
| Britton & Rey / Goddard, *Map of the State of California*, 1857 | 1857 | Via Allmaps | Check |
| OTCA public-use declarations | 1956– | N/A | **Restricted** |
| OTCA Gaia GPS tracks | current | Yes | OTCA |
| OSM | current | Yes | ODbL — attribution required |

Anything not in this table needs a `docs/sources.md` entry before use.

The table includes previously investigated sources, not geographic priorities or
confirmed coverage for every decade. Pre-1950 collections are background only. Seek
equivalent local and agency records throughout both counties; the Meadow Vista entry
does not make that locality a prerequisite for other work.
