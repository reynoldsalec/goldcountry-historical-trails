"""Edition contract and selected-source preflight for the Auburn map-browser demo.

Reads only the four allowlisted inputs; the other indexed sheets are irrelevant to this
build. Nothing here writes to data/raw/ or to the receipt ledger (AGENTS.md 2.2), and
nothing here dates a mapped feature: every value describes a source sheet.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import click
import numpy as np
import rasterio
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.transformer import TransformerGroup
from rasterio.transform import rowcol
from rasterio.windows import Window
from shapely.geometry import Polygon, shape
from source_archive import check_record, load_receipts

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data/sources/demo-editions.json"
SCHEMA_PATH = REPO_ROOT / "schema/demo-editions.schema.json"
INDEX_PATH = REPO_ROOT / "data/sources/topo_index.csv"
RECEIPTS_PATH = REPO_ROOT / "data/sources/retrievals.jsonl"
SOURCES_PATH = REPO_ROOT / "data/sources/sources.yml"
RAW_ROOT = REPO_ROOT / "data/raw"

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


def check_editions_present(manifest: dict) -> list[dict]:
    editions = manifest["editions"]
    ids = [edition["id"] for edition in editions]
    if len(set(ids)) != len(ids):
        fail(f"Duplicate edition id in the manifest: {sorted(ids)}")
    if ids != manifest["edition_order"]:
        fail(f"editions are not in edition_order: {ids} != {manifest['edition_order']}")
    if ids != EDITION_ORDER:
        fail(f"Edition set or order differs from the fixed contract: {ids} != {EDITION_ORDER}")
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


def check_dates(edition: dict, row: dict, base_row: dict) -> None:
    eid = edition["id"]
    dates = edition["dates"]
    for field in ("base_photography", "revision_photography", "photography"):
        parse_photography(dates[field], f"{eid}.dates.{field}")

    expected = EXPECTED_EDITIONS[eid]["dates"]
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


def check_kind(edition: dict, row: dict) -> None:
    eid = edition["id"]
    expected = EXPECTED_EDITIONS[eid]
    if edition["source_id"] != expected["source_id"]:
        fail(f"{eid}: source_id {edition['source_id']} is not the allowlisted scan variant")
    if edition["kind"] != expected["kind"]:
        fail(f"{eid}: kind {edition['kind']!r} differs from the contract {expected['kind']!r}")
    # Field-checked lineage is what separates the topo sheets from the orthophotoquad.
    checked = bool(row["field_check_year"])
    if edition["kind"] == "topo" and not checked:
        fail(f"{eid}: index records no field check, so it is not a topo sheet")
    if edition["kind"] == "orthophotoquad":
        if checked:
            fail(f"{eid}: index records a field check, so it is not an orthophotoquad")
        if not row["aerial_photo_year"]:
            fail(f"{eid}: index records no aerial photography year for an orthophotoquad")


def check_rights(edition: dict, row: dict, entry: dict) -> None:
    eid = edition["id"]
    if row["rights"] != "public_domain":
        fail(f"{eid}: index rights {row['rights']!r} is not public_domain")
    if edition["rights"] != entry["rights"]:
        fail(f"{eid}: rights {edition['rights']!r} != sources.yml {entry['rights']!r}")
    if edition["attribution"] != entry["attribution"]:
        fail(f"{eid}: attribution does not match sources.yml for {SOURCE_ENTRY_ID}")
    if edition["source_url"] != row["sciencebase_url"]:
        fail(f"{eid}: source_url does not match the index sciencebase_url")
    if edition["source_id"] not in edition["citation"]:
        fail(f"{eid}: citation does not name the source ID")


def source_entry(path: Path) -> dict:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"Cannot read {path}: {exc}")
    for entry in document.get("sources", []):
        if entry.get("id") == SOURCE_ENTRY_ID:
            return entry
    fail(f"{path} has no {SOURCE_ENTRY_ID} entry to take rights and attribution from")


def check_metadata(
    manifest: dict,
    schema_path: Path,
    index_path: Path,
    sources_path: Path,
) -> dict[str, Polygon]:
    """Everything verifiable without opening a raster."""
    check_schema(manifest, schema_path)
    if manifest["area_id"] != AREA_ID or manifest["tile_zoom"] != TILE_ZOOM:
        fail("area_id or tile_zoom differs from the fixed contract")
    editions = check_editions_present(manifest)
    check_bounds_shape(manifest)
    rows = read_index(index_path)
    entry = source_entry(sources_path)
    missing = [e["source_id"] for e in editions if e["source_id"] not in rows]
    if missing:
        fail(f"Selected source(s) absent from {index_path}: {', '.join(missing)}")
    base_row = rows[EXPECTED_EDITIONS[BASE_EDITION_ID]["source_id"]]
    crops = {}
    for edition in editions:
        row = rows[edition["source_id"]]
        check_kind(edition, row)
        check_rights(edition, row, entry)
        check_dates(edition, row, base_row)
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


def _verify_edges(dataset, edges: dict[str, dict], search: int, path: Path) -> dict:
    """Check the drawn neatline against the projected graticule at both ends of each edge.

    An axis-aligned crop passes a mid-edge check and still cuts metres of map content at
    the south corners, because the meridians converge (PR #47).
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
            if abs(residual) > NEATLINE_TOLERANCE_PX:
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
        locators[label] = found
    return locators


def inspect_source(path: Path, row: dict) -> dict:
    """Derive the crop from the labelled graticule and verify the drawn neatline against it.

    The crop is the graticule quadrilateral, not a rectangle in the source projection: the
    east and west neatlines are meridians and they converge. The scan is read to verify
    that the drawn line really sits on that quadrilateral at both ends of every edge.
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

        locators = _verify_edges(dataset, edges, search, path)

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
                edge["max_abs_residual_px"] for edge in locators.values()
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


def run_check(
    manifest_path: Path,
    schema_path: Path,
    index_path: Path,
    receipts_path: Path,
    sources_path: Path,
    raw_root: Path,
) -> dict:
    manifest = read_json(manifest_path)
    crops = check_metadata(manifest, schema_path, index_path, sources_path)
    selection = {e["id"]: e["source_id"] for e in manifest["editions"]}
    resolved = resolve_selected(selection, receipts_path, raw_root)
    reports = check_georeferencing(manifest, index_path, resolved, crops)
    return {"manifest": manifest, "resolved": resolved, "reports": reports}


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


@cli.command()
@_common_options
def check(
    manifest_path, schema_path, index_path, receipts_path, sources_path, raw_root
) -> None:
    """Verify the manifest contract and the four selected sources. Writes nothing."""
    result = run_check(
        manifest_path, schema_path, index_path, receipts_path, sources_path, raw_root
    )
    for eid in result["manifest"]["edition_order"]:
        record = result["resolved"][eid]["record"]
        report = result["reports"][eid]
        click.echo(
            f"{eid}: {record['topo_id']} sha256={record['sha256']} "
            f"bytes={record['byte_count']} {report['datum']}/"
            f"{report['projection']} -> {report['datum_transformation']['description']}"
        )
    west, south, east, north = result["manifest"]["view_bounds_wgs84"]
    click.echo(
        f"demo-check: 4 public editions verified; common footprint "
        f"{west}, {south}, {east}, {north}; zoom "
        f"{result['manifest']['tile_zoom']['min']}-{result['manifest']['tile_zoom']['max']}"
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


if __name__ == "__main__":
    cli()
