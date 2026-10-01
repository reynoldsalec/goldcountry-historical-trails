"""Edition contract and selected-source preflight for the Auburn map-browser demo.

Reads only the allowlisted inputs of the manifest version it is given: the active nine
editions (version 2, #58) or the original four (version 1, kept for its regression suite).
Nothing here writes to data/raw/ or to a receipt ledger (AGENTS.md 2.2), and no value dates
a mapped feature.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
from datetime import date
from pathlib import Path

import click
import demo_sources
import numpy as np
import rasterio
import shapely
import warp_raster
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.transformer import TransformerGroup
from rasterio.transform import rowcol
from rasterio.windows import Window
from shapely.geometry import LineString, Polygon, shape
from shapely.geometry.polygon import orient
from source_archive import check_record, load_receipts
from warp_raster import WarpError

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data/sources/demo-editions.json"
SCHEMA_PATH = REPO_ROOT / "schema/demo-editions.schema.json"
INDEX_PATH = REPO_ROOT / "data/sources/topo_index.csv"
RECEIPTS_PATH = REPO_ROOT / "data/sources/retrievals.jsonl"
SOURCES_PATH = REPO_ROOT / "data/sources/sources.yml"
RAW_ROOT = REPO_ROOT / "data/raw"
BUILD_ROOT = REPO_ROOT / "build"
RASTER_DIRNAME = "rasters"
TILE_DIRNAME = "tiles"
TILE_SUBDIR = "demo"
PROCESSING_FILENAME = "demo-processing.json"
INCOMING_DIRNAME = ".incoming"

# The viewer asks for this, relative to the published site root (D3/D4 own the site).
TILE_TEMPLATE = "tiles/{edition_id}/{z}/{x}/{y}.png"
# Sample points sit this fraction of the footprint's height in from its north and south ends,
# far enough inside the crop that an opaque reading is not a boundary coincidence.
SAMPLE_INSET_FRACTION = 0.02

# Steps that only reorder lon/lat and so say nothing about which datum shift ran.
AXIS_ORDER_STEP = "axis order change (2D)"

AREA_ID = "auburn"
EDITION_ORDER = ["auburn-1953", "auburn-1973", "auburn-1975", "auburn-1981"]
BASE_EDITION_ID = "auburn-1953"
TILE_ZOOM = {"min": 10, "max": 16}
SOURCE_ENTRY_ID = "usgs-historical-topo"

COORD_DECIMALS = 6
# Two adjacent 6-decimal coordinates differ by ~0.1 m; 1e-5 deg (~1 m) absorbs PROJ
# version drift without letting a hand-edited crop wander off the inspected neatline.
POSITION_TOLERANCE_DEG = 1.0e-5
BOUNDS_TOLERANCE_DEG = 2.0e-6

# Neatline verification: a window this far either side of the projected graticule, sampled
# in a band at each end of the edge because meridian convergence tilts the drawn line by
# several pixels over the sheet height. Bands start INSET_FRACTION in, away from the corner
# ticks and tie marks that darken the collar.
SEARCH_METRES = 60.0
INSET_FRACTION = 0.15
BAND_FRACTION = 0.15
# The drawn neatline ink is 2-3 px wide, so a deviation under this still lands on the line.
# The 1975 orthophotoquad is the worst of the four at 2.61 px; see docs/demo-source-review.md.
NEATLINE_TOLERANCE_PX = 3.0
MIN_CONTRAST = 15.0
GRATICULE_SAMPLES = 129
EDGE_SAMPLES = 8

# Where `_ring` puts each corner, so a caller can check the corners and not just the edges.
RING_CORNER_INDEX = {
    "sw": 0,
    "se": EDGE_SAMPLES + 1,
    "ne": 2 * (EDGE_SAMPLES + 1),
    "nw": 3 * (EDGE_SAMPLES + 1),
}

# Which end of each edge a verification band sits at, in the order the edge is densified.
EDGE_ENDS = {
    "west": ("north", "south"),
    "east": ("north", "south"),
    "north": ("west", "east"),
    "south": ("west", "east"),
}

# The allowlist. Dates are transcribed from the per-sheet topo_index.csv columns for each
# source ID; `check` re-derives them from the index and fails on any disagreement.
EXPECTED_EDITIONS = {
    "auburn-1953": {
        "source_id": "CA_Auburn_288101_1953_24000",
        "kind": "topo",
        "dates": {
            "map_year": 1953,
            "base_year": 1953,
            "revision_year": None,
            "base_photography": "1952",
            "revision_photography": None,
            "photography": None,
            "base_field_check_year": 1953,
            "revision_field_checked": None,
        },
    },
    "auburn-1973": {
        "source_id": "CA_Auburn_288103_1953_24000",
        "kind": "topo",
        "dates": {
            "map_year": 1953,
            "base_year": 1953,
            "revision_year": 1973,
            "base_photography": "1952",
            "revision_photography": "1973",
            "photography": None,
            "base_field_check_year": 1953,
            "revision_field_checked": False,
        },
    },
    "auburn-1975": {
        "source_id": "CA_Auburn_288104_1975_24000",
        "kind": "orthophotoquad",
        "dates": {
            "map_year": 1975,
            "base_year": None,
            "revision_year": None,
            "base_photography": None,
            "revision_photography": None,
            # Month and day are not in topo_index.csv; see docs/demo-source-review.md.
            "photography": "1975-08-29",
            "base_field_check_year": None,
            "revision_field_checked": None,
        },
    },
    "auburn-1981": {
        "source_id": "CA_Auburn_288105_1953_24000",
        "kind": "topo",
        "dates": {
            "map_year": 1953,
            "base_year": 1953,
            "revision_year": 1981,
            "base_photography": "1952",
            "revision_photography": "1978",
            "photography": None,
            "base_field_check_year": 1953,
            "revision_field_checked": False,
        },
    },
}

# --- the nine-edition contract (version 2, #57; active since #58) ---------------------------
# The four editions above are warped by run_cogs into build/rasters/; the five added ones by
# scripts/demo_expansion.py into build/expansion/. run_rasters drives both.
EXPANDED_MANIFEST_PATH = MANIFEST_PATH
EXPANSION_ROOT = BUILD_ROOT / "expansion"
PDF_RECORD_NAME = "demo-pdf-processing.json"
EXPANDED_EDITION_ORDER = list(demo_sources.EXPANSION_ORDER)
INITIAL_EDITION_ID = BASE_EDITION_ID
US_TOPO_ENTRY_ID = "usgs-us-topo"
ENTRY_BY_SOURCE_KIND = {
    "historical_geotiff": SOURCE_ENTRY_ID,
    "us_topo_pdf": US_TOPO_ENTRY_ID,
}
# Index columns a component date is read from, per manifest field.
COMPONENT_COLUMNS = {
    "survey_year": "survey_year",
    "edit_year": "edit_year",
    "imprint_year": "imprint_year",
}
# A source that maps less of the camera footprint than this is the wrong sheet.
MIN_VIEW_COVERAGE = 0.95
NO_COMPONENT_DATES = {"survey_year": None, "edit_year": None, "imprint_year": None}


def _single_edition_dates(map_year: int, base_year: int | None, base_photography=None) -> dict:
    """Dates of a sheet that is neither a photorevision nor an orthophotoquad."""
    return {
        "map_year": map_year,
        "base_year": base_year,
        "revision_year": None,
        "base_photography": base_photography,
        "revision_photography": None,
        "photography": None,
        "base_field_check_year": None,
        "revision_field_checked": None,
    }


def _historical(eid: str, **extra) -> dict:
    """A version-1 edition's contract plus the fields version 2 makes explicit."""
    return {
        **EXPECTED_EDITIONS[eid],
        "source_kind": "historical_geotiff",
        "sheet_name": "Auburn",
        "scale": 24000,
        "native_max_zoom": 16,
        "publication_date": None,
        **extra,
    }


# `lineage_column` names the index column that shows a sheet was mapped, not photographed:
# the regional sheets record a survey or an edit year where the 7.5-minute ones record a
# field check. Zoom limits are derived from the measured pixel size; `check` re-derives them.
EXPANDED_EXPECTED_EDITIONS = {
    "sacramento-1891": {
        "source_id": "CA_Sacramento_299588_1891_125000",
        "kind": "topo",
        "source_kind": "historical_geotiff",
        "sheet_name": "Sacramento",
        "scale": 125000,
        "native_max_zoom": 14,
        "lineage_column": "survey_year",
        "publication_date": None,
        "component_dates": {"survey_year": 1888, "edit_year": None, "imprint_year": None},
        "dates": _single_edition_dates(1891, 1891),
    },
    "auburn-1944": {
        "source_id": "CA_Auburn_296741_1944_62500",
        "kind": "topo",
        "source_kind": "historical_geotiff",
        "sheet_name": "Auburn",
        "scale": 62500,
        "native_max_zoom": 15,
        "lineage_column": "survey_year",
        "publication_date": None,
        "component_dates": {"survey_year": 1941, "edit_year": None, "imprint_year": None},
        "dates": _single_edition_dates(1944, 1944),
    },
    "auburn-1953": _historical(
        "auburn-1953",
        lineage_column="field_check_year",
        component_dates={"survey_year": None, "edit_year": None, "imprint_year": 1955},
    ),
    "auburn-1973": _historical(
        "auburn-1973",
        lineage_column="field_check_year",
        component_dates={"survey_year": None, "edit_year": None, "imprint_year": 1977},
    ),
    "auburn-1975": _historical(
        "auburn-1975",
        lineage_column=None,
        component_dates={"survey_year": None, "edit_year": None, "imprint_year": 1981},
    ),
    "auburn-1981": _historical(
        "auburn-1981",
        lineage_column="field_check_year",
        component_dates={"survey_year": None, "edit_year": 1981, "imprint_year": 1981},
    ),
    "sacramento-1994": {
        "source_id": "CA_Sacramento_299157_1994_100000",
        "kind": "topo",
        "source_kind": "historical_geotiff",
        "sheet_name": "Sacramento",
        "scale": 100000,
        "native_max_zoom": 14,
        "lineage_column": "edit_year",
        "publication_date": None,
        "component_dates": {"survey_year": None, "edit_year": 1994, "imprint_year": 1994},
        "dates": _single_edition_dates(1994, 1994, "1987"),
    },
    "auburn-2018": {
        "source_id": "5d3aeb27e4b01d82ce8d133b",
        "kind": "topo",
        "source_kind": "us_topo_pdf",
        "sheet_name": "Auburn",
        "scale": 24000,
        "native_max_zoom": 16,
        "publication_date": "2018-09-24",
        "component_dates": NO_COMPONENT_DATES,
        "dates": _single_edition_dates(2018, None),
    },
    "auburn-2021": {
        "source_id": "61d7a9e2d34ed79294005276",
        "kind": "topo",
        "source_kind": "us_topo_pdf",
        "sheet_name": "Auburn",
        "scale": 24000,
        "native_max_zoom": 16,
        "publication_date": "2021-12-30",
        "component_dates": NO_COMPONENT_DATES,
        "dates": _single_edition_dates(2021, None),
    },
}

