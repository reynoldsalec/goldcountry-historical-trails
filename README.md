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
| `date_end` | date \| null | public | for range evidence like "used 1958–present" |
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

For decade `D` (e.g. 1970 = 1970-01-01 … 1979-12-31), an alignment renders as:

| State | Condition |
| --- | --- |
| `documented_open` | any known-open date falls in or before `D`, and no known-closed date before `D` |
| `inferred_open` | known open before `D` and known open after `D`, but no observation within `D` |
| `documented_closed` | a known-closed date falls in or before `D` |
| `unobserved` | no supporting observation resolves to `D` or bracketing it |

`inferred_open` renders dashed. `unobserved` does not render but is listed in the panel.
Do not promote `inferred_open` to `documented_open` in exports.

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
│       └── validate.yml    # runs `make validate` on push and PR
├── data/
│   ├── raw/                    # gitignored, immutable
│   ├── working/                # gitignored intermediates
│   ├── sources/                # COMMITTED
│   │   ├── sources.yml         # source manifest: id, url, rights, sensitivity
│   │   ├── topo_index.csv      # per-sheet USGS topo index with lineage dates
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
│   └── support.schema.json
├── scripts/
│   ├── fetch_aoi.py            # TIGERweb + OSM → the two AOI files
│   ├── fetch_topoview.py       # TNM Access API → data/raw/topo/
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

---

## 7. Milestones

Each milestone is a stopping point with a verifiable acceptance test. Complete them in
order. Do not start the next until the current one's acceptance test passes.

### M0 — Scaffold and contracts

Repo skeleton, `pyproject.toml`, `Makefile`, four JSON Schemas, `scripts/validate.py`,
GitHub Actions running `make validate` on push, `.gitignore`, `docs/open-questions.md`.
Seed `data/authoritative/` with 2–3 hand-written fixture records so validation has
something to chew on.

**Accept when:** `make validate` passes on the fixtures and fails loudly if you delete a
`support.csv` row, null a required field, or put a restricted value in a public field.

### M1 — Source manifest and raster acquisition

Inventory sources throughout both counties for 1950 to the present: historical USGS
quad editions, modern maps, candidate aerial flights, and local or agency records.
`scripts/fetch_topoview.py` pulls historical GeoTIFFs via the TNM Access API. Its
historical collection alone does not cover the full period through the present.

**Accept when:** a coverage inventory accounts for every quadrangle intersecting the
countywide AOI and every decade from the 1950s onward, identifying available sources
and explicit gaps. Selected available topo editions are downloaded reproducibly, with
dates, scales, rights, and URLs recorded. A gap may remain unresolved, but cannot be
silently excluded or treated as evidence of no trails.

A sheet's printed date does not resolve each feature's observation date — 149 of the 615
indexed sheets have later lineage dates, by up to 28 years — so `fetch_topoview.py` harvests each
sheet's FGDC lineage dates into `data/sources/topo_index.csv`. See `docs/sources.md` and
`docs/topo-editions.md`. Countywide aerial coverage and later decades remain unresolved;
see `docs/open-questions.md`.

### M2 — Raster pipeline

`scripts/warp_raster.py`: already-georeferenced topos get reproject + COG; scans with a
committed `.points` file get warped. Raster PMTiles or COG output, wired into the
viewer's layer picker with per-layer attribution.

**Accept when:** `make rasters` produces valid COGs for the selected topo editions from
both counties and at least one manually georeferenced aerial frame, and RMS error per
GCP set is logged. Selection follows the coverage inventory rather than a fixed corridor.

### M3 — Seed the vector dataset

Digitize supported foot-trail segments in work batches across both counties and the
study period. Use modern tracks only as dated modern observations. Local spreadsheets,
including OTCA's Meadow Vista inventory, can supply candidates; each alignment still
requires supporting evidence. Declarations are dated observations with declarant names
in restricted fields. Do not infer their geometry beyond what the account supports.

**Accept when:** initial batches include supported alignments from both counties and
multiple decades, every alignment has at least one support row, and `make validate`
passes. Replace synthetic fixtures before publishing real data. Record remaining
coverage gaps; completing the seed dataset does not complete countywide mapping.

### M4 — Viewer

MapLibre GL JS + `pmtiles`, opening to the full extent of both counties. Decade stepper
from the 1950s through the present. Distinguish documented observations, inferred
continuity, closures, and unknown periods. Click a line for supporting observations,
dates, and links. Encode confidence in line style. Include coverage gaps and a raster
overlay picker with opacity + swipe. Any change totals must identify their evidence
and coverage limits; an unobserved trail is not a lost trail.

**Accept when:** `make build-public && make dev` serves a working viewer; every rendered
line resolves to at least one citation in the panel; both counties and all study decades
are reachable; coverage gaps are distinguishable from documented closures; no network
calls beyond the static origin and the basemap.

### M5 — Split builds and deploy

`build-public` strips all restricted fields; `build-restricted` retains them behind
basic auth at the host. Leak test in CI.

**Accept when:** CI fails if a restricted value appears anywhere under `build/public/`,
and the public build deploys to Cloudflare Pages from `main`.

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
