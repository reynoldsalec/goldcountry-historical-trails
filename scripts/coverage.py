#!/usr/bin/env python3
"""Build the coverage bookkeeping artefacts keyed by coverage.json (README §6).

  coverage grid  -> data/sources/coverage_grid.geojson
      A 7.5-minute (0.125°) reference grid over the county AOI, tiled from the global
      origin (-180,-90). Cells are research units: where we looked, not what we found.

The grid comes from the AOI alone, never from an index of sheets we happen to hold —
deriving it from source availability would hide the quadrangles nobody has searched,
which is the one thing the coverage inventory exists to show. Cells are reference
squares with synthetic ids; they are not official USGS quadrangle footprints or names.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import click
from shapely.geometry import box, shape
from shapely.ops import unary_union
from validate import ALLOWED_CRS_NAMES

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
COORD_DECIMALS = 6
CELL_DEGREES = 0.125  # 7.5 minutes
ORIGIN_LON = -180.0
ORIGIN_LAT = -90.0


def fail(message: str) -> None:
    click.echo(f"coverage grid: {message}", err=True)
    sys.exit(1)


def load_geometries(path: Path, label: str) -> list[tuple[dict, object]]:
    """Read a FeatureCollection as (properties, geometry) pairs, refusing repairs."""
    if not path.exists():
        fail(f"{label} {path} does not exist")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{label} {path} is not valid JSON: {exc}")
    crs = document.get("crs")
    if crs is not None:
        named = (crs.get("properties") or {}).get("name") if isinstance(crs, dict) else None
        if named not in ALLOWED_CRS_NAMES:
            fail(f"{label} names crs {named!r}; the grid is EPSG:4326 only (AGENTS.md §3)")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        fail(f"{label} {path} carries no features")

    pairs = []
    for index, feature in enumerate(features):
        geometry = (feature or {}).get("geometry")
        if not geometry:
            fail(f"{label} feature {index} has no geometry")
        geom = shape(geometry)
        if geom.is_empty:
            fail(f"{label} feature {index} has empty geometry")
        if not geom.is_valid:
            fail(
                f"{label} feature {index} is invalid geometry; fix the source rather "
                "than repairing it here"
            )
        pairs.append(((feature.get("properties") or {}), geom))
    return pairs


def cell_polygon(i: int, j: int):
    west = ORIGIN_LON + i * CELL_DEGREES
    south = ORIGIN_LAT + j * CELL_DEGREES
    return box(west, south, west + CELL_DEGREES, south + CELL_DEGREES)


def truncate(value: float) -> float:
    return round(value, COORD_DECIMALS)


def cell_feature(i: int, j: int, geoids: list[str]) -> dict:
    west = truncate(ORIGIN_LON + i * CELL_DEGREES)
    south = truncate(ORIGIN_LAT + j * CELL_DEGREES)
    east = truncate(ORIGIN_LON + (i + 1) * CELL_DEGREES)
    north = truncate(ORIGIN_LAT + (j + 1) * CELL_DEGREES)
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]
            ],
        },
        "properties": {"area_id": f"q7p5-{i}-{j}", "county_geoids": geoids},
    }


def build_cells(aoi, counties: list[tuple[dict, object]]) -> list[dict]:
    minx, miny, maxx, maxy = aoi.bounds
    # One extra ring of candidates absorbs float error at the bbox edges; the
    # positive-area test below is what actually decides membership.
    i_lo = math.floor((minx - ORIGIN_LON) / CELL_DEGREES) - 1
    i_hi = math.floor((maxx - ORIGIN_LON) / CELL_DEGREES) + 1
    j_lo = math.floor((miny - ORIGIN_LAT) / CELL_DEGREES) - 1
    j_hi = math.floor((maxy - ORIGIN_LAT) / CELL_DEGREES) + 1

    features = []
    for i in range(i_lo, i_hi + 1):
        for j in range(j_lo, j_hi + 1):
            cell = cell_polygon(i, j)
            if cell.intersection(aoi).area <= 0:
                continue
            geoids = sorted(
                {
                    str(properties["GEOID"])
                    for properties, geom in counties
                    if properties.get("GEOID") and cell.intersection(geom).area > 0
                }
            )
            if not geoids:
                fail(
                    f"cell q7p5-{i}-{j} intersects the AOI but no county part; "
                    "the AOI and the county parts disagree"
                )
            features.append(cell_feature(i, j, geoids))
    features.sort(key=lambda f: f["properties"]["area_id"])
    return features


def write_staged(out: Path, document: dict) -> None:
    """Stage beside the target so a failed run leaves the committed grid intact."""
    out.parent.mkdir(parents=True, exist_ok=True)
    staged = out.with_name(out.name + ".staged")
    staged.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.replace(staged, out)


@click.group()
def cli() -> None:
    """Build coverage bookkeeping artefacts."""


@cli.command()
@click.option(
    "--aoi",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "aoi_counties.geojson",
    show_default=True,
)
@click.option(
    "--counties",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "aoi_county_parts.geojson",
    show_default=True,
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "coverage_grid.geojson",
    show_default=True,
)
def grid(aoi: Path, counties: Path, out: Path) -> None:
    """Tile the county AOI into 7.5-minute reference cells."""
    aoi_geom = unary_union([geom for _, geom in load_geometries(aoi, "AOI")])
    if not aoi_geom.is_valid:
        fail("the AOI features do not union into a valid geometry")
    county_parts = load_geometries(counties, "county parts")

    features = build_cells(aoi_geom, county_parts)
    if not features:
        fail("no cell intersects the AOI")
    write_staged(out, {"type": "FeatureCollection", "features": features})
    click.echo(f"coverage grid: wrote {out} — {len(features)} cells")


if __name__ == "__main__":
    cli()
