# AGENTS.md

Operating rules for any agent (or human) working in this repository.

Read this file and `README.md` before your first edit in a session. If a rule here
conflicts with an instruction in a task prompt, stop and ask rather than guessing.

---

## 1. What this project is

A temporal GIS dataset and static web viewer documenting historical trail extent in
the Sierra Nevada foothills of Placer and Nevada County, California, from the 19th
century and decade-by-decade from 1950 to present.

The dataset is **evidence**, not decoration. It is used by the Open Trails Community
Alliance (OTCA) in landowner negotiations, easement work, and potentially in legal
filings. Treat every geometry and every attribute as something that may be scrutinized
by an opposing attorney.

---

## 2. Non-negotiable rules

### 2.1 Never invent geometry or attribution

- Do not draw, interpolate, snap, or "clean up" a trail alignment that is not supported
  by a cited observation. An unsupported line is worse than a missing line.
- Do not fabricate a citation, a date, a document ID, or a URL. If you cannot verify a
  source, write `null` and add the gap to `docs/open-questions.md`.
- Do not infer an owner, a parcel, or an APN from context. These come from county
  records only.
- If a source is ambiguous, record the ambiguity in the data (see the four-field
  temporal model, §2.3) rather than resolving it silently.

### 2.2 Raw data is immutable

- `data/raw/` is append-only. Never edit, reproject, crop, or rename a file in place.
- Every derived artifact must be reproducible from `data/raw/` + committed scripts +
  committed GCP files by running `make`. If a step required manual work, the manual
  output (e.g. a `.points` file, a digitized GeoJSON) is committed and the script
  consumes it.
- `data/raw/` and `data/working/` are gitignored. `data/sources/` and
  `data/authoritative/` are committed.

### 2.3 The temporal model has four fields, not two

Every alignment carries `earliest_known_open`, `latest_known_open`,
`earliest_known_closed`, `latest_known_closed`. Any field may be null.

Never collapse these into `start_year` / `end_year`. "Unobserved" is a distinct state
from "known absent" and the distinction is the point of the project. Absence of a trail
from a map sheet is evidence of nothing on its own.

### 2.4 Provenance is mandatory

No row in `alignments.geojson` may exist without at least one row in `support.csv`
linking it to an `observation_id`. `make validate` enforces this. Do not add an
`--allow-orphans` escape hatch.

### 2.5 The public/restricted split is enforced in code, not by convention

Two builds come from one dataset:

- **public** — no parcel APNs, no owner names, no declarant names, no restricted
  observations, no document links to unpublished records.
- **restricted** — everything, for board and counsel use, served behind auth.

Fields marked `sensitivity: restricted` in the schemas must never reach `build/public/`.
`scripts/validate.py` includes a leak test that scans the public build output for
restricted values and fails the build on any hit. Do not weaken or skip that test.

### 2.6 No legal assertions in UI copy

The viewer describes what documents show. It does not state that the public holds a
right, that a parcel is burdened, or that a closure is unlawful. Write "shown as trail
on the 1974 Meadow Vista Community Plan," not "public trail since 1974."

All user-facing copy changes touching legal framing go in a separate commit tagged
`copy:` so counsel can review them in isolation.

### 2.7 Respect source licensing

`data/sources/sources.yml` carries a `rights` field per source. Public-domain (USGS,
BLM GLO, county records) may be redistributed. David Rumsey scans are generally
CC-BY-NC-SA; attribute and do not use commercially. UCSB aerials vary. If `rights` is
`unknown`, the source may be used for digitizing but its imagery must not be published
as a tile layer.

Every published raster layer must carry its attribution string in the viewer's
attribution control.

---

## 3. Geospatial conventions

