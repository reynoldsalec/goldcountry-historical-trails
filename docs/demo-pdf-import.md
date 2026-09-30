# US Topo GeoPDF import (expansion E2, issue #56)

`make expansion-pdf` turns the two receipted US Topo PDFs (auburn-2018, auburn-2021) into
one georeferenced COG each. It writes only to `build/expansion/` (gitignored). Nothing
is published. `demo-build`, `data/sources/demo-editions.json`, `build/public` and
`build/tiles/demo` do not change.

**Inspection method: automated.** The numbers below come from script runs on
2026-09-29. No human reviewed the registration or legibility. Human acceptance stays
with issue #38.

## 1. Tooling, pinned in `pyproject.toml` and `uv.lock`

The GDAL 3.10.3 in the rasterio wheel has no Poppler or PDFium backend, so it cannot
read these PDFs. This machine and CI have no `gdalinfo`, `pdftoppm` or `mutool`. The
import uses three pip-installable libraries instead:

| Job | Library | Why this one |
| --- | --- | --- |
| Read `/VP`, `/Measure`, `/GCS`, `/OCProperties` | pypdf 6.1.1 | Full PDF object model, pure Python |
| Rasterize the page | pypdfium2 5.13.0 (PDFium 153.0.7999.0) | Evaluates `/OCMD` layer visibility correctly |
| Find the neatline and read collar text | PyMuPDF 1.28.2 | Vector paths with layer names, text blocks with positions |
| Write the COG | rasterio 1.4.4 (GDAL 3.10.3) | Same COG options as `make demo-cogs` |

MuPDF is **not** used to render. MuPDF 1.28.2 ignores `/OCMD` membership dictionaries.
With MuPDF, the hidden NAIP orthoimage and the hidden PLSS lines both appear in the
render. US Topo gates every layer through an `/OCMD`, for example
`AllOn(Orthoimage, Images)`. Every run starts with `check_renderer()`. It renders a small
generated PDF and stops if PDFium draws content from an OFF layer, directly or through an
`/OCMD`.

PyMuPDF is AGPL-3.0. Here it runs only as a local build tool. It is not shipped to the
viewer.

## 2. Georeferencing

Each page has three ISO 32000 `/VP` viewports: `Map Layers`, `Quadrangle Location` and
`Adjoining Sheet Diagram`. The importer uses the largest viewport that has a
`/Measure /Subtype /GEO` dictionary. For both PDFs that is `Map Layers`. Its `/GCS` is a
`PROJCS` with the ESRI WKT `GCS North American 1983 UTM Zone 10N (Calculated)`. pyproj
identifies it as EPSG:26910 and confirms the two are equivalent.

The four `/LPTS` points map to page space through the viewport `/BBox`, read as
`[ulx uly lrx lry]` the way GDAL reads it. The four `/GPTS` points are latitude and
longitude on the GCS datum, projected to UTM 10N. The importer fits one least-squares
affine from pixel to UTM. It records the fit as a geotransform and records the residual
at each point.

The importer never uses typed corners, catalog bounds or manual GCPs.

| Edition | Worst `/GPTS` residual | Rotation | Pixel size (300 dpi) |
| --- | --- | --- | --- |
| auburn-2018 | 0.175 m | 1.218° | 2.032 m |
| auburn-2021 | 0.221 m | 1.216° | 2.032 m |

The 1.2° rotation is UTM grid convergence at 121° W. The sheet is printed true-north up
on a UTM grid. The COG therefore has a rotated geotransform, as GDAL would produce.

The importer stops for any of these conditions:

- The page has no `/VP /Measure /GEO`. An LGIDict-only PDF is named as unsupported.
- The WKT cannot be read.
- The CRS is not one of EPSG:26910, 26911, 32610 or 32611.
- A `/GPTS` point is more than 1 m from the affine fit.
- The fit is mirrored.

## 3. Neatline and offset from the nominal 7.5-minute box

