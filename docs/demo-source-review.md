# Demo source review — the four Auburn editions

Automated record of what `scripts/demo.py` verified for the Auburn map-browser manifest
(`data/sources/demo-editions.json`), implementation plan D1.

**Inspection method: automated.** Every value below came from a script run, not from a
person examining a sheet. No human source review has happened and none is recorded here.
Human acceptance belongs to the runbook and to issue #38.

- Run date: 2026-09-28
- Commands: `make demo-inspect`, `make demo-check`
- Runtime: Python 3.11.15, rasterio 1.4.4 (GDAL 3.10.3), pyproj 3.7.2 (PROJ 9.5.1)
- Network: none. PROJ network access is off and nothing fetched a grid or a catalogue page.
- Writes: none to `data/raw/` or `data/sources/retrievals.jsonl`.

---

## 1. Selected inputs and verified bytes

`demo-check` resolves each source ID through `data/sources/retrievals.jsonl` and re-hashes
the file in place. Each of the four has exactly one receipt; a second receipt for the same
source ID under a different `raw_path` is rejected as ambiguous rather than picked from.
All four still live under the legacy `topo/CA_Auburn_*_geo.tif` names.

| Edition | Source ID | SHA-256 | Bytes |
| --- | --- | --- | --- |
| auburn-1953 | CA_Auburn_288101_1953_24000 | `bec9555f90f4928d219212219ed06c15c6eb94a5dd749a0aa90edb1bb416e7c5` | 12532400 |
| auburn-1973 | CA_Auburn_288103_1953_24000 | `2a4427b0969a566fd9b2ff558e2cf114ce5099f63dfc515fd8fd2a38abd25967` | 11709311 |
| auburn-1975 | CA_Auburn_288104_1975_24000 | `4d35331f4a1ff1306decd823e68de0fee02753e921d9deb7c7450a568128fde6` | 14103396 |
| auburn-1981 | CA_Auburn_288105_1953_24000 | `d5621357235c6d65ae2cdbe2265235e70b10972fcb5e2574fb7f5ff7b2313196` | 12427061 |

`python scripts/source_archive.py verify` after this work: `91 sources match SHA-256;
0 local copies absent`. Raw byte mtimes remain 2026-09-16.

Only these four files are read. A raw tree holding just them passes `demo-check`; the other
87 indexed sheets are not a prerequisite for the demo build.

## 2. Rights

`data/sources/topo_index.csv` records `rights: public_domain` for all four, as do their
receipts. `demo-check` also requires each edition's `rights` and `attribution` to equal the
`usgs-historical-topo` entry in `data/sources/sources.yml`
("Historical topographic maps: U.S. Geological Survey"). No source with unknown or
non-commercial rights is in this set.

## 3. CRS and datum transformation

Read from each GeoTIFF, never assumed:

| Edition | Datum | Projection | Scan size (px) | Pixel (m) |
| --- | --- | --- | --- | --- |
| auburn-1953 | NAD27 | American Polyconic | 6604 × 8067 | 2.032 |
| auburn-1973 | NAD27 | American Polyconic | 6608 × 8096 | 2.032 |
| auburn-1975 | NAD27 | Lambert Conic Conformal (2SP) | 6571 × 8029 | 2.032 |
| auburn-1981 | NAD27 | American Polyconic | 6608 × 8054 | 2.032 |

The 1975 orthophotoquad arrives already georeferenced in Lambert Conformal Conic. It is not
a raw aerial frame and needs no GCPs.

**Transformation that actually ran** for NAD27 → WGS84, for all four:

```
axis order change (2D) + NAD27 to WGS 84 (6) + axis order change (2D)
declared accuracy: 7.0 m
```

Better, grid-based operations were requested and are **not installed**: `NAD27 to WGS 84
(40)` and `NAD27 to WGS 84 (79)` (they need `us_noaa_cnhpgn.tif`). PROJ therefore used the
Helmert transformation above. It is a named, non-ballpark operation with a published
accuracy, so `demo-check` accepts it; `demo-check` fails outright if only a ballpark offset
were available, or if the chosen operation reported no accuracy.

Consequence to carry into D2 and into any later trail work: the WGS84 coordinates here
carry a metre-scale datum uncertainty on top of the original map's own accuracy. Installing
the NADCON grids would move them. This is a positional caveat, not a licence to nudge
geometry by hand.

## 4. Neatline residuals — scan margin excluded