CONTRACTS = {
    1: {"order": EDITION_ORDER, "expected": EXPECTED_EDITIONS},
    2: {"order": EXPANDED_EDITION_ORDER, "expected": EXPANDED_EXPECTED_EDITIONS},
}


def fail(message: str) -> None:
    raise click.ClickException(message)


def q6(value: float) -> float:
    return round(float(value), COORD_DECIMALS)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"Cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}")


def read_index(path: Path) -> dict[str, dict]:
    from fetch_topoview import read_index as _read_index

    rows = _read_index(path)
    if not rows:
        fail(f"No source index at {path}; the four selected sheets cannot be resolved.")
    return rows


def parse_photography(value: str | None, field: str) -> None:
    """Reject a date that matches the pattern but is not a real calendar date."""
    if value is None:
        return
    try:
        if len(value) == 4:
            year = int(value)
            if not 1800 <= year <= 2100:
                raise ValueError("year out of range")
        else:
            date.fromisoformat(value)
    except ValueError as exc:
        fail(f"{field} is not a real calendar date: {value!r} ({exc})")


def validator(schema_path: Path) -> Draft202012Validator:
    return Draft202012Validator(read_json(schema_path), format_checker=FormatChecker())


def check_schema(manifest: dict, schema_path: Path) -> None:
    errors = sorted(validator(schema_path).iter_errors(manifest), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.path) or "(root)"
        fail(f"Manifest fails schema at {where}: {first.message}")


def contract_for(manifest: dict) -> dict:
    contract = CONTRACTS.get(manifest.get("version"))
    if contract is None:
        fail(f"No edition contract for manifest version {manifest.get('version')!r}")
    return contract


def check_editions_present(manifest: dict) -> list[dict]:
    order = contract_for(manifest)["order"]
    editions = manifest["editions"]
    ids = [edition["id"] for edition in editions]
    if len(set(ids)) != len(ids):
        fail(f"Duplicate edition id in the manifest: {sorted(ids)}")
    if ids != manifest["edition_order"]:
        fail(f"editions are not in edition_order: {ids} != {manifest['edition_order']}")
    if ids != order:
        fail(f"Edition set or order differs from the fixed contract: {ids} != {order}")
    source_ids = [edition["source_id"] for edition in editions]
    if len(set(source_ids)) != len(source_ids):
        fail(f"Duplicate source_id in the manifest: {sorted(source_ids)}")
    return editions


def check_ring(edition: dict) -> Polygon:
    ring = edition["crop_wgs84"]["coordinates"][0]
    if ring[0] != ring[-1]:
        fail(f"{edition['id']}: crop_wgs84 ring is not closed")
    for lon, lat in ring:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            fail(f"{edition['id']}: crop_wgs84 vertex out of range: {lon}, {lat}")
        if (q6(lon), q6(lat)) != (lon, lat):
            fail(
                f"{edition['id']}: crop_wgs84 carries more than {COORD_DECIMALS} "
                f"decimal places: {lon}, {lat}"
            )
    polygon = shape(edition["crop_wgs84"])
    if not polygon.is_valid:
        fail(f"{edition['id']}: crop_wgs84 is not a valid polygon")
    if polygon.area <= 0:
        fail(f"{edition['id']}: crop_wgs84 has no area")
    return polygon


def check_bounds_shape(manifest: dict) -> None:
    west, south, east, north = manifest["view_bounds_wgs84"]
    if west >= east:
        fail(f"view_bounds_wgs84 is inverted in longitude: west {west} >= east {east}")
    if south >= north:
        fail(f"view_bounds_wgs84 is inverted in latitude: south {south} >= north {north}")
    for value in manifest["view_bounds_wgs84"]:
        if q6(value) != value:
            fail(
                f"view_bounds_wgs84 carries more than {COORD_DECIMALS} decimal places: {value}"
            )


def check_dates(edition: dict, row: dict, base_row: dict, contract: dict | None = None) -> None:
    eid = edition["id"]
    dates = edition["dates"]
    for field in ("base_photography", "revision_photography", "photography"):
        parse_photography(dates[field], f"{eid}.dates.{field}")

    expected = (contract or EXPECTED_EDITIONS[eid])["dates"]
    if dates != expected:
        differing = sorted(k for k in expected if dates.get(k) != expected[k])
        fail(f"{eid}: dates differ from the fixed contract for {', '.join(differing)}")

    # Cross-check against the per-sheet index columns rather than the printed title.
    if dates["map_year"] != int(row["date_on_map"]):
        fail(f"{eid}: map_year {dates['map_year']} != index date_on_map {row['date_on_map']}")
    revision = row["photo_revision_year"] or None
    if (str(dates["revision_year"]) if dates["revision_year"] else None) != revision:
        fail(f"{eid}: revision_year disagrees with index photo_revision_year {revision!r}")
    if dates["revision_year"] is None:
        if dates["revision_field_checked"] is not None:
            fail(f"{eid}: revision_field_checked must be null without a revision year")
        if dates["photography"] is None and dates["base_photography"] != (
            row["aerial_photo_year"] or None
        ):
            fail(
                f"{eid}: base_photography disagrees with index aerial_photo_year "
                f"{row['aerial_photo_year']!r}"
            )
    else:
        if dates["revision_field_checked"] is not False:
            fail(f"{eid}: a photorevision was not field checked; expected false")
        if dates["revision_photography"] != (row["aerial_photo_year"] or None):
            fail(
                f"{eid}: revision_photography disagrees with index aerial_photo_year "
                f"{row['aerial_photo_year']!r}"
            )
        if dates["base_photography"] != (base_row["aerial_photo_year"] or None):
            fail(
                f"{eid}: base_photography disagrees with the 1953 base sheet's "
                f"aerial_photo_year {base_row['aerial_photo_year']!r}"
            )
        if "not field checked" not in edition["date_note"]:
            fail(f"{eid}: date_note must state that the revision was not field checked")
    field_check = row["field_check_year"] or None
    if (str(dates["base_field_check_year"]) if dates["base_field_check_year"] else None) != (
        field_check
    ):
        fail(f"{eid}: base_field_check_year disagrees with index field_check_year")
    if dates["photography"] is not None and not dates["photography"].startswith(
        row["aerial_photo_year"]
    ):
        fail(
            f"{eid}: photography {dates['photography']!r} is not in index "
            f"aerial_photo_year {row['aerial_photo_year']!r}"
        )


def check_kind(edition: dict, row: dict, contract: dict | None = None) -> None:
    eid = edition["id"]
    expected = contract or EXPECTED_EDITIONS[eid]
    if edition["source_id"] != expected["source_id"]:
        fail(f"{eid}: source_id {edition['source_id']} is not the allowlisted scan variant")
    if edition["kind"] != expected["kind"]:
        fail(f"{eid}: kind {edition['kind']!r} differs from the contract {expected['kind']!r}")
    # Field-checked lineage is what separates the topo sheets from the orthophotoquad; the
    # regional sheets record a survey or edit year instead.
    lineage = expected.get("lineage_column") or "field_check_year"
    if edition["kind"] == "topo" and not row[lineage]:
        what = "field check" if lineage == "field_check_year" else lineage
        fail(f"{eid}: index records no {what}, so it is not a topo sheet")
    checked = bool(row["field_check_year"])
    if edition["kind"] == "orthophotoquad":
        if checked:
            fail(f"{eid}: index records a field check, so it is not an orthophotoquad")
        if not row["aerial_photo_year"]:
            fail(f"{eid}: index records no aerial photography year for an orthophotoquad")


def check_rights(
    edition: dict, row: dict, entry: dict, entry_id: str = SOURCE_ENTRY_ID
) -> None:
    eid = edition["id"]
    if row["rights"] != "public_domain":
        fail(f"{eid}: index rights {row['rights']!r} is not public_domain")
    if edition["rights"] != entry["rights"]:
        fail(f"{eid}: rights {edition['rights']!r} != sources.yml {entry['rights']!r}")
    if edition["attribution"] != entry["attribution"]:
        fail(f"{eid}: attribution does not match sources.yml for {entry_id}")
    if edition["source_url"] != row["sciencebase_url"]:
        fail(f"{eid}: source_url does not match the index sciencebase_url")
    if edition["source_id"] not in edition["citation"]:
        fail(f"{eid}: citation does not name the source ID")


def source_entry(path: Path, entry_id: str = SOURCE_ENTRY_ID) -> dict:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"Cannot read {path}: {exc}")
    for entry in document.get("sources", []):
        if entry.get("id") == entry_id:
            return entry
    fail(f"{path} has no {entry_id} entry to take rights and attribution from")


def check_contract_fields(edition: dict, expected: dict) -> None:
    """The version-2 fields that the allowlist fixes outright."""
    eid = edition["id"]
    for field in (
        "source_kind",
        "sheet_name",
        "scale",
        "native_max_zoom",
        "publication_date",
        "component_dates",
    ):
        if edition[field] != expected[field]:
            fail(
                f"{eid}: {field} {edition[field]!r} differs from the contract "
                f"{expected[field]!r}"
            )
    scale = f"1:{edition['scale']:,}"
    if edition["sheet_name"] not in edition["citation"] or scale not in edition["citation"]:
        fail(f"{eid}: citation must name the {edition['sheet_name']} sheet and {scale}")
    # A regional or 15-minute sheet must never read as a detailed Auburn 7.5-minute map.
    if (edition["sheet_name"], edition["scale"]) != ("Auburn", 24000) and (
        edition["sheet_name"] not in edition["label"] or scale not in edition["label"]
    ):
        fail(f"{eid}: label must show the {edition['sheet_name']} sheet name and {scale}")


def check_historical_fields(edition: dict, row: dict) -> None:
    """Version-2 fields of a topoView scan, against its own index row."""
    eid = edition["id"]
    if edition["scale"] != int(row["scale"]):
        fail(f"{eid}: scale {edition['scale']} != index scale {row['scale']}")
    if edition["sheet_name"] != row["map_name"]:
        fail(f"{eid}: sheet_name {edition['sheet_name']!r} != index map_name")
    for field, column in COMPONENT_COLUMNS.items():
        indexed = int(row[column]) if row[column] else None
        if edition["component_dates"][field] != indexed:
            fail(f"{eid}: component_dates.{field} disagrees with index {column} {indexed!r}")
    if edition["printed_credit_note"] is not None:
        fail(f"{eid}: no printed credit note has been transcribed from this scan; use null")


