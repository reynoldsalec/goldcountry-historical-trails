"""Render the two receipted US Topo GeoPDFs to georeferenced COGs under build/expansion/.

Position comes only from each PDF's ISO 32000 /VP /Measure dictionary; the rasterio GDAL
cannot read PDFs, and MuPDF ignores OCMD visibility, so PDFium renders (#56).
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import warnings
from pathlib import Path

import click
import demo_sources
import numpy as np
import pymupdf
import pypdf
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import rasterio
import rasterio.shutil
import source_archive as archive
import warp_raster
from pyproj import CRS, Geod, Transformer
from pyproj.exceptions import CRSError
from rasterio.enums import ColorInterp
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import Affine

REPO_ROOT = demo_sources.REPO_ROOT
OUT_DIR = REPO_ROOT / "build" / "expansion"
RECORD_NAME = "demo-pdf-processing.json"

# Bumped when a change here invalidates every existing PDF COG.
PDF_PROCESSING_VERSION = 1
# 300 dpi on a 1:24,000 sheet is 2.03 m per pixel, finer than the 1953-1981 scans' grid.
DEFAULT_DPI = 300
# The four /GPTS points of a US Topo fit an affine to 0.2 m; more means a non-planar map.
RESIDUAL_LIMIT_M = 1.0
# NAD83 and WGS 84 UTM zones that cover Auburn; anything else has not been verified here.
SUPPORTED_EPSG = (26910, 26911, 32610, 32611)
CRS_MIN_CONFIDENCE = 70
NOMINAL_BOX = {"west": -121.125, "east": -121.0, "south": 38.875, "north": 39.0}
GEOD = Geod(ellps="GRS80")
# No annotation, LCD or no-smoothing flags: the page content as a viewer shows it on screen.
RENDER_FLAGS = pdfium_c.FPDF_REVERSE_BYTE_ORDER
LAYER_POLICY = {
    "configuration": "publisher default /OCProperties /D, unchanged",
    "toggled": [],
    "reason": "No layer is switched on or off. Hidden layers, including Images/Orthoimage, "
    "stay hidden because no recorded policy enables them.",
}
# A neatline candidate must be a large single quadrilateral; smaller ones are insets.
NEATLINE_MIN_PAGE_FRACTION = 0.2
CREDIT_ANCHOR = "Produced by the United States Geological Survey"


class PdfImportError(click.ClickException):
    """A stop condition: bad bytes, no georeferencing, unsupported CRS or a failed render."""


def tool_versions() -> dict:
    versions = warp_raster.tool_versions()
    versions.update(
        {
            "pypdf": pypdf.__version__,
            "pypdfium2": str(pdfium.PYPDFIUM_INFO),
            "pdfium": str(pdfium.PDFIUM_INFO),
            "pymupdf": pymupdf.VersionBind,
            "mupdf": pymupdf.VersionFitz,
        }
    )
    return versions


def canon(text: str) -> str:
    """Leader dots and justified spacing collapsed so printed and catalogued credits compare."""
    text = text.replace("\x00", "").replace("|", " ")
    text = re.sub(r"\.{2,}", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"\.{3,}", " ... ", text)
    return re.sub(r"\s+", " ", text).strip()


def verify_source(record: dict, root: Path) -> Path:
    try:
        return demo_sources.verify_receipted(record, root)
    except FileNotFoundError:
        raise PdfImportError(f"Receipted PDF is absent: {record['path']}") from None
    except click.ClickException as exc:
        raise PdfImportError(exc.format_message()) from None


# --- PDF structure -------------------------------------------------------------------------


def open_structure(path: Path) -> pypdf.PdfReader:
    try:
        reader = pypdf.PdfReader(path, strict=False)
        pages = len(reader.pages)
    except Exception as exc:
        raise PdfImportError(f"{path.name}: corrupt or unreadable PDF: {exc}") from None
    if pages != 1:
        raise PdfImportError(f"{path.name}: expected a single-page map, found {pages} pages")
    return reader


def numbers(value) -> list[float]:
    return [float(v) for v in value]


def text_of(value) -> str | None:
    return None if value is None else str(value).replace("\x00", "")


def page_geometry(page) -> dict:
    media = numbers(page.mediabox)
    crop = numbers(page.cropbox)
    rotation = int(page.get("/Rotate", 0) or 0) % 360
    if media != crop or rotation:
        raise PdfImportError(
            f"Unsupported page geometry: MediaBox {media}, CropBox {crop}, rotation "
            f"{rotation}; only unrotated pages with CropBox = MediaBox are handled"
        )
    return {
        "mediabox": media,
        "width_pt": media[2] - media[0],
        "height_pt": media[3] - media[1],
    }


def read_viewport(page, path: Path) -> dict:
    """The largest /VP entry with a /Measure /GEO dictionary, as ISO 32000-2 12.10 lays out."""
    viewports = page.get("/VP")
    geo = []
    for item in viewports.get_object() if viewports is not None else []:
        vp = item.get_object()
        measure = vp.get("/Measure")
        measure = measure.get_object() if measure is not None else None
        if measure is None or measure.get("/Subtype") != "/GEO":
            continue
        bbox = numbers(vp["/BBox"])
        area = abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        geo.append((area, text_of(vp.get("/Name")), bbox, measure))
    if not geo:
        why = "no /VP viewport with a /Measure /GEO dictionary"
        if page.get("/LGIDict") is not None:
            why += "; it carries an OGC LGIDict, which this importer does not read"
        raise PdfImportError(f"{path.name}: no embedded georeferencing ({why})")
    area, name, bbox, measure = max(geo, key=lambda g: g[0])
    gpts, lpts = numbers(measure.get("/GPTS", [])), numbers(measure.get("/LPTS", []))
    if len(gpts) != len(lpts) or len(gpts) < 6 or len(gpts) % 2:
        raise PdfImportError(f"{path.name}: /GPTS and /LPTS do not pair up into 3+ points")
    gcs = measure.get("/GCS")
    gcs = gcs.get_object() if gcs is not None else None
    if gcs is None:
        raise PdfImportError(f"{path.name}: /Measure has no /GCS coordinate system")
    return {
        "viewport": name,
        "viewports": [g[1] for g in geo],
        "bbox": bbox,
        "gpts": gpts,
        "lpts": lpts,
        "bounds": numbers(measure.get("/Bounds", [0, 0, 0, 1, 1, 1, 1, 0])),
        "gcs_type": str(gcs.get("/Type", "")).lstrip("/") or None,
        "wkt": text_of(gcs.get("/WKT")),
        "gcs_epsg": int(gcs["/EPSG"]) if gcs.get("/EPSG") is not None else None,
    }


def identify_crs(viewport: dict, path: Path) -> tuple[CRS, int]:
    try:
        if viewport["wkt"]:
            crs = CRS.from_wkt(viewport["wkt"])
        elif viewport["gcs_epsg"] is not None:
            crs = CRS.from_epsg(viewport["gcs_epsg"])
        else:
            raise PdfImportError(f"{path.name}: /GCS has neither /WKT nor /EPSG")
    except CRSError as exc:
        raise PdfImportError(f"{path.name}: unsupported CRS, unreadable WKT: {exc}") from None
    epsg = crs.to_epsg(min_confidence=CRS_MIN_CONFIDENCE)
    if not crs.is_projected or epsg not in SUPPORTED_EPSG:
        raise PdfImportError(
            f"{path.name}: unsupported CRS {crs.name!r} (EPSG {epsg}); supported: "
            + ", ".join(f"EPSG:{code}" for code in SUPPORTED_EPSG)
        )
    if not CRS.from_epsg(epsg).equals(crs, ignore_axis_order=True):
        raise PdfImportError(f"{path.name}: CRS {crs.name!r} is not equivalent to EPSG:{epsg}")
    return crs, epsg


def unit_to_pixel(viewport: dict, geometry: dict, scale: tuple[float, float], u, v):
    """/LPTS unit square to pixel; BBox is read as [ulx uly lrx lry], as GDAL reads it."""
    x1, y1, x2, y2 = viewport["bbox"]
    x = x1 + u * (x2 - x1)
    y = y1 + v * (y2 - y1)
    media = geometry["mediabox"]
    return (x - media[0]) * scale[0], (media[3] - y) * scale[1]


def fit_geotransform(viewport: dict, geometry: dict, crs: CRS, scale, path: Path) -> dict:
    to_projected = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    gcps = []
    for i in range(0, len(viewport["lpts"]), 2):
        col, row = unit_to_pixel(viewport, geometry, scale, *viewport["lpts"][i : i + 2])
        lat, lon = viewport["gpts"][i : i + 2]
        x, y = to_projected.transform(lon, lat)
        gcps.append({"pixel": col, "line": row, "lon": lon, "lat": lat, "x": x, "y": y})
    design = np.array([[g["pixel"], g["line"], 1.0] for g in gcps])
    target = np.array([[g["x"], g["y"]] for g in gcps])
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    (a, d), (b, e), (c, f) = coefficients
    residuals = np.hypot(*(design @ coefficients - target).T)
    for gcp, residual in zip(gcps, residuals, strict=True):
        gcp["residual_m"] = round(float(residual), 4)
    if a * e - b * d >= 0:
        raise PdfImportError(f"{path.name}: georeferencing is mirrored; refusing to guess")
    worst = float(residuals.max())
    if worst > RESIDUAL_LIMIT_M:
        raise PdfImportError(
            f"{path.name}: /GPTS do not fit one affine transform (worst {worst:.2f} m > "
            f"{RESIDUAL_LIMIT_M} m)"
        )
    return {
        "affine": Affine(a, b, c, d, e, f),
        "gcps": gcps,
        "max_residual_m": round(worst, 4),
    }


def pixel_to_geo(transform: Affine, crs: CRS, points: list[tuple[float, float]]) -> list:
    to_geodetic = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    out = []
    for col, row in points:
        x, y = transform @ (col, row)
        lon, lat = to_geodetic.transform(x, y)
        out.append(
            {
                "pixel": [round(col, 2), round(row, 2)],
                "lon": round(lon, 7),
                "lat": round(lat, 7),
            }
        )
    return out


# --- optional content ----------------------------------------------------------------------


def ocg_name(ocg) -> str:
    return text_of(ocg.get_object().get("/Name")) or "(unnamed)"


def read_layers(reader: pypdf.PdfReader) -> tuple[list[dict], dict[int, bool]]:
    """Layer names and their default state from /OCProperties /D, with /Order nesting."""
    properties = reader.trailer["/Root"].get("/OCProperties")
    if properties is None:
        return [], {}
    properties = properties.get_object()
    config = properties.get("/D", {}).get_object() if properties.get("/D") else {}
    base = str(config.get("/BaseState", "/ON"))
    on = {ref.idnum for ref in config.get("/ON", [])}
    off = {ref.idnum for ref in config.get("/OFF", [])}
    state = {}
    for ref in properties.get("/OCGs", []):
        visible = ref.idnum not in off if base != "/OFF" else ref.idnum in on
        state[ref.idnum] = visible
    parents: dict[int, str] = {}

    def walk(order, parent):
        previous = None
        for item in order:
            resolved = item.get_object()
            if isinstance(resolved, pypdf.generic.ArrayObject):
                walk(resolved, previous if previous is not None else parent)
            elif isinstance(item, pypdf.generic.IndirectObject):
                if parent is not None:
                    parents[item.idnum] = parent
                previous = ocg_name(item)

    walk(config.get("/Order", []), None)
    layers = [
        {
            "name": ocg_name(ref),
            "object": ref.idnum,
            "parent": parents.get(ref.idnum),
            "default_visible": state[ref.idnum],
        }
        for ref in properties.get("/OCGs", [])
    ]
    return layers, state


def read_memberships(page, state: dict[int, bool], path: Path) -> list[dict]:
    """Every /OCMD the page's content is gated by, evaluated under the default configuration."""
    resources = page.get("/Resources")
    props = resources.get_object().get("/Properties") if resources is not None else None
    groups = {}
    for ref in (props.get_object() if props is not None else {}).values():
        obj = ref.get_object()
        if obj.get("/Type") != "/OCMD":
            continue
        if obj.get("/VE") is not None:
            raise PdfImportError(f"{path.name}: /OCMD visibility expressions are not handled")
        members = obj.get("/OCGs", [])
        members = [members] if isinstance(members, pypdf.generic.IndirectObject) else members
        policy = str(obj.get("/P", "/AnyOn")).lstrip("/")
        states = [state.get(m.idnum, True) for m in members]
        visible = {
            "AllOn": all(states),
            "AnyOn": any(states),
            "AnyOff": not all(states),
            "AllOff": not any(states),
        }[policy]
        names = [ocg_name(m) for m in members]
        groups[(policy, tuple(names))] = {
            "members": names,
            "policy": policy,
            "default_visible": visible,
        }
    return [groups[key] for key in sorted(groups)]