The crop keeps the mapped face of each sheet and drops the decorative collar. Its boundary
is the **labelled graticule quadrilateral** from `topo_index.csv` (−121.125, 38.875,
−121.0, 39.0 NAD27, identical on all four sheets), densified along each edge and sent
through the datum operation. It is deliberately not a rectangle in the source projection:
the east and west neatlines are meridians, they converge, and the drawn line therefore
leans about 4.7 px (≈9.5 m) from the top of the sheet to the bottom. An axis-aligned crop
agrees with the drawn line only near mid-height, and cuts 6–10 m of map content at the
south corners while keeping collar at the north corners.

The scan is still read, but to **verify** rather than to seed. For each of the four edges,
two bands are profiled — one starting 15% in from each end, each 15% of the edge long, away
from the corner ticks and tie marks. The accepted line in a band is the darkest column or
row within 60 m of the projected graticule; a line that is not at least 15 grey levels
darker than its surroundings is a failure, not a guess. The **residual** is that line's
signed distance from the graticule at the band's midpoint, in pixels (1 px ≈ 2.03 m).
A residual over 3.0 px fails `demo-check`.

| Edition | west edge | east edge | north edge | south edge | max |
| --- | --- | --- | --- | --- | --- |
| auburn-1953 | north −0.53 (px 636, dark 105.9/230.0); south −0.97 (px 633, dark 81.6/223.3) | north −0.66 (px 5967, dark 74.7/196.8); south −0.26 (px 5970, dark 85.0/214.2) | west −1.35 (px 385, dark 95.1/238.3); east −1.34 (px 385, dark 67.4/219.5) | west −1.35 (px 7214, dark 75.2/213.6); east −1.33 (px 7214, dark 88.2/229.2) | 1.35 |
| auburn-1973 | north −0.34 (px 611, dark 156.7/236.7); south −0.78 (px 608, dark 112.2/231.4) | north −0.47 (px 5942, dark 101.8/210.7); south −1.07 (px 5944, dark 133.4/224.8) | west −0.03 (px 395, dark 131.4/244.6); east −0.01 (px 395, dark 134.2/227.0) | west −1.02 (px 7223, dark 116.6/226.1); east −1.00 (px 7223, dark 136.2/243.4) | 1.07 |
| auburn-1975 | north −0.47 (px 557, dark 41.9/129.8); south +0.08 (px 555, dark 58.1/138.3) | north −1.51 (px 5858, dark 58.1/204.0); south −1.10 (px 5861, dark 42.4/106.2) | west −2.61 (px 364, dark 37.2/120.7); east −2.60 (px 364, dark 30.6/82.6) | west −2.34 (px 7156, dark 45.4/236.7); east −2.32 (px 7156, dark 67.0/225.0) | 2.61 |
| auburn-1981 | north +0.21 (px 622, dark 108.5/234.2); south −0.23 (px 619, dark 133.8/232.7) | north −0.92 (px 5952, dark 133.7/223.3); south −1.51 (px 5954, dark 140.9/232.3) | west −0.79 (px 365, dark 122.8/244.2); east −0.78 (px 365, dark 121.8/228.1) | west −1.79 (px 7193, dark 122.8/221.4); east −0.77 (px 7194, dark 153.0/242.6) | 1.79 |

What these sixteen measurements say, stated as measured rather than in general terms:

- The largest deviation anywhere is **2.61 px (5.3 m)**, on the 1975 orthophotoquad's north
  edge. The three topo sheets stay within 1.79 px (3.6 m).
- The residual is the measured pixel minus the graticule pixel, so a negative value puts
  the drawn line north of the graticule on the north/south edges and west of it on the
  east/west edges. Every north and south residual is negative, and all but two of the
  eight east/west residuals are: the drawn face sits about 1–2.6 px north-west of the
  georeferencing the GeoTIFF delivers. The two ends of an edge agree to within 1.02 px in
  the worst case (the 1981 south edge) and within 0.60 px on the other fifteen edges, so
  what is left is one offset of the whole face, not the tilt the earlier axis-aligned crop
  showed.
- That single offset cuts two ways, because the crop follows the graticule. On the north
  and west edges the crop trims up to about 1 px (2 m) of map tone just inside the drawn
  line; the worst is the 1975 north edge, where the ink is rows 363–365, the orthophoto
  tone starts at row 366–367 and the graticule falls at row 366.6. On the south and east
  edges it keeps up to about 1 px of white collar past the line; the worst is the 1975
  south edge, where the ink is rows 7155–7157, the collar starts at row 7158 and the
  graticule falls at row 7158.3. The drawn ink is 2–3 px wide on all four sheets.
- `demo-check` fails outright, rather than warning, if any residual exceeds 3.0 px. The
  3.0 px limit is set from the 2.61 px measurement above, not chosen in advance.

## 5. Derived geometry