def check_pdf_fields(edition: dict, expected: dict, catalog: dict, entry: dict) -> None:
    """A US Topo edition against demo-pdf-sources.json and sources.yml usgs-us-topo."""
    eid = edition["id"]
    item = catalog.get(edition["source_id"])
    if item is None or item["edition_id"] != eid:
        fail(f"{eid}: {edition['source_id']} is not catalogued for this edition")
    if edition["source_id"] != expected["source_id"]:
        fail(f"{eid}: source_id {edition['source_id']} is not the allowlisted product")
    if edition["kind"] != expected["kind"]:
        fail(f"{eid}: kind {edition['kind']!r} differs from the contract {expected['kind']!r}")
    if item["rights"]["status"] != "public_domain":
        fail(f"{eid}: catalog rights {item['rights']['status']!r} is not public_domain")
    if edition["rights"] != entry["rights"]:
        fail(f"{eid}: rights {edition['rights']!r} != sources.yml {entry['rights']!r}")
    if edition["attribution"] != entry["attribution"]:
        fail(f"{eid}: attribution does not match sources.yml for {US_TOPO_ENTRY_ID}")
    if edition["source_url"] != item["sciencebase_url"]:
        fail(f"{eid}: source_url does not match the catalog sciencebase_url")
    if edition["source_id"] not in edition["citation"]:
        fail(f"{eid}: citation does not name the source ID")
    if edition["publication_date"] != item["publication_date"]:
        fail(f"{eid}: publication_date disagrees with the catalog {item['publication_date']}")
    if edition["scale"] != item["scale"] or edition["sheet_name"] not in item["title"]:
        fail(f"{eid}: sheet or scale disagrees with the catalog title and scale")
    if edition["printed_credit_note"] != item["rights"]["credit_note"]:
        fail(f"{eid}: printed_credit_note is not the catalog credit note verbatim")
    if edition["dates"] != expected["dates"]:
        differing = sorted(
            k for k in expected["dates"] if edition["dates"][k] != expected["dates"][k]
        )
        fail(f"{eid}: dates differ from the fixed contract for {', '.join(differing)}")
    if edition["dates"]["map_year"] != int(item["publication_date"][:4]):
        fail(f"{eid}: map_year is not the catalog publication year")


def check_metadata(
    manifest: dict,
    schema_path: Path,
    index_path: Path,
    sources_path: Path,
    catalog_path: Path | None = None,
) -> dict[str, Polygon]:
    """Everything verifiable without opening a raster."""
    check_schema(manifest, schema_path)
    if manifest["area_id"] != AREA_ID or manifest["tile_zoom"] != TILE_ZOOM:
        fail("area_id or tile_zoom differs from the fixed contract")
    expected = contract_for(manifest)["expected"]
    editions = check_editions_present(manifest)
    check_bounds_shape(manifest)
    if manifest["version"] == 2 and manifest["initial_edition"] != INITIAL_EDITION_ID:
        fail(f"initial_edition must stay {INITIAL_EDITION_ID}")
    rows = read_index(index_path)
    entries = {
        kind: source_entry(sources_path, entry_id)
        for kind, entry_id in ENTRY_BY_SOURCE_KIND.items()
        if kind == "historical_geotiff" or manifest["version"] == 2
    }
    catalog = {}
    if manifest["version"] == 2:
        catalog = demo_sources.load_catalog(catalog_path or demo_sources.CATALOG_PATH)
    scans = [
        e
        for e in editions
        if e.get("source_kind", "historical_geotiff") == "historical_geotiff"
    ]
    missing = [e["source_id"] for e in scans if e["source_id"] not in rows]
    if missing:
        fail(f"Selected source(s) absent from {index_path}: {', '.join(missing)}")
    base_row = rows[EXPECTED_EDITIONS[BASE_EDITION_ID]["source_id"]]
    crops = {}
    for edition in editions:
        contract = expected[edition["id"]]
        if manifest["version"] == 2:
            check_contract_fields(edition, contract)
        if edition.get("source_kind") == "us_topo_pdf":
            check_pdf_fields(edition, contract, catalog, entries["us_topo_pdf"])
        else:
            row = rows[edition["source_id"]]
            check_kind(edition, row, contract)
            check_rights(edition, row, entries["historical_geotiff"])
            check_dates(edition, row, base_row, contract)
            if manifest["version"] == 2:
                check_historical_fields(edition, row)
        crops[edition["id"]] = check_ring(edition)
    return crops


def resolve_selected(
    selection: dict[str, str], receipts_path: Path, raw_root: Path
) -> dict[str, dict]:
    """One receipt per selected source ID, with its bytes verified in place.

    Receipts are unique per (topo_id, raw_path), so a source ID stored under both the
    legacy and the content-addressed name is ambiguous, not a duplicate to pick from.
    """
    if not receipts_path.exists():
        fail(f"No retrieval ledger at {receipts_path}; run make catalog-sources first.")
    records = load_receipts(receipts_path)
    resolved = {}
    for edition_id, source_id in selection.items():
        matches = [record for record in records if record["topo_id"] == source_id]
        if not matches:
            fail(f"{edition_id}: no retrieval receipt for {source_id}")
        if len(matches) > 1:
            paths = ", ".join(sorted(record["raw_path"] for record in matches))
            fail(f"{edition_id}: ambiguous receipts for {source_id}: {paths}")
        record = matches[0]
        if record["rights"] != "public_domain":
            fail(f"{edition_id}: receipt rights {record['rights']!r} is not public_domain")
        path = raw_root.resolve() / record["raw_path"]
        if not path.exists():
            fail(
                f"{edition_id}: selected source bytes are missing at {path}. "
                "Fetch them with make fetch-topo-selected; nothing was written."
            )
        resolved[edition_id] = {"record": record, "path": check_record(record, raw_root)}
    return resolved


def datum_transformer(geodetic: CRS, seed: tuple[float, float, float, float]) -> tuple:
    """Pick a named, non-ballpark transformation to WGS84 and report which one ran."""
    target = CRS.from_epsg(4326)
    if geodetic.equals(target):
        return Transformer.from_crs(geodetic, target, always_xy=True), {
            "description": "none (source is already WGS84)",
            "accuracy_metres": 0.0,
            "unavailable_better": [],
        }
    aoi = AreaOfInterest(*seed)
    group = TransformerGroup(
        geodetic, target, always_xy=True, allow_ballpark=False, area_of_interest=aoi
    )
    if not group.transformers:
        fail(
            f"No non-ballpark transformation from {geodetic.name} to WGS84 is available; "
            "install the PROJ grids before trusting these coordinates."
        )
    chosen = group.transformers[0]
    if chosen.accuracy is None or chosen.accuracy < 0:
        fail(f"Transformation {chosen.description!r} reports no accuracy; refusing to use it.")
    if "ballpark" in chosen.description.lower():
        fail(f"Only a ballpark transformation is available: {chosen.description}")
    return chosen, {
        "description": chosen.description,
        "accuracy_metres": chosen.accuracy,
        "unavailable_better": [op.name for op in group.unavailable_operations],
    }


def _edge_profile(dataset, window: Window, axis: int) -> np.ndarray:
    block = dataset.read(window=window).astype("float32").mean(axis=0)
    return block.mean(axis=axis)


def _locate(
    dataset, window: Window, axis: int, start: int, label: str, end: str, path: Path
) -> dict:
    profile = _edge_profile(dataset, window, axis)
    index = int(profile.argmin())
    darkest = float(profile[index])
    median = float(np.median(profile))
    if median - darkest < MIN_CONTRAST:
        fail(
            f"{path.name}: no {label} neatline found at the {end} end; darkest line "
            f"{darkest:.1f} against collar median {median:.1f}. The crop cannot be verified."
        )
    return {
        "pixel": start + index,
        "darkest_mean_value": round(darkest, 1),
        "profile_median_value": round(median, 1),
    }


def _graticule_edges(dataset, forward: Transformer, seed: tuple) -> dict[str, dict]:
    """The four labelled graticule edges in pixel space, densified along each edge.

    `along` runs north to south on a meridian and west to east on a parallel, so a band
    anywhere on the edge can be interpolated instead of assumed straight.
    """
    west, south, east, north = seed
    lats = np.linspace(north, south, GRATICULE_SAMPLES)
    lons = np.linspace(west, east, GRATICULE_SAMPLES)
    edges = {}
    for label, lon in (("west", west), ("east", east)):
        xs, ys = forward.transform(np.full_like(lats, lon), lats)
        rows, cols = rowcol(dataset.transform, xs, ys, op=float)
        edges[label] = {"axis": 0, "along": np.asarray(rows), "across": np.asarray(cols)}
    for label, lat in (("north", north), ("south", south)):
        xs, ys = forward.transform(lons, np.full_like(lons, lat))
        rows, cols = rowcol(dataset.transform, xs, ys, op=float)
        edges[label] = {"axis": 1, "along": np.asarray(cols), "across": np.asarray(rows)}
    return edges


def _verify_edges(
    dataset, edges: dict[str, dict], search: int, path: Path, enforced: set[str] | None
) -> dict:
    """Check the drawn neatline against the projected graticule at both ends of each edge.

    An axis-aligned crop passes a mid-edge check and still cuts metres of map content at
    the south corners, because the meridians converge (PR #47). With `enforced` set, the
    limit applies only to those edges and the others are measured and marked (#57).
    """
    locators = {}
    for label, edge in edges.items():
        along, across = edge["along"], edge["across"]
        start, length = along[0], along[-1] - along[0]
        found = {}
        for end, offset in zip(
            EDGE_ENDS[label],
            (INSET_FRACTION, 1.0 - INSET_FRACTION - BAND_FRACTION),
            strict=True,
        ):
            band_start = round(start + offset * length)
            band_span = round(BAND_FRACTION * length)
            middle = band_start + band_span / 2
            graticule = float(np.interp(middle, along, across))
            centre = round(graticule)
            if edge["axis"] == 0:
                window = Window(centre - search, band_start, 2 * search + 1, band_span)
            else:
                window = Window(band_start, centre - search, band_span, 2 * search + 1)
            measured = _locate(dataset, window, edge["axis"], centre - search, label, end, path)
            residual = measured["pixel"] - graticule
            if abs(residual) > NEATLINE_TOLERANCE_PX and (
                enforced is None or label in enforced
            ):
                fail(
                    f"{path.name}: the drawn {label} neatline is {residual:+.2f} px from the "
                    f"labelled graticule at the {end} end, over the {NEATLINE_TOLERANCE_PX} px "
                    "limit. The crop cannot be verified."
                )
            measured["graticule_px"] = round(graticule, 2)
            measured["residual_px"] = round(residual, 2)
            found[f"{end}_end"] = measured
        found["max_abs_residual_px"] = max(
            abs(value["residual_px"]) for value in found.values()
        )
        if enforced is not None:
            found["enforced"] = label in enforced
        locators[label] = found
    return locators


