"""Reproject a georeferenced source scan onto the shared EPSG:3857 demo grid as a COG.

GDAL is reached only through rasterio's bundled library, because no gdalwarp/gdalinfo
binary exists in this checkout or in CI (issue #40). The datum operation is pinned with
pyproj and passed to GDAL, because the two carry different PROJ builds and would
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
from rasterio.transform import Affine
from rasterio.warp import calculate_default_transform, reproject
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

# Bumped when a change to this module invalidates every existing COG.
PROCESSING_VERSION = 1

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


def sha256_file(path: Path) -> tuple[str, int]:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        return digest, os.fstat(handle.fileno()).st_size


def fingerprint(plan: dict) -> str:
    """Content identity of a COG's inputs, so an unchanged edition is reused, not rewarped."""
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
