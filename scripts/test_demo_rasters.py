"""D2a: the COG preparation stage, on synthetic scans only.

The four-edition fixture tree comes from test_demo.py so both stages are checked against
the same synthetic sources. Nothing here reads data/raw/ or the committed receipt ledger.
"""

import hashlib
import json

import demo
import numpy as np
import pytest
import rasterio
import test_demo
import warp_raster
from click.testing import CliRunner
from pyproj import CRS, Transformer
from rasterio.transform import Affine
from warp_raster import WarpError

# The full-resolution grid is zoom 16; these run at zoom 12 so a warp costs a second.
TEST_ZOOM = 12

scans = test_demo.scans
tree = test_demo.tree


def run_cogs(tree, build_root, *args):
    return CliRunner().invoke(
        demo.cli,
        [
            "cogs",
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
    assert [entry["id"] for entry in record["editions"]] == list(demo.EDITION_ORDER)
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