`crop_wgs84` per edition is that graticule quadrilateral, densified to 9 points per edge so
the constant-longitude and constant-latitude sides stay curves through the datum shift
instead of collapsing to chords, then expressed in WGS84 at six decimal places. Because all
four sheets carry the same graticule labels, the four crops are the same polygon, and the
common mapped footprint is that polygon exactly. `view_bounds_wgs84` is its bounding box:

```
[-121.126028, 38.874881, -121.001023, 38.99988]
```

That box is a few metres wider than the polygon itself, because the sheet edges are curves
in WGS84 rather than straight lines. D2 must keep nodata/alpha explicit so the sliver
outside the mapped face reads as "no data", not as a failed tile.

`demo-check` recomputes the crop and the bounds from the index labels and the rasters on
every run, fails if the manifest drifts by more than 1e-5 degrees, and fails if the drawn
line has moved off the graticule.

The footprint spans the whole original Auburn quadrangle, including ground outside Placer
County. That is source context only. It does not widen the county scope of the deferred
authoritative trail dataset.

## 6. Dates — what is verified and what is not

Every date in the manifest is cross-checked against the per-sheet columns of
`topo_index.csv` for that exact scan variant, never against the sheet title:

- `map_year` against `date_on_map`.
- `revision_year` against `photo_revision_year`.
- `revision_photography` against that sheet's `aerial_photo_year` (1973 and 1978).
- `base_photography` against the 1953 base sheet's `aerial_photo_year` (1952).
- `base_field_check_year` against `field_check_year` (1953; empty for the orthophotoquad).
- Both photorevisions carry `revision_field_checked: false`, and `demo-check` requires their
  `date_note` to say the revision was not field checked.
- `kind` is cross-checked against lineage: a sheet with no `field_check_year` cannot be a
  topo, and an orthophotoquad must have an aerial photography year and no field check.