The `/Measure /Bounds` polygon spans the whole page, not the map frame. The importer
records it as `measure_bounds`, but it does not use it as a neatline. The neatline is the
largest stroked quadrilateral drawn on the page. In both PDFs it is on the `Map Frame`
layer. The importer converts its corners to NAD83 through the fitted transform. It then
compares them with the nominal box (-121.125..-121.0, 38.875..39.0) as a ground offset:

| Edition | UL | UR | LL | LR |
| --- | --- | --- | --- | --- |
| auburn-2018 | 0.60 m | 1.37 m | 0.69 m | 0.86 m |
| auburn-2021 | 1.03 m | 1.17 m | 1.22 m | 0.95 m |

Each corner is within about one pixel of its nominal position. The offset is **reported,
not accepted**: `registration_status` says so in the record.

## 4. Layers

The importer renders with the publisher's default configuration (`/OCProperties /D`) and
does not change it. `layer_policy.toggled` is empty. Observed defaults are the same in
both PDFs:

- **Off:** `Images` (the parent of `Orthoimage`), `Shaded Relief`, `PLSS`.
- **On:** every other layer, including `Contours`, `Trails`, `Woodland`, `Hydrography`,
  `Map Collar` and `Barcode`.

`Orthoimage` is ON in its own right, but its content is gated by
`AllOn(Orthoimage, Images)`. It is therefore hidden, and the NAIP image is not in the COG.
The record lists every layer with its `/Order` parent and default state. It also lists
every `/OCMD` group with its evaluated visibility.

## 5. Collar text and credits

The importer records every text block whose centre is outside the neatline as
`collar_text`: title, credit column, datum and projection note, scale, contour interval,
legend and notices. It reads the credit column under `Produced by the United States
Geological Survey`. It then checks each ` | ` segment of the catalog `credit_note` against
that column. Leader dots and spacing are ignored in the comparison. A missing segment
stops the run. All segments were found for both editions. The full page, collar included,
is in the COG, so nothing is cropped away at this stage.

## 6. Outputs and reruns

| Edition | Source sha256 | COG sha256 | COG bytes | Size (px) |
| --- | --- | --- | --- | --- |
| auburn-2018 | `063afdbe…cd5981` | `649b3390…5aa50c` | 39,310,553 | 7200 x 8700 |
| auburn-2021 | `6723d80f…b1deb` | `fe4c868b…342fb9` | 39,542,863 | 7200 x 8700 |

- COGs: `build/expansion/pdf/<edition>.tif`. RGB, DEFLATE, 256 px tiles, nearest
  overviews.
- Record: `build/expansion/demo-pdf-processing.json`. It has no timestamps, so a rerun
  writes identical bytes.

The run verifies both PDFs against `data/sources/demo-pdf-retrievals.jsonl` before
anything else. It verifies them again after each render. A mismatch stops the run and
leaves the raw file unchanged. A rerun reuses a COG only when its input fingerprint
matches and its own sha256 still matches the record. Otherwise the COG is rendered again.
A fresh render after `rm -rf build/expansion` gave the same COG bytes, so the render is
deterministic.

In a worktree, point the target at the primary raw root:

```
make expansion-pdf DEMO_RAW_ROOT=/path/to/primary/checkout/data/raw
```

## 7. Tests

`scripts/test_demo_pdf.py` (part of `make expansion-test`) builds synthetic GeoPDFs at
test time. No binary fixtures are committed. Each fixture has a known rotated UTM
transform, a hidden `AllOn(Orthoimage, Images)` square, a neatline on the nominal box and
a credit column. The tests check the following:

- The fitted transform reproduces the known transform to 0.5 m.
- The hidden square is absent from the COG.
- Reruns reuse outputs, a fresh render is byte-identical, and raw bytes do not change.

The tests reject each of these inputs:

- a PDF with no georeferencing, and an LGIDict-only PDF
- an unsupported CRS, and unreadable WKT
- inconsistent `/GPTS`
- garbage and truncated PDFs
- a blank or crashing render
- a hash mismatch
- a missing credit
- blocked rights