# --- rendering -----------------------------------------------------------------------------


def render_page(path: Path, width: int, height: int) -> np.ndarray:
    """RGB page raster at an exact pixel size, through PDFium's default optional content."""
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise PdfImportError(f"{path.name}: PDFium cannot open it: {exc}") from None
    try:
        page = document[0]
        bitmap = pdfium.PdfBitmap.new_native(width, height, pdfium_c.FPDFBitmap_BGR)
        bitmap.fill_rect((255, 255, 255, 255), 0, 0, width, height)
        pdfium_c.FPDF_RenderPageBitmap(
            bitmap.raw, page.raw, 0, 0, width, height, 0, RENDER_FLAGS
        )
        pixels = np.array(bitmap.to_numpy()[:, :, :3])
    except PdfImportError:
        raise
    except Exception as exc:
        raise PdfImportError(f"{path.name}: rendering failed: {exc}") from None
    finally:
        document.close()
    if pixels.shape != (height, width, 3):
        raise PdfImportError(f"{path.name}: rendering returned {pixels.shape}")
    if (pixels == pixels[0, 0]).all():
        raise PdfImportError(f"{path.name}: rendering failed: the page rendered blank")
    return pixels


def check_renderer() -> None:
    """Stop unless PDFium hides content gated by an OFF layer, directly or through an /OCMD."""
    doc = pymupdf.open()
    page = doc.new_page(width=40, height=20)
    hidden = doc.add_ocg("hidden", on=False)
    shown = doc.add_ocg("shown", on=True)
    page.draw_rect(pymupdf.Rect(0, 0, 10, 10), fill=(0, 0, 0), width=0, oc=hidden)
    gate = doc.set_ocmd(ocgs=[hidden, shown], policy="AllOn")
    page.draw_rect(pymupdf.Rect(10, 0, 20, 10), fill=(0, 0, 0), width=0, oc=gate)
    page.draw_rect(pymupdf.Rect(20, 0, 30, 10), fill=(0, 0, 0), width=0, oc=shown)
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.pdf"
        doc.save(probe)
        pixels = render_page(probe, 40, 20)
    if pixels[5, 5].min() < 250 or pixels[5, 15].min() < 250 or pixels[5, 25].max() > 5:
        raise PdfImportError(
            f"PDFium {pdfium.PDFIUM_INFO} does not honour default layer visibility; "
            "refusing to render hidden layers"
        )


