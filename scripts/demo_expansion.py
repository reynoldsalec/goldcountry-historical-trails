"""Warp and tile the five editions the staged nine-edition manifest adds (#57).

Writes only under build/expansion/. The live four-edition COGs, pyramids and site are not
read or touched; each added edition is tiled only up to its own native zoom.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import click
import demo
import demo_sources
import numpy as np
import warp_raster
from pyproj import CRS
from shapely.geometry import shape
from source_archive import check_record
from warp_raster import WarpError

RASTER_DIRNAME = "rasters"
TILE_DIRNAME = "tiles"
RECORD_NAME = "demo-expansion-processing.json"
INCOMING_DIRNAME = ".incoming"
TILE_TEMPLATE = "tiles/{edition_id}/{z}/{x}/{y}.png"
# Registration is measured against the initial edition, the base sheet the viewer opens on.
REFERENCE_EDITION_ID = demo.INITIAL_EDITION_ID
# Dispersed patch centres, as fractions of the crop's bounding box (west-east, south-north).
PATCH_FRACTIONS = {
    "centre": (0.5, 0.5),
    "north_west": (0.25, 0.75),
    "north_east": (0.75, 0.75),
    "south_west": (0.25, 0.25),
    "south_east": (0.75, 0.25),
}


def added_editions(manifest: dict) -> list[dict]:
    return [e for e in manifest["editions"] if e["id"] not in demo.EDITION_ORDER]


def patch_points(crop) -> dict:
    west, south, east, north = crop.bounds
    points = {}
    for name, (fx, fy) in PATCH_FRACTIONS.items():
        lon, lat = demo.q6(west + fx * (east - west)), demo.q6(south + fy * (north - south))
        points[name] = (lon, lat)
    return points


def source_lineage(edition: dict, resolved: dict, report: dict) -> dict:
    """Which bytes a COG came from: the raw TIFF, or the raw PDF through its E2 render."""
    if edition["source_kind"] == "us_topo_pdf":
        receipt, rendered = resolved["pdf_receipt"], resolved["pdf_source"]
        return {
            "source_id": edition["source_id"],
            "pdf_sha256": receipt["sha256"],
            "pdf_size_bytes": receipt["size_bytes"],
            "pdf_raw_path": receipt["path"],
            "rendered_by": f"make expansion-pdf ({demo.PDF_RECORD_NAME})",
            "rendered_cog": f"pdf/{edition['id']}.tif",
            "rendered_cog_sha256": rendered["raster"]["sha256"],
            "rendered_cog_byte_count": rendered["raster"]["byte_count"],
            "render_dpi": rendered["raster"]["dpi"],
            "size_px": report["size_px"],
            "pixel_size_metres": report["pixel_size_metres"],
        }
    record = resolved["record"]
    return {
        "source_id": record["topo_id"],
        "sha256": record["sha256"],
        "byte_count": record["byte_count"],
        "raw_path": record["raw_path"],
        "size_px": report["size_px"],
        "pixel_size_metres": report["pixel_size_metres"],
    }


def reverify(edition: dict, resolved: dict, raw_root: Path, expansion_root: Path) -> None:
    """Raw bytes, and a PDF's rendered COG, must be exactly what the check verified."""
    if edition["source_kind"] == "us_topo_pdf":
        demo_sources.verify_receipted(resolved["pdf_receipt"], raw_root)
        raster = resolved["pdf_source"]["raster"]
        cog = expansion_root / "pdf" / f"{edition['id']}.tif"
        if warp_raster.sha256_file(cog) != (raster["sha256"], raster["byte_count"]):
            demo.fail(f"{edition['id']}: {cog.name} changed during the run")
    else:
        check_record(resolved["record"], raw_root)


def registration(report: dict, pinned: dict, offsets: list[dict], operation: dict) -> dict:
    measured = {
        **pinned,
        "datum_accuracy_metres": operation["accuracy_metres"],
        "offsets_vs_reference": offsets,
        "distinct_offsets": sum(1 for offset in offsets if offset["distinct"]),
        "correction_applied": "none; no GCP adjustment was made to any source",
    }
    pixel = report["pixel_size_metres"]
    if "neatline_locators_px" in report:
        measured["neatline_residual_px"] = report["max_abs_neatline_residual_px"]
        measured["neatline_residual_metres"] = round(
            report["max_abs_neatline_residual_px"] * pixel, 3
        )
        measured["neatline_edges_enforced"] = report["enforced_edges"]
        measured["neatline_residual_px_all_edges"] = report[
            "max_abs_neatline_residual_px_all_edges"
        ]
        measured["neatline_locators_px"] = report["neatline_locators_px"]
    else:
        measured["neatline_offset_from_nominal_metres"] = report[
            "neatline_offset_from_nominal_m"
        ]
        measured["gpts_max_residual_metres"] = report["gpts_max_residual_m"]
    return measured