| Concern | Rule |
| --- | --- |
| Source vector CRS | EPSG:4326, decimal degrees |
| Coordinate precision | 6 decimal places (~0.1 m); truncate on write |
| Tile CRS | EPSG:3857 |
| Vector geometry | `LineString` for alignments; no `MultiLineString` — split into separate alignments |
| Raster output | Cloud-Optimized GeoTIFF with internal overviews, or raster PMTiles |
| Raster resampling | `cubic` for aerials, `nearest` for scanned map sheets (preserves line color) |
| Warp method | Thin-plate spline for aerial frames; polynomial 1 or 2 for map sheets |
| Null geometry | Not permitted; a record without geometry belongs in a CSV, not GeoJSON |

Historical topo GeoTIFFs from USGS topoView arrive already georeferenced. Do not
re-georeference them. Reproject and tile only.

Historical aerial frames arrive as raw scans. They require manual GCPs. Commit the
`.points` file alongside the frame ID in `data/sources/gcp/`.

---

## 4. Repository conventions

### 4.1 Layout

See `README.md` §Layout. Do not create new top-level directories without updating both
files.

### 4.2 Language and tooling

- Python 3.11+, managed with `uv`. Dependencies in `pyproject.toml`.
- Geospatial: GDAL/OGR CLI, `geopandas`, `shapely`, `rasterio`, `pyproj`.
- Tiling: `tippecanoe` (vector), `rio-cogeo` (raster).
- Frontend: vanilla TypeScript + MapLibre GL JS + `pmtiles`. No React, no build
  framework beyond `vite`. Keep the viewer readable by a volunteer.
- Formatting: `ruff format` for Python, `prettier` for TS/JS/JSON/Markdown.

### 4.3 Everything runs through the Makefile

Add a target rather than documenting a bare command. Targets must be idempotent and
safe to re-run. `make` with no argument runs `validate build-public`.

### 4.4 Commits

- Conventional prefixes: `feat:`, `fix:`, `data:`, `copy:`, `docs:`, `chore:`.
- `data:` commits touch only `data/` and must state the source in the body.
- Never commit files over 25 MB. Rasters go to `data/raw/` (gitignored) and are
  fetched by script.
- Never commit credentials, EarthExplorer logins, or unredacted declaration PDFs.

---

## 5. How to work

### 5.1 Scope discipline

The project is tiered (README §Scope). Tier 1 is the Bear River Canal corridor in
Meadow Vista. Do not start Tier 2 or Tier 3 work, or widen the AOI, unless the task
explicitly says so. Breadth is the failure mode that kills this project.

### 5.2 Before writing code

Check whether a script already covers the step. This repo should stay small. Prefer
extending `scripts/` over adding new entry points.

### 5.3 Validation before commit

Run `make validate`. It checks:
1. JSON Schema conformance for all files in `data/authoritative/`.
2. Referential integrity (`support.csv` → alignments and observations).
3. No orphan alignments.
4. Temporal coherence (`earliest_known_open <= latest_known_open`, etc.).
5. Geometry validity and CRS.
6. Restricted-field leakage in `build/public/`.

A failing validation is a stop condition. Do not commit around it.

### 5.4 When you are uncertain

Append to `docs/open-questions.md` with a date, the question, what you tried, and what
a human would need to resolve it. This is preferred over a plausible guess, every time.

### 5.5 Do not

- Do not add a database, a backend service, or an API. The deliverable is static files.
- Do not add analytics, telemetry, or third-party trackers.
- Do not use `localStorage` or any browser storage in the viewer.
- Do not auto-generate trail "history" prose from an LLM into `data/`. Narrative fields
  are human-authored and human-attributed.
- Do not rewrite git history on `main`.

---

## 6. Definitions

| Term | Meaning |
| --- | --- |
| **Trail** | A persistent named corridor concept. Has many alignments over time. |
| **Alignment** | One dated geometry version of a trail. The unit that gets rendered. |
| **Observation** | One dated piece of evidence: a map sheet, aerial frame, plan, recorded map, declaration, photo. |
| **Support** | A link from an alignment to an observation, with a role and a confidence. |
| **Berm side** | Downhill side of the Bear River Canal (northwestern), single-track. |
| **Bank side** | Uphill side (southeastern), maintenance road. |
| **AOI** | Area of interest. Tier 1 AOI is defined in `data/sources/aoi_tier1.geojson`. |