# --- page content inspection ---------------------------------------------------------------


def open_content(path: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfImportError(f"{path.name}: corrupt or unreadable PDF: {exc}") from None
    if doc.is_repaired:
        doc.close()
        raise PdfImportError(
            f"{path.name}: corrupt PDF; its cross-reference table needed repair"
        )
    return doc


def quad_corners(drawing) -> list[tuple[float, float]] | None:
    items = drawing["items"]
    if len(items) == 1 and items[0][0] == "qu":
        quad = items[0][1]
        points = [quad.ul, quad.ur, quad.lr, quad.ll]
    elif len(items) == 1 and items[0][0] == "re":
        rect = items[0][1]
        points = [rect.tl, rect.tr, rect.br, rect.bl]
    elif len(items) in (3, 4) and all(item[0] == "l" for item in items):
        points = [item[1] for item in items]
        if len(items) == 3 and not drawing.get("closePath"):
            return None
    else:
        return None
    return [(p.x, p.y) for p in points]


def find_neatline(page: pymupdf.Page) -> dict | None:
    """The largest stroked quadrilateral drawn on the page: the map frame's neatline."""
    page_area = page.rect.width * page.rect.height
    best = None
    for drawing in page.get_drawings():
        if "s" not in drawing["type"]:
            continue
        corners = quad_corners(drawing)
        if corners is None:
            continue
        xs, ys = zip(*corners, strict=True)
        area = 0.5 * abs(
            sum(xs[i] * ys[i - 1] - xs[i - 1] * ys[i] for i in range(len(corners)))
        )
        if area < NEATLINE_MIN_PAGE_FRACTION * page_area:
            continue
        if best is None or area > best[0]:
            best = (area, corners, drawing.get("layer"))
    if best is None:
        return None
    corners = best[1]
    ordered = {
        "upper_left": min(corners, key=lambda p: p[0] + p[1]),
        "lower_right": max(corners, key=lambda p: p[0] + p[1]),
        "upper_right": max(corners, key=lambda p: p[0] - p[1]),
        "lower_left": min(corners, key=lambda p: p[0] - p[1]),
    }
    return {"layer": best[2], "corners_pt": ordered}


def collar_text(page: pymupdf.Page, neatline: dict | None) -> list[dict]:
    """Text blocks outside the neatline: title, credits, datum, scale and notices."""
    if neatline is None:
        inside = pymupdf.Rect()
    else:
        xs = [p[0] for p in neatline["corners_pt"].values()]
        ys = [p[1] for p in neatline["corners_pt"].values()]
        inside = pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))
    blocks = []
    for x0, y0, x1, y1, text, *_ in page.get_text("blocks", sort=True):
        box = pymupdf.Rect(x0, y0, x1, y1)
        # Map labels clipped by the neatline belong to the map, not the collar.
        if not inside.is_empty and inside.contains((box.tl + box.br) / 2):
            continue
        text = clean(text)
        if text:
            blocks.append({"bbox_pt": [round(v, 1) for v in (x0, y0, x1, y1)], "text": text})
    return blocks


