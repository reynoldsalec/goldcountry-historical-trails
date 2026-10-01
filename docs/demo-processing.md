# Demo raster processing — common-grid COGs and XYZ tiles

Automated record of what `make demo-cogs` (D2a, issue #40) and `make demo-rasters`
(D2b, issue #41) do and what they actually produced for the four Auburn editions. The stage
before both is `make demo-check` (D1, `docs/demo-source-review.md`). Sections 1-8 are the
COG stage; section 9 is the tile stage. `make demo-rasters` runs the preflight, the COG
stage and the tile stage in that order, so it is the only command a build needs.

**Inspection method: automated.** Every number below came from a script run, not from a
person looking at a map. No human source review, registration acceptance or legibility
judgement is asserted here. Human acceptance belongs to issue #38.

- Run date: 2026-09-28
- Commands: `make demo-cogs` (twice), `make demo-rasters` (twice), `make demo-test`,
  `make demo-check`, `make validate`, `make lint`
- Network: none.
- Writes: `build/rasters/` and `build/tiles/demo/` only. Nothing was written to `data/raw/`
  or to `data/sources/retrievals.jsonl`.

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
`build/rasters/` only after every edition has succeeded and every source's raw bytes have
hashed to their receipt a second time. The record is written last,
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
failed post-warp source re-check leaving the published run and its record intact, a
corrupt source, a non-raster source, a missing source, and `write_cog` leaving no partial
file; and that a run changes no raw byte, no receipt and nothing outside the build root.

---

## 9. The XYZ PNG pyramid (D2b, `make demo-rasters`)

### 9.1 The tiler, pinned

`gdal2tiles` is a GDAL command-line script, and no GDAL command line exists here or in CI
(§1). The pyramid is therefore cut by `warp_raster.cut_pyramid`, through the same GDAL
inside the rasterio wheel that §1 pins, and `require_gdal()` probes the PNG driver before
any tile is written. The `gdal2tiles --xyz` flag has no counterpart here because nothing in
this code can emit TMS: `tile_xy` counts y down from the north edge of the world, and that
is the only numbering it has.

| Property | Value |
| --- | --- |
| Tiler | `scripts/warp_raster.py cut_pyramid` (rasterio 1.4.4 / GDAL 3.10.3) |
| Scheme | XYZ, `build/tiles/demo/<edition-id>/{z}/{x}/{y}.png` |
| Zooms | 10-16 (`tile_zoom` in `data/sources/demo-editions.json`) |
| Tile size | 256 px |
| Format | PNG, 4 bands uint8 (RGB + alpha), `ZLEVEL=9`, no PAM sidecars |
| Resampling | `nearest` for the three topo sheets, `cubic` for the 1975 orthophotoquad |
| Alpha resampling | `nearest` at every zoom, so alpha stays two-valued |

Zoom 16 is the grid the COGs are already on (§3), so a zoom-16 tile is a block copy of the
COG and the published imagery is the warp D2a recorded, not a second resampling of it.
Coarser zooms decimate whole 2^n blocks of that same grid. The pyramid is never cut finer
than the grid: `--grid-zoom` lowers both together, which is what the tests use.

No PMTiles, no tippecanoe, no tile server, no new download: the stage reads the four COGs
and writes PNG files.

### 9.2 What was produced

One pyramid per edition, 1005 tiles each, 4020 in total:

| Edition | Resampling | Tiles | Bytes | Pyramid digest | COG SHA-256 |
| --- | --- | --- | --- | --- | --- |
| auburn-1953 | nearest | 1005 | 114,341,115 | `50e0562d0000…` | `8c5f94a071c1…` |
| auburn-1973 | nearest | 1005 | 111,621,938 | `636760d8b0cb…` | `95b68bb5fa64…` |
| auburn-1975 | cubic | 1005 | 109,372,894 | `72b3daa79b4a…` | `cdb24a754bb2…` |
| auburn-1981 | nearest | 1005 | 114,515,125 | `aeaa3ddce2eb…` | `cff62b021c58…` |
| **total** | | **4020** | **449,851,072** | | |

Per zoom, with the tile range every edition shares and the bytes summed over the four:

| Zoom | Tiles per edition | x range | y range | Bytes (4 editions) |
| --- | --- | --- | --- | --- |
| 10 | 1 | 167 | 391 | 135,994 |
| 11 | 4 | 334-335 | 782-783 | 523,554 |
| 12 | 9 | 669-671 | 1565-1567 | 2,004,676 |
| 13 | 20 | 1339-1342 | 3130-3134 | 7,691,902 |
| 14 | 56 | 2679-2685 | 6261-6268 | 29,039,513 |
| 15 | 195 | 5358-5370 | 12523-12537 | 101,835,957 |
| 16 | 720 | 10717-10740 | 25046-25075 | 308,619,476 |

Bounds of the bounded pyramid, from the shared grid and the manifest, not from a file label:

- EPSG:3857: -13484103.285731371, 4703628.972556606, -13469427.376300618, 4721973.859345049
- EPSG:4326: -121.126028, 38.874881, -121.001023, 38.99988

429 MiB for four editions is a measurement, not a target. PNG on a scanned colour sheet is
large; whether the published build keeps all seven zooms, or trades format for size, is a
D3/D4 decision and no change was made here to anticipate it.

### 9.3 Generation time, measured

| Run | Work | Wall clock |
| --- | --- | --- |
| Cold | warp four COGs + cut four pyramids | 265.6 s |
| Tiles only | COGs reused, four pyramids cut | 213.1 s |
| Rerun | everything reused | 1.6 s |

One machine, one run each. No rate is extrapolated from these.

### 9.4 Transparency, and what the counts say

Alpha comes from the COG's alpha band, which is the source's own valid-data coverage
intersected with the committed crop (§4). No pixel colour takes part in it at any zoom.
Measured over every published tile: alpha holds only 0 and 255, and no colour survives
where alpha is 0.

**No fully transparent tile occurs in this real pyramid**, because the bounded grid is the
bounding box of the common footprint and every tile in it touches the crop; the corner tiles
are partly transparent instead. The fully transparent path is exercised by a synthetic
fixture in `make demo-test`, where a whole tile of the grid falls outside the crop and the
run writes a transparent PNG for it rather than nothing. Encoding the tile is what keeps a
blank area distinguishable from a failed request.

Opaque pixel counts per zoom are identical for the three topo editions (43,630,914 at zoom
16, matching §4) and larger by 91-3,329 px for the 1975 edition at zooms 10-14, because its
COG's overviews were built with `CUBIC` per AGENTS.md §3 and a nearest read off a cubic
overview lands on a slightly different sample. The values read are still only 0 and 255.

### 9.5 Line survival per zoom, as a count

Legibility is a human judgement and belongs to issue #38. What is recorded here is a count:
the share of opaque pixels with at least one channel darker than 128, per zoom. For a scanned
topo sheet that tracks drawn line and lettering; for the orthophotoquad it tracks dark
imagery and says nothing about line work.

| Zoom | auburn-1953 | auburn-1973 | auburn-1975 | auburn-1981 |
| --- | --- | --- | --- | --- |
| 16 | 38.30 % | 15.60 % | 70.23 % | 14.33 % |
| 15 | 38.30 % | 15.61 % | 70.59 % | 14.34 % |
| 14 | 38.27 % | 15.56 % | 71.73 % | 14.28 % |
| 13 | 38.20 % | 15.54 % | 73.34 % | 14.28 % |
| 12 | 38.26 % | 15.55 % | 74.85 % | 14.26 % |
| 11 | 38.23 % | 15.72 % | 76.32 % | 14.46 % |
| 10 | 40.81 % | 18.14 % | 81.42 % | 16.91 % |

The dark share is flat from zoom 16 to zoom 11 and rises at zoom 10, where one tile covers
the whole sheet. A flat share means nearest decimation is not thinning the ink away, not
that a reader can follow a trail at that zoom.

### 9.6 The sample points

D2a found no independent ground control in this repository (§7), and none was added. The two
sample points are derived from the four committed crops: the north and south ends of the
footprint's central meridian, inset 2 % of its length. They are not landmarks and are not
named as any.

Both resolve through the XYZ formula to a tile that exists, and the tile's pixel is compared
against the COG's pixel at the same coordinate. A pyramid with TMS y, a shifted window, or
one cut from another edition's COG fails that comparison, and the run publishes nothing.

| Sample | Coordinate | Tile (z/x/y) | Pixel | 1953 RGBA | 1975 RGBA |
| --- | --- | --- | --- | --- | --- |
| north | -121.063525, 38.997379 | 16/10729/25047 | 14, 27 | 246, 246, 124, 255 | 33, 23, 23, 255 |
| south | -121.063525, 38.877381 | 16/10729/25075 | 14, 49 | 250, 222, 113, 255 | 28, 19, 14, 255 |

The north tile's y (25047) is smaller than the south tile's (25075). Under TMS it would be
larger. All four editions report the same tiles and pixels, opaque in every case; the full
set is in `build/rasters/demo-processing.json` under `tiles.editions[].sample_points`.

### 9.7 Publishing, reuse and the source bytes

A run cuts into `build/tiles/.incoming/` and moves a pyramid into `build/tiles/demo/` only
after all four have been cut and both sample points have been checked against their COG. A
run that fails part way publishes no pyramid and writes no tiles section, so a retry cannot
make partial output look complete. An unexpected directory under the tile root stops the run
instead of being published alongside the four editions.

Reuse is by content. Each edition's `fingerprint` is the SHA-256 of the tiling version, the
COG's hash and byte count, the whole grid, the zoom list, the scheme, the format and its
options, the tile size, both resampling choices and the tool versions. A published pyramid is
reused only when that fingerprint matches **and** its own file set and bytes still hash to the
recorded digest, so a deleted tile, an altered tile or a changed parameter is cut again.
`make demo-cogs` carries the tiles section through untouched, so a COG-only run does not make
a valid pyramid look stale.

Observed: the first full cut and a second full cut after deleting `build/tiles/` produced the
same four digests; the immediate rerun reused all four, left `demo-processing.json`
byte-identical and left every tile's mtime untouched. The four raw SHA-256 values before and
after are the ones committed in `data/sources/retrievals.jsonl`
(`bec9555f90f4…`, `2a4427b0969a…`, `4d35331f4a1f…`, `d5621357235c…`), and
`data/sources/retrievals.jsonl` itself was not written.

### 9.8 Tests

`make demo-test` covers the tile stage on synthetic rasters only, small enough for CI: the
XYZ numbering against TMS and a known tile; the tile range per zoom and its halving; a zoom
finer than the grid; whole-pixel windows; a zoom-16 tile as a block copy of its COG; the
north half of a COG landing in the northern tile; PNG driver, band count, alpha colour
interpretation and the absence of PAM sidecars; fully transparent tiles for an empty part of
the footprint; no tile outside the bounded range; alpha staying two-valued under cubic
colour resampling; the per-zoom opaque and dark-pixel counts; a COG that is not on the shared
grid; a stray file in a pyramid; the sample points resolving to the right tile and pixel; a
mirrored (TMS) pyramid, a pyramid cut from another COG and a missing tile all failing the
sample check; the sample points falling inside the shared footprint; all four pyramids over
the manifest zoom range, each naming its own edition, source and COG; the record's scheme,
totals, per-level numbers and notes; alpha on every published tile; a rerun reusing
everything and rewriting an identical record; a deleted tile, an altered tile and a changed
zoom range each forcing a re-cut; the fingerprint responding to every recorded parameter; a
failure part way through publishing nothing; a later failure leaving the published pyramids
and the record intact; an unexpected directory under the tile root; a `demo-cogs` run not
invalidating a valid pyramid; and a tiling run changing no raw byte and no receipt.

## 10. The five added editions (expansion E3, `make expansion-rasters`)

`make expansion-rasters` first runs `make expansion-pdf`, which reuses its outputs when
nothing changed. It then runs `scripts/demo_expansion.py rasters`, which checks the
version-2 manifest (see `docs/demo-source-review.md` §8). It warps and tiles only the
five added editions, and only into `build/expansion/`:

- `rasters/<edition>.tif`: COG with an alpha band.
- `tiles/<edition>/{z}/{x}/{y}.png`: XYZ tiles.
- `demo-expansion-processing.json`: the record.

The run does not read or write the four live COGs and pyramids, `build/tiles/demo` or
`build/public`. The run date is 2026-09-29, with the tool versions of §1. Each result
below is a machine check. No human reviewed any of them.

### 10.1 Per-edition grid and zoom range

Each edition is warped onto the XYZ-aligned grid of its own `native_max_zoom`, over the
unchanged `view_bounds_wgs84`. It is tiled from zoom 10 up to that zoom and no further.
The record stores the range per edition as `zoom.min`/`zoom.max`. A later public build
checks each tree against its own range, not against a global 10–16. A camera zoom above
`zoom.max` must overzoom that level. The number of tiles at each level equals the grid's
tile range at that level, so no tile outside the view is written. Resampling is
`nearest` for all five, because all five are map sheets. Only the 1975 orthophotoquad
uses `cubic`, and this stage does not re-tile it.

Two resampling-independent changes to shared code:

- **Pipeline agreement limit.** `verify_pipeline` now allows the larger of 5 m and one
  source pixel. On the 47 km-wide 1891 sheet, GDAL's coarse outline sampling gave
  6.29 m, which is 0.6 of its 10.58 m pixel. The 2.03 m scans still get 5 m.
- **Alpha band.** It is still source coverage intersected with the crop polygon only. No
  pixel value is used.

### 10.2 What was produced

Record totals: **2,475 tiles, 132,917,652 bytes** of PNG.

| Edition | Zooms | Grid (px) | COG bytes | Tiles (z10…top) | Tile bytes |
| --- | --- | --- | --- | --- | --- |
| sacramento-1891 | 10–14 | 1792 × 2048 at 9.555 m | 5,251,088 | 1, 4, 9, 20, 56 = 90 | 4,992,968 |
| auburn-1944 | 10–15 | 3328 × 3840 at 4.777 m | 24,572,648 | 1, 4, 9, 20, 56, 195 = 285 | 23,457,155 |
| sacramento-1994 | 10–14 | 1792 × 2048 at 9.555 m | 8,813,952 | 90 | 8,407,559 |
| auburn-2018 | 10–16 | 6144 × 7680 at 2.389 m | 43,455,435 | …, 195, 720 = 1,005 | 47,904,484 |
| auburn-2021 | 10–16 | 6144 × 7680 at 2.389 m | 43,765,295 | 1,005 | 48,155,486 |

Grid resolution is in EPSG:3857 metres. The first run took 137 s. A second
`make expansion-rasters` reused all five COGs and pyramids in 1.3 s and wrote the same
record. A fresh warp after a change to the registration settings gave the same COG and tile
byte counts per edition.
Before and after each run, the stage re-hashes every raw TIFF, the two raw PDFs and the
two rendered PDF COGs.

### 10.3 Registration: machine checks only

The record states for each edition:

- the pinned datum operation and its accuracy;
- the GDAL-versus-pyproj extent agreement;
- the neatline residuals of §8.3 in `docs/demo-source-review.md`;
- `offsets_vs_reference`, a phase-correlation measurement against auburn-1953.

The offset check uses five dispersed patches: the crop centre, and 25%/75% of the crop's
extent in each direction. Each patch is 4 km wide in EPSG:3857 (about 3.1 km on the
ground). Both editions are warped to the added edition's grid for the check. An offset
is reported only when the correlation peak is at least twice the next-highest peak
outside a 3 px neighbourhood. Otherwise the patch records "not distinct" and gives no
offset. No feature is named or surveyed, and no offset was corrected.

| Edition | Distinct patches | Offsets found (east, north; ground m) |
| --- | --- | --- |
| sacramento-1891 | 0 of 5 | none established |
| auburn-1944 | 0 of 5 | none established |
| sacramento-1994 | 3 of 5 | NW (+2.8, −14.3), NE (+4.5, −6.5), SW (+7.4, −21.6) |
| auburn-2018 | 1 of 5 | SE (−7.5, +3.7) |
| auburn-2021 | 1 of 5 | SE (−7.2, +3.2) |

Uncertainty of a distinct offset: about ±1 grid pixel (7.4 m at zoom 14, 1.9 m at
zoom 16). That is on top of the 7 m and 4 m accuracies of the datum operations. The
offsets are as large as those accuracies, so they show no gross misregistration. They
do not establish sub-datum agreement. For 1891 and 1944 the maps share too little drawn
linework with 1953 for this measurement to say anything. Their registration evidence is
only the neatline check. See `docs/open-questions.md`.

### 10.4 Tests

`scripts/test_demo_expansion.py` (in `make expansion-test`) runs on synthetic sources
from `scripts/test_demo.py`: three regional scans at their real pixel sizes and CRSs,
and two NAD83 UTM pages standing in for the PDF renders. The tests cover:

- the nine-edition allowlist and order;
- a duplicate source, and a wrong or unknown source kind;
- labels and scales of the regional sheets;
- component dates against the index;
- verbatim credits;
- `initial_edition`;
- zoom limits on the lower-resolution sheets: a claimed zoom 16 is refused, and the
  pyramids stop at 14;
- a shrunk crop and the coverage floor;
- PDF, render and COG hash lineage;
- the recorded index CRS disagreements;
- bounded tile ranges and two-valued, crop-exact alpha;
- output confined to the expansion root, reuse, and raw bytes left unchanged;
- phase-correlation sign and refusal on unrelated patches;
- compatibility of the four old editions with the live manifest.

The negative tests in `scripts/test_demo.py` now run against both the four-edition and
the nine-edition tree. They cover missing, duplicate, extra and reordered editions; kind
mismatches; index date disagreement; non-public rights; and attribution against
`sources.yml`.
