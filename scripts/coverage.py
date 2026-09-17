#!/usr/bin/env python3
"""Build the coverage bookkeeping artefacts keyed by coverage.json (README §6).

  coverage grid     -> data/sources/coverage_grid.geojson
      A 7.5-minute (0.125°) reference grid over the county AOI, tiled from the global
      origin (-180,-90). Cells are research units: where we looked, not what we found.

  coverage refresh  -> data/sources/coverage.json
      Every grid area x every decade from 1950, with the topo editions and verified
      candidates whose footprint and explicit dates reach that cell. An attached
      reference is a lead to examine, never a review, an observation or evidence.

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
from datetime import UTC, datetime
from pathlib import Path

import click
from fetch_topoview import read_index
from jsonschema import Draft202012Validator
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


FIRST_DECADE = 1950
# A generated cell records only that nobody has looked yet.
NEW_CELL_GAP_CODES = ["not_digitized", "not_examined", "unsearched"]
# Dates of the depicted ground. imprint_year is a printing date and content_year is a
# sort convenience, so neither dates a feature.
FEATURE_YEAR_FIELDS = (
    "date_on_map",
    "aerial_photo_year",
    "photo_revision_year",
    "field_check_year",
    "edit_year",
    "photo_inspection_year",
    "survey_year",
)
BOUND_FIELDS = ("west", "south", "east", "north")


def refresh_fail(message: str) -> None:
    click.echo(f"coverage refresh: {message}", err=True)
    sys.exit(1)


def current_decade() -> int:
    return datetime.now(UTC).year // 10 * 10


def read_json(path: Path, label: str) -> dict:
    if not path.exists():
        refresh_fail(f"{label} {path} does not exist")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        refresh_fail(f"{label} {path} is not valid JSON: {exc}")


def grid_areas(path: Path) -> dict[str, tuple[float, float, float, float]]:
    """area_id -> bounding box, taken from the committed grid rather than recomputed."""
    document = read_json(path, "grid")
    areas: dict[str, tuple[float, float, float, float]] = {}
    for index, feature in enumerate(document.get("features") or []):
        properties = (feature or {}).get("properties") or {}
        area_id = properties.get("area_id")
        if not area_id:
            refresh_fail(f"grid feature {index} has no area_id")
        if area_id in areas:
            refresh_fail(f"grid names area {area_id} twice")
        geometry = feature.get("geometry")
        if not geometry:
            refresh_fail(f"grid feature {area_id} has no geometry")
        areas[area_id] = shape(geometry).bounds
    if not areas:
        refresh_fail(f"grid {path} carries no features")
    return areas


def parse_year(value: str, label: str) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) != 4 or not text.isdigit():
        refresh_fail(f"{label} is {value!r}, which is not a four-digit year")
    return int(text)


def parse_bounds(row: dict, label: str) -> tuple[float, float, float, float] | None:
    values = []
    for field in BOUND_FIELDS:
        text = (row.get(field) or "").strip()
        if not text:
            return None
        try:
            values.append(float(text))
        except ValueError:
            refresh_fail(f"{label} {field} is {row[field]!r}, which is not a number")
    west, south, east, north = values
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        refresh_fail(f"{label} bounds {values} are not an ordered lon/lat box")
    return west, south, east, north


def overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """Positive-area intersection; a shared edge or corner is not coverage."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def topo_decades(row: dict, topo_id: str, decades: list[int]) -> set[int]:
    """Decades an edition explicitly dates. Gaps between two dates stay unclaimed."""
    allowed = set(decades)
    found = set()
    for field in FEATURE_YEAR_FIELDS:
        year = parse_year(row.get(field, ""), f"topo {topo_id} {field}")
        if year is None or year < FIRST_DECADE:
            continue
        decade = year // 10 * 10
        if decade in allowed:
            found.add(decade)
    return found


