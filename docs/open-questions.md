# Open questions

> **Scope update — 2026-09-28:** the next MVP is the [Auburn map browser](../README.md).
> This document retains countywide research history/requirements; those requirements
> are deferred and are not the new demo gate. Use the [active runbook](mvp-runbook.md)
> and [implementation plan](implementation-plan.md). No historical evidence or issue
> acceptance is changed by this notice.

Gaps and ambiguities that need a human decision. Append with a date, the question, what
was tried, and what would resolve it (AGENTS.md §5.4). Do not resolve one by guessing.

Current scope: historical foot trails throughout Nevada and Placer Counties from 1950
to the present. Earlier entries retain the research history. References to Tier 1,
the 1967–1972 priority window, and a required 19th-century layer are superseded by the
2026-09-16 scope correction below and must not guide new work.

---

## 2026-08-30 — Which topo date dates an observation?

**Status, 2026-09-16:** the acquisition review confirmed that `content_year` is the
maximum of map, photo-revision, aerial-photo, and field-check years. It is a sorting
aid, not the date of every depicted feature. The proposed observation-dating rules
below remain unresolved and require inspection of the relevant base and revision.

**Question.** A USGS sheet carries up to six dates: date on map, imprint year, aerial
photo year, field check year, photo revision year, edit year. `CA_Auburn_100355_1953_24000`
is titled 1953, was imprinted in 1981, and was photo-revised in 1981 from 1978 aerials.
A trail traced off that sheet is evidence about *what year*?

The four-field temporal model (AGENTS.md §2.3) makes this sharper, not softer. If a
segment appears on that sheet, is `earliest_known_open` 1953 (the sheet's nominal date,
which its base planimetry does reflect) or 1978 (the aerials the revision was drawn
from)? And if the segment appears on the 1953 original *and* the 1981 revision, that is
two observations, not one.

**What was tried.** `scripts/fetch_topoview.py index` records every date field per sheet
in `data/sources/topo_index.csv` rather than choosing among them, and derives one
convenience column, `content_year` — the latest of photo revision, aerial photo and field
check — as the most recent ground condition the sheet can attest to. 149 of the 615
indexed sheets have a `content_year` later than their printed date; the largest gap is 28
years. No script picks a date for an observation.

**To resolve.** Decide the rule for M3, and write it into `docs/data-model.md`. A
defensible starting position is that a photo-revised sheet is *two* observations — the
base compilation at `date_on_map` and the revision at `content_year` — since the revision
overprints only changed features, usually in purple. Someone should look at an actual
1973-revised Auburn sheet and confirm whether the corridor is on the base or the
overprint before this is decided. This is not a question a script can settle.

---

## 2026-08-30 — No aerial frames identified for the 1967–1972 hinge

**Status, 2026-09-16:** retained as a local research gap. The legal framing and narrow
date priority below belong to the previous plan. Countywide aerial coverage from 1950
onward is the current task; this locality is not a prerequisite.

**Question.** Which aerial flights and frames cover the Bear River Canal corridor between
1967 and 1972, the window Civil Code 1009 turns on (README §1)?

**What was tried.** Both candidate indexes were probed and neither can be queried by this
repo:

- **USGS EarthExplorer** (`earthexplorer.usgs.gov`, Aerial Photo Single Frames) needs a
  free USGS ERS account to search and a token for the M2M API. No credentials are held
  here and none may be committed (AGENTS.md §4.4).
- **UCSB FrameFinder** (`mil.library.ucsb.edu/ap_indexes/FrameFinder/`) is an Esri Web
  AppBuilder application. Its `config.json` was fetched and contains only an ArcGIS
  geometry utility endpoint, no queryable feature service, so its flights cannot be
  enumerated without reverse-engineering the app further.

Both are recorded in `data/sources/sources.yml` as candidates with `blocked_on` set. **No
frame IDs are recorded, because none were verified and inventing one is forbidden**
(AGENTS.md §2.1).

**What partially covers the gap.** All three Tier 1 7.5-minute quads have a 1973 photo
revision flown in 1973, and originals from 1949–1953. That brackets the window but does
not sit inside it.

**To resolve.** A human with a USGS ERS account should search EarthExplorer for
single-frame aerials over the corridor for 1965–1975, and check FrameFinder for
Cartwright Aerial Surveys flights in the same window. Record flight ID, date, scale and
frame numbers in `data/sources/sources.yml`. Frames then need manual GCPs committed to
`data/sources/gcp/` (AGENTS.md §3).