def warp_edition(
    edition: dict,
    source_path: Path,
    report: dict,
    grid: dict,
    operation: dict,
    resampling: str,
    destination: Path,
) -> tuple[dict, dict]:
    """One edition onto its own grid, alpha from coverage and the crop polygon only."""
    with warp_raster.open_source(source_path) as dataset:
        pinned = warp_raster.verify_pipeline(dataset, operation["pipeline"])
        data, coverage = warp_raster.warp(dataset, grid, resampling, operation["pipeline"])
    alpha = np.where(coverage > 0, warp_raster.crop_mask(edition["crop_wgs84"], grid), 0)
    alpha = alpha.astype("uint8")
    if not alpha.any():
        raise WarpError("nothing of the source lands inside its crop on its grid")
    data[:, alpha == 0] = 0
    warp_raster.write_cog(destination, data, alpha, grid, resampling)
    digest, byte_count = warp_raster.sha256_file(destination)
    bands = data.shape[0]
    output = {
        "path": f"{RASTER_DIRNAME}/{edition['id']}.tif",
        "sha256": digest,
        "byte_count": byte_count,
        "width": grid["width"],
        "height": grid["height"],
        "bands": bands + 1,
        "dtype": "uint8",
        "alpha_band": bands + 1,
        "nodata_representation": "alpha band; no nodata value and no colour keying",
    }
    coverage_counts = {
        "alpha_opaque_px": int((alpha > 0).sum()),
        "grid_px": grid["width"] * grid["height"],
    }
    return {"output": output, "coverage": coverage_counts}, pinned


def cut_tiles(entry: dict, cog: Path, grid: dict, zooms: list[int], destination: Path) -> dict:
    cut = warp_raster.cut_pyramid(cog, grid, zooms, entry["resampling"], destination)
    samples = demo.sample_points(shape(entry["crop_wgs84"]))
    checked = warp_raster.verify_tile_samples(cog, destination, grid, max(zooms), samples)
    for sample in checked:
        if not sample["opaque"]:
            raise WarpError(
                f"the {sample['name']} sample point is transparent in tile {sample['tile']}"
            )
    for level in cut["levels"]:
        # Each level must stay inside the grid's own tiles: nothing world-wide is cut.
        if level["tile_range"] != warp_raster.tile_indices(grid, level["zoom"]):
            raise WarpError(f"zoom {level['zoom']} was cut outside the view's tile range")
    return {
        "path": f"{TILE_DIRNAME}/{entry['id']}",
        "template": TILE_TEMPLATE.format(edition_id=entry["id"], z="{z}", x="{x}", y="{y}"),
        "zoom": {"min": min(zooms), "max": max(zooms)},
        "sample_points": checked,
        **cut,
    }


def reusable(entry: dict | None, fingerprints: tuple[str, str], root: Path) -> dict | None:
    """A prior edition is reused only when its inputs and its COG and tile bytes all match."""
    if entry is None or (entry.get("fingerprint"), entry["tiles"].get("fingerprint")) != (
        fingerprints
    ):
        return None
    cog = root / entry["output"]["path"]
    tiles = root / entry["tiles"]["path"]
    if not cog.is_file() or not tiles.is_dir():
        return None
    if warp_raster.sha256_file(cog) != (
        entry["output"]["sha256"],
        entry["output"]["byte_count"],
    ):
        return None
    if warp_raster.pyramid_digest(tiles) != (
        entry["tiles"]["digest"],
        entry["tiles"]["tiles"],
        entry["tiles"]["bytes"],
    ):
        return None
    return entry