def candidate_decades(item: dict, decades: list[int]) -> set[int]:
    """Only a verified candidate with real bounds and a real start date links to cells."""
    label = f"candidate {item['candidate_id']}"
    if item.get("verification") != "verified":
        return set()
    if any(item.get(field) is None for field in BOUND_FIELDS):
        return set()
    start = parse_year(str(item.get("date_start") or "")[:4], label)
    if start is None:
        return set()
    end = parse_year(str(item.get("date_end") or "")[:4], label)
    last = max(start, end) if end is not None else start
    return {d for d in decades if start // 10 * 10 <= d <= last // 10 * 10}


def candidate_bounds(item: dict) -> tuple[float, ...]:
    return tuple(float(item[field]) for field in BOUND_FIELDS)


def check_references(
    existing: dict, areas: dict, decades: list[int], topo_ids: set[str]
) -> None:
    """Refuse to drop a manual record whose target is gone; a human reconciles it."""
    known_decades = set(decades)
    candidate_ids = {item["candidate_id"] for item in existing["candidates"]}
    record_ids = {
        "search": {item["search_id"] for item in existing["searches"]},
        "review": {item["review_id"] for item in existing["reviews"]},
        "batch": {item["batch_id"] for item in existing["batches"]},
    }

    def check_source_refs(refs, label):
        for ref in refs:
            kind, _, value = ref.partition(":")
            if kind == "topo" and value not in topo_ids:
                refresh_fail(f"{label} references {ref}, absent from the topo index")
            if kind == "candidate" and value not in candidate_ids:
                refresh_fail(f"{label} references {ref}, absent from candidates")

    def check_area(area_id, label):
        if area_id not in areas:
            refresh_fail(f"{label} references area {area_id}, absent from the grid")

    def check_decade(decade, label):
        if decade not in known_decades:
            refresh_fail(f"{label} references decade {decade}, outside the inventory")

    for item in existing["searches"]:
        label = f"search {item['search_id']}"
        for area_id in item["area_ids"]:
            check_area(area_id, label)
        for decade in item["decades"]:
            check_decade(decade, label)
        check_source_refs(item["source_refs"], label)

    for item in existing["reviews"]:
        label = f"review {item['review_id']}"
        check_area(item["area_id"], label)
        check_decade(item["decade"], label)
        check_source_refs([item["source_ref"]], label)

    for item in existing["batches"]:
        label = f"batch {item['batch_id']}"
        for area_id in item["area_ids"]:
            check_area(area_id, label)
        check_decade(item["decade"], label)
        check_source_refs(item["source_refs"], label)
        for review_id in item["review_ids"]:
            if review_id not in record_ids["review"]:
                refresh_fail(f"{label} references review {review_id}, which does not exist")

    for cell in existing["cells"]:
        label = f"cell {cell['area_id']}/{cell['decade']}"
        if cell["area_id"] not in areas or cell["decade"] not in known_decades:
            recorded = any(
                cell[key]
                for key in ("source_refs", "search_ids", "review_ids", "batch_ids", "gap_codes")
            )
            if recorded or cell["gap_note"]:
                refresh_fail(
                    f"{label} carries recorded work but its area or decade left the "
                    "inventory; reconcile it by hand"
                )
            continue
        check_source_refs(cell["source_refs"], label)
        for key, kind in (
            ("search_ids", "search"),
            ("review_ids", "review"),
            ("batch_ids", "batch"),
        ):
            for value in cell[key]:
                if value not in record_ids[kind]:
                    refresh_fail(f"{label} references {kind} {value}, which does not exist")


def check_unique_ids(existing: dict) -> None:
    for bucket, key in (
        ("candidates", "candidate_id"),
        ("searches", "search_id"),
        ("reviews", "review_id"),
        ("batches", "batch_id"),
    ):
        seen = set()
        for item in existing[bucket]:
            value = item[key]
            if value in seen:
                refresh_fail(f"{bucket} names {key} {value} twice")
            seen.add(value)
    keys = set()
    for cell in existing["cells"]:
        key = (cell["area_id"], cell["decade"])
        if key in keys:
            refresh_fail(f"cells name {key[0]}/{key[1]} twice")
        keys.add(key)


def validate_document(document: dict, schema_path: Path, label: str) -> None:
    schema = read_json(schema_path, "schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.absolute_path)
    )
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        refresh_fail(f"{label} fails schema at {location}: {first.message}")


def load_existing(path: Path, schema: Path) -> dict:
    if not path.exists():
        return {
            "version": 1,
            "through_decade": FIRST_DECADE,
            "cells": [],
            "candidates": [],
            "searches": [],
            "reviews": [],
            "batches": [],
        }
    existing = read_json(path, "inventory")
    validate_document(existing, schema, "the existing inventory")
    return existing


def build_inventory_cells(
    existing: dict, areas: dict, decades: list[int], generated: dict
) -> list[dict]:
    kept = {(cell["area_id"], cell["decade"]): cell for cell in existing["cells"]}
    cells = []
    for area_id in sorted(areas):
        for decade in decades:
            previous = kept.get((area_id, decade))
            manual = [
                ref
                for ref in (previous["source_refs"] if previous else [])
                if ref.startswith("candidate:")
            ]
            refs = sorted(set(manual) | generated.get((area_id, decade), set()))
            if previous is None:
                cells.append(
                    {
                        "area_id": area_id,
                        "decade": decade,
                        "source_refs": refs,
                        "search_ids": [],
                        "review_ids": [],
                        "batch_ids": [],
                        "gap_codes": list(NEW_CELL_GAP_CODES),
                        "gap_note": None,
                    }
                )
                continue
            cells.append(
                {
                    "area_id": area_id,
                    "decade": decade,
                    "source_refs": refs,
                    "search_ids": previous["search_ids"],
                    "review_ids": previous["review_ids"],
                    "batch_ids": previous["batch_ids"],
                    "gap_codes": previous["gap_codes"],
                    "gap_note": previous["gap_note"],
                }
            )
    return cells


@cli.command()
@click.option(
    "--grid",
    "grid_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "coverage_grid.geojson",
    show_default=True,
)
@click.option(
    "--index",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "topo_index.csv",
    show_default=True,
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "coverage.json",
    show_default=True,
)
@click.option(
    "--schema",
    type=click.Path(dir_okay=False, path_type=Path),
    default=REPO_ROOT / "schema" / "coverage.schema.json",
    show_default=True,
)
@click.option(
    "--through-decade",
    type=int,
    default=None,
    help="Latest decade to account for. Defaults to the current UTC decade.",
)
def refresh(grid_path: Path, index: Path, out: Path, schema: Path, through_decade: int) -> None:
    """Rebuild every area/decade cell and attach candidate source references."""
    through = current_decade() if through_decade is None else through_decade
    if through < FIRST_DECADE or through % 10:
        refresh_fail(
            f"--through-decade {through} must be a multiple of 10 and >= {FIRST_DECADE}"
        )
    decades = list(range(FIRST_DECADE, through + 1, 10))

    areas = grid_areas(grid_path)
    rows = read_index(index)
    existing = load_existing(out, schema)
    check_unique_ids(existing)
    check_references(existing, areas, decades, set(rows))

    generated: dict[tuple[str, int], set[str]] = {}

    def associate(ref: str, bounds, source_decades: set[int]) -> None:
        for area_id, area_bounds in areas.items():
            if not overlaps(area_bounds, bounds):
                continue
            for decade in source_decades:
                generated.setdefault((area_id, decade), set()).add(ref)

    for topo_id, row in rows.items():
        bounds = parse_bounds(row, f"topo {topo_id}")
        linked = topo_decades(row, topo_id, decades)
        if bounds is not None and linked:
            associate(f"topo:{topo_id}", bounds, linked)

    for item in existing["candidates"]:
        linked = candidate_decades(item, decades)
        if linked:
            associate(f"candidate:{item['candidate_id']}", candidate_bounds(item), linked)

    document = {
        "version": 1,
        "through_decade": through,
        "cells": build_inventory_cells(existing, areas, decades, generated),
        "candidates": existing["candidates"],
        "searches": existing["searches"],
        "reviews": existing["reviews"],
        "batches": existing["batches"],
    }
    validate_document(document, schema, "the refreshed inventory")
    write_staged(out, document)
    linked_cells = sum(1 for cell in document["cells"] if cell["source_refs"])
    click.echo(
        f"coverage refresh: wrote {out} — {len(document['cells'])} cells "
        f"({len(areas)} areas x {len(decades)} decades), {linked_cells} with a source reference"
    )


if __name__ == "__main__":
    cli()