**Not verified: the month and day of the 1975 photography.** `topo_index.csv` records only
`aerial_photo_year: 1975`. The manifest carries `1975-08-29` from the fixed input table in
`docs/implementation-plan.md` (issue #39). `demo-check` confirms only that the year agrees
with the index. Reading the date off the orthophotoquad's own margin, or from its ScienceBase
metadata, is open work; see `docs/open-questions.md`.

The 1981 sheet cites other source data besides its 1978 photography, so its `date_note` says
1978 does not date every revised feature.

No value here dates a mapped feature, and nothing in this task created a trail observation.
Showing one of these rasters does not assert that a road or track on it is a trail, or that
anyone may use it today.

## 7. Reproducing this

```
make demo-inspect   # locators, CRS, datum transformation, derived geometry as JSON
make demo-check     # the manifest contract plus the four sources; prints the hashes
make demo-test      # scripts/test_demo.py
```

All three read `data/raw` by default. Set `DEMO_RAW_ROOT` when the scans live in another
checkout, as they do in a worktree (`data/raw` is gitignored). The tests that need real bytes
skip when they are absent; the fixture cases run everywhere from synthetic scans.

---

## 8. The staged nine-edition manifest (version 2, issue #57)

`data/sources/demo-editions-expanded.json` is a version-2 manifest. It adds five editions
to the four above. It is staged only: `make demo-*` and `build/public` still use
`demo-editions.json`, and `demo.py cogs/rasters` refuse a version-2 manifest. The same
inspection caveat applies: every value here came from a script run on 2026-09-29. No
human reviewed a sheet.

- Commands: `make expansion-check` (runs `demo.py check --manifest
  data/sources/demo-editions-expanded.json` after the source hash check) and
  `demo.py inspect-expanded`, which printed the derived values that the manifest records.
- Schema: `schema/demo-editions.schema.json` selects version 1 or version 2 with `if`/`then`.
  Version 1 is unchanged. Version 2 fixes the nine IDs, their order and
  `initial_edition: auburn-1953`. Every edition must also carry `source_kind`,
  `sheet_name`, `scale`, `publication_date`, `component_dates`, `printed_credit_note`,
  `native_resolution_metres` and `native_max_zoom`.
- The four live editions keep their IDs, source IDs, dates, labels, notes and crops
  unchanged. A test compares each of their fields with `demo-editions.json`.
  `view_bounds_wgs84` and `tile_zoom` (10–16) are unchanged.

### 8.1 Sources, kinds and credits

| Edition | Source kind | Sheet, scale | Bytes verified (sha256) |
| --- | --- | --- | --- |
| sacramento-1891 | historical_geotiff | Sacramento 1:125,000 | `c0323977a7d5…` (4,379,097) |
| auburn-1944 | historical_geotiff | Auburn 1:62,500 | `986b31a266a1…` (8,057,515) |
| sacramento-1994 | historical_geotiff | Sacramento 1:100,000 | `4bd33df67082…` (20,019,247) |
| auburn-2018 | us_topo_pdf | Auburn 1:24,000 | PDF `063afdbe7cb6…` → COG `649b33904073…` |
| auburn-2021 | us_topo_pdf | Auburn 1:24,000 | PDF `6723d80faca1…` → COG `fe4c868b6523…` |

The check traces a US Topo edition through three files. It reads the PDF receipt in
`demo-pdf-retrievals.jsonl` and re-hashes the raw PDF. It then requires the
`build/expansion/demo-pdf-processing.json` entry to name the same PDF bytes. Last, it
requires the rendered COG to hash to the value in that entry. A regional or 15-minute
sheet must name its own sheet and scale in its label. The check refuses a label such as
"Auburn 1891 topographic map".

`printed_credit_note` holds the catalog credit note verbatim for the two US Topo maps.
It is `null` for the seven historical scans, because nobody has transcribed their printed
credits. Their attribution comes from `sources.yml` (`usgs-historical-topo`). The US
Topo attribution comes from `usgs-us-topo`.

Dates: `map_year` comes from the index `date_on_map` or the catalog publication year.
`component_dates` (`survey_year`, `edit_year`, `imprint_year`) comes from the index and
is null where the index has no value. The US Topo maps carry their full publication
date. The historical sheets carry `publication_date: null`, because ScienceBase gives
only a `YYYY-01-01` placeholder for them. For a regional sheet, `kind: topo` needs the
index column that shows the sheet was mapped: `survey_year` for 1891 and 1944, and
`edit_year` for 1994.

### 8.2 CRS: embedded versus indexed

The embedded CRS is always used for positioning. A disagreement with the index is
recorded under `index_crs`. It is not resolved.

| Edition | Embedded | Index datum / projection | Agrees |
| --- | --- | --- | --- |
| sacramento-1891 | NAD27 American Polyconic, central meridian 121°15′W | Unstated / Unstated | no |
| auburn-1944 | NAD27 American Polyconic, central meridian 121°07′30″W | NAD27 / Polyconic | yes |
| sacramento-1994 | NAD27 Transverse Mercator, central meridian 121°30′W, scale factor 1, false easting 0 | NAD27 / Universal Transverse Mercator | no: not a UTM zone |
| auburn-2018, auburn-2021 | NAD83 UTM zone 10N (EPSG:26910), from the PDF | not indexed | n/a |

Datum operations: `NAD27 to WGS 84 (6)` (7 m) for the three scans, and
`NAD83 to WGS 84 (1)` (4 m) for the PDFs.

### 8.3 Neatlines and crops

A regional sheet's crop is its verified graticule face clipped to the camera footprint.
The camera footprint is the intersection of the four live crops. Only the sheet edges
that bound that footprint are held to the 3.0 px neatline limit. For all three scans
these are the east and north edges. The other edges are measured and recorded, but they
bound nothing that is shown.

| Edition | Worst residual, enforced edges | Worst residual, all edges | View coverage |
| --- | --- | --- | --- |
| sacramento-1891 | 2.76 px (29.2 m), east edge, south band | 4.32 px (45.7 m), west edge, south band | 100% |
| auburn-1944 | 1.87 px (9.9 m) | 2.48 px (13.1 m) | 100% |
| sacramento-1994 | 1.80 px (15.2 m) | 1.83 px | 100% |
| auburn-2018 | neatline 1.37 m from nominal | – | 99.07% |
| auburn-2021 | neatline 1.22 m from nominal | – | 99.08% |

All three regional faces contain the whole view, so their crop is the view polygon
itself. The US Topo neatline is the NAD83 7.5-minute graticule, which lies about 89 m
east of the NAD27 one. That leaves an uncovered strip about 89 m wide on the west edge
of the view and a thinner one on the south edge. These strips stay transparent. The
camera is not moved or shrunk. The check fails if any source maps less than 95% of the
view, or if a crop drifts more than 1e-5° from its re-derivation.

### 8.4 Native zoom

`native_max_zoom` is the coarsest XYZ zoom whose ground pixel at the view's centre
latitude is no larger than the measured source pixel. The same rule gives zoom 16 for
the live 2.03 m scans.

| Edition | Measured pixel | native_max_zoom |
| --- | --- | --- |
| sacramento-1891 | 10.58 m | 14 |
| auburn-1944 | 5.29 m | 15 |
| sacramento-1994 | 8.47 m | 14 |
| auburn-2018, auburn-2021 | 2.03 m (300 dpi render) | 16 |

The check re-derives each value from the pixels and fails on any disagreement. Whether
a sheet is legible at that zoom is a human judgement for issue #38.
