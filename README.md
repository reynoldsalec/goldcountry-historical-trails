# Foothill Trail Atlas

A temporal GIS dataset and static web viewer documenting historical trail extent in the
Sierra Nevada foothills of Placer and Nevada County, California: the 19th century as a
single era, then decade-by-decade from 1950 to the present.

Built for the Open Trails Community Alliance (OTCA), Meadow Vista, CA.

> Agents: read `AGENTS.md` first. It contains the non-negotiable rules. This file
> contains the plan.

---

## 1. Why this exists

California Civil Code 1009 (1972) requires that a claim of *public* prescriptive
easement be supported by proof of public use for at least five years prior to March
1972. OTCA holds signed public-use declarations from trail users describing use from
1956 onward, and Placer County has shown the Bear River Canal Trail in the Meadow Vista
Community Plan since the 1974 edition.

This project makes that evidence spatial and queryable. **1967–1972 is the hinge**, and
the interface treats it as such.

The 19th-century layer serves a different purpose: showing that these corridors predate
every subdivision that now crosses them. That is a persuasion argument, not an
evidentiary one, and the viewer keeps the two visually distinct.

### Success criteria

1. Any rendered line can answer "what document supports this, and from what date?" in
   one click.
2. A decade stepper shows persisting / newly documented / newly lost segments, with a
   running "miles lost since 1950" figure.
3. The 1967–1972 window is directly reachable and visually marked.
4. The whole thing deploys as static files with no server and no recurring cost.
5. Public and restricted builds come from one dataset, with the split enforced by a
   failing test rather than by discipline.

### Non-goals

- Not a trail navigation or route-planning app.
- Not a legal claim. See `AGENTS.md` §2.6.
- Not a general historical atlas. Scope is trails and the corridors that carry them.
- No backend, no database, no user accounts in the public build.

---

## 2. Scope tiers

Work Tier 1 to completion before touching Tier 2. Breadth is the failure mode.

| Tier | Extent | Resolution | Time slices |
| --- | --- | --- | --- |
| **1** | Bear River Canal corridor, Crother Rd to Placer Hills Rd, plus Bowman feeder and Meadow Vista connectors | Segment-level, digitized | 19c + every decade 1950–2020s |
| **2** | Auburn–Colfax–Grass Valley foothill band | Coarse, principal corridors only | 19c, 1950s, 1970s, 2020s |
| **3** | Placer + Nevada County | Raster overlays only, no digitizing | Whatever sheets exist |

Tier 1 AOI is defined by `data/sources/aoi_tier1.geojson`. Do not widen it.

**Acquisition is scoped wider than digitizing.** As of 2026-08-29, raster acquisition and
clipping cover all of Placer and Nevada County, bounded by
`data/sources/aoi_counties.geojson` (Census TIGERweb, Census 2020 vintage, built by
`make fetch-aoi`). Segment-level digitizing remains Tier 1, bounded by
`data/sources/aoi_tier1.geojson` — the Bear River Canal corridor from the Crother Rd
crossing to the Placer Hills Rd crossing plus the Bowman feeder, derived from a dated
OSM snapshot and buffered 250 m. The two AOIs are not
interchangeable: `aoi_counties.geojson` answers "which sheets do we pull and warp",
`aoi_tier1.geojson` answers "what do we trace". Widening the second is still forbidden.

---

## 3. Data model

Three entities plus a join. Full JSON Schemas live in `schema/`.

### `trails.geojson` — persistent corridor concepts (no geometry; `null` geometry FeatureCollection is not used, this is a **JSON array**, stored as `data/authoritative/trails.json`)

| Field | Type | Notes |
| --- | --- | --- |
| `trail_id` | string | stable slug, e.g. `brct-crother-to-simpson-bridge` |
| `name` | string | |
| `aka` | string[] | local/colloquial names |
| `corridor` | enum | `brct` \| `bowman` \| `simpson` \| `combie` \| `sugar-pine` \| `other` |
| `tier` | 1 \| 2 \| 3 | |
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
│   │   ├── aoi_counties.geojson  # Placer + Nevada, acquisition/clip envelope
│   │   ├── aoi_tier1.geojson     # Bear River Canal corridor, digitizing bound (OSM)
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
    ├── georeferencing.md
    └── open-questions.md
```

---

## 6. Commands

| Command | Does |
| --- | --- |
| `make setup` | `uv sync`, check for `gdal`, `tippecanoe`, `node` |
| `make fetch-aoi` | rebuild both AOIs: `aoi_counties.geojson` (TIGERweb), `aoi_tier1.geojson` (OSM) |
| `make fetch-topo` | pull quads covering the acquisition AOI from TNM Access API into `data/raw/topo/` |
| `make rasters` | warp + COG everything with a GCP file, write to `build/rasters/` |
| `make validate` | schemas, referential integrity, temporal coherence, geometry, leak test |
| `make tiles` | tippecanoe → `build/tiles/alignments.pmtiles` |
| `make build-public` | assemble `build/public/` (restricted fields stripped) |
| `make build-restricted` | assemble `build/restricted/` |
| `make dev` | vite dev server against `build/public/` |
| `make` | `validate build-public` |

All targets idempotent and safe to re-run.

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
`data/sources/sources.yml` populated for Tier 1: every USGS quad covering the AOI
(verify quad names in topoView — likely Auburn, Colfax, Lake Combie, Chicago Park),
plus candidate aerial flights and the 19c county maps. `scripts/fetch_topoview.py`
pulls GeoTIFFs via the TNM Access API.

**Accept when:** `make fetch-topo` downloads every Tier 1 quad edition, and
`docs/sources.md` lists each with date, scale, rights, and URL.

### M2 — Raster pipeline
`scripts/warp_raster.py`: already-georeferenced topos get reproject + COG; scans with a
committed `.points` file get warped. Raster PMTiles or COG output, wired into the
viewer's layer picker with per-layer attribution.

**Accept when:** `make rasters` produces valid COGs for every Tier 1 topo edition and at
least one manually georeferenced aerial frame, and RMS error per GCP set is logged.

### M3 — Seed the vector dataset
Ingest OTCA's existing `Meadow Vista Trail Database.xlsx` into `trails.json`. Ingest
Gaia GPX tracks as the modern (2020s) alignment baseline. Structure the public-use
declarations into `observations.geojson` with `obs_type: declaration`, one per
declarant, geometry = the corridor they describe, `date_start` = first stated year.
Declarant names go in the restricted field.

**Accept when:** every trail in the spreadsheet has a `trail_id`; every 2020s alignment
has ≥1 support row; every declaration on file is an observation; `make validate` passes.

### M4 — Viewer
MapLibre GL JS + `pmtiles`. Decade stepper (19c, 1950s…2020s). Change rendering
(persisting / newly documented / newly lost). Running "miles lost since 1950" counter.
Click a line → provenance panel listing supporting observations with dates and links.
Confidence encoded in line style. 1967–1972 window marked on the stepper.
Raster overlay picker with opacity + swipe.

**Accept when:** `make build-public && make dev` serves a working viewer; every rendered
line resolves to at least one citation in the panel; no network calls beyond the static
origin and the basemap.

### M5 — Split builds and deploy
`build-public` strips all restricted fields; `build-restricted` retains them behind
basic auth at the host. Leak test in CI.

**Accept when:** CI fails if a restricted value appears anywhere under `build/public/`,
and the public build deploys to Cloudflare Pages from `main`.

### Backlog (not scheduled)
Tier 2 digitizing · GLO field-note chainage recovery · subdivision-map dedication layer
· parcel-subdivision-date vs trail-loss analysis · Felt round-trip export.

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
