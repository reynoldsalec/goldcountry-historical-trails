#!/usr/bin/env python3
"""Build the coverage bookkeeping artefacts keyed by coverage.json (README §6).

  coverage grid     -> data/sources/coverage_grid.geojson
      A 7.5-minute (0.125°) reference grid over the county AOI, tiled from the global
      origin (-180,-90). Cells are research units: where we looked, not what we found.

  coverage refresh  -> data/sources/coverage.json
      Every grid area x every decade from 1950, with the topo editions and verified
      candidates whose footprint and explicit dates reach that cell. An attached
      reference is a lead to examine, never a review, an observation or evidence.

  coverage validate -> exit status
      Cross-reference integrity for the inventory, and with --release-ready the M1
      batch and aerial-frame gate. An explicit gap passes; an unsupported claim fails.

  coverage report   -> docs/coverage.md
      Per county and decade: how many cells have a located source, how many were
      examined, how many were digitized, and how many nobody has looked at yet.
      A count is bookkeeping about the research, never a finding about the ground.

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
import yaml
from fetch_topoview import read_index
from jsonschema import Draft202012Validator
from shapely.geometry import box, shape
from shapely.ops import unary_union
from validate import ALLOWED_CRS_NAMES, Failure, as_bound

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


def read_json(path: Path, label: str, on_fail=refresh_fail) -> dict:
    if not path.exists():
        on_fail(f"{label} {path} does not exist")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        on_fail(f"{label} {path} is not valid JSON: {exc}")


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


# --------------------------------------------------------------------------------------
# validate — cross-reference integrity for the inventory (issue #12)
# --------------------------------------------------------------------------------------

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
RELEASE_DECADE_SPLIT = 2000
COUNTY_GEOIDS = ("06057", "06061")


def validate_fail(message: str) -> None:
    click.echo(f"coverage validate: {message}", err=True)
    sys.exit(1)


def report(failures: list[Failure]) -> None:
    for failure in sorted(failures, key=lambda f: (f.check, f.record, f.message)):
        click.echo(failure.render(), err=True)
    click.echo(f"coverage validate: {len(failures)} failure(s)", err=True)
    sys.exit(1)


def schema_failures(document, schema_path: Path, label: str) -> list[Failure]:
    schema = read_json(schema_path, "schema", validate_fail)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.absolute_path)
    )
    failures = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        failures.append(Failure("schema", f"{label} {location}", error.message))
    return failures


def read_source_ids(path: Path) -> set[str]:
    """sources.yml ids. A collection_id naming nothing here cites no collection."""
    if not path.exists():
        validate_fail(f"source manifest {path} does not exist")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        validate_fail(f"source manifest {path} is not valid YAML: {exc}")
    entries = document.get("sources")
    if not isinstance(entries, list):
        validate_fail(f"source manifest {path} has no sources list")
    return {entry["id"] for entry in entries if isinstance(entry, dict) and entry.get("id")}


def read_grid(path: Path, schema_path: Path) -> dict[str, dict]:
    """area_id -> bounds and counties. The grid is the only per-cell county source."""
    document = read_json(path, "grid", validate_fail)
    failures = schema_failures(document, schema_path, "coverage_grid.geojson")
    if failures:
        report(failures)
    areas: dict[str, dict] = {}
    for feature in document["features"]:
        properties = feature["properties"]
        area_id = properties["area_id"]
        if area_id in areas:
            validate_fail(f"grid names area {area_id} twice")
        geom = shape(feature["geometry"])
        areas[area_id] = {
            "bounds": geom.bounds,
            "county_geoids": list(properties["county_geoids"]),
        }
    if not areas:
        validate_fail(f"grid {path} carries no features")
    return areas


def index_bounds(row: dict) -> tuple[float, ...] | None:
    """Bounds of an index row, or None when absent or unreadable."""
    values = []
    for field in BOUND_FIELDS:
        text = (row.get(field) or "").strip()
        if not text:
            return None
        try:
            values.append(float(text))
        except ValueError:
            return None
    west, south, east, north = values
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        return None
    return west, south, east, north


def check_ids(document: dict) -> list[Failure]:
    failures = []
    for bucket, key in (
        ("candidates", "candidate_id"),
        ("searches", "search_id"),
        ("reviews", "review_id"),
        ("batches", "batch_id"),
    ):
        seen = set()
        for item in document[bucket]:
            if item[key] in seen:
                failures.append(
                    Failure("unique", f"{bucket} {item[key]}", f"{key} appears twice")
                )
            seen.add(item[key])
    seen_cells = set()
    for cell in document["cells"]:
        key = (cell["area_id"], cell["decade"])
        if key in seen_cells:
            failures.append(
                Failure("unique", f"cell {key[0]}/{key[1]}", "area_id + decade appears twice")
            )
        seen_cells.add(key)
    return failures


def check_cell_grid(document: dict, areas: dict, decades: list[int]) -> list[Failure]:
    """Every grid area x decade exactly once; a missing cell would hide a gap."""
    failures = []
    present = {(cell["area_id"], cell["decade"]) for cell in document["cells"]}
    for area_id in sorted(areas):
        for decade in decades:
            if (area_id, decade) not in present:
                failures.append(
                    Failure(
                        "cells", f"cell {area_id}/{decade}", "the inventory has no such cell"
                    )
                )
    for cell in document["cells"]:
        label = f"cell {cell['area_id']}/{cell['decade']}"
        if cell["area_id"] not in areas:
            failures.append(Failure("cells", label, "area_id is absent from the grid"))
        if cell["decade"] not in decades:
            failures.append(Failure("cells", label, f"decade is outside 1950..{decades[-1]}"))
    return failures


def check_dates(document: dict) -> list[Failure]:
    """Real calendar dates, ordered candidate ranges, observed UTC timestamps."""
    failures = []
    for item in document["candidates"]:
        label = f"candidate {item['candidate_id']}"
        start, end = item["date_start"], item["date_end"]
        for field, value in (("date_start", start), ("date_end", end)):
            if value is not None and as_bound(value, upper=False) is None:
                failures.append(
                    Failure("dates", label, f"{field} {value!r} is not a real calendar date")
                )
        if start and end:
            lo, hi = as_bound(start, upper=False), as_bound(end, upper=True)
            if lo is not None and hi is not None and hi < lo:
                failures.append(
                    Failure("dates", label, f"date_end {end} precedes date_start {start}")
                )
        if end and not start:
            failures.append(Failure("dates", label, "date_end without a date_start"))
        bounds = [item[field] for field in BOUND_FIELDS]
        if all(value is not None for value in bounds):
            west, south, east, north = (float(value) for value in bounds)
            if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                failures.append(
                    Failure("dates", label, f"bounds {bounds} are not an ordered lon/lat box")
                )
        elif any(value is not None for value in bounds):
            failures.append(Failure("dates", label, "bounds are partly known; use all or none"))
    for bucket, key, field in (
        ("searches", "search_id", "searched_at"),
        ("reviews", "review_id", "reviewed_at"),
    ):
        for item in document[bucket]:
            try:
                datetime.strptime(item[field], TIMESTAMP_FORMAT).replace(tzinfo=UTC)
            except ValueError:
                failures.append(
                    Failure(
                        "dates",
                        f"{bucket[:-1]} {item[key]}",
                        f"{field} {item[field]!r} is not a valid UTC instant",
                    )
                )
    return failures


def check_reference_targets(
    document: dict, areas: dict, decades: list[int], topo_ids: set[str], source_ids: set[str]
) -> list[Failure]:
    failures = []
    candidate_ids = {item["candidate_id"] for item in document["candidates"]}
    record_ids = {
        "search": {item["search_id"] for item in document["searches"]},
        "review": {item["review_id"] for item in document["reviews"]},
        "batch": {item["batch_id"] for item in document["batches"]},
    }

    def check_refs(refs, label):
        for ref in refs:
            kind, _, value = ref.partition(":")
            if kind == "topo" and value not in topo_ids:
                failures.append(
                    Failure("references", label, f"{ref} is absent from topo_index.csv")
                )
            if kind == "candidate" and value not in candidate_ids:
                failures.append(
                    Failure("references", label, f"{ref} is absent from candidates")
                )

    def check_area(area_id, label):
        if area_id not in areas:
            failures.append(
                Failure("references", label, f"area {area_id} is absent from the grid")
            )

    def check_decade(decade, label):
        if decade not in decades:
            failures.append(
                Failure("references", label, f"decade {decade} is outside the inventory")
            )

    def check_collection(collection_id, label):
        if collection_id not in source_ids:
            failures.append(
                Failure(
                    "references",
                    label,
                    f"collection {collection_id} is absent from sources.yml",
                )
            )

    for item in document["candidates"]:
        check_collection(item["collection_id"], f"candidate {item['candidate_id']}")

    for item in document["searches"]:
        label = f"search {item['search_id']}"
        check_collection(item["collection_id"], label)
        for area_id in item["area_ids"]:
            check_area(area_id, label)
        for decade in item["decades"]:
            check_decade(decade, label)
        check_refs(item["source_refs"], label)

    for item in document["reviews"]:
        label = f"review {item['review_id']}"
        check_area(item["area_id"], label)
        check_decade(item["decade"], label)
        check_refs([item["source_ref"]], label)
        counties = areas.get(item["area_id"], {}).get("county_geoids", [])
        if counties and item["county_geoid"] not in counties:
            failures.append(
                Failure(
                    "references",
                    label,
                    f"county {item['county_geoid']} does not meet area {item['area_id']}",
                )
            )

    for item in document["batches"]:
        label = f"batch {item['batch_id']}"
        for area_id in item["area_ids"]:
            check_area(area_id, label)
        check_decade(item["decade"], label)
        check_refs(item["source_refs"], label)
        for review_id in item["review_ids"]:
            if review_id not in record_ids["review"]:
                failures.append(
                    Failure("references", label, f"review {review_id} does not exist")
                )

    for cell in document["cells"]:
        label = f"cell {cell['area_id']}/{cell['decade']}"
        check_refs(cell["source_refs"], label)
        for key, kind in (
            ("search_ids", "search"),
            ("review_ids", "review"),
            ("batch_ids", "batch"),
        ):
            for value in cell[key]:
                if value not in record_ids[kind]:
                    failures.append(
                        Failure("references", label, f"{kind} {value} does not exist")
                    )
    return failures


def check_cell_records(document: dict, areas: dict, rows: dict) -> list[Failure]:
    """A record linked to a cell must be about that cell, and a gap flag needs support."""
    failures = []
    searches = {item["search_id"]: item for item in document["searches"]}
    reviews = {item["review_id"]: item for item in document["reviews"]}
    batches = {item["batch_id"]: item for item in document["batches"]}
    candidates = {item["candidate_id"]: item for item in document["candidates"]}

    for cell in document["cells"]:
        label = f"cell {cell['area_id']}/{cell['decade']}"
        linked_searches = [searches[s] for s in cell["search_ids"] if s in searches]

        for search in linked_searches:
            covers = (
                cell["area_id"] in search["area_ids"] and cell["decade"] in search["decades"]
            )
            if not covers:
                failures.append(
                    Failure(
                        "records",
                        label,
                        f"search {search['search_id']} covers another area or decade",
                    )
                )
        for review_id in cell["review_ids"]:
            review = reviews.get(review_id)
            if review is None:
                continue
            if review["area_id"] != cell["area_id"] or review["decade"] != cell["decade"]:
                failures.append(
                    Failure(
                        "records",
                        label,
                        f"review {review_id} examined "
                        f"{review['area_id']}/{review['decade']}, not this cell",
                    )
                )
        for batch_id in cell["batch_ids"]:
            batch = batches.get(batch_id)
            if batch is None:
                continue
            if cell["area_id"] not in batch["area_ids"] or batch["decade"] != cell["decade"]:
                failures.append(
                    Failure("records", label, f"batch {batch_id} does not cover this cell")
                )

        outcomes = {search["outcome"] for search in linked_searches}
        for code, outcome in (
            ("no_source_located", "no_match"),
            ("access_blocked", "access_blocked"),
        ):
            if code in cell["gap_codes"] and outcome not in outcomes:
                failures.append(
                    Failure(
                        "gaps",
                        label,
                        f"gap {code} needs a linked search with outcome {outcome}",
                    )
                )
        if "not_digitized" not in cell["gap_codes"]:
            digitized = [
                batch_id
                for batch_id in cell["batch_ids"]
                if batches.get(batch_id, {}).get("status") == "digitized"
            ]
            if not digitized:
                failures.append(
                    Failure(
                        "gaps",
                        label,
                        "not_digitized was cleared without a digitized batch on this cell",
                    )
                )

        area = areas.get(cell["area_id"])
        if area is None:
            continue
        for ref in cell["source_refs"]:
            kind, _, value = ref.partition(":")
            bounds = None
            if kind == "candidate" and value in candidates:
                item = candidates[value]
                if all(item[field] is not None for field in BOUND_FIELDS):
                    bounds = candidate_bounds(item)
            elif kind == "topo" and value in rows:
                bounds = index_bounds(rows[value])
            if bounds is not None and not overlaps(area["bounds"], bounds):
                failures.append(
                    Failure("records", label, f"{ref} does not reach this area's footprint")
                )
    return failures


def ready_batch_failures(batch: dict, document: dict, areas: dict) -> list[Failure]:
    """What a status: ready batch must carry before anyone digitizes against it."""
    failures = []
    label = f"batch {batch['batch_id']}"
    reviews = {item["review_id"]: item for item in document["reviews"]}
    if not batch["tasks"]:
        failures.append(Failure("batches", label, "status ready with no review tasks"))
    if not batch["source_refs"]:
        failures.append(Failure("batches", label, "status ready with no source_refs"))
    in_county = [
        area_id
        for area_id in batch["area_ids"]
        if batch["county_geoid"] in areas.get(area_id, {}).get("county_geoids", [])
    ]
    if not in_county:
        failures.append(
            Failure("batches", label, f"no listed area meets county {batch['county_geoid']}")
        )
    supporting = [
        review_id
        for review_id in batch["review_ids"]
        if (review := reviews.get(review_id))
        and review["dating"] == "resolved"
        and review["foot_trail_evidence"] == "yes"
        and review["evidence_locator"]
        and review["county_geoid"] == batch["county_geoid"]
        and review["decade"] == batch["decade"]
        and review["area_id"] in batch["area_ids"]
    ]
    if not supporting:
        failures.append(
            Failure(
                "batches",
                label,
                "status ready without a dated, located foot-trail review for its county, "
                "decade and areas",
            )
        )
    return failures


def check_batches(document: dict, areas: dict) -> tuple[list[Failure], list[dict]]:
    failures = []
    qualifying = []
    for batch in document["batches"]:
        label = f"batch {batch['batch_id']}"
        if batch["status"] == "digitized":
            failures.append(
                Failure(
                    "batches",
                    label,
                    "status digitized is rejected until M3 links sources to observations",
                )
            )
        if batch["alignment_ids"]:
            failures.append(
                Failure(
                    "batches",
                    label,
                    "alignment_ids stays empty until M3 validates it against alignments",
                )
            )
        if batch["status"] != "ready":
            continue
        batch_failures = ready_batch_failures(batch, document, areas)
        failures.extend(batch_failures)
        if not batch_failures:
            qualifying.append(batch)
    return failures, qualifying


def release_aerial_failures(document: dict, aoi) -> list[Failure]:
    """The M1 gate needs one obtainable dated aerial frame (README §7)."""
    reasons = []
    for item in document["candidates"]:
        if item["kind"] != "aerial_frame":
            continue
        problems = []
        if item["verification"] != "verified":
            problems.append("verification is not verified")
        if not item["source_identifier"]:
            problems.append("no publisher source_identifier")
        if item["access"] != "available":
            problems.append(f"access is {item['access']}")
        if item["rights"] == "unknown":
            problems.append("rights unknown is not a redistribution permission")
        if any(item[field] is None for field in BOUND_FIELDS):
            problems.append("bounds are not fully known")
        elif box(*candidate_bounds(item)).intersection(aoi).area <= 0:
            problems.append("bounds do not reach the county AOI")
        start, end = item["date_start"], item["date_end"]
        start_year = int(start[:4]) if start else None
        end_year = int(end[:4]) if end else None
        if start_year is None:
            problems.append("no date_start")
        elif start_year < FIRST_DECADE and end_year is not None and end_year >= FIRST_DECADE:
            problems.append("date range straddles 1950; resolve the dating first")
        elif start_year < FIRST_DECADE:
            problems.append(f"date_start {start} precedes {FIRST_DECADE}")
        if not problems:
            return []
        reasons.append(
            Failure("release", f"candidate {item['candidate_id']}", "; ".join(problems))
        )
    if not reasons:
        reasons.append(
            Failure(
                "release",
                "candidates",
                "no verified, available, dated aerial_frame candidate inside the county AOI",
            )
        )
    return reasons


def release_batch_failures(qualifying: list[dict]) -> list[Failure]:
    """Planned batches never count here; only what a reviewer has declared ready."""
    failures = []
    for county in COUNTY_GEOIDS:
        decades = sorted({b["decade"] for b in qualifying if b["county_geoid"] == county})
        label = f"county {county}"
        if len(decades) < 2:
            failures.append(
                Failure(
                    "release",
                    label,
                    f"needs two decades of status ready batches, has {decades or 'none'}",
                )
            )
        if not any(decade < RELEASE_DECADE_SPLIT for decade in decades):
            failures.append(
                Failure("release", label, "no status ready batch in a decade before 2000")
            )
        if not any(decade >= RELEASE_DECADE_SPLIT for decade in decades):
            failures.append(
                Failure("release", label, "no status ready batch in a decade from 2000 onward")
            )
    return failures


@cli.command("validate")
@click.option(
    "--data",
    "data_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "coverage.json",
    show_default=True,
)
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
    "--sources",
    "sources_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "sources.yml",
    show_default=True,
)
@click.option(
    "--aoi",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "aoi_counties.geojson",
    show_default=True,
)
@click.option(
    "--schema",
    type=click.Path(dir_okay=False, path_type=Path),
    default=REPO_ROOT / "schema" / "coverage.schema.json",
    show_default=True,
)
@click.option(
    "--grid-schema",
    type=click.Path(dir_okay=False, path_type=Path),
    default=REPO_ROOT / "schema" / "coverage_grid.schema.json",
    show_default=True,
)
@click.option(
    "--release-ready",
    is_flag=True,
    help="Also check the M1 gate: four ready county/decade batches and an aerial frame.",
)
def validate_inventory(
    data_path: Path,
    grid_path: Path,
    index: Path,
    sources_path: Path,
    aoi: Path,
    schema: Path,
    grid_schema: Path,
    release_ready: bool,
) -> None:
    """Check inventory references, cell coverage and batch readiness.

    An explicit gap passes: an unsearched cell is recorded bookkeeping, not an error.
    What fails is a claim with no record behind it.
    """
    document = read_json(data_path, "inventory", validate_fail)
    schema_problems = schema_failures(document, schema, "coverage.json")
    if schema_problems:
        report(schema_problems)

    areas = read_grid(grid_path, grid_schema)
    decades = list(range(FIRST_DECADE, document["through_decade"] + 1, 10))
    rows = read_index(index)
    source_ids = read_source_ids(sources_path)

    failures = check_ids(document)
    failures += check_cell_grid(document, areas, decades)
    failures += check_dates(document)
    failures += check_reference_targets(document, areas, decades, set(rows), source_ids)
    failures += check_cell_records(document, areas, rows)
    batch_failures, qualifying = check_batches(document, areas)
    failures += batch_failures

    if release_ready:
        aoi_geom = unary_union([geom for _, geom in load_geometries(aoi, "AOI")])
        failures += release_batch_failures(qualifying)
        failures += release_aerial_failures(document, aoi_geom)

    if failures:
        report(failures)
    scope = "release-ready" if release_ready else "inventory"
    click.echo(
        f"coverage validate: {scope} OK — {len(document['cells'])} cells, "
        f"{len(document['candidates'])} candidates, {len(document['searches'])} searches, "
        f"{len(document['reviews'])} reviews, {len(document['batches'])} batches"
    )


# --------------------------------------------------------------------------------------
# report — docs/coverage.md from the grid and the inventory (issue #13)
# --------------------------------------------------------------------------------------

DOCS_DIR = REPO_ROOT / "docs"
COVERAGE_DOC = DOCS_DIR / "coverage.md"
COUNTY_NAMES = {"06057": "Nevada County", "06061": "Placer County"}
GAP_CODES = (
    "unsearched",
    "no_source_located",
    "access_blocked",
    "dating_unresolved",
    "not_examined",
    "partially_examined",
    "not_digitized",
)


def report_fail(message: str) -> None:
    click.echo(f"coverage report: {message}", err=True)
    sys.exit(1)


def empty_counts() -> dict:
    counts = {
        "cells": 0,
        "located": 0,
        "examined_whole": 0,
        "examined_partial": 0,
        "unexamined": 0,
        "ready": 0,
        "digitized": 0,
    }
    counts.update({code: 0 for code in GAP_CODES})
    return counts


def summarise(document: dict, areas: dict, decades: list[int]) -> dict:
    """county -> decade -> counts. A shared-border cell is counted in each county."""
    reviews = {item["review_id"]: item for item in document["reviews"]}
    tally = {
        geoid: {decade: empty_counts() for decade in decades} for geoid in sorted(COUNTY_NAMES)
    }

    for cell in document["cells"]:
        area = areas.get(cell["area_id"])
        if area is None:
            report_fail(f"cell {cell['area_id']}/{cell['decade']} names no grid area")
        if cell["decade"] not in decades:
            report_fail(f"cell {cell['area_id']}/{cell['decade']} lies outside through_decade")
        scopes = set()
        for review_id in cell["review_ids"]:
            review = reviews.get(review_id)
            if review is None:
                report_fail(
                    f"cell {cell['area_id']}/{cell['decade']} references review "
                    f"{review_id}, which does not exist"
                )
            scopes.add(review["scope"])
        for geoid in area["county_geoids"]:
            counts = tally[geoid][cell["decade"]]
            counts["cells"] += 1
            if cell["source_refs"]:
                counts["located"] += 1
            if "whole_source_footprint" in scopes:
                counts["examined_whole"] += 1
            elif scopes:
                counts["examined_partial"] += 1
            else:
                counts["unexamined"] += 1
            for code in cell["gap_codes"]:
                counts[code] += 1

    for batch in document["batches"]:
        if batch["status"] == "planned":
            continue
        if batch["decade"] not in decades:
            report_fail(f"batch {batch['batch_id']} names a decade outside the inventory")
        tally[batch["county_geoid"]][batch["decade"]][batch["status"]] += 1

    return tally


def totals(rows: dict) -> dict:
    """Sum the decade rows of one county. Two decades never share a cell, so this is exact."""
    summed = empty_counts()
    for counts in rows.values():
        for key, value in counts.items():
            summed[key] += value
    return summed


def county_area_counts(areas: dict) -> tuple[dict[str, int], int]:
    per_county = {geoid: 0 for geoid in sorted(COUNTY_NAMES)}
    shared = 0
    for area in areas.values():
        geoids = area["county_geoids"]
        if len(geoids) > 1:
            shared += 1
        for geoid in geoids:
            per_county[geoid] += 1
    return per_county, shared


def state_row(label: str, counts: dict) -> str:
    return (
        f"| {label} | {counts['cells']} | {counts['located']} | "
        f"{counts['examined_partial']} | {counts['examined_whole']} | "
        f"{counts['unexamined']} | {counts['ready']} | {counts['digitized']} |"
    )


def gap_row(label: str, counts: dict) -> str:
    cells = " | ".join(str(counts[code]) for code in GAP_CODES)
    return f"| {label} | {cells} |"


def repo_relative(path: Path) -> str:
    """Repo-relative so the doc is identical wherever the checkout lives."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


