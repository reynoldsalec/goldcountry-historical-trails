"""Reproject a georeferenced source scan onto the shared EPSG:3857 demo grid, then tile it.

GDAL is reached only through rasterio's bundled library, because no gdalwarp/gdalinfo
binary exists in this checkout or in CI (issue #40); gdal2tiles is unavailable for the
same reason, so the XYZ pyramid is cut here (issue #41). The datum operation is pinned
with pyproj and passed to GDAL, because the two carry different PROJ builds and would
otherwise be free to disagree; see docs/demo-processing.md.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np
import pyproj
import rasterio
import rasterio.shutil
from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.transformer import TransformerGroup
from rasterio.enums import ColorInterp, Resampling
from rasterio.features import rasterize
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from rasterio.warp import calculate_default_transform, reproject
from rasterio.windows import Window
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

# Bumped when a change to this module invalidates every existing COG.
PROCESSING_VERSION = 1
# Bumped when a change to the tile cutter invalidates every existing pyramid.
TILING_VERSION = 1

TILE_CRS_EPSG = 3857
TILE_SIZE = 256

# AGENTS.md §3: scanned map sheets keep their line colour only under nearest neighbour.
RESAMPLING_BY_KIND = {"topo": "nearest", "orthophotoquad": "cubic"}
# Overview resampling follows the full-resolution choice for the same reason.
OVERVIEW_RESAMPLING = {"nearest": "NEAREST", "cubic": "CUBIC"}

# GDAL samples the source outline at a coarse step when it suggests a warp extent, so its
# answer and a densified pyproj answer differ by a fraction of a pixel, not by a datum.
PIPELINE_AGREEMENT_METRES = 5.0
OUTLINE_SAMPLES = 128

# The tile pyramid is XYZ: y counts down from the north edge of the world, the opposite of
# TMS. gdal2tiles would default to TMS without --xyz; nothing here has a TMS mode at all.
TILE_SCHEME = "xyz"
TILE_FORMAT = "png"
# Tiles are small, so the slowest deflate level costs little and keeps the pyramid compact.
PNG_OPTIONS = {"ZLEVEL": 9}
# Alpha is decimated with nearest at every zoom so it stays two-valued; an interpolated
# alpha would put semi-transparent pixels along every crop edge.
ALPHA_RESAMPLING = "nearest"
# Dark pixels counted per zoom as a proxy for how much drawn line survives decimation. It is
# a count, not a verdict: whether a zoom is legible is a human judgement (issue #38).
INK_THRESHOLD = 128

COG_OPTIONS = {
    "BLOCKSIZE": TILE_SIZE,
    "COMPRESS": "DEFLATE",
    "PREDICTOR": "YES",
    "OVERVIEWS": "IGNORE_EXISTING",
    "BIGTIFF": "IF_SAFER",
}


class WarpError(Exception):
    """A stop condition: a missing tool, an unusable CRS, or a source that cannot be read."""


def tool_versions() -> dict:
    """Both PROJ builds, because pyproj picks the operation and GDAL applies it."""
    return {
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "proj_gdal": rasterio.__proj_version__,
        "pyproj": pyproj.__version__,
        "proj_pyproj": pyproj.proj_version_str,
        "gdal_provider": "rasterio wheel (no gdalwarp/gdalinfo binary is used)",
    }


def require_gdal() -> dict:
    """Fail before any output is produced if the bundled GDAL cannot write a COG."""
    try:
        with rasterio.Env():
            drivers = rasterio.drivers.raster_driver_extensions()
    except Exception as exc:  # pragma: no cover - a broken wheel, not a code path
        raise WarpError(f"rasterio's bundled GDAL failed to initialise: {exc}") from exc
    if "tif" not in drivers:
        raise WarpError("rasterio's bundled GDAL has no GTiff driver; reinstall rasterio.")
    versions = tool_versions()
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.tif"
        cog = Path(directory) / "probe-cog.tif"
        with rasterio.open(
            probe,
            "w",
            driver="GTiff",
            width=TILE_SIZE,
            height=TILE_SIZE,
            count=1,
            dtype="uint8",
            crs=f"EPSG:{TILE_CRS_EPSG}",
            transform=Affine(1.0, 0.0, 0.0, 0.0, -1.0, float(TILE_SIZE)),
        ) as dataset:
            dataset.write(np.zeros((TILE_SIZE, TILE_SIZE), "uint8"), 1)
        try:
            rasterio.shutil.copy(probe, cog, driver="COG")
        except Exception as exc:
            raise WarpError(
                f"rasterio's bundled GDAL {versions['gdal']} cannot write a COG: {exc}. "
                "Install a GDAL 3.1+ build (the COG driver) before running make demo-cogs."
            ) from exc
        try:
            write_png(
                Path(directory) / "probe.png", np.zeros((2, TILE_SIZE, TILE_SIZE), "uint8")
            )
        except Exception as exc:
            raise WarpError(
                f"rasterio's bundled GDAL {versions['gdal']} cannot write a PNG tile: {exc}. "
                "Install a GDAL build with the PNG driver before running make demo-rasters."
            ) from exc
    return versions


def resampling_for(kind: str) -> str:
    if kind not in RESAMPLING_BY_KIND:
        raise WarpError(
            f"No resampling rule for source kind {kind!r}; "
            f"known kinds are {sorted(RESAMPLING_BY_KIND)}."
        )
    return RESAMPLING_BY_KIND[kind]


def _mercator_origin() -> float:
    """Half the EPSG:3857 world width, derived rather than pasted in as a constant."""
    return abs(
        Transformer.from_crs(4326, TILE_CRS_EPSG, always_xy=True).transform(180.0, 0.0)[0]
    )


def select_operation(
    src_crs: CRS, aoi: tuple[float, float, float, float], required_steps: list[str]
) -> dict:
    """Pin one named, non-ballpark source-CRS to EPSG:3857 operation and return its pipeline.

    `required_steps` are the datum steps `demo.py check` recorded. Warping through a
    different one would move the imagery off the crops that check verified.
    """
    geodetic = src_crs.geodetic_crs
    if geodetic is None:
        raise WarpError(
            f"Source CRS {src_crs.name!r} has no datum; refusing to guess one. "
            "Nothing was written."
        )
    group = TransformerGroup(
        src_crs,
        CRS.from_epsg(TILE_CRS_EPSG),
        always_xy=True,
        allow_ballpark=False,
        area_of_interest=AreaOfInterest(*aoi),
    )
    if not group.transformers:
        raise WarpError(
            f"No non-ballpark transformation from {src_crs.name!r} to EPSG:{TILE_CRS_EPSG} "
            "is available; install the PROJ grids before warping."
        )
    chosen = group.transformers[0]
    if chosen.accuracy is None or chosen.accuracy < 0:
        raise WarpError(f"Transformation {chosen.description!r} reports no accuracy.")
    if "ballpark" in chosen.description.lower():
        raise WarpError(f"Only a ballpark transformation is available: {chosen.description}")
    missing = [step for step in required_steps if step not in chosen.description]
    if missing:
        raise WarpError(
            f"The warp would use {chosen.description!r}, which omits the datum step(s) "
            f"demo-check recorded ({', '.join(missing)}). The COG would not agree with the "
            "committed crops; nothing was written."
        )
    return {
        "description": chosen.description,
        "accuracy_metres": chosen.accuracy,
        "pipeline": chosen.to_proj4(),
        "unavailable_better": [op.name for op in group.unavailable_operations],
    }


def common_grid(view_bounds_wgs84: list[float], zoom: int) -> dict:
    """One EPSG:3857 extent and resolution for every edition, snapped to the XYZ pyramid.

    Snapping to whole zoom-`zoom` tiles is what lets D2b cut tiles without resampling
    again, and it makes "same grid" checkable by comparing integers.
    """
    if not 0 <= zoom <= 24:
        raise WarpError(f"Grid zoom {zoom} is outside 0-24.")
    west, south, east, north = view_bounds_wgs84
    if west >= east or south >= north:
        raise WarpError(f"view_bounds_wgs84 is inverted or empty: {view_bounds_wgs84}")
    origin = _mercator_origin()
    forward = Transformer.from_crs(4326, TILE_CRS_EPSG, always_xy=True)
    # Parallels and meridians stay straight in web Mercator, so the corners bound the box.
    x_min, y_min = forward.transform(west, south)
    x_max, y_max = forward.transform(east, north)
    span = 2 * origin / 2**zoom
    x_first = math.floor((x_min + origin) / span)
    x_last = math.ceil((x_max + origin) / span) - 1
    y_first = math.floor((origin - y_max) / span)
    y_last = math.ceil((origin - y_min) / span) - 1
    left = -origin + x_first * span
    top = origin - y_first * span
    resolution = span / TILE_SIZE
    width = (x_last - x_first + 1) * TILE_SIZE
    height = (y_last - y_first + 1) * TILE_SIZE
    return {
        "crs": f"EPSG:{TILE_CRS_EPSG}",
        "zoom": zoom,
        "tile_size": TILE_SIZE,
        "tile_range": {"x_min": x_first, "x_max": x_last, "y_min": y_first, "y_max": y_last},
        "resolution_metres": resolution,
        "width": width,
        "height": height,
        "transform": [resolution, 0.0, left, 0.0, -resolution, top],
        "bounds": [left, top - height * resolution, left + width * resolution, top],
    }


def grid_transform(grid: dict) -> Affine:
    return Affine(*grid["transform"])


def crop_mask(crop_wgs84: dict, grid: dict) -> np.ndarray:
    """The alpha band: inside the committed crop polygon, and nothing else.

    Derived from geometry alone. A white-pixel rule would erase legitimate white map
    content, so no pixel value takes part in this decision (AGENTS.md §2.1).
    """
    forward = Transformer.from_crs(4326, TILE_CRS_EPSG, always_xy=True)
    projected = shapely_transform(
        lambda xs, ys: forward.transform(np.asarray(xs), np.asarray(ys)), shape(crop_wgs84)
    )
    if not projected.is_valid or projected.is_empty:
        raise WarpError("The crop polygon is empty or invalid in EPSG:3857.")
    mask = rasterize(
        [(mapping(projected), 255)],
        out_shape=(grid["height"], grid["width"]),
        transform=grid_transform(grid),
        fill=0,
        dtype="uint8",
        all_touched=False,
    )
    if not mask.any():
        raise WarpError("The crop polygon does not intersect the shared grid.")
    return mask


def verify_pipeline(dataset, pipeline: str) -> dict:
    """Prove GDAL warps through the pinned operation, and record what it would pick alone.

    GDAL's suggested warp extent comes from the same transformer the warp itself uses, so
    comparing it against the pinned pipeline is a check on the warp and not on a bystander.
    """
    src_crs = dataset.crs
    args = (
        src_crs,
        CRS.from_epsg(TILE_CRS_EPSG),
        dataset.width,
        dataset.height,
        *dataset.bounds,
    )

    def suggested(**extra) -> np.ndarray:
        transform, width, height = calculate_default_transform(*args, **extra)
        return np.array(
            [
                transform.c,
                transform.f + height * transform.e,
                transform.c + width * transform.a,
                transform.f,
            ]
        )

    pinned = suggested(COORDINATE_OPERATION=pipeline)
    default = suggested()
    left, bottom, right, top = dataset.bounds
    xs = np.linspace(left, right, OUTLINE_SAMPLES)
    ys = np.linspace(bottom, top, OUTLINE_SAMPLES)
    outline_x = np.concatenate(
        [xs, np.full(OUTLINE_SAMPLES, right), xs, np.full(OUTLINE_SAMPLES, left)]
    )
    outline_y = np.concatenate(
        [np.full(OUTLINE_SAMPLES, bottom), ys, np.full(OUTLINE_SAMPLES, top), ys]
    )
    px, py = Transformer.from_pipeline(pipeline).transform(outline_x, outline_y)
    expected = np.array([px.min(), py.min(), px.max(), py.max()])
    pinned_residual = float(np.abs(pinned - expected).max())
    if pinned_residual > PIPELINE_AGREEMENT_METRES:
        raise WarpError(
            f"GDAL warped extent is {pinned_residual:.3f} m from the pinned pipeline, over the "
            f"{PIPELINE_AGREEMENT_METRES} m limit: GDAL {rasterio.__proj_version__} did not "
            f"honour COORDINATE_OPERATION. Nothing was written."
        )
    return {
        "pinned_vs_pyproj_metres": round(pinned_residual, 4),
        "gdal_default_vs_pinned_metres": round(float(np.abs(default - pinned).max()), 4),
    }


def warp(dataset, grid: dict, resampling: str, pipeline: str) -> tuple[np.ndarray, np.ndarray]:
    """Warp every band plus the source validity mask onto the shared grid."""
    try:
        enum = Resampling[resampling]
    except KeyError as exc:  # pragma: no cover - resampling_for guards the caller
        raise WarpError(f"Unknown resampling {resampling!r}") from exc
    shape_out = (grid["height"], grid["width"])
    transform = grid_transform(grid)
    dst_crs = f"EPSG:{TILE_CRS_EPSG}"
    data = np.zeros((dataset.count, *shape_out), dtype="uint8")
    for index in range(dataset.count):
        reproject(
            source=rasterio.band(dataset, index + 1),
            destination=data[index],
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=enum,
            COORDINATE_OPERATION=pipeline,
        )
    coverage = np.zeros(shape_out, dtype="uint8")
    reproject(
        source=dataset.dataset_mask(),
        src_transform=dataset.transform,
        src_crs=dataset.crs,
        destination=coverage,
        dst_transform=transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,
        COORDINATE_OPERATION=pipeline,
    )
    return data, coverage


def open_source(path: Path):
    """Open a scan, refusing one that carries no CRS rather than assuming a datum."""
    try:
        dataset = rasterio.open(path)
    except Exception as exc:
        raise WarpError(f"Cannot read source raster {path}: {exc}") from exc
    if dataset.crs is None:
        dataset.close()
        raise WarpError(
            f"{path.name} carries no CRS; its position is unknown and it will not be warped."
        )
    if dataset.dtypes[0] != "uint8":
        dataset.close()
        raise WarpError(f"{path.name} is {dataset.dtypes[0]}, not the uint8 these scans use.")
    return dataset


def write_cog(
    path: Path, data: np.ndarray, alpha: np.ndarray, grid: dict, resampling: str
) -> None:
    """Write one COG, replacing `path` only once the whole file exists."""
    bands, height, width = data.shape
    if (height, width) != (grid["height"], grid["width"]):
        raise WarpError("Warped array does not match the shared grid.")
    colours = {
        1: [ColorInterp.gray, ColorInterp.alpha],
        3: [ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha],
    }.get(bands)
    if colours is None:
        raise WarpError(f"Cannot label the colour bands of a {bands}-band source.")
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
            count=bands + 1,
            dtype="uint8",
            crs=grid["crs"],
            transform=grid_transform(grid),
            tiled=True,
            blockxsize=TILE_SIZE,
            blockysize=TILE_SIZE,
            compress="deflate",
        ) as dataset:
            dataset.write(data, indexes=list(range(1, bands + 1)))
            dataset.write(alpha, bands + 1)
            dataset.colorinterp = colours
        cog = staged / "cog.tif"
        rasterio.shutil.copy(
            plain,
            cog,
            driver="COG",
            RESAMPLING=OVERVIEW_RESAMPLING[resampling],
            **COG_OPTIONS,
        )
        os.replace(cog, path)
    finally:
        for leftover in staged.glob("*"):
            leftover.unlink()
        staged.rmdir()


BAND_COLOURS = {
    2: [ColorInterp.gray, ColorInterp.alpha],
    4: [ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha],
}


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """The XYZ tile a coordinate falls in: y counts down from the north, not up as in TMS."""
    origin = _mercator_origin()
    x_metres, y_metres = Transformer.from_crs(4326, TILE_CRS_EPSG, always_xy=True).transform(
        lon, lat
    )
    span = 2 * origin / 2**zoom
    return int(math.floor((x_metres + origin) / span)), int(
        math.floor((origin - y_metres) / span)
    )


def tile_pixel(lon: float, lat: float, zoom: int) -> dict:
    """Which XYZ tile a coordinate lands in, and which pixel of that tile."""
    origin = _mercator_origin()
    x_metres, y_metres = Transformer.from_crs(4326, TILE_CRS_EPSG, always_xy=True).transform(
        lon, lat
    )
    span = 2 * origin / 2**zoom
    x, y = tile_xy(lon, lat, zoom)
    pixel = span / TILE_SIZE
    return {
        "zoom": zoom,
        "x": x,
        "y": y,
        "column": int(math.floor(((x_metres + origin) - x * span) / pixel)),
        "row": int(math.floor(((origin - y_metres) - y * span) / pixel)),
        "x_3857": x_metres,
        "y_3857": y_metres,
    }


def verify_tile_samples(
    cog_path: Path, tile_root: Path, grid: dict, zoom: int, samples: dict
) -> list[dict]:
    """Prove named coordinates land on the tile the XYZ formula names, holding the COG's pixels.

    A pyramid written with TMS y, with a shifted window, or cut from another edition's COG
    fails here: at `zoom` a tile is a block copy, so the two readings must be equal exactly.
    """
    results = []
    with rasterio.open(cog_path) as dataset:
        for name, (lon, lat) in samples.items():
            located = tile_pixel(lon, lat, zoom)
            path = tile_root / str(zoom) / str(located["x"]) / f"{located['y']}.{TILE_FORMAT}"
            if not path.is_file():
                raise WarpError(
                    f"The {name} sample point ({lon}, {lat}) falls in tile "
                    f"{zoom}/{located['x']}/{located['y']}, which is missing from "
                    f"{tile_root.name}."
                )
            row, column = dataset.index(located["x_3857"], located["y_3857"])
            expected = dataset.read(window=Window(column, row, 1, 1)).reshape(-1)
            with rasterio.open(path) as tile:
                found = tile.read(
                    window=Window(located["column"], located["row"], 1, 1)
                ).reshape(-1)
            if found.tolist() != expected.tolist():
                raise WarpError(
                    f"Tile {zoom}/{located['x']}/{located['y']} reads {found.tolist()} at the "
                    f"{name} sample point but {cog_path.name} reads {expected.tolist()} there: "
                    "the pyramid does not match the COG it was cut from."
                )
            results.append(
                {
                    "name": name,
                    "lon": lon,
                    "lat": lat,
                    "tile": f"{zoom}/{located['x']}/{located['y']}",
                    "pixel": [located["column"], located["row"]],
                    "values": found.tolist(),
                    "opaque": bool(found[-1] > 0),
                }
            )
    return results


def tile_indices(grid: dict, zoom: int) -> dict:
    """The tile range at `zoom` that covers the shared grid, and no more than that."""
    if zoom > grid["zoom"]:
        raise WarpError(
            f"Zoom {zoom} is finer than the grid the COGs were warped onto (zoom "
            f"{grid['zoom']}); the pyramid is not upsampled past its source grid."
        )
    if zoom < 0:
        raise WarpError(f"Zoom {zoom} is negative.")
    step = 2 ** (grid["zoom"] - zoom)
    extent = grid["tile_range"]
    return {
        "x_min": extent["x_min"] // step,
        "x_max": extent["x_max"] // step,
        "y_min": extent["y_min"] // step,
        "y_max": extent["y_max"] // step,
    }


def tile_window(grid: dict, zoom: int, x: int, y: int) -> Window:
    """The part of the shared grid one tile covers, in whole grid pixels.

    The grid's own origin is a tile corner at `grid["zoom"]`, so every offset and size here
    is an exact integer and a coarser zoom is a whole-block decimation, never a resample
    against a shifted grid.
    """
    step = 2 ** (grid["zoom"] - zoom)
    extent = grid["tile_range"]
    size = TILE_SIZE * step
    return Window(
        (x * step - extent["x_min"]) * TILE_SIZE,
        (y * step - extent["y_min"]) * TILE_SIZE,
        size,
        size,
    )


def write_png(path: Path, data: np.ndarray) -> None:
    """Write one RGBA or grey+alpha tile. GDAL's PNG driver only copies, so this stages it."""
    bands, height, width = data.shape
    colours = BAND_COLOURS.get(bands)
    if colours is None:
        raise WarpError(f"A {bands}-band tile is neither grey+alpha nor RGBA.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # PAM would drop a .aux.xml beside every tile and make the pyramid's file set unstable.
    with rasterio.Env(GDAL_PAM_ENABLED="NO"), MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=width, height=height, count=bands, dtype="uint8"
        ) as staged:
            staged.write(data)
            staged.colorinterp = colours
        with memory.open() as staged:
            rasterio.shutil.copy(staged, path, driver="PNG", **PNG_OPTIONS)