def credit_note(blocks: list[dict], catalogued: str) -> dict:
    """The printed credit column under the anchor line, compared with the catalog's note."""
    anchor = next((b for b in blocks if CREDIT_ANCHOR in b["text"]), None)
    segments = [s.strip() for s in catalogued.split("|") if s.strip()]
    if anchor is None:
        text = None
    else:
        x0, y0 = anchor["bbox_pt"][:2]
        column = [
            b for b in blocks if abs(b["bbox_pt"][0] - x0) <= 2 and b["bbox_pt"][1] >= y0 - 1
        ]
        text = " ".join(b["text"] for b in sorted(column, key=lambda b: b["bbox_pt"][1]))
    found = [
        {"segment": s, "found": text is not None and canon(s) in canon(text)} for s in segments
    ]
    return {"printed": text, "catalog_segments": found}


def nominal_offset(neatline_geo: dict[str, dict]) -> dict:
    """Metres from each nominal 7.5-minute corner to the drawn neatline corner."""
    corners = {
        "upper_left": (NOMINAL_BOX["west"], NOMINAL_BOX["north"]),
        "upper_right": (NOMINAL_BOX["east"], NOMINAL_BOX["north"]),
        "lower_left": (NOMINAL_BOX["west"], NOMINAL_BOX["south"]),
        "lower_right": (NOMINAL_BOX["east"], NOMINAL_BOX["south"]),
    }
    report = {}
    for key, (lon, lat) in corners.items():
        found = neatline_geo[key]
        azimuth, _, distance = GEOD.inv(lon, lat, found["lon"], found["lat"])
        report[key] = {
            "nominal": [lon, lat],
            "east_m": round(distance * math.sin(math.radians(azimuth)), 3),
            "north_m": round(distance * math.cos(math.radians(azimuth)), 3),
            "distance_m": round(distance, 3),
        }
    report["max_distance_m"] = max(v["distance_m"] for v in report.values())
    return report


