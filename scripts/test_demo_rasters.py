"""D2a and D2b: the COG preparation and XYZ tiling stages, on synthetic scans only.

The four-edition fixture tree comes from test_demo.py so both stages are checked against
the same synthetic sources. Nothing here reads data/raw/ or the committed receipt ledger.
"""

import hashlib
import json

import click
import demo
import numpy as np
import pytest
import rasterio
import test_demo
import warp_raster
from click.testing import CliRunner
from pyproj import CRS, Transformer
from rasterio.transform import Affine
from shapely.geometry import Point
from warp_raster import WarpError

# The full-resolution grid is zoom 16; these run at zoom 12 so a warp costs a second.
TEST_ZOOM = 12
# The committed view bounds, so a hand-built grid here is the one the demo really uses.
VIEW_BOUNDS = [-121.126028, 38.874881, -121.001023, 38.99988]

scans = test_demo.scans
tree = test_demo.tree


def run_cogs(tree, build_root, *args):
    return _invoke(tree, build_root, "cogs", args)


def run_rasters(tree, build_root, *args):
    return _invoke(tree, build_root, "rasters", args)


def _invoke(tree, build_root, command, args):
    return CliRunner().invoke(
        demo.cli,
        [
            command,
            "--manifest",
            str(tree.manifest_path),
            "--schema",
            str(demo.SCHEMA_PATH),
            "--index",
            str(tree.index_path),
            "--receipts",
            str(tree.receipts_path),
            "--sources",
            str(tree.sources_path),
            "--raw-root",
            str(tree.raw_root),
            "--build-root",
            str(build_root),
            "--grid-zoom",
            str(TEST_ZOOM),
            *args,
        ],
    )


def record_of(build_root):
    path = build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def cog_paths(build_root):
    return sorted((build_root / demo.RASTER_DIRNAME).glob("*.tif"))


def tiny_raster(path, *, crs, value=255, size=32, bands=1, centre=(-121.06, 38.94)):
    """A uniform patch inside the Auburn quadrangle, small enough that a warp is instant."""
    if crs is None:
        transform = Affine(10.0, 0.0, 0.0, 0.0, -10.0, 10.0 * size)
    else:
        x, y = Transformer.from_crs(4326, crs, always_xy=True).transform(*centre)
        transform = Affine(10.0, 0.0, x - 5.0 * size, 0.0, -10.0, y + 5.0 * size)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=bands,
        dtype="uint8",
        crs=crs,
        transform=transform,
    ) as dataset:
        for index in range(bands):
            dataset.write(np.full((size, size), value, "uint8"), index + 1)
    return path


def tree_digests(tree):
    """Every raw byte and every receipt byte, so a warp can be shown not to touch them."""
    digests = {}
    for path in sorted(tree.raw_root.rglob("*")) + [tree.receipts_path]:
        if path.is_file():
            digests[str(path)] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
    return digests


# --- tool prerequisites ----------------------------------------------------------------


def test_require_gdal_reports_the_versions_actually_loaded():
    versions = warp_raster.require_gdal()
    assert versions["gdal"] == rasterio.__gdal_version__
    assert versions["proj_gdal"] == rasterio.__proj_version__
    # pyproj selects the datum operation and GDAL applies it, so both builds are recorded.
    assert versions["proj_pyproj"]
    assert "gdalwarp" in versions["gdal_provider"]


