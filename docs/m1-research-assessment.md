# M1 research assessment — 2026-09-18 UTC

**M1 is not complete.** This is an agent-performed discovery and readiness assessment,
not a human source review or acceptance record. Follow [the human runbook](m1-human-runbook.md).

## Authority and boundary of this work

Baseline: `main` / `origin/main` at `3f67c0e10a9977bc10abd40a287ce32b0a399197`.
The checkout was clean before creating `docs/m1-human-research-runbook`.
M0's accepted record is [issue #1](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/1#issuecomment-5718453615).
M1 coding PRs #30–#35 are merged. The full #2 and #15–#23 bodies and comments
were read and saved in `m1-research-evidence/issue-contracts.json`; #15–#23 were
open with no comments at retrieval. This assessment PR closes none of them.

The labels “researcher” and “source operator” do not make every substep human-only.
Public discovery, metadata transcription, link/access probes, deterministic spatial
intersection, hashes and tests are automatable. Contracts explicitly retain human
citation/footprint checks (#15–#16), frame metadata/access review (#17), actual source
examination/feature dating (#18–#21), and manual final acceptance (#23).
`schema/coverage.schema.json` also defines a review as a human examination and notes
as human-authored. No agent-written review, person identifier, review timestamp,
trail-history narrative, observation, or ready batch was added.

This PR delivers documentation and staging evidence, not a combined implementation
of nine child issues. Promotion to `coverage.json` remains serialized per child and
requires the prescribed checks. The staging files use their own documented shape;
they are **not** drop-in coverage records. Existing inventory gaps stay visible.
No source has been promoted to `verification: verified` by this assessment.

## Autonomous work completed

### Modern USGS metadata: both full county bounding boxes

Two actual TNM `US Topo` queries retrieved 222 and 320 records respectively;
returned count and unique `sourceId` count both matched each response's `total`.
These are bounding-box results, not counts of accepted county sources.[16][17]

A deterministic positive-area intersection against committed county parts reduced
these to the following metadata leads. This calculation uses the API bounding boxes,
not manually verified map neatlines; counts overlap across counties and must not be
summed as unique maps. Publication dates do not establish feature observation dates.

| County | County-intersecting records | 2000s publication | 2010s publication | 2020s publication |
| --- | ---: | ---: | ---: | ---: |
| Nevada (06057) | 128 | 0 | 96 | 32 |
| Placer (06061) | 182 | 0 | 132 | 50 |

Evidence and reproducible method:

- `m1-research-evidence/tnm-nevada.json` and `tnm-placer.json`: exact request URLs,
  UTC observations and unmodified browser response text. Queries were not date-filtered.
- `modern-map-triage.json`: exact publisher IDs, dates, bounds, PDF and metadata URLs,
  format, byte-size metadata and computed reference-cell IDs for each intersecting item.
- `modern-review-queue.json`: all county reference cells by later publication decade,
  including explicit no-lead lists. Nevada has 32 reference cells and Placer 44;
  each has metadata leads in the 2010s and 2020s. All cells have no 2000s lead in
  **these queries**, not proof of absent sources or trails.
- Calculation: parse `items`; assert `len(items) == total == unique(sourceId)`;
  construct EPSG:4326 boxes from `minX,minY,maxX,maxY`; retain positive-area
  intersection with each county polygon; link only grid cells whose intersection
  with that box **and the county** has positive area; group by publication year decade.
  No geometry was invented or added to authoritative data.

All item rights remain `unknown` in staging until item-level metadata is checked.
PDF URLs were discovered, not full PDF acquisitions; no bulk downloads were made.
The small `tnm-modern.json` probe preceded the complete county-box queries and is
not the basis of the counts above. A human should check citation, footprint and
lineage before importing candidates. The absence of 2000s results requires other
collections/searches, not a temporal interpolation from modern maps.

### Official county agency sources and license checks

**Nevada:** the county landing page links final-plan chapters, including “Chapter
4-6 State of the System.” This is a concrete agency-record lead, not a verified
trail observation or a mapped extent.[3] See `nevada-plan.json`, `links` entries:

- `https://www.nevadacountyca.gov/DocumentCenter/View/53512/NevCo-RRMP_Chp-4-6_Final-Draft_240516`
- `https://www.nevadacountyca.gov/DocumentCenter/View/53511/NevCo-RRMP_Chp-0-3_Final-Draft_240516`

These PDF contents were not inspected; a date-like filename is not a verified source
date. Check title/adoption pages, figure legends, historical citations and geographic
scope. The earlier western-county plan at DocumentCenter item 14259 is a search-only
lead in `discovery-1.json`, not an examined PDF. Neither western coverage nor a county
landing page establishes full eastern-county coverage.

**Placer:** the county page says the plan was approved in 2022, links Volume 2's
trail inventory and recommendations, and identifies Appendix D as a detailed Trail
Atlas organized by community/specific plan. It also explicitly distinguishes proposed
projects from approval of new trails.[6] See `placer-plan.json`, `links` entries:

- `https://www.placer.ca.gov/DocumentCenter/View/79488/Placer-Parks--Trails-Plan--Volume-2`
- `https://www.placer.ca.gov/DocumentCenter/View/79489/Placer-Parks--Trails-Plan--Appendix-D`

These are exact discovered document links, not fabricated page/feature locators.
The human must read the actual PDFs and distinguish existing, planned, motorized,
bicycle-only and foot-trail features. No map image was interpreted here.

**Rights conflict — stop the affected classification/publication step:** both county
website copyright pages assert “All rights reserved.”[22][23] AGENTS §2.7 broadly
labels county records public-domain; that blanket statement is not item-specific
redistribution evidence for these pages, third-party maps or attached imagery.
Do not silently resolve this discrepancy, mark these sources public-domain, or
publish their imagery. Ask the owner/researcher for item-level terms or an explicit
policy clarification. Retain `rights: unknown` until resolved. Access to these
landing pages required no login/payment; attached-document license and access checks
remain separate tasks. No external contact or purchase was made.

### Aerial discovery: a public route exists without EarthExplorer credentials

The previous repository statement that FrameFinder's configuration prevents all
automatic enumeration is too broad: UCSB's public documentation links county flight
catalogs and the scanned-image directory as alternatives.[11] The browser's FrameFinder
page remained blank on two attempts; that is an observed UI limitation, not evidence
that the collection is unavailable. Public county catalogs listed 37 Nevada and 76
Placer flights; unique flight-report links were counted and matched those totals.[18][19]

A bounded follow-up located **flight CAS-4042**. Its report specifies **1974-03-14**,
Nevada County / Grass Valley, 1:16,000, and one photograph; it warns that the scale
stamped on the frame is incorrect. Copyright is attributed to Cartwright Aerial
Surveys.[20] The actual scanned-image directory lists **`cas-4042_1.tif`**.[26]

- Flight report: `https://mil.library.ucsb.edu/apcatalog/report/report.php?filed_by=CAS-4042`
- Index: `https://mil.library.ucsb.edu/ap_indexes/cas4042/CAS_4042.pdf`
- Scan: `https://mil.library.ucsb.edu/ap_images/cas-4042/cas-4042_1.tif`
- Evidence: `ucsb-cas4042.json` (catalog fields), `ucsb-cas4042-index.json` (index link),
  `aerial-index-extract.json` (index text extraction), `ucsb-cas4042-scans.json`
  (filename), `aerial-access-probe.json` (actual HTTP probe).

At `2026-09-18T00:08:59Z`, a **16-byte range request**, without credentials,
returned HTTP 206, `image/tiff`, `Content-Range: bytes 0-15/29520680`, and a
little-endian TIFF signature. This verifies that a scan endpoint serves TIFF bytes,
not merely a thumbnail. It does **not** prove full-file completeness, readable image
quality, exact printed frame identity, or footprint. No full scan was downloaded,
no aerial retrieval receipt was fabricated, and no footprint was guessed from “Grass
Valley.” The catalog/index must be visually matched to the scan by the researcher.
The published filename is a locator, not yet a human-confirmed printed frame ID.

The fallback flight report **PAI-Tahoe-50** is dated 1950-09-23, lists Placer among
several counties, describes C-112 frame-number ranges, and prints uncertain copyright
as “Pacific Air Industries?”. This is a flight lead, not a selected frame.[21]

UCSB's policy states that on-demand aerial scanning stopped on June 14, 2024, while
existing/newly digitized scans are available free; republication permission must be
obtained from the copyright holder where applicable. Free access is not a publication
license.[12] Prefer an already scanned frame. Do not request a paid scan or contact an
archive on the user's behalf. Unknown rights exclude public tiles but do not by
 themselves satisfy or defeat the internal-review requirement; respect any actual
use restriction. #17 stays open for footprint, frame/scan matching and human access
review. M2 manual GCP work has not begun.

## Deterministic readiness and preservation checks

Actual command results are in `m1-research-evidence/initial-checks.json` (local
checkout prefixes redacted to `<repo>`). Its topo-test output was truncated by the
original capture; the complete rerun is in `completion-checks.json`, alongside fresh
validation, regression, release-gate and archive checks. `additional-checks.json`
records the final four table rows; `numeric-verification.json` records offline
recalculation of metadata counts, flight-link counts, receipt digest and AOI difference.
These were run on this baseline during this assessment, not copied from issue comments.

| Command | Actual result |
| --- | --- |
| `make lint` | exit 0; 15 files formatted; all checks passed |
| `make validate` | exit 0; fixture dataset validated; 91 source hashes match; 504 coverage cells valid |
| `make test-topo` | exit 0; 53 passed, 8 existing rasterio deprecation warnings |
| `make test-validation` | exit 0; 84 passed |
| `make test-coverage` | exit 0; 200 passed |
| `make coverage-ready` | exit 2; seven unmet release checks (aerial plus three batch checks per county) |
| `make verify-sources` | exit 0; 91 sources match SHA-256, zero local copies absent |
| `make verify-backup` | exit 2; archive parent unavailable; mount the drive first |
| `make coverage-grid` | exit 0; 63 cells; no tracked change |
| `make coverage-refresh THROUGH_DECADE=2020` | exit 0; 504 cells, 310 with source reference; no tracked change |
| `make coverage-report` | exit 0; 504 cells; no tracked change |
| `make topo-plan` | exit 0; 615 selected, 91 present, 524 to fetch (5.4 GB); dry-run only |

The final four rows are independent additional probes; do not run the unselected
plan as an acquisition. No `fetch-topo`, `fetch-topo-selected`, `catalog-sources`,
`restore-sources` or `backup-sources` was run. #22's approved selection does not exist
and its dependencies are not accepted; missing archive storage is a further blocker.
No replacement mount directory was created. No raw file or receipt was changed.

Receipt ledger SHA-256:
`3bfbcbf64f9e60a5ef3836a2d4d5239959280fe222392f47ad243b91ebb4fe20`.
This is the current local ledger digest, **not a newly verified archive snapshot**.
`baseline.json` records the counts/digest and missing selection. Existing 91 files
are not proof that the eventual both-county reviewed selection has been acquired.
`build/public` is absent: ordinary validation's leak-check skip is not a publication
safety check. Authoritative records remain explicitly synthetic fixtures.

## AOI follow-up, not a scope expansion

The local dissolved AOI is not exactly equal to the union of committed county parts;
computed symmetric difference is `5.1999998326998494e-11` square degrees. This is a
coordinate-space difference, not a claim about ground area. The dissolved properties
lack an attribution field and retain an obsolete “not a digitizing bound” role string
(`baseline.json`). The earlier #2 comment reports TIGERweb one-vertex drift.
This session compared committed geometry; it did not requery TIGERweb or establish
when drift occurred. Existing grid/refresh/validation passed unchanged. Leave files
untouched; owner/GIS reviewer should decide a separate provenance reconciliation
before a future AOI refresh. The approved per-county polygons are internal bookkeeping,
not a requirement for visible county separation in the viewer.

## What genuinely remains human-driven

- Researcher: citation/footprint checks, source-specific rights ambiguity, faithful
  notes, targeted 2000s and land-management/agency follow-up, and coverage-gap account.
- Researcher with GIS assistance: match one actual scan to frame metadata and establish
  dated footprint; authorize any login/contact/physical visit rather than assuming it.
- GIS reviewer: readable-scale foot-trail identity, precise feature locator, base vs
  revision dating and justified county/decade batches. Map omission never means absence.
- Source operator: choose/mount the real archive and approve the reviewed download
  plan; automation can then acquire, verify and back up without historical judgment.
- Engineering reviewer/owner: manually audit sources, batches, archive and all children,
  accept #23/#2 explicitly, and only then authorize M2.

The requested automation was performed without commissioning a coder. No code/schema
change is necessary for these documentation and metadata checks. A first bounded
HTTP probe failed because the project lacks `requests`; it was retried successfully
with Python's standard-library HTTP client without installing anything.

## Sources

[3] https://www.nevadacountyca.gov/3641/Recreation-and-Resiliency-Master-Plan — Recreation and Resiliency Master Plan | Nevada County, CA
[6] https://www.placer.ca.gov/9724/Parks-and-Trails-Master-Plan — Parks and Trails Master Plan | Placer County, CA
[11] https://www.library.ucsb.edu/geospatial/finding-airphotos — Finding Aerial Photographs | UCSB Library
[12] https://www.library.ucsb.edu/geospatial/policies-and-fees — Policies and Fees | UCSB Library
[16] https://tnmaccess.nationalmap.gov/api/v1/products?datasets=US%20Topo&bbox=-121.279784,39.00516,-120.003773,39.52692&max=1000
[17] https://tnmaccess.nationalmap.gov/api/v1/products?datasets=US%20Topo&bbox=-121.484442,38.711395,-120.002461,39.316496&max=1000
[18] https://mil.library.ucsb.edu/apcatalog/ap_indexes/county.php?county_id=213&state_id=5
[19] https://mil.library.ucsb.edu/apcatalog/ap_indexes/county.php?county_id=215&state_id=5
[20] https://mil.library.ucsb.edu/apcatalog/report/report.php?filed_by=CAS-4042
[21] https://mil.library.ucsb.edu/apcatalog/report/report.php?filed_by=PAI-Tahoe-50
[22] https://www.nevadacountyca.gov/site/copyright
[23] https://www.placer.ca.gov/site/copyright
[26] https://mil.library.ucsb.edu/ap_images/cas-4042