# --- outputs -------------------------------------------------------------------------------


def write_cog(path: Path, pixels: np.ndarray, transform: Affine, epsg: int) -> None:
    """Write one RGB COG, replacing `path` only once the whole file exists."""
    height, width, _ = pixels.shape
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(dir=path.parent, prefix=".staging-"))
    try:
        plain = staged / "plain.tif"
        with rasterio.open(
            plain,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=3,
            dtype="uint8",
            crs=CRS.from_epsg(epsg).to_wkt(),
            transform=transform,
            tiled=True,
            blockxsize=warp_raster.TILE_SIZE,
            blockysize=warp_raster.TILE_SIZE,
            compress="deflate",
        ) as dataset:
            dataset.write(np.moveaxis(pixels, 2, 0))
            dataset.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]
        cog = staged / "cog.tif"
        rasterio.shutil.copy(
            plain,
            cog,
            driver="COG",
            RESAMPLING=warp_raster.OVERVIEW_RESAMPLING["nearest"],
            **warp_raster.COG_OPTIONS,
        )
        os.replace(cog, path)
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def plan(entry: dict, receipt: dict, dpi: int, versions: dict) -> dict:
    return {
        "processing_version": PDF_PROCESSING_VERSION,
        "edition_id": entry["edition_id"],
        "source_sha256": receipt["sha256"],
        "credit_note": entry["rights"]["credit_note"],
        "dpi": dpi,
        "layer_policy": LAYER_POLICY,
        "render_flags": RENDER_FLAGS,
        "tool_versions": versions,
    }


