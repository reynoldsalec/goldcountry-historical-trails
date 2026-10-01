# AGENTS.md

Operating rules for any agent (or human) working in this repository.

Read this file and `README.md` before your first edit in a session. If a rule here
conflicts with an instruction in a task prompt, stop and ask rather than guessing.

---

## 1. What this project is

**Active MVP, revised 2026-09-28:** a static Auburn historical map browser. Users
page through the 1953 base topo, 1973 photorevision, 1975 orthophotoquad and 1981
photorevision while retaining the same map camera. README and
`docs/implementation-plan.md` define this bounded release; `docs/mvp-runbook.md`
is its acceptance checklist. These documents are plans, not proof of implementation.

**Expansion authorized 2026-09-29 (issue #55):** the owner approved nine editions in
this order: sacramento-1891, auburn-1944, auburn-1953, auburn-1973, auburn-1975,
auburn-1981, sacramento-1994, auburn-2018, auburn-2021. The 1891 and 1994 editions
are regional Sacramento sheets at 1:125,000 and 1:100,000; label them so, never as
Auburn 7.5-minute maps. Pre-1950 sheets may be shown as raster display context. This
replaces the four-edition cap and the 1950 start date for raster display only. It
does not relax any §2 safeguard or expand trail-data claims.

The countywide Nevada/Placer temporal foot-trail atlas remains a long-term program.
Its preserved roadmap is `docs/countywide-roadmap.md`; it is not the current MVP gate.
Do not require trail identification, digitizing, four county/era batches, new aerial
acquisition, restricted hosting or completed countywide research for the map browser.

The evidence safeguards below still apply. The MVP shows original source rasters,
not reconstructed trail geometry or public-access claims. It may show context across
the original Auburn sheet, including outside Placer County; that does not expand the
future authoritative trail dataset's county scope.

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
- Public USGS TIFF retrieval receipts live in `data/sources/retrievals.jsonl`.
  Commit the receipts, not raw bytes. Record SHA-256, byte count, source identifiers,
  relative storage path, and observed UTC retrieval time for new downloads. For
  existing files without retrieval records, use `retrieved_at: null`; file modification
  time is not proof of retrieval time.
- New TIFF names use `data/raw/topo/sha256/<first-two-hash-characters>/<sha256>.tif`.
  Keep existing raw filenames unchanged. A receipt maps either naming convention to
  its source. Verify known bytes before reuse; never replace a hash mismatch.
- Use `make backup-sources` and `make verify-backup` for the separate raw-source
  archive. Configure its root through `TRAIL_ARCHIVE_ROOT`; the root may be a symlink.
  Backups are additive, verified copies, not a mirror that deletes older evidence.

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

The future trail atlas has two audience builds. The current raster-only MVP has
only a public allowlisted build and must not import authoritative/restricted records.
Authenticated/restricted build implementation is deferred, not its security safeguards.

For the future atlas, two builds come from one dataset:

- **public** — no parcel APNs, no owner names, no declarant names, no restricted
  observations, no document links to unpublished records.
- **restricted** — everything, for board and counsel use, served behind auth.

Fields marked `sensitivity: restricted` in the schemas must never reach `build/public/`.
`scripts/validate.py` includes a leak test that scans the public build output for
restricted values and fails the build on any hit. Do not weaken or skip that test.

### 2.6 No legal assertions in UI copy

The viewer describes what documents show. It does not state that the public holds a
right, that a parcel is burdened, or that a closure is unlawful. Describe the trail
depiction and its source date. A mapped foot trail does not establish public access.

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
| Raster output | MVP: COG intermediates plus static XYZ PNG tiles; raster PMTiles deferred |
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
- MVP raster tiling: GDAL-based static XYZ PNG pipeline, versions pinned during implementation.
- Future vector tiling: `tippecanoe`; not an MVP prerequisite. PMTiles packaging is deferred.
- Frontend: vanilla TypeScript + MapLibre GL JS; `pmtiles` is deferred. No React, no build
  framework beyond `vite`. Keep the viewer readable by a volunteer.
- Formatting: `ruff format` for Python, `prettier` for TS/JS/JSON/Markdown.

### 4.3 Everything runs through the Makefile

Add a target rather than documenting a bare command. Targets must be idempotent and
safe to re-run. Current bare `make` still runs the legacy `validate build-public`
placeholder flow. D4 must build real public output before final validation. Until then,
use existing regression targets and label future demo targets as unimplemented.

### 4.4 Commits

- Conventional prefixes: `feat:`, `fix:`, `data:`, `copy:`, `docs:`, `chore:`.
- `data:` commits touch only `data/` and must state the source in the body.
- Never commit files over 25 MB. Rasters go to `data/raw/` (gitignored) and are
  fetched by script.
- Never commit credentials, EarthExplorer logins, or unredacted declaration PDFs.

---

## 5. How to work

### 5.1 Scope discipline

The owner selected the Auburn map browser as the next MVP: four editions in D1–D4,
then the nine-edition expansion of §1. Implement D1–D4 and the expansion steps (E1
onward) from `docs/implementation-plan.md` only when authorized. Use an explicit source
allowlist, common mapped footprint and honest date cards. Existing raw bytes, receipts,
research inventory and schemas remain intact. No synthetic trails reach the browser.
The US Topo PDFs have their own receipt ledger, `data/sources/demo-pdf-retrievals.jsonl`;
do not force them into `retrievals.jsonl`.

The countywide atlas and its M0–M5 roadmap are deferred, not silently marked complete.
`make coverage-ready` remains the old countywide release check; do not weaken it and
do not make it a prerequisite for the demo. New demo targets must have their own
artifact, source, privacy and browser gates. Preserve existing regression suites.

No automatic GitHub milestone migration: existing issues and Looper plans are not
rewritten by these documents. Reconcile/create a separate demo issue set before a
new dispatch. Do not resume an old countywide milestone to implement the new scope.

For future trail work, both counties from 1950 onward remain in scope; legacy tier
filters impose no priority. Roads/canals are not trails without evidence, modern lines
cannot be projected backward, and pre-1950 context does not establish later presence.

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
| **Berm side / bank side** | Legacy canal-specific alignment terms. Apply only where a source supports the distinction; they do not classify foot trails across the counties. |
| **AOI** | Area of interest. `data/sources/aoi_counties.geojson` bounds the countywide project, including digitizing. `data/sources/aoi_tier1.geojson` is an optional legacy work area. |