def notes() -> dict:
    return {
        "inspection": "automated only; no human source review or map review is asserted here",
        "human_acceptance": "deferred to the acceptance tracker (issue #38)",
        "registration": (
            "offsets_vs_reference are phase-correlation machine checks of each added edition "
            f"against {REFERENCE_EDITION_ID} over dispersed patches of shared linework; a "
            "patch without a distinct correlation peak gives no offset. No feature is named "
            "or surveyed, and no offset was corrected."
        ),
        "zoom": (
            "each edition is warped onto the XYZ grid of its native_max_zoom and tiled from "
            "tile_zoom.min up to it only; a camera zoom above it overzooms that level"
        ),
        "active_editions": (
            "the four live editions are not reprocessed here; make demo-rasters owns "
            "build/tiles/demo"
        ),
        "published": "nothing in build/expansion is published",
    }


def run_rasters(
    manifest_path: Path,
    schema_path: Path,
    index_path: Path,
    receipts_path: Path,
    sources_path: Path,
    raw_root: Path,
    catalog_path: Path,
    ledger_path: Path,
    expansion_root: Path,
    zoom_cap: int | None = None,
) -> dict:
    """Check the version-2 manifest, then warp and tile each added edition."""
    checked = demo.run_check(
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
    if manifest["version"] != 2:
        demo.fail("expansion-rasters builds only the version-2 nine-edition manifest.")
    try:
        versions = warp_raster.require_gdal()
    except WarpError as exc:
        demo.fail(str(exc))
    record_path = expansion_root / RECORD_NAME
    previous = demo.read_json(record_path) if record_path.is_file() else {"editions": []}
    known = {entry["id"]: entry for entry in previous.get("editions", [])}

    reference = manifest["editions"][manifest["edition_order"].index(REFERENCE_EDITION_ID)]
    with warp_raster.open_source(resolved[REFERENCE_EDITION_ID]["path"]) as dataset:
        reference_crs = CRS.from_user_input(dataset.crs)
    reference_report = reports[REFERENCE_EDITION_ID]
    reference_operation = warp_raster.select_operation(
        reference_crs,
        tuple(reference_report["graticule_labels_source_datum"]),
        demo.datum_steps(reference_report["datum_transformation"]["description"]),
    )

    incoming = expansion_root / INCOMING_DIRNAME
    if incoming.exists():
        shutil.rmtree(incoming)
    (incoming / RASTER_DIRNAME).mkdir(parents=True)
    (incoming / TILE_DIRNAME).mkdir(parents=True)
    entries, reused = [], []
    try:
        for edition in added_editions(manifest):
            eid = edition["id"]
            try:
                entries.append(
                    process_edition(
                        edition,
                        manifest,
                        resolved[eid],
                        reports[eid],
                        versions,
                        zoom_cap,
                        known.get(eid),
                        expansion_root,
                        incoming,
                        (
                            resolved[REFERENCE_EDITION_ID]["path"],
                            reference_operation,
                            resolved[REFERENCE_EDITION_ID]["record"]["sha256"],
                        ),
                        reused,
                    )
                )
            except WarpError as exc:
                demo.fail(f"{eid}: {exc}")
        for edition in added_editions(manifest):
            reverify(edition, resolved[edition["id"]], raw_root, expansion_root)
        check_record(resolved[REFERENCE_EDITION_ID]["record"], raw_root)
        # Nothing reaches build/expansion/ until every edition is warped, cut and checked.
        for entry in entries:
            staged_cog = incoming / entry["output"]["path"]
            staged_tiles = incoming / entry["tiles"]["path"]
            if staged_cog.is_file():
                (expansion_root / RASTER_DIRNAME).mkdir(parents=True, exist_ok=True)
                os.replace(staged_cog, expansion_root / entry["output"]["path"])
            if staged_tiles.is_dir():
                (expansion_root / TILE_DIRNAME).mkdir(parents=True, exist_ok=True)
                shutil.rmtree(expansion_root / entry["tiles"]["path"], ignore_errors=True)
                os.replace(staged_tiles, expansion_root / entry["tiles"]["path"])
    finally:
        shutil.rmtree(incoming, ignore_errors=True)

    expected = {entry["id"] for entry in entries}
    for dirname, suffix in ((TILE_DIRNAME, ""), (RASTER_DIRNAME, ".tif")):
        unexpected = sorted(
            path.name
            for path in (expansion_root / dirname).iterdir()
            if path.name.removesuffix(suffix) not in expected
        )
        if unexpected:
            demo.fail(f"{expansion_root / dirname} holds unexpected entries {unexpected}")
    payload = {
        "version": 1,
        "processing_version": warp_raster.PROCESSING_VERSION,
        "tiling_version": warp_raster.TILING_VERSION,
        "area_id": manifest["area_id"],
        "manifest_version": manifest["version"],
        "edition_order": list(manifest["edition_order"]),
        "initial_edition": manifest["initial_edition"],
        "added_editions": [entry["id"] for entry in entries],
        "active_editions": list(demo.EDITION_ORDER),
        "view_bounds_wgs84": list(manifest["view_bounds_wgs84"]),
        "tile_zoom": manifest["tile_zoom"],
        "zoom_cap": zoom_cap,
        "reference_edition": {
            "id": reference["id"],
            "source_id": reference["source_id"],
            "sha256": resolved[REFERENCE_EDITION_ID]["record"]["sha256"],
            "datum_transformation": {
                key: reference_operation[key] for key in ("description", "accuracy_metres")
            },
        },
        "tool_versions": versions,
        "tiles": {
            "scheme": warp_raster.TILE_SCHEME,
            "format": warp_raster.TILE_FORMAT,
            "tile_size": warp_raster.TILE_SIZE,
            "png_options": warp_raster.PNG_OPTIONS,
            "root": TILE_DIRNAME,
            "template": TILE_TEMPLATE,
            "totals": {
                "tiles": sum(entry["tiles"]["tiles"] for entry in entries),
                "bytes": sum(entry["tiles"]["bytes"] for entry in entries),
            },
        },
        "editions": entries,
        "notes": notes(),
    }
    demo.write_record(record_path, payload)
    return {"record": payload, "record_path": record_path, "reused": reused}


def process_edition(
    edition: dict,
    manifest: dict,
    resolved: dict,
    report: dict,
    versions: dict,
    zoom_cap: int | None,
    known: dict | None,
    root: Path,
    incoming: Path,
    reference: tuple[Path, dict, str],
    reused: list[str],
) -> dict:
    eid = edition["id"]
    top = (
        edition["native_max_zoom"]
        if zoom_cap is None
        else min(edition["native_max_zoom"], zoom_cap)
    )
    zooms = list(range(manifest["tile_zoom"]["min"], top + 1))
    if not zooms:
        raise WarpError(f"zoom cap {zoom_cap} leaves no zoom at or above tile_zoom.min")
    grid = warp_raster.common_grid(manifest["view_bounds_wgs84"], top)
    resampling = warp_raster.resampling_for(edition["kind"])
    with warp_raster.open_source(resolved["path"]) as dataset:
        src_crs = CRS.from_user_input(dataset.crs)
    operation = warp_raster.select_operation(
        src_crs,
        tuple(report["graticule_labels_source_datum"]),
        demo.datum_steps(report["datum_transformation"]["description"]),
    )
    lineage = source_lineage(edition, resolved, report)
    plan = {
        "processing_version": warp_raster.PROCESSING_VERSION,
        "source": lineage,
        "crop_wgs84": edition["crop_wgs84"],
        "grid": grid,
        "resampling": resampling,
        "source_crs_wkt": report["crs_wkt"],
        "datum_transformation": operation,
        "tool_versions": versions,
        # The registration check is part of the record, so its inputs decide reuse too.
        "registration_check": {
            "reference_sha256": reference[2],
            "reference_pipeline": reference[1]["pipeline"],
            "patch_metres": warp_raster.PATCH_METRES,
            "distinct_peak_ratio": warp_raster.DISTINCT_PEAK_RATIO,
            "peak_neighbourhood_px": warp_raster.PEAK_NEIGHBOURHOOD_PX,
            "points": patch_points(shape(edition["crop_wgs84"])),
        },
    }
    fingerprint = warp_raster.fingerprint(plan)
    entry = {
        "id": eid,
        "source_kind": edition["source_kind"],
        "kind": edition["kind"],
        "sheet_name": edition["sheet_name"],
        "scale": edition["scale"],
        "source": lineage,
        "resampling": resampling,
        "source_crs_wkt": report["crs_wkt"],
        "source_datum": report["datum"],
        "source_projection": report["projection"],
        "index_crs": report.get("index_crs"),
        "datum_transformation": operation,
        "crop_wgs84": edition["crop_wgs84"],
        "view_coverage_fraction": report["view_coverage_fraction"],
        "zoom": {
            "min": zooms[0],
            "max": top,
            "native_max_zoom": edition["native_max_zoom"],
            "native_resolution_metres": edition["native_resolution_metres"],
            "overzoom_above": top,
        },
        "grid": grid,
        "fingerprint": fingerprint,
    }
    staged_cog = incoming / RASTER_DIRNAME / f"{eid}.tif"
    prior_output = known.get("output") if known else None
    tile_fingerprint = None
    if prior_output is not None:
        tile_fingerprint = warp_raster.fingerprint(
            demo.tile_plan({**entry, "output": prior_output}, grid, zooms, versions)
        )
    prior = reusable(known, (fingerprint, tile_fingerprint), root)
    if prior is not None:
        reused.append(eid)
        return prior
    warped, pinned = warp_edition(
        edition, resolved["path"], report, grid, operation, resampling, staged_cog
    )
    entry.update(warped)
    reference_path, reference_operation, _ = reference
    with (
        warp_raster.open_source(reference_path) as base,
        warp_raster.open_source(resolved["path"]) as dataset,
    ):
        offsets = warp_raster.patch_offsets(
            base,
            reference_operation["pipeline"],
            dataset,
            operation["pipeline"],
            patch_points(shape(edition["crop_wgs84"])),
            grid["resolution_metres"],
        )
    entry["registration"] = registration(report, pinned, offsets, operation)
    tile_fingerprint = warp_raster.fingerprint(demo.tile_plan(entry, grid, zooms, versions))
    tiles = cut_tiles(entry, staged_cog, grid, zooms, incoming / TILE_DIRNAME / eid)
    entry["tiles"] = {**tiles, "fingerprint": tile_fingerprint}
    return entry


@click.group()
def cli() -> None:
    """Staged nine-edition expansion tools (#57)."""


@cli.command()
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path),
    default=demo.EXPANDED_MANIFEST_PATH,
)
@click.option(
    "--schema", "schema_path", type=click.Path(path_type=Path), default=demo.SCHEMA_PATH
)
@click.option("--index", "index_path", type=click.Path(path_type=Path), default=demo.INDEX_PATH)
@click.option(
    "--receipts", "receipts_path", type=click.Path(path_type=Path), default=demo.RECEIPTS_PATH
)
@click.option(
    "--sources", "sources_path", type=click.Path(path_type=Path), default=demo.SOURCES_PATH
)
@click.option(
    "--raw-root",
    "raw_root",
    type=click.Path(path_type=Path),
    envvar="DEMO_RAW_ROOT",
    default=demo.RAW_ROOT,
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(path_type=Path),
    default=demo_sources.CATALOG_PATH,
)
@click.option(
    "--ledger", "ledger_path", type=click.Path(path_type=Path), default=demo_sources.LEDGER_PATH
)
@click.option(
    "--expansion-root",
    "expansion_root",
    type=click.Path(path_type=Path),
    default=demo.EXPANSION_ROOT,
)
@click.option(
    "--zoom-cap",
    "zoom_cap",
    type=click.IntRange(0, 24),
    default=None,
    help="Tile no edition above this zoom. For tests; the cap is recorded with the output.",
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
    zoom_cap,
) -> None:
    """Warp and tile the five added editions into build/expansion/ (never build/public)."""
    started = time.monotonic()
    result = run_rasters(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        catalog_path,
        ledger_path,
        expansion_root,
        zoom_cap,
    )
    record = result["record"]
    for entry in record["editions"]:
        state = "reused" if entry["id"] in result["reused"] else "cut"
        tiles = entry["tiles"]
        levels = ", ".join(f"z{level['zoom']}:{level['tiles']}" for level in tiles["levels"])
        distinct = entry["registration"]["distinct_offsets"]
        click.echo(
            f"{entry['id']}: {state} {entry['resampling']} zoom {entry['zoom']['min']}-"
            f"{entry['zoom']['max']} ({levels}) {tiles['tiles']} tiles, "
            f"{tiles['bytes']} bytes; "
            f"COG {entry['output']['byte_count']} bytes; {distinct}/"
            f"{len(entry['registration']['offsets_vs_reference'])} distinct offsets"
        )
    totals = record["tiles"]["totals"]
    click.echo(
        f"expansion-rasters: {len(record['editions'])} pyramids, {totals['tiles']} tiles, "
        f"{totals['bytes']} bytes; {time.monotonic() - started:.1f} s; record "
        f"{result['record_path'].name}"
    )


if __name__ == "__main__":
    cli()