def render(document: dict, areas: dict, data_path: Path, grid_path: Path) -> str:
    decades = list(range(FIRST_DECADE, document["through_decade"] + 1, 10))
    tally = summarise(document, areas, decades)
    per_county, shared = county_area_counts(areas)

    lines = [
        "# Coverage inventory report",
        "",
        "<!-- Generated by `scripts/coverage.py report`. Do not edit by hand; edit",
        "     `data/sources/coverage.json` or the script and regenerate with",
        "     `make coverage-report`. -->",
        "",
        "Research bookkeeping for both counties, 1950 onward: which area/decade cells have",
        "a located source, which have been examined, and which nobody has looked at yet.",
        f"The machine-readable form is `{repo_relative(data_path)}`, keyed on the reference",
        f"cells in `{repo_relative(grid_path)}`. This is an internal research output. It is",
        "not the public viewer and it carries no trail geometry.",
        "",
        "## Reading the counts",
        "",
        "Four states are distinct and are never merged:",
        "",
        "- **Located** — a source footprint and an explicit date reach the cell. A lead to",
        "  examine, not a review and not evidence.",
        "- **Examined** — a person reviewed a located source for that cell and recorded the",
        "  review. `partial` covered part of the source footprint; `whole source footprint`",
        "  covered all of it.",
        "- **Digitized** — a batch recorded as digitized. Zero throughout M1: digitizing",
        "  starts in M3.",
        "- **Unexamined** — no review is recorded for the cell. Nobody has looked yet.",
        "",
        "A zero, a `no_source_located` gap or a `no_match` search outcome says that this",
        "research has not found a source, or has not looked. None of them states that a",
        "trail was absent, closed or lost. Absence from a map sheet is evidence of nothing",
        "on its own (AGENTS.md §2.3).",
        "",
        "## Grid areas",
        "",
        f"The grid holds {len(areas)} reference cells over both counties. {shared} of them",
        "cross the county boundary and are counted once in each county they intersect, so",
        "**the county columns below overlap and must not be summed as a unique total**.",
        "",
        "| County | Grid areas | Decades | Area/decade cells |",
        "| --- | --- | --- | --- |",
    ]
    for geoid in sorted(COUNTY_NAMES):
        lines.append(
            f"| {COUNTY_NAMES[geoid]} ({geoid}) | {per_county[geoid]} | {len(decades)} | "
            f"{totals(tally[geoid])['cells']} |"
        )
    lines += [
        f"| unique across both | {len(areas)} | {len(decades)} | {len(areas) * len(decades)} |",
        "",
    ]

    for geoid in sorted(COUNTY_NAMES):
        rows = tally[geoid]
        lines += [
            f"## {COUNTY_NAMES[geoid]} ({geoid})",
            "",
            "| Decade | Cells | Located | Examined (partial) | Examined (whole source "
            "footprint) | Unexamined | Ready batches | Digitized batches |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for decade in decades:
            lines.append(state_row(f"{decade}s", rows[decade]))
        lines += [
            state_row("**all decades**", totals(rows)),
            "",
            "Recorded gaps for the same cells. A cell can carry more than one code, so the",
            "codes do not sum to the cell count.",
            "",
            "| Decade | " + " | ".join(f"`{code}`" for code in GAP_CODES) + " |",
            "| --- | " + " | ".join("---" for _ in GAP_CODES) + " |",
        ]
        for decade in decades:
            lines.append(gap_row(f"{decade}s", rows[decade]))
        lines += [gap_row("**all decades**", totals(rows)), ""]

    lines += [
        "## What the report does not say",
        "",
        "Nothing here supports a trail alignment. An alignment still needs an observation",
        "and a support row in `data/authoritative/` (AGENTS.md §2.4). Uneven counts across",
        "the counties record uneven source availability and uneven research effort.",
        "",
    ]
    return "\n".join(lines) + "\n"


@cli.command("report")
@click.option(
    "--data",
    "data_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "coverage.json",
    show_default=True,
)
@click.option(
    "--grid",
    "grid_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "coverage_grid.geojson",
    show_default=True,
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=COVERAGE_DOC,
    show_default=True,
)
@click.option(
    "--schema",
    type=click.Path(dir_okay=False, path_type=Path),
    default=REPO_ROOT / "schema" / "coverage.schema.json",
    show_default=True,
)
@click.option(
    "--grid-schema",
    type=click.Path(dir_okay=False, path_type=Path),
    default=REPO_ROOT / "schema" / "coverage_grid.schema.json",
    show_default=True,
)
def report_cmd(data_path: Path, grid_path: Path, out: Path, schema: Path, grid_schema: Path):
    """Regenerate docs/coverage.md from the grid and the inventory.

    The output carries no timestamp and is ordered by county, decade and gap code, so a
    re-run over unchanged inputs is byte-identical.
    """
    document = read_json(data_path, "inventory", report_fail)
    problems = schema_failures(document, schema, "coverage.json")
    if problems:
        for failure in sorted(problems, key=lambda f: (f.check, f.record, f.message)):
            click.echo(failure.render(), err=True)
        report_fail(f"{len(problems)} schema failure(s); run 'make validate-coverage'")
    areas = read_grid(grid_path, grid_schema)

    text = render(document, areas, data_path, grid_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    staged = out.with_name(out.name + ".staged")
    staged.write_text(text, encoding="utf-8")
    os.replace(staged, out)
    click.echo(f"coverage report: wrote {out} — {len(document['cells'])} cells")


if __name__ == "__main__":
    cli()
