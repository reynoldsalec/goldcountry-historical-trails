# Extra map options beyond the nine editions

The browser publishes four more editions after the nine-edition contract. They are
catalogued in `data/sources/demo-extra-editions.json` and processed by
`scripts/demo_extra.py`. The nine-edition manifest and its checks are unchanged.

| Edition | Source | Coverage | Placement |
| --- | --- | --- | --- |
| tahoe-nf-1916 | Internet Archive `CAT10680171`, leaf 25 (USDA NAL scan) | Its own neatline, about 121.36–119.64 W, 38.91–39.90 N | Control points, polynomial order 2 |
| sacramento-1947 | USGS `CA_Sacramento_707563_1947_250000` | Auburn view | Embedded GeoTIFF georeferencing |
| auburn-1954 | USGS `CA_Auburn_296743_1954_62500` | Auburn view | Embedded GeoTIFF georeferencing |
| sacramento-1956 | USGS `CA_Sacramento_299855_1956_250000` | Auburn view | Embedded GeoTIFF georeferencing |

The three USGS sheets reuse their existing `retrievals.jsonl` receipts. Their card
dates and ScienceBase links are checked against `topo_index.csv` on every run.

## The 1916 scan

The sheet carries a Mount Diablo township grid and no graticule. Placement works this
way:

1. `make extra-fetch` downloads the archive.org JP2 package and checks the publisher's
   SHA-1. It also downloads the BLM PLSS sections for T12–23N, R5–19E and the GNIS
   checkpoint towns. Each download gets a receipt in
   `data/sources/demo-extra-retrievals.jsonl`.
2. `make extra-control` starts from four seed corners read near the south-west corner
   of the map. It grows outward one township at a time. The script snaps each corner
   to the nearest long printed line within 45 px of a prediction from accepted
   neighbours. Corners where the BLM sections disagree by more than 100 m are dropped.
   A second-order fit then rejects outliers over max(3 × RMS, 400 m).
3. The script checks 13 town symbols, read from the scan, against GNIS positions. The
   run fails if any is more than 1.5 km off. That distance is about one section, so a
   corner snapped to the wrong line shows up here even though the fit hides it.

Result (`data/sources/gcp/CAT10680171_0025.control.json`): 73 control points, RMS
381 m, worst control corner 1001 m. Checkpoint errors are 159–1294 m. The source card
publishes this as its Placement row. Features on this layer can sit hundreds of metres
from where the USGS sheets put them.

`make extra-rasters` warps the scan with GDAL (`MAX_GCP_ORDER=2`, nearest). The alpha
mask comes from the printed neatline, not from pixel colour. Before warping, the script
checks that GDAL's fit equals the reviewed RMS. Native zoom is 13 (about 16 m per
source pixel). Output: `build/extra/`, 1612 tiles. `make demo-build` publishes the
extras with the nine.

## Viewer behaviour

- Panning is bounded by the union of all coverage (`pan_bounds_wgs84`).
- A switch never moves the camera. When the edition on screen does not reach the
  viewport, the status line says so.
- "Show this map's area" is a second explicit camera action. It appears when the
  selected map's coverage centre is off screen. It cannot zoom below 10, so on a
  narrow screen it frames the middle of the 1916 sheet.

Unresolved sources and the accuracy question are in `docs/open-questions.md`
(2026-10-02).