def test_missing_cog_driver_fails_with_an_installation_message(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("COG driver not available")

    monkeypatch.setattr(warp_raster.rasterio.shutil, "copy", refuse)
    with pytest.raises(WarpError, match="cannot write a COG"):
        warp_raster.require_gdal()


# --- resampling dispatch ---------------------------------------------------------------


def test_resampling_follows_the_source_kind():
    assert warp_raster.resampling_for("topo") == "nearest"
    assert warp_raster.resampling_for("orthophotoquad") == "cubic"


def test_unknown_source_kind_has_no_resampling_rule():
    with pytest.raises(WarpError, match="No resampling rule"):
        warp_raster.resampling_for("aerial-frame")


def test_each_edition_gets_the_resampling_its_kind_requires(tree, tmp_path):
    result = run_cogs(tree, tmp_path / "build")
    assert result.exit_code == 0, result.output
    by_id = {entry["id"]: entry for entry in record_of(tmp_path / "build")["editions"]}
    assert by_id["auburn-1975"]["resampling"] == "cubic"
    for eid in ("auburn-1953", "auburn-1973", "auburn-1981"):
        assert by_id[eid]["resampling"] == "nearest"


# --- datum and CRS handling ------------------------------------------------------------


def test_the_warp_uses_the_datum_operation_demo_check_recorded(scans):
    paths, reports = scans
    report = reports["auburn-1953"]
    with rasterio.open(paths["auburn-1953"]) as dataset:
        src_crs = CRS.from_user_input(dataset.crs)
    steps = demo.datum_steps(report["datum_transformation"]["description"])
    assert steps, "the fixture scans are on NAD27, so a datum step must be named"
    operation = warp_raster.select_operation(
        src_crs, tuple(report["graticule_labels_source_datum"]), steps
    )
    for step in steps:
        assert step in operation["description"]
    assert operation["pipeline"].startswith("+proj=pipeline")
    assert operation["accuracy_metres"] > 0


def test_a_different_datum_operation_is_refused(scans):
    paths, reports = scans
    with rasterio.open(paths["auburn-1953"]) as dataset:
        src_crs = CRS.from_user_input(dataset.crs)
    seed = tuple(reports["auburn-1953"]["graticule_labels_source_datum"])
    with pytest.raises(WarpError, match="omits the datum step"):
        warp_raster.select_operation(src_crs, seed, ["NAD27 to WGS 84 (99)"])


def test_a_source_without_a_crs_is_refused(tmp_path):
    path = tiny_raster(tmp_path / "nocrs.tif", crs=None)
    with pytest.raises(WarpError, match="no CRS"):
        warp_raster.open_source(path)


def test_a_crs_without_a_datum_is_refused():
    engineering = CRS.from_user_input(
        'LOCAL_CS["scanner",UNIT["metre",1],AXIS["X",EAST],AXIS["Y",NORTH]]'
    )
    with pytest.raises(WarpError, match="no datum"):
        warp_raster.select_operation(engineering, (-121.2, 38.8, -121.0, 39.0), [])


def test_an_unreadable_file_is_refused(tmp_path):
    path = tmp_path / "broken.tif"
    path.write_bytes(b"II*\x00 not a tiff")
    with pytest.raises(WarpError, match="Cannot read source raster"):
        warp_raster.open_source(path)


def test_a_pipeline_gdal_ignores_is_caught(monkeypatch, scans):
    """If GDAL ever stops honouring COORDINATE_OPERATION the warp must stop, not drift."""
    paths, reports = scans
    with rasterio.open(paths["auburn-1953"]) as dataset:
        honest = warp_raster.select_operation(
            CRS.from_user_input(dataset.crs),
            tuple(reports["auburn-1953"]["graticule_labels_source_datum"]),
            [],
        )["pipeline"]
        shifted = honest.replace("+x=-8 +y=159 +z=175", "+x=0 +y=0 +z=0")
        assert shifted != honest
        real = warp_raster.calculate_default_transform

        def ignore_the_option(*args, **kwargs):
            kwargs.pop("COORDINATE_OPERATION", None)
            return real(*args, **kwargs)

        monkeypatch.setattr(warp_raster, "calculate_default_transform", ignore_the_option)
        with pytest.raises(WarpError, match="did not honour COORDINATE_OPERATION"):
            warp_raster.verify_pipeline(dataset, shifted)


# --- the shared grid -------------------------------------------------------------------


def test_the_grid_is_whole_tiles_of_the_xyz_pyramid():
    bounds = [-121.126028, 38.874881, -121.001023, 38.99988]
    grid = warp_raster.common_grid(bounds, 16)
    assert grid["crs"] == "EPSG:3857"
    assert grid["width"] % warp_raster.TILE_SIZE == 0
    assert grid["height"] % warp_raster.TILE_SIZE == 0
    tiles = grid["tile_range"]
    assert grid["width"] == (tiles["x_max"] - tiles["x_min"] + 1) * warp_raster.TILE_SIZE
    assert grid["height"] == (tiles["y_max"] - tiles["y_min"] + 1) * warp_raster.TILE_SIZE
    world = 2 * warp_raster._mercator_origin()
    assert grid["resolution_metres"] == pytest.approx(world / (warp_raster.TILE_SIZE * 2**16))
    left, bottom, right, top = grid["bounds"]
    assert right - left == pytest.approx(grid["width"] * grid["resolution_metres"])
    assert top - bottom == pytest.approx(grid["height"] * grid["resolution_metres"])


def test_the_grid_covers_the_declared_view_bounds():
    bounds = [-121.126028, 38.874881, -121.001023, 38.99988]
    grid = warp_raster.common_grid(bounds, 14)
    forward = Transformer.from_crs(4326, 3857, always_xy=True)
    x_min, y_min = forward.transform(bounds[0], bounds[1])
    x_max, y_max = forward.transform(bounds[2], bounds[3])
    left, bottom, right, top = grid["bounds"]
    assert left <= x_min and right >= x_max
    assert bottom <= y_min and top >= y_max


def test_inverted_view_bounds_are_refused():
    with pytest.raises(WarpError, match="inverted or empty"):
        warp_raster.common_grid([-121.0, 39.0, -121.2, 38.8], 12)


def test_every_edition_lands_on_the_same_grid(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    record = record_of(build_root)
    grid = record["grid"]
    assert grid["zoom"] == TEST_ZOOM
    seen = set()
    for path in cog_paths(build_root):
        with rasterio.open(path) as dataset:
            seen.add(
                (
                    dataset.crs.to_string(),
                    tuple(dataset.transform)[:6],
                    dataset.width,
                    dataset.height,
                )
            )
    assert len(seen) == 1, seen
    only = seen.pop()
    assert only[1] == tuple(Affine(*grid["transform"]))[:6]
    assert (only[2], only[3]) == (grid["width"], grid["height"])


def test_a_zoom_outside_the_manifest_range_is_refused(tree, tmp_path):
    result = run_cogs(tree, tmp_path / "build", "--grid-zoom", "18")
    assert result.exit_code != 0
    assert "outside the manifest" in result.output


# --- mask and alpha --------------------------------------------------------------------


def test_the_mask_comes_from_geometry_and_keeps_white_pixels(tmp_path):
    """A white-pixel rule would delete legitimate white map content (AGENTS.md §2.1)."""
    grid = warp_raster.common_grid([-121.126028, 38.874881, -121.001023, 38.99988], 10)
    inner = {
        "type": "Polygon",
        "coordinates": [
            [
                [-121.10, 38.90],
                [-121.02, 38.90],
                [-121.02, 38.98],
                [-121.10, 38.98],
                [-121.10, 38.90],
            ]
        ],
    }
    mask = warp_raster.crop_mask(inner, grid)
    assert set(np.unique(mask)) <= {0, 255}
    assert mask.any() and not mask.all()
    white = np.full(mask.shape, 255, "uint8")
    assert white[mask > 0].min() == 255


def test_an_empty_crop_is_refused():
    grid = warp_raster.common_grid([-121.126028, 38.874881, -121.001023, 38.99988], 12)
    elsewhere = {
        "type": "Polygon",
        "coordinates": [[[10.0, 10.0], [10.1, 10.0], [10.1, 10.1], [10.0, 10.1], [10.0, 10.0]]],
    }
    with pytest.raises(WarpError, match="does not intersect the shared grid"):
        warp_raster.crop_mask(elsewhere, grid)


def test_outputs_carry_an_alpha_band_and_no_colour_keying(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    for path in cog_paths(build_root):
        with rasterio.open(path) as dataset:
            assert dataset.colorinterp[-1] == rasterio.enums.ColorInterp.alpha
            assert dataset.nodata is None
            alpha = dataset.read(dataset.count)
            inside = alpha > 0
            assert set(np.unique(alpha)) == {0, 255}
            assert inside.any() and not inside.all()
            # The fixture's map face is pure white; every one of those pixels survives.
            face = dataset.read(1)
            assert (face[inside] == 255).sum() > 0
            assert face[~inside].max() == 0


def test_white_map_content_is_not_made_transparent(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    with rasterio.open(build_root / demo.RASTER_DIRNAME / "auburn-1953.tif") as dataset:
        face = dataset.read(1)
        alpha = dataset.read(dataset.count)
    white = face == 255
    assert white.sum() > 0
    assert alpha[white].min() == 255


# --- the processing record -------------------------------------------------------------


def test_the_record_holds_versions_hashes_transform_crop_and_digests(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    record = record_of(build_root)
    assert record["tool_versions"]["gdal"] == rasterio.__gdal_version__
    assert record["tool_versions"]["proj_gdal"] == rasterio.__proj_version__
    assert record["tool_versions"]["proj_pyproj"]
    assert record["grid"]["transform"]
    assert [entry["id"] for entry in record["editions"]] == tree.manifest["edition_order"]
    assert tree.manifest["edition_order"] == demo.contract_for(tree.manifest)["order"]
    manifest_crops = {e["id"]: e["crop_wgs84"] for e in tree.manifest["editions"]}
    for entry in record["editions"]:
        output = build_root / demo.RASTER_DIRNAME / f"{entry['id']}.tif"
        digest, byte_count = warp_raster.sha256_file(output)
        assert (digest, byte_count) == (
            entry["output"]["sha256"],
            entry["output"]["byte_count"],
        )
        assert entry["crop_wgs84"] == manifest_crops[entry["id"]]
        assert entry["datum_transformation"]["pipeline"].startswith("+proj=pipeline")
        assert entry["source_crs_wkt"].startswith("PROJCRS")
        assert entry["registration"]["neatline_residual_px"] >= 0
        assert entry["output"]["nodata_representation"].startswith("alpha band")


def test_each_cog_links_to_exactly_one_selected_source(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    record = record_of(build_root)
    selected = {e["source_id"]: e["id"] for e in tree.manifest["editions"]}
    seen = {}
    for entry in record["editions"]:
        source = entry["source"]
        assert selected[source["source_id"]] == entry["id"]
        raw = tree.raw_root / source["raw_path"]
        assert warp_raster.sha256_file(raw) == (source["sha256"], source["byte_count"])
        seen[source["source_id"]] = entry["id"]
    assert len(seen) == len(record["editions"]) == 4


def test_the_record_states_what_registration_evidence_exists(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    notes = record_of(build_root)["registration_notes"]
    assert "automated only" in notes["inspection"]
    assert "#38" in notes["human_acceptance"]
    assert "none available" in notes["independent_ground_control"]
    offsets = {row["edition_id"]: row for row in notes["unresolved_systematic_offsets"]}
    assert set(offsets) == set(demo.EDITION_ORDER)
    for row in offsets.values():
        assert row["drawn_neatline_off_labelled_graticule_metres"] >= 0
        assert row["datum_transformation_accuracy_metres"] > 0


# --- reruns ----------------------------------------------------------------------------


def test_a_rerun_reuses_every_output_and_rewrites_an_identical_record(tree, tmp_path):
    build_root = tmp_path / "build"
    first = run_cogs(tree, build_root)
    assert first.exit_code == 0, first.output
    assert "warped" in first.output
    record_path = build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME
    before = record_path.read_bytes()
    stamps = {p: p.stat().st_mtime_ns for p in cog_paths(build_root)}
    second = run_cogs(tree, build_root)
    assert second.exit_code == 0, second.output
    assert "warped" not in second.output
    assert second.output.count("reused") == 4
    assert record_path.read_bytes() == before
    assert {p: p.stat().st_mtime_ns for p in cog_paths(build_root)} == stamps


def test_a_deleted_output_is_warped_again(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    (build_root / demo.RASTER_DIRNAME / "auburn-1973.tif").unlink()
    result = run_cogs(tree, build_root)
    assert result.exit_code == 0, result.output
    assert "auburn-1973: warped" in result.output
    assert "auburn-1953: reused" in result.output


def test_an_output_whose_bytes_changed_is_warped_again(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    target = build_root / demo.RASTER_DIRNAME / "auburn-1981.tif"
    target.write_bytes(target.read_bytes()[:-64])
    result = run_cogs(tree, build_root)
    assert result.exit_code == 0, result.output
    assert "auburn-1981: warped" in result.output
    with rasterio.open(target) as dataset:
        assert dataset.count == 2


def test_a_changed_grid_warps_everything_again(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    result = run_cogs(tree, build_root, "--grid-zoom", str(TEST_ZOOM - 1))
    assert result.exit_code == 0, result.output
    assert result.output.count("warped") == 4


# --- nothing is published by a run that did not finish ---------------------------------


def test_a_failure_part_way_through_publishes_nothing(tree, tmp_path, monkeypatch):
    build_root = tmp_path / "build"
    real = warp_raster.write_cog
    calls = []

    def fail_on_the_third(path, *args, **kwargs):
        calls.append(path.name)
        if len(calls) == 3:
            raise WarpError("disk full")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(warp_raster, "write_cog", fail_on_the_third)
    result = run_cogs(tree, build_root)
    assert result.exit_code != 0
    assert "disk full" in result.output
    assert cog_paths(build_root) == []
    assert not (build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME).exists()
    assert not (build_root / demo.RASTER_DIRNAME / demo.INCOMING_DIRNAME).exists()


def test_a_failed_post_warp_source_recheck_leaves_the_published_run_intact(
    tree, tmp_path, monkeypatch
):
    build_root = tmp_path / "build"
    assert run_cogs(tree, build_root).exit_code == 0
    published = {path: path.read_bytes() for path in cog_paths(build_root)}
    record_bytes = (build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME).read_bytes()

    real_run_check = demo.run_check

    def refuse_after_the_warp(*args, **kwargs):
        checked = real_run_check(*args, **kwargs)

        def refuse(record, root):
            raise click.ClickException("Checksum mismatch; left unchanged")

        monkeypatch.setattr(demo, "check_record", refuse)
        return checked

    monkeypatch.setattr(demo, "run_check", refuse_after_the_warp)
    # A different grid forces all four warps, so all four would have been promoted.
    result = run_cogs(tree, build_root, "--grid-zoom", str(TEST_ZOOM - 1))
    assert result.exit_code != 0
    assert {path: path.read_bytes() for path in cog_paths(build_root)} == published
    assert (
        build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME
    ).read_bytes() == record_bytes
    assert not (build_root / demo.RASTER_DIRNAME / demo.INCOMING_DIRNAME).exists()


def test_a_corrupt_source_stops_the_run_before_anything_is_written(tree, tmp_path):
    scan = tree.raw_root / "topo" / "CA_Auburn_288103_1953_24000_geo.tif"
    # The tree hard-links the session fixture, so replace the link instead of writing to it.
    truncated = scan.read_bytes()[:-2048]
    scan.unlink()
    scan.write_bytes(truncated)
    build_root = tmp_path / "build"
    result = run_cogs(tree, build_root)
    assert result.exit_code != 0
    assert "Checksum mismatch" in str(result.exception) + result.output
    assert cog_paths(build_root) == []


def test_a_source_that_is_not_a_raster_stops_the_run(tree, tmp_path):
    scan = tree.raw_root / "topo" / "CA_Auburn_288101_1953_24000_geo.tif"
    scan.unlink()
    scan.write_bytes(b"II*\x00 not a tiff")
    records = []
    for eid in demo.EDITION_ORDER:
        topo_id = demo.EXPECTED_EDITIONS[eid]["source_id"]
        path = tree.raw_root / "topo" / f"{topo_id}_geo.tif"
        records.append(test_demo.receipt(topo_id, path, tree.raw_root))
    tree.write_receipts(records)
    build_root = tmp_path / "build"
    result = run_cogs(tree, build_root)
    assert result.exit_code != 0
    assert cog_paths(build_root) == []


def test_a_missing_source_stops_the_run(tree, tmp_path):
    (tree.raw_root / "topo" / "CA_Auburn_288104_1975_24000_geo.tif").unlink()
    build_root = tmp_path / "build"
    result = run_cogs(tree, build_root)
    assert result.exit_code != 0
    assert "missing" in str(result.exception) + result.output
    assert cog_paths(build_root) == []


def test_write_cog_leaves_no_partial_file_or_staging_directory(tmp_path, monkeypatch):
    target = tmp_path / "out.tif"
    grid = warp_raster.common_grid([-121.126028, 38.874881, -121.001023, 38.99988], 10)
    data = np.zeros((1, grid["height"], grid["width"]), "uint8")
    alpha = np.full((grid["height"], grid["width"]), 255, "uint8")

    def refuse(*args, **kwargs):
        raise RuntimeError("no space left on device")

    monkeypatch.setattr(warp_raster.rasterio.shutil, "copy", refuse)
    with pytest.raises(RuntimeError):
        warp_raster.write_cog(target, data, alpha, grid, "nearest")
    assert not target.exists()
    assert list(tmp_path.glob(".staging-*")) == []


# --- the sources are left exactly as they were -----------------------------------------


def test_a_run_changes_no_raw_byte_and_no_receipt(tree, tmp_path):
    before = tree_digests(tree)
    result = run_cogs(tree, tmp_path / "build")
    assert result.exit_code == 0, result.output
    assert tree_digests(tree) == before


def test_a_run_writes_only_inside_the_build_root(tree, tmp_path):
    build_root = tmp_path / "build"
    watched = [tree.manifest_path, tree.index_path, tree.sources_path, tree.receipts_path]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}
    assert run_cogs(tree, build_root).exit_code == 0
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched} == before
    assert {p.name for p in (build_root / demo.RASTER_DIRNAME).iterdir()} == {
        demo.PROCESSING_FILENAME,
        *(f"{eid}.tif" for eid in demo.EDITION_ORDER),
    }


# --- the fingerprint ------------------------------------------------------------------


def test_the_fingerprint_changes_with_any_recorded_input():
    base = {"a": 1, "b": {"c": [1, 2]}}
    assert warp_raster.fingerprint(base) == warp_raster.fingerprint(
        {"b": {"c": [1, 2]}, "a": 1}
    )
    assert warp_raster.fingerprint(base) != warp_raster.fingerprint(
        {"a": 1, "b": {"c": [1, 3]}}
    )


def test_datum_steps_drops_axis_reordering_and_keeps_the_shift():
    assert demo.datum_steps(
        "axis order change (2D) + NAD27 to WGS 84 (6) + axis order change (2D)"
    ) == ["NAD27 to WGS 84 (6)"]
    assert demo.datum_steps("none (source is already WGS84)") == []


def test_a_white_patch_stays_white_through_the_datum_shift(tmp_path):
    """The warp invents nothing: a uniform white source stays white where it lands."""
    path = tiny_raster(
        tmp_path / "patch.tif", crs=CRS.from_wkt(test_demo.POLYCONIC_WKT), value=255
    )
    grid = warp_raster.common_grid([-121.126028, 38.874881, -121.001023, 38.99988], 14)
    with warp_raster.open_source(path) as dataset:
        operation = warp_raster.select_operation(
            CRS.from_user_input(dataset.crs), (-121.2, 38.8, -121.0, 39.0), ["NAD27 to WGS 84"]
        )
        data, coverage = warp_raster.warp(dataset, grid, "nearest", operation["pipeline"])
    assert coverage.any()
    assert set(np.unique(data[0][coverage > 0])) == {255}


# === D2b: the bounded XYZ PNG pyramid ==================================================


def synthetic_cog(path, grid, *, north=255, south=100, margin=64):
    """A COG on the shared grid whose north half differs from its south half.

    A pyramid written with TMS y, or with a mirrored window, puts the southern value in the
    northern tile, which no uniform fixture could reveal.
    """
    height, width = grid["height"], grid["width"]
    data = np.full((1, height, width), south, "uint8")
    data[0, : height // 2] = north
    alpha = np.zeros((height, width), "uint8")
    alpha[margin : height - margin, margin : width - margin] = 255
    data[:, alpha == 0] = 0
    warp_raster.write_cog(path, data, alpha, grid, "nearest")
    return path


def tile_path(root, zoom, x, y):
    return root / str(zoom) / str(x) / f"{y}.png"


def read_tile(root, zoom, x, y):
    with rasterio.open(tile_path(root, zoom, x, y)) as dataset:
        return dataset.read()


def tiles_record(build_root):
    return record_of(build_root)["tiles"]


def published_tiles(build_root):
    root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.png"))


# --- the XYZ convention ----------------------------------------------------------------


def test_tile_numbering_is_xyz_and_not_tms():
    assert warp_raster.tile_xy(-179.0, 85.0, 1) == (0, 0)
    assert warp_raster.tile_xy(1.0, -1.0, 1) == (1, 1)
    north = warp_raster.tile_xy(-121.06, 38.99, 14)
    south = warp_raster.tile_xy(-121.06, 38.88, 14)
    # TMS counts y up from the south; XYZ counts it down from the north.
    assert north[1] < south[1]
    assert north[0] == south[0]


def test_the_tile_pixel_of_a_coordinate_is_inside_its_tile():
    located = warp_raster.tile_pixel(-121.06, 38.94, 16)
    assert (located["x"], located["y"]) == warp_raster.tile_xy(-121.06, 38.94, 16)
    assert 0 <= located["column"] < warp_raster.TILE_SIZE
    assert 0 <= located["row"] < warp_raster.TILE_SIZE


def test_the_tile_range_matches_the_grid_and_halves_each_level():
    grid = warp_raster.common_grid(VIEW_BOUNDS, 16)
    assert warp_raster.tile_indices(grid, 16) == grid["tile_range"]
    for zoom in range(10, 16):
        coarse = warp_raster.tile_indices(grid, zoom)
        finer = warp_raster.tile_indices(grid, zoom + 1)
        assert coarse["x_min"] == finer["x_min"] // 2
        assert coarse["y_max"] == finer["y_max"] // 2


def test_a_zoom_finer_than_the_grid_is_refused():
    grid = warp_raster.common_grid(VIEW_BOUNDS, 12)
    with pytest.raises(WarpError, match="finer than the grid"):
        warp_raster.tile_indices(grid, 13)


def test_the_tile_window_is_whole_pixels_of_the_shared_grid():
    grid = warp_raster.common_grid(VIEW_BOUNDS, 14)
    extent = grid["tile_range"]
    top_left = warp_raster.tile_window(grid, 14, extent["x_min"], extent["y_min"])
    assert (top_left.col_off, top_left.row_off) == (0, 0)
    assert (top_left.width, top_left.height) == (warp_raster.TILE_SIZE,) * 2
    coarse = warp_raster.tile_window(grid, 12, extent["x_min"] // 4, extent["y_min"] // 4)
    assert coarse.width == coarse.height == warp_raster.TILE_SIZE * 4
    assert float(coarse.col_off).is_integer() and float(coarse.row_off).is_integer()


# --- the tiles themselves --------------------------------------------------------------


def test_the_top_zoom_tile_is_a_block_copy_of_the_cog(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    extent = grid["tile_range"]
    with rasterio.open(cog) as dataset:
        block = dataset.read(window=warp_raster.Window(0, 0, 256, 256))
    assert np.array_equal(read_tile(out, TEST_ZOOM, extent["x_min"], extent["y_min"]), block)


def test_the_northern_tile_holds_the_northern_half_of_the_cog(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid, north=255, south=100)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    extent = grid["tile_range"]
    top = read_tile(out, TEST_ZOOM, extent["x_min"], extent["y_min"])
    bottom = read_tile(out, TEST_ZOOM, extent["x_min"], extent["y_max"])
    assert set(np.unique(top[0][top[1] > 0])) == {255}
    assert set(np.unique(bottom[0][bottom[1] > 0])) == {100}


def test_tiles_are_png_with_an_alpha_band(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    extent = grid["tile_range"]
    with rasterio.open(tile_path(out, TEST_ZOOM, extent["x_min"], extent["y_min"])) as tile:
        assert tile.driver == "PNG"
        assert tile.count == 2
        assert tile.colorinterp[-1] == rasterio.enums.ColorInterp.alpha
        assert (tile.width, tile.height) == (warp_raster.TILE_SIZE,) * 2
    # PAM sidecars would make the pyramid's file set unstable.
    assert list(out.rglob("*.aux.xml")) == []


def test_empty_parts_of_the_footprint_get_fully_transparent_tiles(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    height, width = grid["height"], grid["width"]
    data = np.zeros((1, height, width), "uint8")
    alpha = np.zeros((height, width), "uint8")
    # Only the first tile of the grid carries data; the rest of the pyramid is empty.
    data[0, :256, :256] = 200
    alpha[:256, :256] = 255
    cog = tmp_path / "corner.tif"
    warp_raster.write_cog(cog, data, alpha, grid, "nearest")
    out = tmp_path / "tiles"
    cut = warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    extent = grid["tile_range"]
    expected = (extent["x_max"] - extent["x_min"] + 1) * (extent["y_max"] - extent["y_min"] + 1)
    assert cut["tiles"] == expected
    assert cut["transparent_tiles"] == expected - 1
    empty = read_tile(out, TEST_ZOOM, extent["x_max"], extent["y_max"])
    assert empty.shape == (2, 256, 256)
    assert empty.max() == 0


def test_no_tile_is_written_outside_the_bounded_range(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM - 1, TEST_ZOOM], "nearest", out)
    extent = grid["tile_range"]
    assert not tile_path(out, TEST_ZOOM, extent["x_min"], extent["y_min"] - 1).exists()
    assert not tile_path(out, TEST_ZOOM, extent["x_max"] + 1, extent["y_min"]).exists()
    assert sorted(int(p.name) for p in out.iterdir()) == [TEST_ZOOM - 1, TEST_ZOOM]


def test_alpha_stays_two_valued_at_every_zoom_even_under_cubic(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM - 2, TEST_ZOOM - 1, TEST_ZOOM], "cubic", out)
    for path in out.rglob("*.png"):
        with rasterio.open(path) as tile:
            pixels = tile.read()
        assert set(np.unique(pixels[-1])) <= {0, 255}
        # Colour never survives where the tile is transparent.
        assert pixels[0][pixels[-1] == 0].max(initial=0) == 0


def test_each_level_records_its_opaque_and_ink_pixel_counts(tmp_path):
    """The ink count is how much drawn line survives a zoom; the synthetic south half is ink."""
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid, north=255, south=100)
    cut = warp_raster.cut_pyramid(
        cog, grid, [TEST_ZOOM - 1, TEST_ZOOM], "nearest", tmp_path / "tiles"
    )
    with rasterio.open(cog) as dataset:
        pixels = dataset.read()
    opaque = pixels[-1] > 0
    levels = {level["zoom"]: level for level in cut["levels"]}
    assert levels[TEST_ZOOM]["opaque_px"] == int(opaque.sum())
    assert levels[TEST_ZOOM]["ink_px"] == int(
        (opaque & (pixels[0] < warp_raster.INK_THRESHOLD)).sum()
    )
    assert 0 < levels[TEST_ZOOM - 1]["ink_px"] < levels[TEST_ZOOM]["ink_px"]


def test_a_cog_that_is_not_on_the_shared_grid_is_refused(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    other = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM - 1)
    cog = synthetic_cog(tmp_path / "cog.tif", other)
    with pytest.raises(WarpError, match="not the shared grid"):
        warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", tmp_path / "tiles")


def test_a_stray_file_in_a_pyramid_is_reported(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    (out / str(TEST_ZOOM) / "notes.txt").write_text("stray", encoding="utf-8")
    with pytest.raises(WarpError, match="not tiles"):
        warp_raster.pyramid_digest(out)


# --- the sample-point check ------------------------------------------------------------


def sample_pair(grid):
    """Two points inside the synthetic COG's opaque area, one north and one south of centre."""
    left, bottom, right, top = grid["bounds"]
    inverse = Transformer.from_crs(3857, 4326, always_xy=True)
    lon, north_lat = inverse.transform((left + right) / 2, top - 0.25 * (top - bottom))
    _, south_lat = inverse.transform((left + right) / 2, bottom + 0.25 * (top - bottom))
    return {"north": (lon, north_lat), "south": (lon, south_lat)}


def test_the_sample_points_resolve_to_the_tile_holding_their_pixels(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    samples = sample_pair(grid)
    checked = warp_raster.verify_tile_samples(cog, out, grid, TEST_ZOOM, samples)
    by_name = {sample["name"]: sample for sample in checked}
    assert by_name["north"]["opaque"] and by_name["south"]["opaque"]
    north_y = int(by_name["north"]["tile"].split("/")[2])
    south_y = int(by_name["south"]["tile"].split("/")[2])
    assert north_y < south_y
    assert by_name["north"]["values"][0] == 255
    assert by_name["south"]["values"][0] == 100


def test_a_pyramid_with_tms_y_fails_the_sample_check(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    extent = grid["tile_range"]
    mirrored = {}
    for x in range(extent["x_min"], extent["x_max"] + 1):
        for y in range(extent["y_min"], extent["y_max"] + 1):
            flipped = extent["y_min"] + extent["y_max"] - y
            mirrored[(x, flipped)] = tile_path(out, TEST_ZOOM, x, y).read_bytes()
    for (x, y), payload in mirrored.items():
        tile_path(out, TEST_ZOOM, x, y).write_bytes(payload)
    with pytest.raises(WarpError, match="does not match the COG"):
        warp_raster.verify_tile_samples(cog, out, grid, TEST_ZOOM, sample_pair(grid))


def test_a_pyramid_cut_from_another_cog_fails_the_sample_check(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    mine = synthetic_cog(tmp_path / "mine.tif", grid, north=255, south=100)
    other = synthetic_cog(tmp_path / "other.tif", grid, north=60, south=30)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(other, grid, [TEST_ZOOM], "nearest", out)
    with pytest.raises(WarpError, match="does not match the COG"):
        warp_raster.verify_tile_samples(mine, out, grid, TEST_ZOOM, sample_pair(grid))


def test_a_missing_tile_at_a_sample_point_is_reported(tmp_path):
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    cog = synthetic_cog(tmp_path / "cog.tif", grid)
    out = tmp_path / "tiles"
    warp_raster.cut_pyramid(cog, grid, [TEST_ZOOM], "nearest", out)
    samples = sample_pair(grid)
    located = warp_raster.tile_pixel(*samples["north"], TEST_ZOOM)
    tile_path(out, TEST_ZOOM, located["x"], located["y"]).unlink()
    with pytest.raises(WarpError, match="which is missing"):
        warp_raster.verify_tile_samples(cog, out, grid, TEST_ZOOM, samples)


def test_the_sample_points_sit_inside_the_shared_footprint(tree):
    footprint = demo.common_footprint(tree.manifest)
    samples = demo.sample_points(footprint)
    assert set(samples) == {"north", "south"}
    for lon, lat in samples.values():
        assert footprint.contains(Point(lon, lat))
    assert samples["north"][1] > samples["south"][1]


# --- the whole stage, over the four synthetic editions ---------------------------------


def test_all_four_pyramids_are_produced_over_the_manifest_zoom_range(tree, tmp_path):
    build_root = tmp_path / "build"
    result = run_rasters(tree, build_root)
    assert result.exit_code == 0, result.output
    tiles = tiles_record(build_root)
    assert tiles["scheme"] == "xyz"
    assert tiles["zoom"] == {"min": tree.manifest["tile_zoom"]["min"], "max": TEST_ZOOM}
    assert [entry["id"] for entry in tiles["editions"]] == tree.manifest["edition_order"]
    grid = record_of(build_root)["grid"]
    for entry in tiles["editions"]:
        root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR / entry["id"]
        assert entry["template"] == f"tiles/{entry['id']}/{{z}}/{{x}}/{{y}}.png"
        zooms = sorted(int(p.name) for p in root.iterdir())
        assert zooms == list(range(tree.manifest["tile_zoom"]["min"], TEST_ZOOM + 1))
        assert entry["tiles"] == len(list(root.rglob("*.png")))
        for level in entry["levels"]:
            assert level["tile_range"] == warp_raster.tile_indices(grid, level["zoom"])
            assert level["tiles"] == len(list((root / str(level["zoom"])).rglob("*.png")))
            assert level["bytes"] > 0
    assert tiles["totals"]["tiles"] == sum(e["tiles"] for e in tiles["editions"])
    assert tiles["totals"]["bytes"] == sum(e["bytes"] for e in tiles["editions"])


def test_each_pyramid_names_its_own_edition_and_cog(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    record = record_of(build_root)
    cogs = {entry["id"]: entry for entry in record["editions"]}
    selected = {e["id"]: e["source_id"] for e in tree.manifest["editions"]}
    for entry in record["tiles"]["editions"]:
        assert entry["source_id"] == selected[entry["id"]]
        assert entry["cog_sha256"] == cogs[entry["id"]]["output"]["sha256"]
        assert entry["resampling"] == cogs[entry["id"]]["resampling"]
        assert entry["path"] == f"tiles/demo/{entry['id']}"
    assert record["tiles"]["editions"][2]["resampling"] == "cubic"


def test_the_record_says_the_pyramid_is_xyz_and_inspected_automatically(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    notes = tiles_record(build_root)["notes"]
    assert "XYZ" in notes["y_orientation"]
    assert "TMS" in notes["y_orientation"]
    assert "automated only" in notes["inspection"]
    assert "#38" in notes["human_acceptance"]
    assert "transparent" in notes["empty_areas"]


def test_every_published_tile_carries_alpha_and_zero_colour_outside_it(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR
    seen = 0
    for path in root.rglob("*.png"):
        with rasterio.open(path) as tile:
            assert tile.colorinterp[-1] == rasterio.enums.ColorInterp.alpha
            pixels = tile.read()
        assert set(np.unique(pixels[-1])) <= {0, 255}
        assert pixels[0][pixels[-1] == 0].max(initial=0) == 0
        seen += 1
    assert seen == tiles_record(build_root)["totals"]["tiles"] > 0


def test_a_rerun_reuses_every_pyramid_and_rewrites_an_identical_record(tree, tmp_path):
    build_root = tmp_path / "build"
    first = run_rasters(tree, build_root)
    assert first.exit_code == 0, first.output
    assert first.output.count(": cut") == 4
    record_path = build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME
    before = record_path.read_bytes()
    root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR
    stamps = {p: p.stat().st_mtime_ns for p in root.rglob("*.png")}
    second = run_rasters(tree, build_root)
    assert second.exit_code == 0, second.output
    assert ": cut" not in second.output
    assert second.output.count(": reused") == 4
    assert record_path.read_bytes() == before
    assert {p: p.stat().st_mtime_ns for p in root.rglob("*.png")} == stamps


def test_a_partial_pyramid_is_cut_again_and_never_recorded_as_complete(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    before = tiles_record(build_root)
    root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR / "auburn-1973"
    victim = sorted(root.rglob("*.png"))[-1]
    victim.unlink()
    result = run_rasters(tree, build_root)
    assert result.exit_code == 0, result.output
    assert "auburn-1973: cut" in result.output
    assert "auburn-1953: reused" in result.output
    assert victim.is_file()
    assert tiles_record(build_root) == before


def test_a_tile_whose_bytes_changed_is_cut_again(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR / "auburn-1981"
    victim = sorted(root.rglob("*.png"))[0]
    victim.write_bytes(victim.read_bytes()[:-8])
    result = run_rasters(tree, build_root)
    assert result.exit_code == 0, result.output
    assert "auburn-1981: cut" in result.output
    with rasterio.open(victim) as tile:
        assert tile.driver == "PNG"


def test_a_changed_zoom_range_cuts_every_pyramid_again(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    result = run_rasters(tree, build_root, "--grid-zoom", str(TEST_ZOOM - 1))
    assert result.exit_code == 0, result.output
    assert result.output.count(": cut") == 4
    assert tiles_record(build_root)["zoom"]["max"] == TEST_ZOOM - 1


def test_the_tile_fingerprint_follows_the_cog_and_every_parameter():
    """Stale tiles are found by the key, so the key holds more than the COG's hash."""
    grid = warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM)
    versions = {"gdal": "3.10.3"}
    entry = {
        "id": "auburn-1953",
        "resampling": "nearest",
        "output": {"sha256": "a" * 64, "byte_count": 1024},
    }
    zooms = [10, 11, 12]
    base = warp_raster.fingerprint(demo.tile_plan(entry, grid, zooms, versions))
    variants = [
        demo.tile_plan(
            {**entry, "output": {"sha256": "b" * 64, "byte_count": 1024}}, grid, zooms, versions
        ),
        demo.tile_plan(
            {**entry, "output": {"sha256": "a" * 64, "byte_count": 2048}}, grid, zooms, versions
        ),
        demo.tile_plan({**entry, "resampling": "cubic"}, grid, zooms, versions),
        demo.tile_plan(entry, grid, [10, 11], versions),
        demo.tile_plan(
            entry, warp_raster.common_grid(VIEW_BOUNDS, TEST_ZOOM - 1), zooms, versions
        ),
        demo.tile_plan(entry, grid, zooms, {"gdal": "3.11.0"}),
    ]
    assert (
        len({warp_raster.fingerprint(plan) for plan in variants} | {base}) == len(variants) + 1
    )


def test_the_top_zoom_never_exceeds_the_grid_the_cogs_are_on(tree, tmp_path):
    build_root = tmp_path / "build"
    result = run_rasters(tree, build_root, "--grid-zoom", "10")
    assert result.exit_code == 0, result.output
    tiles = tiles_record(build_root)
    assert tiles["zoom"] == {"min": 10, "max": 10}
    for entry in tiles["editions"]:
        root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR / entry["id"]
        assert [p.name for p in root.iterdir()] == ["10"]
        assert entry["tiles"] == 1


def test_a_failure_part_way_through_publishes_no_pyramid(tree, tmp_path, monkeypatch):
    build_root = tmp_path / "build"
    real = warp_raster.cut_pyramid
    calls = []

    def fail_on_the_third(cog_path, *args, **kwargs):
        calls.append(cog_path.name)
        if len(calls) == 3:
            raise WarpError("disk full")
        return real(cog_path, *args, **kwargs)

    monkeypatch.setattr(warp_raster, "cut_pyramid", fail_on_the_third)
    result = run_rasters(tree, build_root)
    assert result.exit_code != 0
    assert "disk full" in result.output
    assert published_tiles(build_root) == []
    assert "tiles" not in record_of(build_root)
    assert not (build_root / demo.TILE_DIRNAME / demo.INCOMING_DIRNAME).exists()


def test_a_later_failure_leaves_the_published_pyramids_and_record_intact(
    tree, tmp_path, monkeypatch
):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR
    published = {p: p.read_bytes() for p in root.rglob("*.png")}
    record_path = build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME
    record_bytes = record_path.read_bytes()

    def refuse(*args, **kwargs):
        raise WarpError("tiler crashed")

    monkeypatch.setattr(warp_raster, "cut_pyramid", refuse)
    # A different zoom range invalidates all four, so all four would have been republished.
    result = run_rasters(tree, build_root, "--grid-zoom", str(TEST_ZOOM - 1))
    assert result.exit_code != 0
    assert {p: p.read_bytes() for p in root.rglob("*.png")} == published
    assert not (build_root / demo.TILE_DIRNAME / demo.INCOMING_DIRNAME).exists()
    # The COG stage reran, so the record was rewritten; its tiles section still describes
    # exactly the pyramids that are on disk.
    reread = json.loads(record_path.read_bytes())["tiles"]
    assert reread == json.loads(record_bytes)["tiles"]
    for entry in reread["editions"]:
        assert warp_raster.pyramid_digest(root / entry["id"])[0] == entry["digest"]


def test_an_unexpected_directory_under_the_tile_root_is_reported(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    (build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR / "auburn-1999").mkdir()
    result = run_rasters(tree, build_root)
    assert result.exit_code != 0
    assert "unexpected entries" in result.output


def test_a_tiling_run_changes_no_raw_byte_and_no_receipt(tree, tmp_path):
    before = tree_digests(tree)
    result = run_rasters(tree, tmp_path / "build")
    assert result.exit_code == 0, result.output
    assert tree_digests(tree) == before


def test_the_cog_stage_keeps_a_valid_pyramid_from_looking_stale(tree, tmp_path):
    build_root = tmp_path / "build"
    assert run_rasters(tree, build_root).exit_code == 0
    assert run_cogs(tree, build_root).exit_code == 0
    assert "tiles" in record_of(build_root)
    result = run_rasters(tree, build_root)
    assert result.exit_code == 0, result.output
    assert result.output.count(": reused") == 4