def inspect_source(path: Path, row: dict, enforced: set[str] | None = None) -> dict:
    """Derive the crop from the labelled graticule and verify the drawn neatline against it.

    The crop is the graticule quadrilateral, not a rectangle in the source projection: the
    east and west neatlines are meridians and they converge. The scan is read to verify
    that the drawn line really sits on that quadrilateral at both ends of every edge, or
    of the `enforced` edges only, for a regional sheet whose far edges bound no crop.
    """
    with rasterio.open(path) as dataset:
        if dataset.crs is None:
            fail(f"{path.name}: no CRS in the GeoTIFF; georeferencing cannot be verified.")
        crs = CRS.from_user_input(dataset.crs)
        geodetic = crs.geodetic_crs
        if geodetic is None:
            fail(f"{path.name}: source CRS has no datum; refusing to guess one.")
        seed = (
            float(row["west"]),
            float(row["south"]),
            float(row["east"]),
            float(row["north"]),
        )
        forward = Transformer.from_crs(geodetic, crs, always_xy=True)
        edges = _graticule_edges(dataset, forward, seed)
        pixel_size = abs(dataset.transform.a)
        search = max(8, round(SEARCH_METRES / pixel_size))
        all_rows = np.concatenate(
            [edge["along" if edge["axis"] == 0 else "across"] for edge in edges.values()]
        )
        all_cols = np.concatenate(
            [edge["across" if edge["axis"] == 0 else "along"] for edge in edges.values()]
        )
        if (
            all_rows.min() - search < 0
            or all_rows.max() + search >= dataset.height
            or all_cols.min() - search < 0
            or all_cols.max() + search >= dataset.width
        ):
            fail(
                f"{path.name}: the graticule quadrilateral or its neatline search window "
                "falls outside the scan."
            )

        locators = _verify_edges(dataset, edges, search, path, enforced)

        inverse = Transformer.from_crs(crs, geodetic, always_xy=True)
        shift, datum_note = datum_transformer(geodetic, seed)

        def geodetic_to_wgs84(points: list[tuple[float, float]]) -> list[list[float]]:
            lons, lats = shift.transform(*zip(*points, strict=True))
            return [[q6(lon), q6(lat)] for lon, lat in zip(lons, lats, strict=True)]

        def to_wgs84(projected: list[tuple[float, float]]) -> list[list[float]]:
            lons, lats = inverse.transform(*zip(*projected, strict=True))
            return geodetic_to_wgs84(list(zip(lons, lats, strict=True)))

        return {
            "path": path.name,
            "crs_wkt": crs.to_wkt(),
            "projection": crs.coordinate_operation.method_name
            if crs.coordinate_operation
            else None,
            "datum": geodetic.name,
            "size_px": [dataset.width, dataset.height],
            "pixel_size_metres": round(pixel_size, 4),
            "graticule_labels_source_datum": list(seed),
            "neatline_locators_px": locators,
            "max_abs_neatline_residual_px": max(
                edge["max_abs_residual_px"]
                for label, edge in locators.items()
                if enforced is None or label in enforced
            ),
            **(
                {}
                if enforced is None
                else {
                    "enforced_edges": sorted(enforced),
                    "max_abs_neatline_residual_px_all_edges": max(
                        edge["max_abs_residual_px"] for edge in locators.values()
                    ),
                }
            ),
            "inspection_method": (
                f"automated: crop = the labelled graticule quadrilateral, {EDGE_SAMPLES + 1} "
                "points per edge, through the named datum operation; verified against the "
                f"darkest column/row within {SEARCH_METRES:g} m of that quadrilateral in a "
                f"{BAND_FRACTION * 100:g}% band at each end of each edge, starting "
                f"{INSET_FRACTION * 100:g}% in, to a limit of {NEATLINE_TOLERANCE_PX} px"
            ),
            "datum_transformation": datum_note,
            "crop_wgs84": {
                "type": "Polygon",
                "coordinates": [geodetic_to_wgs84(_ring(*seed))],
            },
            "source_footprint_wgs84": {
                "type": "Polygon",
                "coordinates": [
                    to_wgs84(
                        _ring(
                            dataset.bounds.left,
                            dataset.bounds.bottom,
                            dataset.bounds.right,
                            dataset.bounds.top,
                        )
                    )
                ],
            },
        }


def _ring(west: float, south: float, east: float, north: float) -> list[tuple[float, float]]:
    """Counterclockwise quadrilateral, densified so edge curvature is not lost.

    Used on lon/lat graticule bounds and on projected bounds alike; a straight edge in one
    frame is a curve in the other, and the crop has to carry the curve.
    """

    def span(a: float, b: float) -> list[float]:
        step = (b - a) / (EDGE_SAMPLES + 1)
        return [a + step * i for i in range(EDGE_SAMPLES + 1)]

    points = [(x, south) for x in span(west, east)]
    points += [(east, y) for y in span(south, north)]
    points += [(x, north) for x in span(east, west)]
    points += [(west, y) for y in span(north, south)]
    points.append((west, south))
    return points


def check_georeferencing(
    manifest: dict, index_path: Path, resolved: dict[str, dict], crops: dict[str, Polygon]
) -> dict[str, dict]:
    rows = read_index(index_path)
    reports = {}
    for edition in manifest["editions"]:
        eid = edition["id"]
        report = inspect_source(resolved[eid]["path"], rows[edition["source_id"]])
        footprint = shape(report["source_footprint_wgs84"])
        if not crops[eid].within(footprint):
            fail(f"{eid}: crop_wgs84 falls outside the georeferenced source footprint")
        expected = report["crop_wgs84"]["coordinates"][0]
        actual = edition["crop_wgs84"]["coordinates"][0]
        if len(expected) != len(actual):
            fail(
                f"{eid}: crop_wgs84 has {len(actual)} vertices; the inspected neatline "
                f"has {len(expected)}"
            )
        worst = max(
            max(abs(a[0] - b[0]), abs(a[1] - b[1]))
            for a, b in zip(expected, actual, strict=True)
        )
        if worst > POSITION_TOLERANCE_DEG:
            fail(
                f"{eid}: crop_wgs84 is {worst:.6f} deg off the inspected neatline; "
                "re-derive it with make demo-inspect"
            )
        reports[eid] = report

    common = crops[EDITION_ORDER[0]]
    for eid in EDITION_ORDER[1:]:
        common = common.intersection(crops[eid])
    if common.is_empty:
        fail("The four crops do not overlap; there is no common mapped footprint")
    expected_bounds = [q6(value) for value in common.bounds]
    declared = manifest["view_bounds_wgs84"]
    if any(
        abs(a - b) > BOUNDS_TOLERANCE_DEG
        for a, b in zip(expected_bounds, declared, strict=True)
    ):
        fail(
            f"view_bounds_wgs84 {declared} is not the common mapped footprint {expected_bounds}"
        )
    return reports


# topo_index.csv projection names and the PROJ method each should embed.
INDEX_PROJECTION_METHODS = {
    "Polyconic": "American Polyconic",
    "Lambert Conformal Conic": "Lambert Conic Conformal (2SP)",
    "Universal Transverse Mercator": "Transverse Mercator",
}
UTM_SCALE_FACTOR = 0.9996
UTM_FALSE_EASTING = 500000.0


def seed_of(row: dict) -> tuple[float, float, float, float]:
    return (float(row["west"]), float(row["south"]), float(row["east"]), float(row["north"]))


def bounding_edges(sheet: tuple, view: tuple) -> set[str]:
    """The sheet's graticule edges that are also edges of the view's graticule.

    Only these bound a crop clipped to the view, so only these must pass the neatline limit.
    """
    west, south, east, north = sheet
    v_west, v_south, v_east, v_north = view
    lon_span = west <= v_west and v_east <= east
    lat_span = south <= v_south and v_north <= north
    edges = set()
    if west == v_west and lat_span:
        edges.add("west")
    if east == v_east and lat_span:
        edges.add("east")
    if south == v_south and lon_span:
        edges.add("south")
    if north == v_north and lon_span:
        edges.add("north")
    return edges


def compare_index_crs(row: dict, crs_wkt: str) -> dict:
    """The index's datum/projection columns against the CRS the scan embeds.

    Positioning always uses the embedded CRS; a disagreement is recorded, not resolved.
    """
    crs = CRS.from_wkt(crs_wkt)
    operation = crs.coordinate_operation
    parameters = {param.name: param.value for param in operation.params} if operation else {}
    method = operation.method_name if operation else None
    datum = crs.geodetic_crs.name if crs.geodetic_crs else None
    datum_agrees = row["datum"] == "NAD27" and datum == "NAD27"
    projection_agrees = INDEX_PROJECTION_METHODS.get(row["projection"]) == method
    if projection_agrees and row["projection"] == "Universal Transverse Mercator":
        origin = parameters.get("Longitude of natural origin")
        projection_agrees = (
            parameters.get("Scale factor at natural origin") == UTM_SCALE_FACTOR
            and parameters.get("False easting") == UTM_FALSE_EASTING
            and origin is not None
            and (origin + 183) % 6 == 0
        )
    return {
        "index_datum": row["datum"],
        "index_projection": row["projection"],
        "embedded_datum": datum,
        "embedded_projection": method,
        "embedded_parameters": {name: round(value, 6) for name, value in parameters.items()},
        "agrees": datum_agrees and projection_agrees,
    }


def native_max_zoom(pixel_metres: float, latitude: float) -> int:
    """The coarsest XYZ zoom whose ground pixel at `latitude` is no larger than a source pixel.

    Tiling finer than this adds no source detail; a camera beyond it overzooms this level.
    For the 2.03 m Auburn scans it gives 16, the live pyramid's top zoom.
    """
    ground = (
        2 * warp_raster._mercator_origin() * math.cos(math.radians(latitude))
    ) / warp_raster.TILE_SIZE
    return math.ceil(math.log2(ground / pixel_metres))


def clip_to_view(face: Polygon, view: Polygon) -> dict:
    """The part of a source's verified map face inside the camera footprint, as GeoJSON.

    Where the face covers the whole view to within the crop tolerance, the crop is the view
    itself, so a regional sheet shows exactly the area the Auburn editions show.
    """
    if view.within(face.buffer(POSITION_TOLERANCE_DEG)):
        clipped = view
    else:
        clipped = view.intersection(face)
    clipped = shapely.set_precision(clipped, 10.0**-COORD_DECIMALS)
    if clipped.is_empty or clipped.geom_type != "Polygon":
        fail("The source face does not overlap the view footprint in one polygon.")
    ring = [[q6(x), q6(y)] for x, y in orient(clipped, sign=1.0).exterior.coords]
    return {"type": "Polygon", "coordinates": [ring]}


def resolve_pdf_sources(
    selection: dict[str, str],
    ledger_path: Path,
    raw_root: Path,
    expansion_root: Path,
) -> dict[str, dict]:
    """Each US Topo edition's COG, traced to its receipted PDF through the E2 record (#56).

    The PDF is re-hashed in place; the COG must be the one the record says that PDF made.
    """
    record_path = expansion_root / PDF_RECORD_NAME
    if not record_path.is_file():
        fail(f"No {PDF_RECORD_NAME} at {record_path}; run make expansion-pdf first.")
    record = read_json(record_path)
    rendered = {entry["edition_id"]: entry for entry in record.get("sources", [])}
    receipts = demo_sources.load_ledger(ledger_path)
    resolved = {}
    for edition_id, source_id in selection.items():
        receipt = receipts.get(source_id)
        if receipt is None:
            fail(f"{edition_id}: no PDF receipt for {source_id}; run make expansion-fetch")
        try:
            pdf_path = demo_sources.verify_receipted(receipt, raw_root)
        except FileNotFoundError:
            fail(f"{edition_id}: receipted PDF bytes are missing at {receipt['path']}")
        except click.ClickException as exc:
            fail(f"{edition_id}: {exc.format_message()}")
        source = rendered.get(edition_id)
        if source is None:
            fail(f"{edition_id}: {PDF_RECORD_NAME} has no render; run make expansion-pdf")
        if source["source_id"] != source_id or (
            source["source"]["sha256"],
            source["source"]["size_bytes"],
        ) != (receipt["sha256"], receipt["size_bytes"]):
            fail(f"{edition_id}: the recorded render is not of the receipted PDF bytes")
        if source.get("neatline") is None:
            fail(f"{edition_id}: the recorded render has no measured neatline to crop to")
        cog = expansion_root / "pdf" / f"{edition_id}.tif"
        if not cog.is_file():
            fail(f"{edition_id}: rendered COG missing at {cog}; run make expansion-pdf")
        if warp_raster.sha256_file(cog) != (
            source["raster"]["sha256"],
            source["raster"]["byte_count"],
        ):
            fail(f"{edition_id}: {cog.name} differs from {PDF_RECORD_NAME}; rerun it")
        resolved[edition_id] = {
            "path": cog,
            "pdf_path": pdf_path,
            "pdf_receipt": receipt,
            "pdf_source": source,
        }
    return resolved