def process_source(
    entry: dict, receipt: dict, root: Path, out_dir: Path, dpi: int, versions: dict
) -> dict:
    """Verify, inspect, georeference and render one PDF; return its processing record."""
    path = verify_source(receipt, root)
    if entry["rights"]["status"] != "public_domain":
        raise PdfImportError(f"{entry['edition_id']}: publication rights are unresolved")
    reader = open_structure(path)
    page = reader.pages[0]
    geometry = page_geometry(page)
    viewport = read_viewport(page, path)
    crs, epsg = identify_crs(viewport, path)
    width = round(geometry["width_pt"] * dpi / 72)
    height = round(geometry["height_pt"] * dpi / 72)
    scale = (width / geometry["width_pt"], height / geometry["height_pt"])
    fit = fit_geotransform(viewport, geometry, crs, scale, path)
    transform = fit["affine"]
    layers, state = read_layers(reader)
    memberships = read_memberships(page, state, path)

    content = open_content(path)
    try:
        mu_page = content[0]
        annotations = len(list(mu_page.annots()))
        neatline = find_neatline(mu_page)
        blocks = collar_text(mu_page, neatline)
    finally:
        content.close()

    bounds_pixels = [
        unit_to_pixel(viewport, geometry, scale, *viewport["bounds"][i : i + 2])
        for i in range(0, len(viewport["bounds"]), 2)
    ]
    neatline_record, offset = None, None
    if neatline is not None:
        names = list(neatline["corners_pt"])
        pixels = [(x * scale[0], y * scale[1]) for x, y in neatline["corners_pt"].values()]
        geo = dict(zip(names, pixel_to_geo(transform, crs, pixels), strict=True))
        for name in names:
            geo[name]["page_pt"] = [round(v, 3) for v in neatline["corners_pt"][name]]
        neatline_record = {
            "method": "largest stroked quadrilateral in the page content",
            "layer": neatline["layer"],
            "corners": geo,
        }
        offset = nominal_offset(geo)

    credits = credit_note(blocks, entry["rights"]["credit_note"])
    missing = [c["segment"] for c in credits["catalog_segments"] if not c["found"]]
    if missing:
        raise PdfImportError(
            f"{path.name}: catalogued credit not found in the printed collar: "
            + "; ".join(missing)
        )

    pixels = render_page(path, width, height)
    output = out_dir / "pdf" / f"{entry['edition_id']}.tif"
    write_cog(output, pixels, transform, epsg)
    del pixels
    verify_source(receipt, root)
    digest, byte_count = warp_raster.sha256_file(output)
    a, b, c, d, e, f = transform[:6]
    return {
        "edition_id": entry["edition_id"],
        "source_id": entry["source_id"],
        "title": entry["title"],
        "source": {
            "path": receipt["path"],
            "sha256": receipt["sha256"],
            "size_bytes": receipt["size_bytes"],
            "verified_before_and_after": True,
        },
        "page": {
            "mediabox_pt": geometry["mediabox"],
            "annotations": annotations,
            "annotations_rendered": False,
        },
        "georeferencing": {
            "method": "ISO 32000 /VP /Measure /GEO (GPTS to LPTS, least-squares affine)",
            "viewport": viewport["viewport"],
            "viewports": viewport["viewports"],
            "viewport_bbox_pt": viewport["bbox"],
            "gcs_type": viewport["gcs_type"],
            "wkt": viewport["wkt"],
            "epsg": epsg,
            "epsg_identification": f"pyproj confidence >= {CRS_MIN_CONFIDENCE}, equivalent",
            "gpts": viewport["gpts"],
            "lpts": viewport["lpts"],
            "gcps": fit["gcps"],
            "max_residual_m": fit["max_residual_m"],
            "geotransform": [c, a, b, f, d, e],
            "rotation_deg": round(math.degrees(math.atan2(d, a)), 5),
            "measure_bounds": pixel_to_geo(transform, crs, bounds_pixels),
        },
        "neatline": neatline_record,
        "nominal_box": NOMINAL_BOX,
        "nominal_offset": offset,
        "registration_status": "offset reported, registration not reviewed or accepted",
        "layers": layers,
        "content_groups": memberships,
        "layer_policy": LAYER_POLICY,
        "collar_text": blocks,
        "credit_note": credits,
        "raster": {
            "path": relative(output),
            "sha256": digest,
            "byte_count": byte_count,
            "crs": f"EPSG:{epsg}",
            "dpi": dpi,
            "width": width,
            "height": height,
            "pixel_size_m": [round(math.hypot(a, d), 5), round(math.hypot(b, e), 5)],
            "bands": ["red", "green", "blue"],
            "overview_resampling": "nearest",
        },
    }


