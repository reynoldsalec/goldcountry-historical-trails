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

## 4. Neatline locators — scan margin excluded

The crop keeps the mapped face of each sheet and drops the decorative collar. The locator
is found, not assumed: the quadrangle graticule corners from `topo_index.csv` are projected
into the scan only to **seed** a search, then the accepted line is the darkest column or row
within 60 m of that seed, profiled over the middle 70% of each edge (away from the corner
ticks and tie marks).

`offset` is the accepted line's distance from the seeded corner, in pixels (1 px ≈ 2.03 m).
`dark` is the mean value of the accepted line, `collar` the median of the search window; a
line that is not at least 15 grey levels darker than its surroundings is a failure, not a
guess.

| Edition | west | east | north | south |
| --- | --- | --- | --- | --- |
| auburn-1953 | col 635, offset +0, dark 157.0 / collar 218.5 | col 5968, offset −1, dark 134.5 / collar 194.9 | row 385, offset −1, dark 71.8 / collar 211.9 | row 7214, offset −1, dark 86.3 / collar 200.0 |
| auburn-1973 | col 611, offset +1, dark 180.3 / collar 227.9 | col 5943, offset −1, dark 168.3 / collar 213.7 | row 395, offset +1, dark 126.6 / collar 224.9 | row 7223, offset +0, dark 138.0 / collar 218.4 |
| auburn-1975 | col 557, offset +1, dark 93.7 / collar 129.1 | col 5859, offset −2, dark 71.9 / collar 157.5 | row 364, offset −2, dark 31.8 / collar 78.9 | row 7156, offset −2, dark 58.1 / collar 228.8 |
| auburn-1981 | col 622, offset +1, dark 173.9 / collar 228.0 | col 5953, offset −1, dark 162.9 / collar 216.3 | row 365, offset +0, dark 109.7 / collar 219.6 | row 7194, offset +0, dark 129.9 / collar 220.8 |

Every offset is within 2 px (≈4 m) of the projected graticule corner, so the delivered
georeferencing and the drawn neatline agree on all sixteen edges. The crop follows the
neatline and therefore excludes only the collar; no white map content inside the neatline is
removed.

## 5. Derived geometry

`crop_wgs84` per edition is that neatline rectangle, densified to 9 points per edge so the
Polyconic and Lambert curvature survives the conversion, then expressed in WGS84 at six
decimal places. `view_bounds_wgs84` is the bounding box of the intersection of the four
crops:

```
[-121.126036, 38.874903, -121.001, 38.999875]
```

That box is a few metres wider than the intersection polygon itself, because the sheet edges
are curves rather than meridians and parallels. D2 must keep nodata/alpha explicit so the
sliver outside the mapped face reads as "no data", not as a failed tile.

None of these numbers comes from the index corner labels; `demo-check` recomputes them from
the rasters on every run and fails if the manifest drifts by more than 1e-5 degrees.

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