def _projected_ring(corners: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A closed ring through `corners`, densified along straight edges between them."""
    points = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1], strict=True):
        for step in range(EDGE_SAMPLES + 1):
            t = step / (EDGE_SAMPLES + 1)
            points.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
    points.append(points[0])
    return points


def inspect_pdf_cog(path: Path, source: dict) -> dict:
    """The rendered US Topo page's map face and extent in WGS84, from its drawn neatline.

    make expansion-pdf measured the neatline corners from the PDF's vector content. The page
    is affine in its UTM CRS, so the face's edges are straight in that CRS.
    """
    with rasterio.open(path) as dataset:
        crs = CRS.from_user_input(dataset.crs)
        if crs.to_epsg() != source["georeferencing"]["epsg"]:
            fail(
                f"{path.name}: CRS is not the recorded EPSG:{source['georeferencing']['epsg']}"
            )
        transform = dataset.transform
        width, height = dataset.width, dataset.height
    c, a, b, f, d, e = source["georeferencing"]["geotransform"]
    if not np.allclose(transform[:6], (a, b, c, d, e, f), rtol=0, atol=1e-6):
        fail(f"{path.name}: geotransform differs from the recorded PDF georeferencing")
    geodetic = crs.geodetic_crs
    box = source["nominal_box"]
    seed = (box["west"], box["south"], box["east"], box["north"])
    shift, datum_note = datum_transformer(geodetic, seed)
    inverse = Transformer.from_crs(crs, geodetic, always_xy=True)

    def to_wgs84(pixels: list[tuple[float, float]]) -> list[list[float]]:
        projected = [transform * point for point in pixels]
        lons, lats = inverse.transform(*zip(*projected, strict=True))
        lons, lats = shift.transform(lons, lats)
        return [[float(lon), float(lat)] for lon, lat in zip(lons, lats, strict=True)]

    corners = source["neatline"]["corners"]
    # Counterclockwise on the ground, the order `_ring` gives the scan crops.
    face = [
        tuple(corners[name]["pixel"])
        for name in ("lower_left", "lower_right", "upper_right", "upper_left")
    ]
    extent = [(0.0, float(height)), (float(width), float(height)), (float(width), 0.0), (0, 0)]
    return {
        "path": path.name,
        "crs_wkt": crs.to_wkt(),
        "projection": crs.coordinate_operation.method_name,
        "datum": geodetic.name,
        "size_px": [width, height],
        "pixel_size_metres": round(math.hypot(transform.a, transform.d), 4),
        "graticule_labels_source_datum": list(seed),
        "datum_transformation": datum_note,
        "inspection_method": (
            "automated: face = the drawn Map Frame neatline that make expansion-pdf measured, "
            f"{EDGE_SAMPLES + 1} points per straight edge in the page's UTM CRS, through the "
            "named datum operation"
        ),
        "neatline_offset_from_nominal_m": source["nominal_offset"]["max_distance_m"],
        "gpts_max_residual_m": source["georeferencing"]["max_residual_m"],
        "face_wgs84": {"type": "Polygon", "coordinates": [to_wgs84(_projected_ring(face))]},
        "source_footprint_wgs84": {
            "type": "Polygon",
            "coordinates": [to_wgs84(_projected_ring(extent))],
        },
    }


def check_expanded_georeferencing(
    manifest: dict,
    index_path: Path,
    resolved: dict[str, dict],
    crops: dict[str, Polygon],
) -> dict[str, dict]:
    """Version 2: the four view editions as in version 1, then each added source's face."""
    rows = read_index(index_path)
    view_manifest = {
        "editions": [e for e in manifest["editions"] if e["id"] in EDITION_ORDER],
        "view_bounds_wgs84": manifest["view_bounds_wgs84"],
    }
    reports = check_georeferencing(view_manifest, index_path, resolved, crops)
    view = common_footprint(view_manifest)
    view_seed = seed_of(rows[EXPECTED_EDITIONS[BASE_EDITION_ID]["source_id"]])
    _, south, _, north = manifest["view_bounds_wgs84"]
    latitude = (south + north) / 2
    zoom = manifest["tile_zoom"]
    for edition in manifest["editions"]:
        eid = edition["id"]
        if eid in reports:
            report = reports[eid]
            report["index_crs"] = compare_index_crs(
                rows[edition["source_id"]], report["crs_wkt"]
            )
        elif edition["source_kind"] == "historical_geotiff":
            row = rows[edition["source_id"]]
            enforced = bounding_edges(seed_of(row), view_seed)
            if not enforced:
                fail(f"{eid}: no neatline of the sheet bounds the view; the crop is unverified")
            report = inspect_source(resolved[eid]["path"], row, enforced)
            report["face_wgs84"] = report["crop_wgs84"]
            report["index_crs"] = compare_index_crs(row, report["crs_wkt"])
        else:
            report = inspect_pdf_cog(resolved[eid]["path"], resolved[eid]["pdf_source"])
        if eid not in EDITION_ORDER:
            face = shape(report["face_wgs84"])
            expected = shape(clip_to_view(face, view))
            drift = expected.hausdorff_distance(crops[eid])
            if drift > POSITION_TOLERANCE_DEG:
                fail(
                    f"{eid}: crop_wgs84 is {drift:.6f} deg off the source face clipped to the "
                    "view; re-derive it with demo.py inspect-expanded"
                )
            if not crops[eid].within(view.buffer(POSITION_TOLERANCE_DEG)):
                fail(f"{eid}: crop_wgs84 extends past the view footprint")
            report["crop_wgs84"] = edition["crop_wgs84"]
        if not crops[eid].within(shape(report["source_footprint_wgs84"])):
            fail(f"{eid}: crop_wgs84 falls outside the georeferenced source footprint")
        coverage = crops[eid].intersection(view).area / view.area
        if coverage < MIN_VIEW_COVERAGE:
            fail(
                f"{eid}: the source maps {coverage:.1%} of the view footprint, under the "
                f"{MIN_VIEW_COVERAGE:.0%} floor; it is not a sheet of this area"
            )
        pixel = report["pixel_size_metres"]
        if edition["native_resolution_metres"] != round(pixel, 2):
            fail(f"{eid}: native_resolution_metres is not the measured {pixel} m pixel")
        derived = native_max_zoom(pixel, latitude)
        if edition["native_max_zoom"] != derived:
            fail(
                f"{eid}: native_max_zoom {edition['native_max_zoom']} is not the {derived} "
                f"that its measured {pixel} m pixel supports"
            )
        if not zoom["min"] <= derived <= zoom["max"]:
            fail(f"{eid}: native zoom {derived} is outside tile_zoom {zoom}")
        report["view_coverage_fraction"] = round(coverage, 6)
        report["native_max_zoom"] = derived
        reports[eid] = report
    return reports


def run_check(
    manifest_path: Path,
    schema_path: Path,
    index_path: Path,
    receipts_path: Path,
    sources_path: Path,
    raw_root: Path,
    catalog_path: Path | None = None,
    ledger_path: Path | None = None,
    expansion_root: Path | None = None,
) -> dict:
    manifest = read_json(manifest_path)
    crops = check_metadata(manifest, schema_path, index_path, sources_path, catalog_path)
    if manifest["version"] == 1:
        selection = {e["id"]: e["source_id"] for e in manifest["editions"]}
        resolved = resolve_selected(selection, receipts_path, raw_root)
        reports = check_georeferencing(manifest, index_path, resolved, crops)
        return {"manifest": manifest, "resolved": resolved, "reports": reports}
    by_kind = {kind: {} for kind in ENTRY_BY_SOURCE_KIND}
    for edition in manifest["editions"]:
        by_kind[edition["source_kind"]][edition["id"]] = edition["source_id"]
    resolved = resolve_selected(by_kind["historical_geotiff"], receipts_path, raw_root)
    resolved.update(
        resolve_pdf_sources(
            by_kind["us_topo_pdf"],
            ledger_path or demo_sources.LEDGER_PATH,
            raw_root,
            expansion_root or EXPANSION_ROOT,
        )
    )
    reports = check_expanded_georeferencing(manifest, index_path, resolved, crops)
    return {"manifest": manifest, "resolved": resolved, "reports": reports}


def datum_steps(description: str) -> list[str]:
    """The named datum steps in a transformation description, axis reorderings dropped."""
    if description.startswith("none "):
        return []
    return [
        step.strip()
        for step in description.split(" + ")
        if step.strip() and step.strip() != AXIS_ORDER_STEP
    ]


def edition_plan(
    edition: dict,
    record: dict,
    report: dict,
    grid: dict,
    operation: dict,
    resampling: str,
    versions: dict,
) -> dict:
    """Everything a COG's content depends on. Its digest decides whether to rewarp."""
    return {
        "processing_version": warp_raster.PROCESSING_VERSION,
        "source": {
            "source_id": record["topo_id"],
            "sha256": record["sha256"],
            "byte_count": record["byte_count"],
        },
        "crop_wgs84": edition["crop_wgs84"],
        "grid": grid,
        "resampling": resampling,
        "source_crs_wkt": report["crs_wkt"],
        "datum_transformation": operation,
        "tool_versions": versions,
    }


def edition_recipe(
    edition: dict, resolved: dict, report: dict, grid: dict, versions: dict
) -> dict:
    """Resolve how one edition would be warped, without reading a pixel of it."""
    resampling = warp_raster.resampling_for(edition["kind"])
    with warp_raster.open_source(resolved["path"]) as dataset:
        src_crs = CRS.from_user_input(dataset.crs)
    operation = warp_raster.select_operation(
        src_crs,
        tuple(report["graticule_labels_source_datum"]),
        datum_steps(report["datum_transformation"]["description"]),
    )
    plan = edition_plan(
        edition, resolved["record"], report, grid, operation, resampling, versions
    )
    return {
        "resampling": resampling,
        "operation": operation,
        "fingerprint": warp_raster.fingerprint(plan),
    }


def reusable(entry: dict | None, plan_digest: str, output: Path) -> dict | None:
    """An existing COG is reused only when its inputs and its own bytes both still match."""
    if entry is None or entry.get("fingerprint") != plan_digest or not output.is_file():
        return None
    digest, byte_count = warp_raster.sha256_file(output)
    if (digest, byte_count) != (entry["output"]["sha256"], entry["output"]["byte_count"]):
        return None
    return entry


def process_edition(
    edition: dict,
    resolved: dict,
    report: dict,
    grid: dict,
    recipe: dict,
    destination: Path,
) -> dict:
    """Warp one edition onto the shared grid and write its COG to `destination`."""
    eid = edition["id"]
    resampling = recipe["resampling"]
    operation = recipe["operation"]
    with warp_raster.open_source(resolved["path"]) as dataset:
        registration = warp_raster.verify_pipeline(dataset, operation["pipeline"])
        data, coverage = warp_raster.warp(dataset, grid, resampling, operation["pipeline"])
        bands = dataset.count
    alpha = np.where(
        coverage > 0, warp_raster.crop_mask(edition["crop_wgs84"], grid), 0
    ).astype("uint8")
    if not alpha.any():
        fail(f"{eid}: nothing of the source lands inside its crop on the shared grid.")
    # Masked-out pixels are zeroed so the COG's bytes depend only on the recorded inputs.
    data[:, alpha == 0] = 0
    warp_raster.write_cog(destination, data, alpha, grid, resampling)
    digest, byte_count = warp_raster.sha256_file(destination)
    pixel_size = report["pixel_size_metres"]
    return {
        "id": eid,
        "source": {
            "source_id": resolved["record"]["topo_id"],
            "sha256": resolved["record"]["sha256"],
            "byte_count": resolved["record"]["byte_count"],
            "raw_path": resolved["record"]["raw_path"],
            "size_px": report["size_px"],
            "pixel_size_metres": pixel_size,
        },
        "kind": edition["kind"],
        "resampling": resampling,
        "source_crs_wkt": report["crs_wkt"],
        "source_datum": report["datum"],
        "source_projection": report["projection"],
        "datum_transformation": operation,
        "crop_wgs84": edition["crop_wgs84"],
        "registration": {
            **registration,
            "neatline_residual_px": report["max_abs_neatline_residual_px"],
            "neatline_residual_metres": round(
                report["max_abs_neatline_residual_px"] * pixel_size, 3
            ),
            "datum_accuracy_metres": operation["accuracy_metres"],
            "correction_applied": "none; no GCP adjustment was made to any source",
        },
        "coverage": {
            "alpha_opaque_px": int((alpha > 0).sum()),
            "grid_px": grid["width"] * grid["height"],
        },
        "output": {
            "path": f"{RASTER_DIRNAME}/{destination.name}",
            "sha256": digest,
            "byte_count": byte_count,
            "width": grid["width"],
            "height": grid["height"],
            "bands": bands + 1,
            "dtype": "uint8",
            "alpha_band": bands + 1,
            "nodata_representation": "alpha band; no nodata value and no colour keying",
        },
        "fingerprint": recipe["fingerprint"],
    }


def registration_notes(entries: list[dict]) -> dict:
    """What is and is not established about registration, in the numbers actually measured."""
    return {
        "inspection": "automated only; no human source review is asserted here",
        "human_acceptance": "deferred to the acceptance tracker (issue #38)",
        "independent_ground_control": (
            "none available in this repository: no surveyed landmark or modern reference "
            "layer is committed, so no landmark check was run"
        ),
        "checks_run": [
            "the drawn neatline of each scan against its labelled graticule (demo-check, px)",
            "GDAL's warped extent against the pinned pyproj pipeline (m)",
            "GDAL's unpinned choice of operation against the pinned one (m)",
        ],
        "unresolved_systematic_offsets": [
            {
                "edition_id": entry["id"],
                "drawn_neatline_off_labelled_graticule_metres": entry["registration"][
                    "neatline_residual_metres"
                ],
                "datum_transformation_accuracy_metres": entry["registration"][
                    "datum_accuracy_metres"
                ],
            }
            for entry in entries
        ],
        "note": (
            "These offsets are carried, not corrected. The scans are used as published; "
            "no control point was moved."
        ),
    }


def write_record(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=".demo-processing-", suffix=".json", delete=False
    ) as handle:
        staged = Path(handle.name)
        try:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def run_cogs(
    manifest_path: Path,
    schema_path: Path,
    index_path: Path,
    receipts_path: Path,
    sources_path: Path,
    raw_root: Path,
    build_root: Path,
    zoom: int | None = None,
    catalog_path: Path | None = None,
    ledger_path: Path | None = None,
    expansion_root: Path | None = None,
) -> dict:
    """Warp the four 1:24,000 base sources onto one EPSG:3857 grid and record how it was done.

    A version-2 manifest is checked whole, all nine sources, but only its four base editions
    are warped here; scripts/demo_expansion.py warps the other five.
    """
    checked = run_check(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        catalog_path,
        ledger_path,
        expansion_root,
    )
    manifest, resolved, reports = checked["manifest"], checked["resolved"], checked["reports"]
    base = base_editions(manifest)
    try:
        versions = warp_raster.require_gdal()
        grid_zoom = manifest["tile_zoom"]["max"] if zoom is None else zoom
        if not manifest["tile_zoom"]["min"] <= grid_zoom <= manifest["tile_zoom"]["max"]:
            fail(f"Grid zoom {grid_zoom} is outside the manifest's tile_zoom range.")
        grid = warp_raster.common_grid(manifest["view_bounds_wgs84"], grid_zoom)
    except WarpError as exc:
        fail(str(exc))

    raster_root = build_root / RASTER_DIRNAME
    incoming = raster_root / INCOMING_DIRNAME
    record_path = raster_root / PROCESSING_FILENAME
    previous = read_json(record_path) if record_path.is_file() else {"editions": []}
    known = {entry["id"]: entry for entry in previous.get("editions", [])}

    entries, reused = [], []
    if incoming.exists():
        shutil.rmtree(incoming)
    incoming.mkdir(parents=True)
    try:
        for edition in base:
            eid = edition["id"]
            published = raster_root / f"{eid}.tif"
            try:
                recipe = edition_recipe(edition, resolved[eid], reports[eid], grid, versions)
                entry = reusable(known.get(eid), recipe["fingerprint"], published)
                if entry is not None:
                    entries.append(entry)
                    reused.append(eid)
                    continue
                entries.append(
                    process_edition(
                        edition,
                        resolved[eid],
                        reports[eid],
                        grid,
                        recipe,
                        incoming / f"{eid}.tif",
                    )
                )
            except WarpError as exc:
                fail(f"{eid}: {exc}")
        for edition in base:
            # Raw bytes must be exactly what they were before the warp (AGENTS.md §2.2).
            check_record(resolved[edition["id"]]["record"], raw_root)
        # Nothing reaches build/rasters/ until every edition has been warped and
        # every source has been re-verified.
        for edition in base:
            staged = incoming / f"{edition['id']}.tif"
            if staged.is_file():
                os.replace(staged, raster_root / f"{edition['id']}.tif")
    finally:
        shutil.rmtree(incoming, ignore_errors=True)

    payload = {
        "version": 1,
        "processing_version": warp_raster.PROCESSING_VERSION,
        "area_id": manifest["area_id"],
        "manifest_version": manifest["version"],
        "edition_order": list(manifest["edition_order"]),
        "base_editions": [edition["id"] for edition in base],
        "tile_zoom": manifest["tile_zoom"],
        "tool_versions": versions,
        "grid": grid,
        "editions": entries,
        "registration_notes": registration_notes(entries),
    }
    # `rasters` owns the tiles section; carrying it through means a COG-only run does not
    # make a still-valid pyramid look stale. A rewarped COG changes the tile fingerprint.
    if "tiles" in previous:
        payload["tiles"] = previous["tiles"]
    write_record(record_path, payload)
    return {"record": payload, "record_path": record_path, "reused": reused}


def base_editions(manifest: dict) -> list[dict]:
    """The four 1:24,000 editions whose crops define the camera footprint, in manifest order."""
    return [edition for edition in manifest["editions"] if edition["id"] in EDITION_ORDER]


def common_footprint(manifest: dict) -> Polygon:
    """The shared mapped footprint: the intersection of the four committed crops."""
    footprint = shape(manifest["editions"][0]["crop_wgs84"])
    for edition in manifest["editions"][1:]:
        footprint = footprint.intersection(shape(edition["crop_wgs84"]))
    if footprint.is_empty or not footprint.is_valid:
        fail("The four crops do not share a footprint.")
    return footprint


def sample_points(footprint: Polygon) -> dict:
    """One north and one south point inside the footprint, on its central meridian.

    Derived from the committed crops, not named from a gazetteer: no surveyed landmark is
    committed to this repository, so nothing here claims one (see docs/demo-processing.md).
    """
    west, south, east, north = footprint.bounds
    meridian = (west + east) / 2
    crossing = footprint.intersection(
        LineString([(meridian, south - 1.0), (meridian, north + 1.0)])
    )
    if crossing.is_empty:
        fail("The footprint's central meridian does not cross it.")
    low, high = crossing.bounds[1], crossing.bounds[3]
    inset = SAMPLE_INSET_FRACTION * (high - low)
    return {
        "north": (q6(meridian), q6(high - inset)),
        "south": (q6(meridian), q6(low + inset)),
    }


def tile_plan(entry: dict, grid: dict, zooms: list[int], versions: dict) -> dict:
    """Everything a pyramid's bytes depend on. Its digest decides whether to cut again."""
    return {
        "tiling_version": warp_raster.TILING_VERSION,
        "cog": {
            "sha256": entry["output"]["sha256"],
            "byte_count": entry["output"]["byte_count"],
        },
        "grid": grid,
        "zooms": zooms,
        "scheme": warp_raster.TILE_SCHEME,
        "format": warp_raster.TILE_FORMAT,
        "tile_size": warp_raster.TILE_SIZE,
        "png_options": warp_raster.PNG_OPTIONS,
        "resampling": entry["resampling"],
        "alpha_resampling": warp_raster.ALPHA_RESAMPLING,
        "tool_versions": versions,
    }


def reusable_pyramid(entry: dict | None, plan_digest: str, root: Path) -> dict | None:
    """A pyramid is reused only when its inputs, its file set and its own bytes all match."""
    if entry is None or entry.get("fingerprint") != plan_digest or not root.is_dir():
        return None
    digest, tiles, byte_count = warp_raster.pyramid_digest(root)
    if (digest, tiles, byte_count) != (entry["digest"], entry["tiles"], entry["bytes"]):
        return None
    return entry


def process_pyramid(
    entry: dict,
    cog_path: Path,
    grid: dict,
    zooms: list[int],
    samples: dict,
    fingerprint: str,
    destination: Path,
) -> dict:
    """Cut one edition's pyramid and check it against the COG at the sample points."""
    cut = warp_raster.cut_pyramid(cog_path, grid, zooms, entry["resampling"], destination)
    checked = warp_raster.verify_tile_samples(cog_path, destination, grid, max(zooms), samples)
    for sample in checked:
        if not sample["opaque"]:
            raise WarpError(
                f"The {sample['name']} sample point is transparent in tile {sample['tile']}; "
                "a point inside the shared footprint must be covered."
            )
    return {
        "id": entry["id"],
        "source_id": entry["source"]["source_id"],
        "cog_sha256": entry["output"]["sha256"],
        "resampling": entry["resampling"],
        "alpha_resampling": warp_raster.ALPHA_RESAMPLING,
        "path": f"{TILE_DIRNAME}/{TILE_SUBDIR}/{entry['id']}",
        "template": TILE_TEMPLATE.format(edition_id=entry["id"], z="{z}", x="{x}", y="{y}"),
        "sample_points": checked,
        "fingerprint": fingerprint,
        **cut,
    }


def tiling_notes() -> dict:
    """What the pyramid is, in the terms a reviewer would otherwise have to infer."""
    return {
        "inspection": "automated only; no human map review is asserted here",
        "human_acceptance": "deferred to the acceptance tracker (issue #38)",
        "tiler": (
            "scripts/warp_raster.cut_pyramid, on the GDAL inside the rasterio wheel; "
            "gdal2tiles and the GDAL command line are not installed here or in CI"
        ),
        "y_orientation": (
            "XYZ: y increases southwards from the north edge of the world. TMS y is never "
            "written, and no tiler flag selects it"
        ),
        "empty_areas": (
            "tiles outside the crop are written fully transparent, so a blank area is not a "
            "failed request"
        ),
        "top_zoom_is_a_block_copy": (
            "at the grid zoom a tile is copied from the COG without resampling; coarser "
            "zooms decimate whole blocks of the same grid"
        ),
        "sample_points": (
            "derived from the committed crops; no surveyed landmark or modern reference "
            "layer is committed to this repository"
        ),
    }


def run_rasters(
    manifest_path: Path,
    schema_path: Path,
    index_path: Path,
    receipts_path: Path,
    sources_path: Path,
    raw_root: Path,
    build_root: Path,
    zoom: int | None = None,
    catalog_path: Path | None = None,
    ledger_path: Path | None = None,
    expansion_root: Path | None = None,
) -> dict:
    """Preflight, warp the four base sources onto one grid, then cut one XYZ pyramid each.

    For the version-2 manifest the five added editions are then warped and tiled by
    scripts/demo_expansion.py, each to its own native zoom capped at the same `zoom`.
    """
    tile_root = build_root / TILE_DIRNAME / TILE_SUBDIR
    record_path = build_root / RASTER_DIRNAME / PROCESSING_FILENAME
    known = {}
    if record_path.is_file():
        known = {
            entry["id"]: entry
            for entry in read_json(record_path).get("tiles", {}).get("editions", [])
        }

    prepared = run_cogs(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        build_root,
        zoom,
        catalog_path,
        ledger_path,
        expansion_root,
    )
    record = prepared["record"]
    grid = record["grid"]
    # The top zoom is the grid the COGs are on, never finer: upsampling past the source grid
    # would publish detail no source has.
    zoom_min, zoom_max = record["tile_zoom"]["min"], grid["zoom"]
    zooms = list(range(zoom_min, zoom_max + 1))
    manifest = read_json(manifest_path)
    samples = sample_points(common_footprint({"editions": base_editions(manifest)}))

    incoming = build_root / TILE_DIRNAME / INCOMING_DIRNAME
    if incoming.exists():
        shutil.rmtree(incoming)
    incoming.mkdir(parents=True)
    entries, reused = [], []
    try:
        for entry in record["editions"]:
            eid = entry["id"]
            cog_path = build_root / RASTER_DIRNAME / f"{eid}.tif"
            try:
                fingerprint = warp_raster.fingerprint(
                    tile_plan(entry, grid, zooms, record["tool_versions"])
                )
                published = reusable_pyramid(known.get(eid), fingerprint, tile_root / eid)
                if published is not None:
                    entries.append(published)
                    reused.append(eid)
                    continue
                entries.append(
                    process_pyramid(
                        entry, cog_path, grid, zooms, samples, fingerprint, incoming / eid
                    )
                )
            except WarpError as exc:
                fail(f"{eid}: {exc}")
        # Nothing reaches build/tiles/demo/ until every edition has been cut and checked,
        # so a retry cannot leave a partial pyramid looking complete.
        tile_root.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            staged = incoming / entry["id"]
            if staged.is_dir():
                shutil.rmtree(tile_root / entry["id"], ignore_errors=True)
                os.replace(staged, tile_root / entry["id"])
    finally:
        shutil.rmtree(incoming, ignore_errors=True)

    unexpected = sorted(
        path.name for path in tile_root.iterdir() if path.name not in record["edition_order"]
    )
    if unexpected:
        fail(
            f"{tile_root} holds unexpected entries {unexpected}; remove them or run make clean."
        )
    payload = {
        **record,
        "tiles": {
            "version": 1,
            "tiling_version": warp_raster.TILING_VERSION,
            "scheme": warp_raster.TILE_SCHEME,
            "format": warp_raster.TILE_FORMAT,
            "tile_size": warp_raster.TILE_SIZE,
            "png_options": warp_raster.PNG_OPTIONS,
            "root": f"{TILE_DIRNAME}/{TILE_SUBDIR}",
            "template": TILE_TEMPLATE,
            "zoom": {"min": zoom_min, "max": zoom_max},
            "bounds_3857": grid["bounds"],
            "bounds_wgs84": list(manifest["view_bounds_wgs84"]),
            "totals": {
                "tiles": sum(entry["tiles"] for entry in entries),
                "bytes": sum(entry["bytes"] for entry in entries),
            },
            "editions": entries,
            "notes": tiling_notes(),
        },
    }
    write_record(record_path, payload)
    expansion = None
    if manifest["version"] == 2:
        import demo_expansion

        expansion = demo_expansion.run_rasters(
            manifest_path,
            schema_path,
            index_path,
            receipts_path,
            sources_path,
            raw_root,
            catalog_path or demo_sources.CATALOG_PATH,
            ledger_path or demo_sources.LEDGER_PATH,
            expansion_root or EXPANSION_ROOT,
            zoom,
        )
    return {
        "record": payload,
        "record_path": record_path,
        "tile_root": tile_root,
        "reused_cogs": prepared["reused"],
        "reused": reused,
        "samples": samples,
        "expansion": expansion,
    }


@click.group()
def cli() -> None:
    """Auburn demo edition manifest tools."""


def _common_options(command):
    options = [
        click.option(
            "--manifest",
            "manifest_path",
            type=click.Path(path_type=Path),
            default=MANIFEST_PATH,
            show_default=False,
        ),
        click.option(
            "--schema",
            "schema_path",
            type=click.Path(path_type=Path),
            default=SCHEMA_PATH,
            show_default=False,
        ),
        click.option(
            "--index",
            "index_path",
            type=click.Path(path_type=Path),
            default=INDEX_PATH,
            show_default=False,
        ),
        click.option(
            "--receipts",
            "receipts_path",
            type=click.Path(path_type=Path),
            default=RECEIPTS_PATH,
            show_default=False,
        ),
        click.option(
            "--sources",
            "sources_path",
            type=click.Path(path_type=Path),
            default=SOURCES_PATH,
            show_default=False,
        ),
        click.option(
            "--raw-root",
            "raw_root",
            type=click.Path(path_type=Path),
            envvar="DEMO_RAW_ROOT",
            default=RAW_ROOT,
            show_default=False,
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def _expansion_options(command):
    """Inputs only a version-2 manifest reads: the PDF catalog, its ledger and the E2 output."""
    options = [
        click.option(
            "--catalog",
            "catalog_path",
            type=click.Path(path_type=Path),
            default=demo_sources.CATALOG_PATH,
            show_default=False,
        ),
        click.option(
            "--ledger",
            "ledger_path",
            type=click.Path(path_type=Path),
            default=demo_sources.LEDGER_PATH,
            show_default=False,
        ),
        click.option(
            "--expansion-root",
            "expansion_root",
            type=click.Path(path_type=Path),
            default=EXPANSION_ROOT,
            show_default=False,
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def describe_source(resolved: dict) -> str:
    """One line of byte lineage for a checked edition, either source kind."""
    if "pdf_receipt" in resolved:
        receipt, raster = resolved["pdf_receipt"], resolved["pdf_source"]["raster"]
        return (
            f"{receipt['source_id']} pdf sha256={receipt['sha256']} "
            f"bytes={receipt['size_bytes']}"
            f" -> cog sha256={raster['sha256']}"
        )
    record = resolved["record"]
    return f"{record['topo_id']} sha256={record['sha256']} bytes={record['byte_count']}"


@cli.command()
@_common_options
@_expansion_options
def check(
    manifest_path,
    schema_path,
    index_path,
    receipts_path,
    sources_path,
    raw_root,
    catalog_path,
    ledger_path,
    expansion_root,
) -> None:
    """Verify the manifest contract and its selected sources. Writes nothing."""
    result = run_check(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        catalog_path,
        ledger_path,
        expansion_root,
    )
    for eid in result["manifest"]["edition_order"]:
        report = result["reports"][eid]
        extra = ""
        if result["manifest"]["version"] == 2:
            extra = (
                f"; {report['pixel_size_metres']} m/px -> native zoom "
                f"{report['native_max_zoom']}; view coverage {report['view_coverage_fraction']}"
            )
        click.echo(
            f"{eid}: {describe_source(result['resolved'][eid])} {report['datum']}/"
            f"{report['projection']} -> {report['datum_transformation']['description']}{extra}"
        )
    west, south, east, north = result["manifest"]["view_bounds_wgs84"]
    click.echo(
        f"demo-check: {len(result['manifest']['editions'])} public editions verified; "
        f"common footprint {west}, {south}, {east}, {north}; zoom "
        f"{result['manifest']['tile_zoom']['min']}-{result['manifest']['tile_zoom']['max']}"
    )


@cli.command()
@_common_options
@_expansion_options
@click.option(
    "--build-root",
    "build_root",
    type=click.Path(path_type=Path),
    default=BUILD_ROOT,
    show_default=False,
)
@click.option(
    "--grid-zoom",
    "zoom",
    type=int,
    default=None,
    help="Grid zoom to warp onto; defaults to the manifest maximum. Lower values are for "
    "inspection and tests, and the chosen zoom is recorded with the output.",
)
def cogs(
    manifest_path,
    schema_path,
    index_path,
    receipts_path,
    sources_path,
    raw_root,
    catalog_path,
    ledger_path,
    expansion_root,
    build_root,
    zoom,
) -> None:
    """Warp the four base sources onto one EPSG:3857 grid as COGs under build/rasters/."""
    result = run_cogs(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        build_root,
        zoom,
        catalog_path,
        ledger_path,
        expansion_root,
    )
    record = result["record"]
    grid = record["grid"]
    for entry in record["editions"]:
        state = "reused" if entry["id"] in result["reused"] else "warped"
        click.echo(
            f"{entry['id']}: {state} {entry['resampling']} from {entry['source']['source_id']} "
            f"-> {entry['output']['path']} sha256={entry['output']['sha256']} "
            f"alpha={entry['coverage']['alpha_opaque_px']}/{entry['coverage']['grid_px']} px"
        )
    versions = record["tool_versions"]
    click.echo(
        f"demo-cogs: {len(record['editions'])} COGs on one {grid['width']}x{grid['height']} "
        f"{grid['crs']} grid at {grid['resolution_metres']:.6f} m/px (zoom {grid['zoom']}); "
        f"GDAL {versions['gdal']} / PROJ {versions['proj_gdal']}; "
        f"record {result['record_path'].name}"
    )


@cli.command()
@_common_options
@_expansion_options
@click.option(
    "--build-root",
    "build_root",
    type=click.Path(path_type=Path),
    default=BUILD_ROOT,
    show_default=False,
)
@click.option(
    "--grid-zoom",
    "zoom",
    type=int,
    default=None,
    help="Grid zoom to warp onto, and the top zoom of every pyramid; defaults to the "
    "manifest maximum. Lower values are for inspection and tests.",
)
def rasters(
    manifest_path,
    schema_path,
    index_path,
    receipts_path,
    sources_path,
    raw_root,
    catalog_path,
    ledger_path,
    expansion_root,
    build_root,
    zoom,
) -> None:
    """Preflight, warp to COGs, then cut bounded XYZ PNG pyramids for every edition.

    The four base pyramids go to build/tiles/demo/, the five added ones to
    build/expansion/tiles/.
    """
    started = time.monotonic()
    result = run_rasters(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        build_root,
        zoom,
        catalog_path,
        ledger_path,
        expansion_root,
    )
    tiles = result["record"]["tiles"]
    for entry in tiles["editions"]:
        state = "reused" if entry["id"] in result["reused"] else "cut"
        levels = ", ".join(f"z{level['zoom']}:{level['tiles']}" for level in entry["levels"])
        click.echo(
            f"{entry['id']}: {state} {entry['tiles']} tiles ({levels}) "
            f"{entry['transparent_tiles']} transparent, {entry['bytes']} bytes, "
            f"digest={entry['digest'][:12]}"
        )
    for sample in tiles["editions"][0]["sample_points"]:
        click.echo(
            f"sample {sample['name']}: {sample['lon']}, {sample['lat']} -> tile "
            f"{sample['tile']} pixel {sample['pixel']} (XYZ z/x/y)"
        )
    click.echo(
        f"demo-rasters: {len(tiles['editions'])} pyramids, zoom {tiles['zoom']['min']}-"
        f"{tiles['zoom']['max']}, {tiles['totals']['tiles']} tiles, "
        f"{tiles['totals']['bytes']} bytes, {warp_raster.TILE_SCHEME.upper()} scheme; "
        f"{time.monotonic() - started:.1f} s; record {result['record_path'].name}"
    )
    if result["expansion"] is not None:
        added = result["expansion"]["record"]
        for entry in added["editions"]:
            state = "reused" if entry["id"] in result["expansion"]["reused"] else "cut"
            click.echo(
                f"{entry['id']}: {state} {entry['tiles']['tiles']} tiles, zoom "
                f"{entry['zoom']['min']}-{entry['zoom']['max']} (native "
                f"{entry['zoom']['native_max_zoom']}), {entry['tiles']['bytes']} bytes"
            )
        click.echo(
            f"demo-rasters: {len(added['editions'])} added pyramids, "
            f"{added['tiles']['totals']['tiles']} tiles; record "
            f"{result['expansion']['record_path'].name}"
        )


@cli.command()
@_common_options
@_expansion_options
@click.option(
    "--build-root",
    "build_root",
    type=click.Path(path_type=Path),
    default=BUILD_ROOT,
    show_default=False,
)
@click.option(
    "--grid-zoom",
    "zoom",
    type=int,
    default=None,
    help="Grid zoom to warp onto, and the pyramid's top zoom; defaults to the manifest "
    "maximum. A lower value publishes, and advertises, only the zooms it cut.",
)
@click.option("--site-dir", "site_dir", type=click.Path(path_type=Path), default=None)
@click.option(
    "--dist",
    "dist",
    type=click.Path(path_type=Path),
    default=None,
    help="Built site to publish from. Used with --no-vite to publish an existing bundle.",
)
@click.option("--data-dir", "data_dir", type=click.Path(path_type=Path), default=None)
@click.option("--schema-dir", "schema_dir", type=click.Path(path_type=Path), default=None)
@click.option("--npm", "npm", default="npm", show_default=True)
@click.option(
    "--vite/--no-vite",
    "vite",
    default=True,
    help="Run 'npm run build' in site/ first. --no-vite republishes the existing site/dist.",
)
def build(
    manifest_path,
    schema_path,
    index_path,
    receipts_path,
    sources_path,
    raw_root,
    catalog_path,
    ledger_path,
    expansion_root,
    build_root,
    zoom,
    site_dir,
    dist,
    data_dir,
    schema_dir,
    npm,
    vite,
) -> None:
    """Assemble the allowlisted public site into build/public/ (D4a).

    Preflight, rasters, site build, staging, the restricted-value scan, then one atomic
    swap. A failure publishes nothing and leaves any previous build/public untouched.
    """
    import build_site

    started = time.monotonic()
    optional = {
        key: value
        for key, value in (
            ("site_dir", site_dir),
            ("dist", dist),
            ("data_dir", data_dir),
            ("schema_dir", schema_dir),
        )
        if value is not None
    }
    result = build_site.run_build(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        build_root,
        zoom,
        catalog_path=catalog_path,
        ledger_path=ledger_path,
        expansion_root=expansion_root,
        npm=npm,
        vite=vite,
        **optional,
    )
    inventory = result["inventory"]
    for entry in inventory["app_assets"]:
        click.echo(f"asset {entry['path']}: {entry['byte_count']} bytes")
    click.echo(
        f"metadata {inventory['metadata']['path']}: {inventory['metadata']['byte_count']} bytes"
    )
    for entry in inventory["editions"]:
        click.echo(
            f"{entry['id']}: {entry['path']}/{{z}}/{{x}}/{{y}}.png {entry['tiles']} tiles, "
            f"zoom {entry['zoom']['min']}-{entry['zoom']['max']}, {entry['bytes']} bytes, "
            f"digest={entry['digest'][:12]}"
        )
    click.echo(inventory["leak_scan"])
    totals = inventory["totals"]
    click.echo(
        f"demo-build: published {totals['files']} files, {totals['bytes']} bytes to "
        f"{inventory['root']}/ (zoom {inventory['zoom']['min']}-{inventory['zoom']['max']}, "
        f"{totals['tiles']} tiles); {time.monotonic() - started:.1f} s; "
        f"inventory {result['inventory_path'].name}"
    )


@cli.command()
@click.option("--index", "index_path", type=click.Path(path_type=Path), default=INDEX_PATH)
@click.option(
    "--receipts", "receipts_path", type=click.Path(path_type=Path), default=RECEIPTS_PATH
)
@click.option(
    "--raw-root",
    "raw_root",
    type=click.Path(path_type=Path),
    envvar="DEMO_RAW_ROOT",
    default=RAW_ROOT,
)
def inspect(index_path, receipts_path, raw_root) -> None:
    """Print the neatline locators and derived geometry that `check` compares against.

    Works from the allowlist alone, so it can author the manifest it later verifies.
    """
    rows = read_index(index_path)
    selection = {eid: EXPECTED_EDITIONS[eid]["source_id"] for eid in EDITION_ORDER}
    resolved = resolve_selected(selection, receipts_path, raw_root)
    payload = {
        eid: inspect_source(resolved[eid]["path"], rows[selection[eid]])
        for eid in EDITION_ORDER
    }
    crops = {eid: shape(report["crop_wgs84"]) for eid, report in payload.items()}
    common = crops[EDITION_ORDER[0]]
    for eid in EDITION_ORDER[1:]:
        common = common.intersection(crops[eid])
    click.echo(
        json.dumps(
            {"editions": payload, "view_bounds_wgs84": [q6(v) for v in common.bounds]},
            indent=2,
            sort_keys=True,
        )
    )


def derive_added_editions(
    view_manifest: dict,
    index_path: Path,
    receipts_path: Path,
    raw_root: Path,
    ledger_path: Path,
    expansion_root: Path,
) -> dict[str, dict]:
    """Geometry, pixel size and zoom limit of the five added sources, from the allowlist.

    `view_manifest` supplies the verified crops of the four base editions. `check` recomputes
    every value here and compares it with the committed version-2 manifest.
    """
    rows = read_index(index_path)
    view = common_footprint({"editions": base_editions(view_manifest)})
    view_seed = seed_of(rows[EXPECTED_EDITIONS[BASE_EDITION_ID]["source_id"]])
    _, south, _, north = view_manifest["view_bounds_wgs84"]
    added = [eid for eid in EXPANDED_EDITION_ORDER if eid not in EDITION_ORDER]
    scans = {
        eid: EXPANDED_EXPECTED_EDITIONS[eid]["source_id"]
        for eid in added
        if EXPANDED_EXPECTED_EDITIONS[eid]["source_kind"] == "historical_geotiff"
    }
    pdfs = {
        eid: EXPANDED_EXPECTED_EDITIONS[eid]["source_id"] for eid in added if eid not in scans
    }
    resolved = resolve_selected(scans, receipts_path, raw_root)
    resolved.update(resolve_pdf_sources(pdfs, ledger_path, raw_root, expansion_root))
    payload = {}
    for eid in added:
        if eid in scans:
            row = rows[scans[eid]]
            report = inspect_source(
                resolved[eid]["path"], row, bounding_edges(seed_of(row), view_seed)
            )
            report["face_wgs84"] = report["crop_wgs84"]
            report["index_crs"] = compare_index_crs(row, report["crs_wkt"])
        else:
            report = inspect_pdf_cog(resolved[eid]["path"], resolved[eid]["pdf_source"])
        report["crop_wgs84"] = clip_to_view(shape(report["face_wgs84"]), view)
        report["view_coverage_fraction"] = round(
            shape(report["crop_wgs84"]).area / view.area, 6
        )
        report["native_resolution_metres"] = round(report["pixel_size_metres"], 2)
        report["native_max_zoom"] = native_max_zoom(
            report["pixel_size_metres"], (south + north) / 2
        )
        payload[eid] = report
    return payload


@cli.command("inspect-expanded")
@click.option(
    "--manifest", "manifest_path", type=click.Path(path_type=Path), default=MANIFEST_PATH
)
@click.option("--index", "index_path", type=click.Path(path_type=Path), default=INDEX_PATH)
@click.option(
    "--receipts", "receipts_path", type=click.Path(path_type=Path), default=RECEIPTS_PATH
)
@click.option(
    "--raw-root",
    "raw_root",
    type=click.Path(path_type=Path),
    envvar="DEMO_RAW_ROOT",
    default=RAW_ROOT,
)
@click.option(
    "--ledger", "ledger_path", type=click.Path(path_type=Path), default=demo_sources.LEDGER_PATH
)
@click.option(
    "--expansion-root",
    "expansion_root",
    type=click.Path(path_type=Path),
    default=EXPANSION_ROOT,
)
def inspect_expanded(
    manifest_path, index_path, receipts_path, raw_root, ledger_path, expansion_root
) -> None:
    """Print the derived crop, pixel size and zoom limit of each added edition.

    The view comes from the verified crops of the manifest's four base editions, so this can
    re-derive the version-2 values that `check` later verifies.
    """
    manifest = read_json(manifest_path)
    payload = derive_added_editions(
        manifest, index_path, receipts_path, raw_root, ledger_path, expansion_root
    )
    click.echo(json.dumps({"editions": payload}, indent=2, sort_keys=True))


if __name__ == "__main__":
    cli()
