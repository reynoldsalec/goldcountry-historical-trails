# Demo raster processing — common-grid COGs

Automated record of what `make demo-cogs` does and what it actually produced for the four
Auburn editions, implementation plan D2a (issue #40). The stage before this one is
`make demo-check` (D1, `docs/demo-source-review.md`); the stage after it cuts tiles.

**Inspection method: automated.** Every number below came from a script run, not from a
person looking at a map. No human source review or registration acceptance is asserted
here. Human acceptance belongs to issue #38.

- Run date: 2026-09-28
- Commands: `make demo-cogs` (twice), `make demo-test`, `make demo-check`
- Network: none.
- Writes: `build/rasters/` only. Nothing was written to `data/raw/` or to
  `data/sources/retrievals.jsonl`.

---

## 1. GDAL prerequisite, pinned

There is **no GDAL command-line tool** on PATH in this checkout, and the CI image has no
`gdal-bin` either. The only GDAL available is the one inside the rasterio wheel. That is
the one this stage uses, through the rasterio Python API:

| Component | Version |
| --- | --- |
| rasterio | 1.4.4 |
| GDAL (in the rasterio wheel) | 3.10.3 |
| PROJ (in the rasterio wheel) | 9.7.1 |
| pyproj | 3.7.2 |
| PROJ (in the pyproj wheel) | 9.5.1 |

`gdalwarp`, `gdalinfo` and `gdal_translate` are **not** invoked. `warp_raster.require_gdal()`
runs before any output is produced: it writes a 256x256 probe through the COG driver and
stops with an installation message if that fails. `make setup` still reports a missing
`gdalinfo` for the deferred countywide targets; `make demo-cogs` does not need it.

The versions above are recorded in `build/rasters/demo-processing.json` under
`tool_versions` on every run, so a COG can be traced to the library that made it.

## 2. The datum operation is chosen once and passed to GDAL

The two PROJ builds differ (9.5.1 in pyproj, 9.7.1 in GDAL), so they are free to pick
different NAD27 to WGS 84 operations. Neither build has the NADCON grids, so the best
available operation is the CONUS Helmert shift. D1 derived every committed crop through
it, and a warp through anything else would put the imagery off those crops.

So the operation is selected once, with pyproj, under the same rules `demo.py check`
uses (`allow_ballpark=False`, area of interest = the sheet's labelled graticule), and its
PROJ pipeline is handed to GDAL as the `COORDINATE_OPERATION` warp transformer option.
`select_operation` refuses to continue unless the chosen operation contains the same named
datum step that `demo-check` recorded for that sheet. The step is read out of the D1
report, not hard-coded.

Measured for all four sources:

| Edition | Datum | Source projection | Operation | Accuracy |
| --- | --- | --- | --- | --- |
| auburn-1953 | NAD27 | American Polyconic | `NAD27 to WGS 84 (6)` | 7.0 m |
| auburn-1973 | NAD27 | American Polyconic | `NAD27 to WGS 84 (6)` | 7.0 m |
| auburn-1975 | NAD27 | Lambert Conic Conformal (2SP) | `NAD27 to WGS 84 (6)` | 7.0 m |
| auburn-1981 | NAD27 | American Polyconic | `NAD27 to WGS 84 (6)` | 7.0 m |

Two better operations exist in the catalogue and are unavailable here for want of grids:
`NAD27 to NAD83 (1) + NAD83 to WGS 84 (43)` and `NAD27 to WGS 84 (79)`. Both are named in
the record under `unavailable_better`.

`verify_pipeline` then compares GDAL's own warped extent, computed through the pinned
pipeline, against the same pipeline applied by pyproj to a 128-point-per-edge outline, and
stops the run if they disagree by more than 5 m. It also records what GDAL would have
chosen unaided.

| Edition | GDAL pinned vs pyproj | GDAL unaided vs pinned |
| --- | --- | --- |
| auburn-1953 | 1.117 m | 0.0 m |
| auburn-1973 | 1.153 m | 0.0 m |
| auburn-1975 | 1.227 m | 0.0 m |
| auburn-1981 | 1.114 m | 0.0 m |

The ~1.1 m residual is GDAL's coarse sampling of the source outline, not a datum
difference: GDAL 3.10.3 picks the same operation the pinning names, which is why the
unaided column is exactly zero. The pinning is kept because that agreement is a property
of these library versions and not a guarantee.

## 3. One shared extent and grid

The output grid is derived from `view_bounds_wgs84` in `data/sources/demo-editions.json`
(the common mapped footprint D1 verified) and snapped outward to whole XYZ tiles at the
manifest's maximum zoom. Every edition is warped onto that one grid, so D2b can cut tiles
without resampling a second time and "same grid" is checkable by comparing integers.

| Property | Value |
| --- | --- |
| CRS | EPSG:3857 |
| Zoom the grid is aligned to | 16 (`tile_zoom.max`) |
| Resolution | 2.388657133911758 m/px |
| Size | 6144 x 7680 px (24 x 30 tiles of 256 px) |
| XYZ tile range | x 10717-10740, y 25046-25075 |
| Bounds (EPSG:3857) | -13484103.285731371, 4703628.972556606, -13469427.376300618, 4721973.859345049 |

`--grid-zoom` warps onto a lower zoom of the same pyramid for inspection and for the
tests. The zoom used is recorded in the record's `grid.zoom`; the default is `tile_zoom.max`.

## 4. Resampling and the crop mask

Resampling follows the source kind, per AGENTS.md §3: `nearest` for the three scanned topo
sheets, `cubic` for the 1975 orthophotoquad. The COG's overviews use the same choice. An
unknown kind has no rule and stops the run rather than getting a default.

The alpha band is the source's own valid-data coverage intersected with the edition's
committed `crop_wgs84` polygon, rasterised in EPSG:3857. **No pixel value takes part in
that decision.** A white-colour transparency rule would delete legitimate white map
content, which is most of a topo sheet's map face. Pixels outside the alpha are zeroed so
a COG's bytes depend only on its recorded inputs.

Counted in the produced COGs: 43,630,914 of 47,185,920 grid pixels are opaque in all four
editions (the grid is the bounding box of a graticule quadrilateral, so its corners fall
outside the crop), alpha holds only 0 and 255, and **no pure-white pixel was made
transparent in any edition**:

| Edition | Opaque px | Pure-white and opaque px | Pure-white and transparent px |
| --- | --- | --- | --- |
| auburn-1953 | 43,630,914 | 4,819 | 0 |
| auburn-1973 | 43,630,914 | 2,843,277 | 0 |
| auburn-1975 | 43,630,914 | 394 | 0 |
| auburn-1981 | 43,630,914 | 1,445,313 | 0 |

The 1953 and 1975 scans carry very little literally pure white; their map faces are
near-white scan tone, and that tone is preserved too. The count is reported because a
colour-keyed mask would have destroyed the 1973 and 1981 figures.

## 5. What was produced, and the source bytes before and after

`make demo-cogs` runs `demo.py check` first, so a missing, ambiguous or mis-hashed receipt
stops the run before a pixel is read. After all four warps it re-hashes every selected
source and fails if a byte moved.

| Edition | Source ID | Resampling | Source SHA-256 | COG SHA-256 | COG bytes |
| --- | --- | --- | --- | --- | --- |
| auburn-1953 | CA_Auburn_288101_1953_24000 | nearest | `bec9555f90f4…` | `8c5f94a071c1…` | 121,902,433 |
| auburn-1973 | CA_Auburn_288103_1953_24000 | nearest | `2a4427b0969a…` | `95b68bb5fa64…` | 119,151,982 |
| auburn-1975 | CA_Auburn_288104_1975_24000 | cubic | `4d35331f4a1f…` | `cdb24a754bb2…` | 99,853,219 |
| auburn-1981 | CA_Auburn_288105_1953_24000 | nearest | `d5621357235c…` | `cff62b021c58…` | 122,301,756 |

Source hashes are the full values already committed in `data/sources/retrievals.jsonl`;
they were identical before and after processing. Each COG's record entry names exactly one
selected source ID, hash, byte count and raw path.

Output form: 4 bands of uint8 (RGB plus alpha), 256 px tiles, DEFLATE, overview levels
2/4/8/16/32, no nodata value.

## 6. Atomic writes and content-aware reuse

A run warps into `build/rasters/.incoming/` and moves the finished files into
`build/rasters/` only after every edition has succeeded. The record is written last,
through a temporary file and `os.replace`. A run that fails part way publishes no COG and
no record. `write_cog` stages the plain GeoTIFF and the COG in a scratch directory it
removes on either outcome, so an interrupted write leaves no partial file behind.

Reuse is by content, not by timestamp. Each entry carries a `fingerprint`: the SHA-256 of
the processing version, the source hash and byte count, the crop polygon, the whole grid
description, the resampling, the source CRS WKT, the datum operation and the tool versions.
An existing COG is reused only when its fingerprint still matches **and** its own bytes
still hash to the recorded digest. The record itself carries no timestamp and no host
detail, so an unchanged rerun rewrites it byte for byte.

Observed: the first run warped all four (56 s); the immediate second run reused all four
(1.6 s) and left `demo-processing.json` byte-identical and the COG mtimes untouched. The
COG bytes are reproducible — deleting one and rerunning reproduced the same SHA-256.

## 7. Registration: what is checked, and what is not

The record's `registration_notes` says this in the file as well as here.

Checks that ran:

1. The drawn neatline of each scan against its labelled graticule (from D1, in pixels).
2. GDAL's warped extent against the pinned pyproj pipeline (§2).
3. GDAL's unaided choice of operation against the pinned one (§2).

**No stable-landmark check was run, because no independent control exists in this
repository.** There is no surveyed landmark set, no modern reference layer and no
orthoimagery committed here to check the warped sheets against. Claiming a landmark
check would be inventing evidence.

Systematic offsets that remain, carried and not corrected:

| Edition | Drawn neatline off the labelled graticule | Datum operation accuracy |
| --- | --- | --- |
| auburn-1953 | 1.35 px = 2.743 m | 7.0 m |
| auburn-1973 | 1.07 px = 2.174 m | 7.0 m |
| auburn-1975 | 2.61 px = 5.304 m | 7.0 m |
| auburn-1981 | 1.79 px = 3.637 m | 7.0 m |

No ground control point was added, moved or fitted, and no aerial frame was acquired. The
sheets are warped as published, from the georeferencing USGS shipped with them. Whether
that registration is good enough to page between editions is a human judgement and stays
in issue #38.

## 8. Tests

`make demo-test` runs `scripts/test_demo.py` (D1) and `scripts/test_demo_rasters.py`
(this stage) against synthetic scans only. The synthetic coverage is: the recorded tool
versions and the COG-driver prerequisite; resampling dispatch per kind and an unknown kind;
the named datum operation, a wrong required operation, a source with no CRS, a CRS with no
datum, an unreadable file, and a pipeline GDAL is made to ignore; grid tile alignment,
coverage of the declared bounds, inverted bounds, one grid for all four editions, and a
zoom outside the manifest range; a geometric mask that keeps white pixels, an empty crop,
the alpha band and its absence of colour keying; the record's versions, hashes, transform,
crops and digests, and one source per COG; reruns that reuse, a deleted output, an output
whose bytes changed, and a changed grid; a failure part way through publishing nothing, a
corrupt source, a non-raster source, a missing source, and `write_cog` leaving no partial
file; and that a run changes no raw byte, no receipt and nothing outside the build root.