def pyramid_digest(root: Path) -> tuple[str, int, int]:
    """Content identity of a pyramid on disk: every tile's relative path and bytes."""
    strays = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix != f".{TILE_FORMAT}"
    ]
    if strays:
        raise WarpError(
            f"{root} holds {len(strays)} file(s) that are not tiles, starting with "
            f"{strays[0].name}; remove them or run make clean."
        )
    lines, byte_count = [], 0
    for path in sorted(root.rglob(f"*.{TILE_FORMAT}")):
        digest, size = sha256_file(path)
        lines.append(f"{path.relative_to(root).as_posix()} {digest}")
        byte_count += size
    return (
        hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
        len(lines),
        byte_count,
    )


def cut_pyramid(
    cog_path: Path, grid: dict, zooms: list[int], resampling: str, out_root: Path
) -> dict:
    """Cut one bounded XYZ PNG pyramid from a COG on the shared grid.

    At `grid["zoom"]` a tile is a block copy of the COG, so the published imagery is the
    warp D2a recorded and not a second resampling of it. Tiles wholly outside the crop are
    still written, fully transparent, so a blank area in the viewer is distinguishable from
    a tile that failed to load.
    """
    try:
        enum = Resampling[resampling]
    except KeyError as exc:  # pragma: no cover - resampling_for guards the caller
        raise WarpError(f"Unknown resampling {resampling!r}") from exc
    if not zooms:
        raise WarpError("No zoom levels were requested.")
    levels = []
    with rasterio.open(cog_path) as dataset:
        alpha_index = dataset.count
        colour_indexes = list(range(1, alpha_index))
        if (dataset.width, dataset.height) != (grid["width"], grid["height"]):
            raise WarpError(
                f"{cog_path.name} is {dataset.width}x{dataset.height}, not the shared grid's "
                f"{grid['width']}x{grid['height']}."
            )
        for zoom in sorted(zooms):
            extent = tile_indices(grid, zoom)
            count = transparent = 0
            opaque_px = ink_px = 0
            for x in range(extent["x_min"], extent["x_max"] + 1):
                for y in range(extent["y_min"], extent["y_max"] + 1):
                    window = tile_window(grid, zoom, x, y)
                    alpha = dataset.read(
                        alpha_index,
                        window=window,
                        out_shape=(TILE_SIZE, TILE_SIZE),
                        resampling=Resampling[ALPHA_RESAMPLING],
                        boundless=True,
                        fill_value=0,
                    )
                    opaque = alpha > 0
                    if opaque.any():
                        pixels = dataset.read(
                            colour_indexes,
                            window=window,
                            out_shape=(len(colour_indexes), TILE_SIZE, TILE_SIZE),
                            resampling=enum,
                            boundless=True,
                            fill_value=0,
                        )
                        # Resampling a coarse zoom can pull colour across the crop edge.
                        pixels[:, ~opaque] = 0
                    else:
                        transparent += 1
                        pixels = np.zeros((len(colour_indexes), TILE_SIZE, TILE_SIZE), "uint8")
                    opaque_px += int(opaque.sum())
                    ink_px += int((opaque & (pixels.min(axis=0) < INK_THRESHOLD)).sum())
                    write_png(
                        out_root / str(zoom) / str(x) / f"{y}.{TILE_FORMAT}",
                        np.concatenate([pixels, alpha[np.newaxis]]),
                    )
                    count += 1
            levels.append(
                {
                    "zoom": zoom,
                    "tile_range": extent,
                    "tiles": count,
                    "transparent_tiles": transparent,
                    "opaque_px": opaque_px,
                    "ink_px": ink_px,
                }
            )
    digest, tiles, byte_count = pyramid_digest(out_root)
    expected = sum(level["tiles"] for level in levels)
    if tiles != expected:
        raise WarpError(f"{out_root} holds {tiles} tiles, not the {expected} that were cut.")
    for level in levels:
        level["bytes"] = sum(
            path.stat().st_size
            for path in (out_root / str(level["zoom"])).rglob(f"*.{TILE_FORMAT}")
        )
    return {
        "levels": levels,
        "tiles": tiles,
        "bytes": byte_count,
        "digest": digest,
        "transparent_tiles": sum(level["transparent_tiles"] for level in levels),
    }


def sha256_file(path: Path) -> tuple[str, int]:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        return digest, os.fstat(handle.fileno()).st_size


def fingerprint(plan: dict) -> str:
    """Content identity of a COG's inputs, so an unchanged edition is reused, not rewarped."""
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
