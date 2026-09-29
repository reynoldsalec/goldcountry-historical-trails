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
- Every residual on the north and south edges is negative, and all but two of the eight
  east/west residuals are: the drawn line sits a pixel or two outside the graticule the
  GeoTIFF delivers. The two ends of an edge agree to within 1.02 px in the worst case (the
  1981 south edge) and within 0.60 px on the other fifteen edges, so what is left is an
  offset of the whole line, not the tilt the earlier axis-aligned crop showed.
- The drawn neatline's own ink is 2–3 px wide on all four sheets, so the crop boundary
  falls within the drawn line, not inside the mapped face. The worst case, the 1975 north
  edge, trims about 1 px (2 m) of orthophoto tone just inside the line; on the topo sheets
  the boundary stays inside the ink.
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