---

## 2026-08-30 — No 19th-century Placer County map located

**Status, 2026-09-16:** outside the core 1950-to-present study period. Retained as
background research, not a blocking requirement.

**Question.** Tier 1 lies in Placer County. What 19c source shows the corridor there?

**What was tried.** The David Rumsey collection was searched. It holds Hartwell's 1880
*Map of Nevada County* (1:79,200, `RUMSEY~8~1~200202~3000113`), whose title advertises
"Mining Ditches" — the Bear River Canal is one, so it is the strongest 19c candidate
found. But it covers **Nevada County only**. The earliest county-level *Placer* sheet in
the collection is Weber 1914 (1:177,000), which is not 19c and belongs to no decade the
viewer renders. Britton & Rey 1857 exists but at 1:1,520,640 puts the entire corridor in
about 5 mm.

The remaining candidate is BLM GLO township plats and survey field notes
(`glorecords.blm.gov`), recorded in `data/sources/sources.yml`. **The specific Mount
Diablo Meridian townships and ranges covering the corridor have not been identified, so
no plat is cited** — citing an unverified one would be fabrication (AGENTS.md §2.1).

**To resolve.** Identify the township/range grid over `data/sources/aoi_tier1.geojson`,
then pull the corresponding GLO plats and field notes and record them. Whether Hartwell
1880 covers any part of the Tier 1 corridor also needs checking: the Placer/Nevada county
line runs near the corridor and the sheet may reach it.

---

## 2026-08-30 — AOI: both files now built from online sources

**Status, 2026-09-16:** both files remain available, but the county boundary now scopes
digitizing as well as acquisition. The corridor buffer and connector questions below
only concern the optional legacy work area. They do not restrict countywide mapping.

**Resolved.** `data/sources/aoi_tier1.geojson` now exists, derived from OpenStreetMap via
a date-pinned Overpass attic query (`make fetch-aoi`). Nothing was hand-drawn. OSM carries
the corridor in detail: `Bear River Canal` (14 ways, merging to one 20.77 mi line), a
named `Bear River Canal Trail` (8 ways, 5.03 mi, `highway=path`, `surface=dirt`), and
`Bowman Feeder Canal`. The canal was cut between its Crother Road and Placer Hills Road
crossings — 5.03 mi — unioned with the trail and the feeder, and buffered 250 m, giving
1.43 sq mi. It sits fully inside the acquisition AOI, which was checked.

The corridor identity question is settled: of the four canals in the area, `Bear River
Canal` is the only one touching all three named roads (Crother, Meadow Gate, Placer
Hills, all at 0 m). `Boardman Canal` is 64 m from Placer Hills Road and is a different
corridor. The README naming is correct.

**Still open: the 250 m buffer is a default, not a decision.** It was chosen to be
generous — a tight buffer around the modern trace would assume historical alignments
followed it, the inference AGENTS.md §2.1 forbids — but nobody has confirmed it is right.
For scale: 100 m gives 0.68 sq mi, 250 m gives 1.43, 400 m gives 2.18, 800 m gives 4.33.
Change with `uv run python scripts/fetch_aoi.py tier1 --buffer N`. Someone who knows how
far the 19c and mid-century alignments wander from the present ditch should set it.

**Still open: "Meadow Vista connectors".** README §2 includes them in Tier 1 but does not
name them, so they are not in the AOI. OSM has a `Sugar Pine Mountain Trail` touching the
corridor, which matches the `sugar-pine` value in the `corridor` enum, and `Simpson
Spillway` and `Combie Ophir Canal` are nearby, matching `simpson` and `combie`. That the
enum maps onto real named OSM features is a good sign, but which of them count as Tier 1
connectors is a scoping decision, not something to infer.

**Caveat carried into the data.** The AOI records `rights: odbl` and the required
attribution. OSM is not an authoritative record of historical trail extent, so no OSM way
may become an alignment in `data/authoritative/` (AGENTS.md §2.1). The file states this in
its own `role` property.

---

## 2026-08-29 — Temporal coherence: which comparisons are in scope?