def reusable(entry: dict | None, fingerprint: str, out_dir: Path) -> dict | None:
    """An existing COG is reused only when its inputs and its own bytes both still match."""
    if entry is None or entry.get("fingerprint") != fingerprint:
        return None
    output = out_dir / "pdf" / f"{entry['edition_id']}.tif"
    if not output.is_file():
        return None
    if warp_raster.sha256_file(output) != (
        entry["raster"]["sha256"],
        entry["raster"]["byte_count"],
    ):
        return None
    return entry


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        staged = Path(handle.name)
    os.replace(staged, path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run(
    root: Path,
    catalog: Path,
    ledger: Path,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
    expected=demo_sources.PDF_SOURCE_IDS,
    echo=click.echo,
) -> dict:
    entries = demo_sources.load_catalog(catalog, expected)
    receipts = demo_sources.load_ledger(ledger)
    missing = [sid for sid in entries if sid not in receipts]
    if missing:
        raise PdfImportError(f"No PDF receipt for {', '.join(missing)}; run expansion-fetch")
    for source_id in entries:
        verify_source(receipts[source_id], root)
    with warnings.catch_warnings():
        # The GDAL probe writes an ungeoreferenced PNG on purpose.
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        warp_raster.require_gdal()
    check_renderer()
    versions = tool_versions()
    record_path = out_dir / RECORD_NAME
    previous = read_json(record_path) or {}
    prior = {s["edition_id"]: s for s in previous.get("sources", [])}
    results = []
    for source_id, entry in entries.items():
        receipt = receipts[source_id]
        fingerprint = warp_raster.fingerprint(plan(entry, receipt, dpi, versions))
        reused = reusable(prior.get(entry["edition_id"]), fingerprint, out_dir)
        if reused is not None:
            verify_source(receipt, root)
            echo(f"  {entry['edition_id']}: reused {reused['raster']['path']} (bytes verified)")
            results.append(reused)
            continue
        result = process_source(entry, receipt, root, out_dir, dpi, versions)
        result["fingerprint"] = fingerprint
        offset = result["nominal_offset"]
        echo(
            f"  {entry['edition_id']}: wrote {result['raster']['path']} "
            f"(EPSG:{result['georeferencing']['epsg']}, "
            f"{result['raster']['pixel_size_m'][0]} m pixels, neatline offset "
            + (f"{offset['max_distance_m']} m" if offset else "not measured")
            + ")"
        )
        results.append(result)
    payload = {
        "version": 1,
        "processing_version": PDF_PROCESSING_VERSION,
        "tool_versions": versions,
        "dpi": dpi,
        "layer_policy": LAYER_POLICY,
        "nominal_box": NOMINAL_BOX,
        "published": False,
        "sources": sorted(results, key=lambda r: r["edition_id"]),
    }
    write_json(record_path, payload)
    return payload


@click.group()
def cli() -> None:
    pass


@cli.command("run")
@click.option(
    "--raw-root",
    type=click.Path(file_okay=False, path_type=Path),
    envvar="DEMO_RAW_ROOT",
    default=archive.RAW_ROOT,
)
@click.option("--catalog", type=click.Path(path_type=Path), default=demo_sources.CATALOG_PATH)
@click.option("--ledger", type=click.Path(path_type=Path), default=demo_sources.LEDGER_PATH)
@click.option("--out-dir", type=click.Path(file_okay=False, path_type=Path), default=OUT_DIR)
@click.option("--dpi", type=click.IntRange(72, 600), default=DEFAULT_DPI, show_default=True)
def run_command(raw_root: Path, catalog: Path, ledger: Path, out_dir: Path, dpi: int) -> None:
    """Verify the receipted PDFs, then write one georeferenced COG per PDF plus a record."""
    run(raw_root, catalog, ledger, out_dir, dpi)
    click.echo(f"expansion-pdf: record at {relative(out_dir / RECORD_NAME)}")


if __name__ == "__main__":
    cli()