**Question.** AGENTS.md §5.3.4 says "temporal coherence (`earliest_known_open <=
latest_known_open`, etc.)". The "etc." is ambiguous. Within-pair comparisons are obvious.
Cross-pair ones are not: should `latest_known_open <= earliest_known_closed` hold?

**What was tried.** `scripts/validate.py` enforces only the two within-pair comparisons
(open pair, closed pair) plus `date_start <= date_end` on observations. It deliberately
does **not** enforce any open-vs-closed ordering, because a corridor that is documented
closed in 1988 and documented open again in 2001 is a real and important pattern, and a
cross-pair rule would reject it.

**To resolve.** Confirm that reopening is in scope for the model. If it is, the current
behaviour is right and this note can be closed. If a trail is never expected to reopen
within the dataset, add the cross-pair check.

---

## 2026-08-29 — A bare `YYYY` on the "latest" side is widened to 31 December

**Question.** Dates may be `YYYY` or `YYYY-MM-DD`. Comparing `earliest_known_open =
"1954-06-01"` against `latest_known_open = "1954"` is undefined: is the bare year the
start of 1954 or the whole of it?

**What was tried.** `as_bound()` widens a bare year to `(Y, 12, 31)` on the upper side and
`(Y, 1, 1)` on the lower, so a bare year means the whole year. This avoids failing records
that are actually coherent.

**To resolve.** Confirm the interpretation. It matters again in M4, where the decade
stepper has to bucket the same dates (README §3, decade rendering logic).

---

## 2026-08-29 — `support.csv` has no sensitivity column

**Question.** README §3 gives alignments and observations a Sensitivity column but gives
`support.csv` none. Its `note` field is free text authored by a human summarising what a
document shows, and for a restricted declaration that note could easily name the
declarant.

**What was tried.** All five `support.csv` fields are marked `x-sensitivity: public` in
`schema/support.schema.json`, matching the README table as written.

**To resolve.** Decide whether `note` should be `restricted`, or whether the rule is that
notes on support rows pointing at a restricted observation are stripped from the public
build. The second is probably right but it is a modelling decision, not a coding one.

---

## 2026-08-29 — `.github/` is a top-level directory not in README §5

**Question.** M0 requires `.github/workflows/validate.yml`, but README §5 does not list
`.github/`, and AGENTS.md §4.1 forbids new top-level directories without updating both
files.

**What was tried.** Added `.github/workflows/validate.yml` to the README §5 layout block
so the two agree. AGENTS.md §4.1 needed no change — it defers to README for the layout.

**To resolve.** Nothing outstanding; recorded so the README edit is traceable.

---

## 2026-08-29 — Bare `make` fails during M0

**Question.** AGENTS.md §4.3 and README §6 both define `make` with no argument as
`validate build-public`. `build-public` is not implementable until M5, and per the M0
brief it exits with a "not implemented" message.

**What was tried.** `.DEFAULT_GOAL` is `all: validate build-public`, exactly as specified.
Bare `make` therefore validates successfully and then exits non-zero on `build-public`.
`make validate` is the working M0 entry point, and CI runs that target, not bare `make`.

**To resolve.** Nothing to decide — it resolves itself at M5. Flagged so nobody reads the
bare-`make` failure as a broken scaffold.

---

## 2026-08-29 — Fixture records are in `data/authoritative/`

**Question.** M0 asks for fixtures so validation has something to chew on, and README §7
puts them in `data/authoritative/`. That directory is otherwise defined as the source of
truth, and synthetic records living there is a standing hazard.

**What was tried.** Every fixture uses `fixture-` prefixed IDs, `FIXTURE`-prefixed names,
`FIXTURE DECLARANT` as the declarant, `FIXTURE-APN-000-000-00N` as APNs, and a `notes`
field saying the record is synthetic and not evidence.

**To resolve.** Delete all `fixture-*` records in M3 when the real OTCA data lands. If
that slips, consider moving fixtures to `tests/` and pointing `validate.py --data-dir` at
them, at the cost of `make validate` no longer exercising the real directory by default.

---

## 2026-08-29 — Acquisition AOI is ~2,365 sq mi, which resizes M1

**Status, 2026-09-16:** the index now records 615 sheets across both counties and the
default download is countywide. The old geographic scope and legal-date priority below
are superseded. Download batching and selection remain implementation concerns.

**Question.** Not a blocker, but M1 was scoped against a 4-mile corridor and is now scoped
against two counties. The combined AOI bbox is roughly 128 km x 90 km, about 84 cells on a
7.5-minute grid and realistically 55-65 quads once clipped to the county shapes. topoView
carries several editions per quad across 1884-2006, so `make fetch-topo` plausibly means
several hundred GeoTIFFs and multiple GB.

**What was tried.** Nothing yet — no quads have been fetched. Flagged before M1 starts
rather than at download time.

**To resolve.** Decide whether `fetch-topo` pulls every edition of every quad, or filters
by date first (the 1967-1972 hinge in README §1 argues for prioritising mid-century
editions). Also worth deciding whether it fetches lazily per-quad on demand. `data/raw/`
is gitignored and fetched by script per AGENTS.md §4.4, so nothing here threatens the
repo; it is a time and disk question.

---

## 2026-09-16 — Countywide scope and 1950 start confirmed

**Decision.** The project owner clarified that the atlas maps historical foot trails
throughout Nevada and Placer Counties from 1950 onward. README and AGENTS now apply
that scope to research, acquisition, digitizing, and the viewer. The former geographic
tiers, corridor-first requirement, 19th-century layer, and special 1967–1972 priority
are superseded. Existing source records remain available.

**What was checked.** Read the orientation documents, trail schema, Makefile, and AOI
and topo acquisition scripts. The county boundary already exists, and the topo index
and default download cover both counties. The implementation still contains a required
`tier` field, local `corridor` enums, `in_tier1`, an optional `--tier1` download filter,
and generated documentation that highlights the corridor subset. `make fetch-aoi`
still rebuilds both the county and legacy corridor files. The historical topo download
includes pre-1950 material and does not supply full coverage through the present.

**Remaining implementation work.** Migrate the schema and consumers so trails anywhere
in either county can be represented without obsolete geographic tiers. Preserve stable
IDs and provenance. Update generated reports and tool descriptions to treat the
corridor as an optional work area. Plan acquisition around the 1950-to-present study
period without discarding older immutable downloads or misdating revised maps.

**Remaining research work.** Build a coverage inventory by quadrangle or source
footprint and decade across both counties. Locate dated aerials and later maps, record
unexamined areas, and choose digitizing batches that improve coverage. Local OTCA
records can contribute without determining the countywide inventory.

**To resolve.** Implement and validate the schema/tooling migration, then populate the
coverage inventory with verified sources and explicit gaps. The geographic scope is
decided; missing evidence must be resolved through source research and human review.

---

## 2026-09-16 — Acquisition review and remaining evidence gaps

**Resolved in code.** Existing raw TIFFs are never overwritten. Downloads use unique
temporary files and fail without publication on incomplete or non-TIFF responses.
Metadata parse failures and incomplete API pagination now fail instead of publishing
an incomplete index. The generated edition report covers both counties, with offline
regeneration and download-preview Make targets.

**What was checked.** Offline regression tests exercise acquisition failures, existing
file preservation, county intersection, index IDs, and report generation. The stored
index is checked against the county boundary and its lineage-year calculation. These
checks do not independently verify each feature on a historical map or establish that
the stored online source inventory is still exhaustive.

**Still open.** Trail observation dates require human source inspection. The countywide
coverage inventory and the trail schema migration remain outstanding. Candidate aerial
flights and pre-1950 sources remain candidates. Resolve these through verified source
research; no alignment or observation was created during acquisition review.

---

## 2026-09-16 — Retrieval dates for existing raw TIFFs are unknown

**Question.** What were the original retrieval times and actual response URLs for the
91 TIFFs downloaded before retrieval receipts were implemented?

**What was tried.** The existing files were matched to the committed source index and
hashed without changing their names or bytes. No contemporaneous retrieval receipts
were available. `data/sources/retrievals.jsonl` therefore records an inventory timestamp,
SHA-256, byte count, index URL, and local path, with `retrieved_at` and `retrieval_url`
set to `null`. File modification times were not treated as retrieval evidence.

**Preservation completed.** All 91 files and an immutable receipt snapshot were copied
to `/Volumes/T7 Shield/historical-trails-backup`, then the archived files were read
back and verified against their SHA-256 values. Future downloads automatically record
observed UTC retrieval times and URLs. Backup and restore use the receipt hashes.

**To resolve.** Locate contemporaneous download logs before adding any historical
retrieval-date attestation. The present checksum inventory proves the bytes held when
inventoried, not when those files were originally downloaded.

---

## 2026-09-16 — Decade states are decided; date ranges and feature dating are not

**Decided.** Decade rendering now follows one table in README §3 and `docs/data-model.md`.
An observation dates the evidence only: nothing projects indefinitely, forward or
backward. Positive evidence in a decade gives `documented_open`, closure evidence gives
`documented_closed`, both together give `unobserved` with reason `conflicting_evidence`
and both citations retained, and `inferred_open` needs positive evidence on both sides
with no closure or unresolved range between them. `attests_alignment` supports geometry
only. `date_end` ends the evidence date range and by itself never authorizes presence
across the intervening decades; the schema description was corrected to drop the
"used 1958–present" continuous-use example. The twelve worked examples are mirrored in
`scripts/fixtures/temporal_cases.json`, which holds fixture-only IDs and synthetic dates
and never enters `data/authoritative/`.

**What this leaves open.** The 2026-08-29 entry "Temporal coherence: which comparisons
are in scope?" and the 2026-08-29 entry "A bare `YYYY` on the 'latest' side is widened to
31 December" both still stand. This decision assumes the second one's reading, that a
bare year means the whole year, and it does not settle the reopening question raised by
the first. The schema still cannot distinguish an uncertain date range from
continuous-use testimony, so a cross-decade range stays unresolved rather than being
guessed.

**To resolve.** A reviewer must supply more precise dates for any cross-decade range
before those decades can render, and must enter each further decade a source explicitly
supports as its own justified observation. Feature-level dating on revised sheets stays
in the research inventory (see the 2026-08-30 entry on which topo date dates an
observation). No real observation, feature date, or alignment was created here.

---

## 2026-09-28 — Two unverified values behind the Auburn edition manifest

**The 1975 photography day.** `data/sources/demo-editions.json` records
`photography: "1975-08-29"` for `CA_Auburn_288104_1975_24000`. The committed index holds
only `aerial_photo_year: 1975`, and `scripts/demo.py check` confirms nothing finer than the
year. The month and day come from the fixed input table in `docs/implementation-plan.md`.

*What was tried.* Every per-sheet column in `data/sources/topo_index.csv`, and the GeoTIFF's
own tags (only TIFF resolution tags and `AREA_OR_POINT` are present). No network lookup was
made and the sheet margin was not read by machine.

*To resolve.* A reviewer reads the photography date off the orthophotoquad's margin, or off
its USGS metadata record at
<https://www.sciencebase.gov/catalog/item/5a8a2905e4b00f54eb3c61d4>, and either confirms
`1975-08-29` or replaces it. If it cannot be confirmed, the field becomes `"1975"` and the
source card says the day is unknown.

**The NAD27 → WGS84 transformation.** The grid-based operations `NAD27 to WGS 84 (40)` and
`(79)` need `us_noaa_cnhpgn.tif`, which the pinned PROJ 9.5.1 install does not carry, so the
crops and view bounds were derived through the Helmert operation `NAD27 to WGS 84 (6)`
(declared accuracy 7 m). `demo-check` records which operation ran and refuses a ballpark
offset, so this is disclosed rather than silent.

*To resolve.* Decide whether to vendor the NADCON grids before D2 warps anything. Installing
them will move the tiles by metres. Either way the caveat belongs on the demo's source
information, and no alignment may be digitized against these rasters until the datum
question is settled. See `docs/demo-source-review.md` §3.

---

## 2026-09-29 — Open items after acquiring the five expansion sources (issue #55)

`make expansion-check` verifies all five candidates by full-file SHA-256 against their
receipts. The items below are not resolved by that check.

**PDF georeferencing was not read by GDAL.** The GDAL 3.10.3 inside the rasterio wheel
has a PDF driver that cannot open PDFs (no Poppler or PDFium backend), so
`expansion-check` lists "georeferencing not inspected" for auburn-2018 and auburn-2021.
A byte scan of both PDFs found ISO 32000 `/Measure /Subtype /GEO` dictionaries. The
visible ones use a World Mercator WGS 84 WKT and cover about 121.25°W–120.87°W,
38.75°N–39.12°N, which is wider than the quadrangle, plus a state-scale locator. It is
not known which dictionary registers the map body.

*To resolve.* The next expansion step pins a PDF-capable GDAL (or a tested
geospatial-preserving alternative), reads the map-body georeferencing and layer list,
and fails if either is absent.

**The 2018 metadata bounding box is transposed.** In
`CA_Auburn_20180924_TM_geo.xml` `westbc` is -121.0 and `eastbc` is -121.125. The
catalog records the values as published and marks them unusable as a crop.

**Credit-note transcription needs human confirmation.** The `credit_note` values in
`data/sources/demo-pdf-sources.json` come from PyMuPDF 1.28.2 text extraction of the
lower-left collar, checked by the agent against a render. The tool was run ad hoc and
is not a project dependency. Leader dots and justified spacing were collapsed.

*To resolve.* A reviewer compares each printed credit note with the catalog and
records the result in the runbook worksheet.

**Embedded CRS of the reused TIFFs.** The 1891 Sacramento GeoTIFF carries NAD27
polyconic georeferencing (central meridian 121°15′W), but `topo_index.csv` records its
datum and projection as "Unstated". The 1994 Sacramento GeoTIFF carries NAD27
transverse Mercator with central meridian 121°30′W, while the index says Universal
Transverse Mercator. The NAD27 on an 1891 sheet is the georeferencer's choice, not a
datum printed on the sheet.

*To resolve.* Registration review in a later expansion step decides whether these
sheets can share the Auburn camera and records any offset on the source card.

**PDF backup is not verified.** `make backup-sources` and `make verify-backup` read only
`retrievals.jsonl`. The two PDFs under `data/raw/us-topo/` have no archive copy.

*To resolve.* Extend `scripts/source_archive.py` to include
`demo-pdf-retrievals.jsonl`, or accept re-download by hash as the recovery path.

**2026-09-29 (#57): registration of the 1891 and 1944 sheets against Auburn is not
established.** `make expansion-rasters` ran a phase-correlation check against
auburn-1953 over five dispersed 4 km patches. It found no distinct peak for either
sheet (`docs/demo-processing.md` §10.3). Their only registration evidence is the
neatline check. On 1891 the east and north edges, which bound the view, are within
2.76 px (29 m). The far west edge is 4.32 px (46 m) off its graticule. The 1994 sheet
and the two US Topo maps gave 3 and 1 distinct patches each, with offsets of 3–22 m.

*To resolve.* A reviewer compares named stable features (for example river confluences
or surveyed benchmarks) across the editions in the staged tiles and records the offsets
and a verdict in the runbook worksheet (issue #38).

**2026-09-29 (#57): printed credits of the historical scans are not transcribed.**
`printed_credit_note` is `null` for all seven topoView scans in
`data/sources/demo-editions-expanded.json`. Their attribution comes from `sources.yml`
only. The two US Topo credit notes come from the catalog.

*To resolve.* Transcribe the collar credit text of each scan, if the source card needs
it, and cite the scan's sha256 as the source of the transcription.

**2026-09-29 (#57), follow-up to "Embedded CRS of the reused TIFFs":** the version-2
check now records these disagreements under `index_crs`, and positioning uses the
embedded CRS. Both regional sheets pass the neatline check on the edges that bound the
view (`docs/demo-source-review.md` §8.3). Whether the 1891 NAD27 assignment is right is
still open.

**2026-10-02: the 1916 Tahoe National Forest scan is only approximately placed.** The
sheet has no graticule. `make extra-control` fits a second-order polynomial to 73
printed township corners matched to BLM PLSS corners: RMS 381 m, worst control corner
1001 m. Thirteen town symbols checked against GNIS are 159–1294 m off. The printed
grid follows the 1916 surveys and the paper is folded, so a polynomial cannot remove
all of the error. AGENTS.md §3 allows only polynomial 1 or 2 for map sheets.

*To resolve.* A reviewer decides whether this accuracy is enough for display. A
piecewise or thin-plate warp would need an explicit exception to AGENTS.md §3.

**2026-10-02: further early Forest Service and county maps are not integrated.**
Found but not added in this run:
- Archive.org USDA NAL scans: Tahoe NF 1915 (CAT31437404), Eldorado NF 1914
  (CAT31437379) and 1916 (CAT10680176), and the Tahoe forest atlas folio of 1909
  (CAT31301920). Each carries the same "not in copyright" statement. Each needs its
  own control points, and none covers the Auburn quadrangle.
- Library of Congress, Placer County, California State Mining Bureau, 1902
  (loc.gov item 2007633931). It covers Auburn and has a township grid, so it needs
  the same control-point method.
- Huntington ephMPCALIF0187 route map: the scan is 825 px, at about 1:1,000,000, and
  its rights page was not readable (HTTP 429).
- UC Davis 1930/1934/1949 holdings and the NFSL collections: no online map images.

*To resolve.* Add each sheet as a `gcp_polynomial` entry in
`data/sources/demo-extra-editions.json`, with seed corners and checkpoints read from
the scan.
