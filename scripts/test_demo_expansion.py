"""The nine-edition manifest (#57, active since #58): contract, crops, zoom limits and the
raster stage of the five added editions.

Synthetic sources come from test_demo.py; nothing here reads data/raw/ or writes outside
tmp_path, except the committed-manifest checks, which read data/sources/ only.
"""

import copy
import hashlib
import json

import demo
import demo_expansion
import demo_sources
import numpy as np
import pytest
import rasterio
import test_demo
import warp_raster
from click.testing import CliRunner
from pyproj import CRS
from shapely.geometry import shape
from test_demo import by_id, failure

scans = test_demo.scans
tree = test_demo.tree
added_scans = test_demo.added_scans
expanded_manifest = test_demo.expanded_manifest
expanded_tree = test_demo.expanded_tree

ADDED = [eid for eid in demo.EXPANDED_EDITION_ORDER if eid not in demo.EDITION_ORDER]
# Zoom 15 is the cheapest cap that still shows the 1891 and 1994 sheets stopping below it.
TEST_ZOOM_CAP = 15
# SHA-256 of each original four-edition entry (sorted-key JSON of its version-1 fields) as
# committed in data/sources/demo-editions.json before #58 promoted the nine-edition file.
ORIGINAL_FOUR = {
    "auburn-1953": "2805b5b7ef23df70b001c94cf0d3286da6853db129dbe66e1b558b92816a6286",
    "auburn-1973": "eb0143445999d6372294deb0632bc60bc2736b3e47545d32c3577bd021839e2e",
    "auburn-1975": "efcb51825633f62b66b62b7b10451ff5f2d780680fccd0c6b084144032c5cc7f",
    "auburn-1981": "40bd8c20db6aafc682d477e18dd8b14932e5004dcb5c47b2a0c7058441c835af",
}
VERSION_1_FIELDS = (
    "attribution",
    "citation",
    "crop_wgs84",
    "date_note",
    "dates",
    "id",
    "kind",
    "label",
    "rights",
    "source_id",
    "source_url",
)


def run_expansion(tree, *args):
    command = [arg for arg in tree.paths_args()]
    return CliRunner().invoke(demo_expansion.cli, ["rasters", *command, *args])


def record_of(tree):
    return json.loads((tree.expansion_root / demo_expansion.RECORD_NAME).read_text())


# --- the committed manifests ------------------------------------------------------------


def test_committed_expanded_manifest_meets_the_contract():
    manifest = demo.read_json(demo.EXPANDED_MANIFEST_PATH)
    crops = demo.check_metadata(manifest, demo.SCHEMA_PATH, demo.INDEX_PATH, demo.SOURCES_PATH)
    assert list(crops) == demo.EXPANDED_EDITION_ORDER
    assert manifest["initial_edition"] == "auburn-1953"


def test_the_nine_edition_manifest_is_the_active_one():
    assert demo.EXPANDED_MANIFEST_PATH == demo.MANIFEST_PATH
    assert not (demo.REPO_ROOT / "data/sources/demo-editions-expanded.json").exists()
    manifest = demo.read_json(demo.MANIFEST_PATH)
    assert manifest["version"] == 2
    assert manifest["edition_order"] == demo.EXPANDED_EDITION_ORDER


def test_the_four_original_editions_are_carried_over_unchanged():
    manifest = demo.read_json(demo.MANIFEST_PATH)
    # The camera bounds and zoom range of the original four-edition viewer.
    assert manifest["view_bounds_wgs84"] == [-121.126028, 38.874881, -121.001023, 38.99988]
    assert manifest["tile_zoom"] == {"min": 10, "max": 16}
    for edition_id, digest in ORIGINAL_FOUR.items():
        carried = {key: by_id(manifest, edition_id)[key] for key in VERSION_1_FIELDS}
        text = json.dumps(carried, sort_keys=True).encode()
        assert hashlib.sha256(text).hexdigest() == digest, edition_id


def test_one_shared_nine_edition_contract():
    assert demo.EXPANDED_EDITION_ORDER == list(demo_sources.EXPANSION_ORDER)
    scans_ = [
        demo.EXPANDED_EXPECTED_EDITIONS[eid]["source_id"]
        for eid in ADDED
        if demo.EXPANDED_EXPECTED_EDITIONS[eid]["source_kind"] == "historical_geotiff"
    ]
    pdfs = [
        demo.EXPANDED_EXPECTED_EDITIONS[eid]["source_id"]
        for eid in ADDED
        if demo.EXPANDED_EXPECTED_EDITIONS[eid]["source_kind"] == "us_topo_pdf"
    ]
    assert tuple(scans_) == demo_sources.TOPO_IDS
    assert tuple(pdfs) == demo_sources.PDF_SOURCE_IDS
    schema = demo.read_json(demo.SCHEMA_PATH)["$defs"]
    assert schema["manifest_v2"]["properties"]["edition_order"]["const"] == (
        demo.EXPANDED_EDITION_ORDER
    )
    assert sorted(schema["edition_v2"]["properties"]["source_id"]["enum"]) == sorted(
        e["source_id"] for e in demo.EXPANDED_EXPECTED_EDITIONS.values()
    )


def test_regional_sheets_carry_their_own_names_and_scales():
    manifest = demo.read_json(demo.EXPANDED_MANIFEST_PATH)
    expected = {
        "sacramento-1891": ("Sacramento", 125000, 14),
        "auburn-1944": ("Auburn", 62500, 15),
        "sacramento-1994": ("Sacramento", 100000, 14),
        "auburn-2018": ("Auburn", 24000, 16),
        "auburn-2021": ("Auburn", 24000, 16),
    }
    for eid, (sheet, scale, zoom) in expected.items():
        edition = by_id(manifest, eid)
        assert (edition["sheet_name"], edition["scale"], edition["native_max_zoom"]) == (
            sheet,
            scale,
            zoom,
        )
    assert "1:125,000" in by_id(manifest, "sacramento-1891")["label"]
    assert "1:100,000" in by_id(manifest, "sacramento-1994")["label"]


def test_regional_crops_are_the_view_and_us_topo_crops_stay_inside_it():
    manifest = demo.read_json(demo.EXPANDED_MANIFEST_PATH)
    view = demo.common_footprint(
        {"editions": [e for e in manifest["editions"] if e["id"] in demo.EDITION_ORDER]}
    )
    for eid in ("sacramento-1891", "auburn-1944", "sacramento-1994"):
        assert shape(by_id(manifest, eid)["crop_wgs84"]).equals(view)
    for eid in ("auburn-2018", "auburn-2021"):
        crop = shape(by_id(manifest, eid)["crop_wgs84"])
        assert crop.within(view.buffer(demo.POSITION_TOLERANCE_DEG))
        assert demo.MIN_VIEW_COVERAGE <= crop.area / view.area < 1


def test_us_topo_credits_are_the_catalog_text_verbatim():
    manifest = demo.read_json(demo.EXPANDED_MANIFEST_PATH)
    catalog = demo_sources.load_catalog()
    for edition in manifest["editions"]:
        if edition["source_kind"] == "us_topo_pdf":
            assert (
                edition["printed_credit_note"]
                == (catalog[edition["source_id"]]["rights"]["credit_note"])
            )
            assert edition["attribution"] == "US Topo maps: U.S. Geological Survey"
        else:
            assert edition["printed_credit_note"] is None


def test_the_base_pipeline_warps_only_the_four_base_editions(expanded_tree, tmp_path):
    result = demo.run_cogs(
        expanded_tree.manifest_path,
        demo.SCHEMA_PATH,
        expanded_tree.index_path,
        expanded_tree.receipts_path,
        expanded_tree.sources_path,
        expanded_tree.raw_root,
        tmp_path / "build",
        12,
        demo_sources.CATALOG_PATH,
        expanded_tree.ledger_path,
        expanded_tree.expansion_root,
    )
    record = result["record"]
    assert [entry["id"] for entry in record["editions"]] == demo.EDITION_ORDER
    assert record["base_editions"] == demo.EDITION_ORDER
    assert record["edition_order"] == demo.EXPANDED_EDITION_ORDER
    assert sorted(p.name for p in (tmp_path / "build" / "rasters").glob("*.tif")) == sorted(
        f"{eid}.tif" for eid in demo.EDITION_ORDER
    )


# --- the version-2 check on synthetic sources ------------------------------------------


def test_the_nine_edition_fixture_tree_passes(expanded_tree):
    result = expanded_tree.run()
    assert result.exit_code == 0, result.output
    assert "9 public editions verified" in result.output
    for eid in demo.EXPANDED_EDITION_ORDER:
        assert eid in result.output


def test_a_duplicate_source_is_rejected(expanded_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-2021")["source_id"] = by_id(manifest, "auburn-2018")[
            "source_id"
        ]

    assert "Duplicate source_id" in failure(expanded_tree, mutate)


@pytest.mark.parametrize(
    ("edition_id", "wrong"),
    [("sacramento-1891", "us_topo_pdf"), ("auburn-2018", "historical_geotiff")],
)
def test_a_wrong_source_kind_is_rejected(expanded_tree, edition_id, wrong):
    def mutate(manifest):
        by_id(manifest, edition_id)["source_kind"] = wrong

    assert "source_kind" in failure(expanded_tree, mutate)


def test_an_unknown_source_kind_is_rejected(expanded_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1944")["source_kind"] = "screenshot"

    assert "schema" in failure(expanded_tree, mutate).lower()


def test_a_regional_sheet_labelled_as_an_auburn_map_is_rejected(expanded_tree):
    def mutate(manifest):
        by_id(manifest, "sacramento-1891")["label"] = "Auburn 1891 topographic map"

    assert "label must show the Sacramento sheet" in failure(expanded_tree, mutate)


def test_a_wrong_scale_is_rejected(expanded_tree):
    def mutate(manifest):
        by_id(manifest, "sacramento-1994")["scale"] = 24000

    assert "scale" in failure(expanded_tree, mutate)


def test_component_dates_must_match_the_index(expanded_tree):
    rows = copy.deepcopy(expanded_tree.index_rows)
    for row in rows:
        if row["topo_id"] == "CA_Auburn_296741_1944_62500":
            row["survey_year"] = "1940"
    expanded_tree.write_index(rows)
    result = expanded_tree.run()
    assert result.exit_code != 0
    assert "component_dates.survey_year" in result.output


def test_a_credit_note_not_in_the_catalog_is_rejected(expanded_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-2021")["printed_credit_note"] = "Produced by someone else"

    assert "credit note verbatim" in failure(expanded_tree, mutate)


def test_a_moved_initial_edition_is_rejected(expanded_tree):
    def mutate(manifest):
        manifest["initial_edition"] = "auburn-2021"

    assert "schema" in failure(expanded_tree, mutate).lower()


def test_a_lower_resolution_sheet_cannot_claim_full_zoom(expanded_tree):
    def mutate(manifest):
        by_id(manifest, "sacramento-1891")["native_max_zoom"] = 16

    assert "native_max_zoom" in failure(expanded_tree, mutate)


def test_native_zoom_follows_the_measured_pixel():
    latitude = 38.937
    assert demo.native_max_zoom(2.032, latitude) == 16
    assert demo.native_max_zoom(5.2917, latitude) == 15
    assert demo.native_max_zoom(8.4667, latitude) == 14
    assert demo.native_max_zoom(10.5833, latitude) == 14
    assert demo.native_max_zoom(20.0, latitude) == 13


@pytest.mark.parametrize(
    ("edition_id", "passes"), [("sacramento-1891", True), ("auburn-1953", False)]
)
def test_pipeline_agreement_limit_scales_with_the_source_pixel(
    monkeypatch, scans, added_scans, edition_id, passes
):
    """An 8 m extent drift is under one 10.58 m pixel but over the 5 m floor at 2.03 m."""
    paths = {**scans[0], **added_scans[0]}
    topo_id = demo.EXPANDED_EXPECTED_EDITIONS[edition_id]["source_id"]
    real = warp_raster.calculate_default_transform

    def drift_the_pinned_extent(*args, **kwargs):
        transform, width, height = real(*args, **kwargs)
        if "COORDINATE_OPERATION" in kwargs:
            transform = rasterio.Affine.translation(8, 0) * transform
        return transform, width, height

    with rasterio.open(paths[edition_id]) as dataset:
        pipeline = warp_raster.select_operation(
            CRS.from_user_input(dataset.crs),
            demo.seed_of(test_demo.index_row(topo_id)),
            [],
        )["pipeline"]
        monkeypatch.setattr(warp_raster, "calculate_default_transform", drift_the_pinned_extent)
        if passes:
            record = warp_raster.verify_pipeline(dataset, pipeline)
            assert 5.0 < record["pinned_vs_pyproj_metres"] <= dataset.transform.a
        else:
            with pytest.raises(warp_raster.WarpError, match="over the 5 m limit"):
                warp_raster.verify_pipeline(dataset, pipeline)


def test_a_misstated_resolution_is_rejected(expanded_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1944")["native_resolution_metres"] = 2.03

    assert "native_resolution_metres" in failure(expanded_tree, mutate)


def test_a_crop_shrunk_inside_the_view_is_rejected(expanded_tree):
    def mutate(manifest):
        ring = by_id(manifest, "auburn-1944")["crop_wgs84"]["coordinates"][0]
        west = min(lon for lon, _ in ring)
        by_id(manifest, "auburn-1944")["crop_wgs84"]["coordinates"][0] = [
            [demo.q6(max(lon, west + 0.01)), lat] for lon, lat in ring
        ]

    assert "off the source face clipped to the view" in failure(expanded_tree, mutate)


def test_a_source_mapping_too_little_of_the_view_is_rejected(expanded_tree, monkeypatch):
    # The US Topo faces sit on NAD83 and cover about 99% of the NAD27 view.
    monkeypatch.setattr(demo, "MIN_VIEW_COVERAGE", 0.999)
    result = expanded_tree.run()
    assert result.exit_code != 0
    assert "of the view footprint" in result.output


def test_a_rendered_cog_not_from_the_receipted_pdf_is_rejected(expanded_tree):
    record_path = expanded_tree.expansion_root / demo.PDF_RECORD_NAME
    record = json.loads(record_path.read_text())
    record["sources"][0]["source"]["sha256"] = "0" * 64
    record_path.write_text(json.dumps(record))
    result = expanded_tree.run()
    assert result.exit_code != 0
    assert "not of the receipted PDF bytes" in result.output


def test_a_changed_rendered_cog_is_rejected(expanded_tree):
    cog = expanded_tree.expansion_root / "pdf" / "auburn-2018.tif"
    data = cog.read_bytes()
    cog.unlink()
    cog.write_bytes(data + b"\0")
    result = expanded_tree.run()
    assert result.exit_code != 0
    assert "differs from demo-pdf-processing.json" in result.output


def test_a_changed_pdf_is_rejected(expanded_tree):
    receipt = demo_sources.load_ledger(expanded_tree.ledger_path)["5d3aeb27e4b01d82ce8d133b"]
    target = expanded_tree.raw_root / receipt["path"]
    target.write_bytes(target.read_bytes() + b"\0")
    result = expanded_tree.run()
    assert result.exit_code != 0
    assert "Checksum mismatch" in result.output


def test_a_missing_pdf_render_record_is_rejected(expanded_tree):
    (expanded_tree.expansion_root / demo.PDF_RECORD_NAME).unlink()
    result = expanded_tree.run()
    assert result.exit_code != 0
    assert "make expansion-pdf" in result.output


# --- index and CRS disagreements are recorded, not resolved ------------------------------


def test_index_crs_disagreements_are_recorded(expanded_tree):
    checked = demo.run_check(
        expanded_tree.manifest_path,
        demo.SCHEMA_PATH,
        expanded_tree.index_path,
        expanded_tree.receipts_path,
        expanded_tree.sources_path,
        expanded_tree.raw_root,
        demo_sources.CATALOG_PATH,
        expanded_tree.ledger_path,
        expanded_tree.expansion_root,
    )
    reports = checked["reports"]
    assert reports["sacramento-1891"]["index_crs"]["agrees"] is False
    assert reports["sacramento-1891"]["index_crs"]["index_datum"] == "Unstated"
    # Indexed as UTM, but the scan is a transverse Mercator with scale 1 on 121 30' W.
    assert reports["sacramento-1994"]["index_crs"]["agrees"] is False
    assert reports["auburn-1944"]["index_crs"]["agrees"] is True
    assert reports["auburn-1953"]["index_crs"]["agrees"] is True
    assert reports["sacramento-1891"]["enforced_edges"] == ["east", "north"]


def test_bounding_edges_are_those_shared_with_the_view():
    view = (-121.125, 38.875, -121.0, 39.0)
    assert demo.bounding_edges(view, view) == {"west", "east", "south", "north"}
    assert demo.bounding_edges((-121.5, 38.5, -121.0, 39.0), view) == {"east", "north"}
    assert demo.bounding_edges((-122.0, 38.0, -121.5, 38.5), view) == set()


# --- the raster stage --------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory, scans, added_scans, expanded_manifest):
    base = tmp_path_factory.mktemp("built") / "tree"
    fixture = test_demo.build_expanded_tree(
        base, scans, added_scans, copy.deepcopy(expanded_manifest)
    )
    raw_before = digests(fixture.raw_root)
    result = run_expansion(fixture, "--zoom-cap", str(TEST_ZOOM_CAP))
    assert result.exit_code == 0, result.output
    return fixture, result, raw_before


def digests(root):
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_record_lists_the_added_editions_in_manifest_order(built):
    fixture, _, _ = built
    record = record_of(fixture)
    manifest = fixture.manifest
    assert record["edition_order"] == manifest["edition_order"]
    added = [eid for eid in manifest["edition_order"] if eid not in record["active_editions"]]
    assert [entry["id"] for entry in record["editions"]] == added
    assert record["active_editions"] == demo.EDITION_ORDER


def test_each_pyramid_stops_at_its_own_native_zoom(built):
    fixture, _, _ = built
    record = record_of(fixture)
    for entry in record["editions"]:
        native = by_id(fixture.manifest, entry["id"])["native_max_zoom"]
        top = min(native, TEST_ZOOM_CAP)
        assert entry["zoom"]["max"] == top == entry["grid"]["zoom"]
        assert entry["zoom"]["native_max_zoom"] == native
        levels = sorted(
            int(p.name) for p in (fixture.expansion_root / entry["tiles"]["path"]).iterdir()
        )
        assert levels == list(range(10, top + 1)), entry["id"]
    zooms = {entry["id"]: entry["zoom"]["max"] for entry in record["editions"]}
    # The lower-resolution regional sheets overzoom rather than cut invented detail.
    assert zooms["sacramento-1891"] == zooms["sacramento-1994"] == 14
    assert zooms["auburn-1944"] == zooms["auburn-2018"] == TEST_ZOOM_CAP


def test_no_tile_falls_outside_the_view(built):
    fixture, _, _ = built
    for entry in record_of(fixture)["editions"]:
        root = fixture.expansion_root / entry["tiles"]["path"]
        for level in entry["tiles"]["levels"]:
            extent = warp_raster.tile_indices(entry["grid"], level["zoom"])
            assert level["tile_range"] == extent
            span = (extent["x_max"] - extent["x_min"] + 1) * (
                extent["y_max"] - extent["y_min"] + 1
            )
            assert level["tiles"] == span
            for tile in (root / str(level["zoom"])).rglob("*.png"):
                x, y = int(tile.parent.name), int(tile.stem)
                assert extent["x_min"] <= x <= extent["x_max"]
                assert extent["y_min"] <= y <= extent["y_max"]
            # A world pyramid at zoom 10 alone would be 1,048,576 tiles.
            assert level["tiles"] <= 4 ** max(0, level["zoom"] - 10) * 4


def test_every_map_sheet_keeps_nearest_sampling(built):
    fixture, _, _ = built
    for entry in record_of(fixture)["editions"]:
        assert entry["resampling"] == "nearest"
    # The 1975 orthophotoquad is the only cubic edition, and it is not re-tiled here.
    assert warp_raster.resampling_for("orthophotoquad") == "cubic"


def test_alpha_is_two_valued_and_follows_the_crop(built):
    fixture, _, _ = built
    for entry in record_of(fixture)["editions"]:
        with rasterio.open(fixture.expansion_root / entry["output"]["path"]) as dataset:
            alpha = dataset.read(dataset.count)
        assert set(np.unique(alpha)) <= {0, 255}
        assert entry["coverage"]["alpha_opaque_px"] == int((alpha > 0).sum())
        expected = warp_raster.crop_mask(entry["crop_wgs84"], entry["grid"])
        assert np.array_equal(alpha > 0, expected > 0), entry["id"]


def test_lineage_traces_each_cog_to_its_receipted_bytes(built):
    fixture, _, _ = built
    receipts = {r["topo_id"]: r for r in demo.load_receipts(fixture.receipts_path)}
    ledger = demo_sources.load_ledger(fixture.ledger_path)
    rendered = {
        s["edition_id"]: s
        for s in json.loads((fixture.expansion_root / demo.PDF_RECORD_NAME).read_text())[
            "sources"
        ]
    }
    for entry in record_of(fixture)["editions"]:
        source = entry["source"]
        if entry["source_kind"] == "us_topo_pdf":
            assert source["pdf_sha256"] == ledger[source["source_id"]]["sha256"]
            assert source["rendered_cog_sha256"] == rendered[entry["id"]]["raster"]["sha256"]
        else:
            assert source["sha256"] == receipts[source["source_id"]]["sha256"]
        assert entry["datum_transformation"]["description"]
        assert "ballpark" not in entry["datum_transformation"]["description"].lower()


def test_registration_is_labelled_as_a_machine_check(built):
    fixture, _, _ = built
    record = record_of(fixture)
    assert "no human" in record["notes"]["inspection"]
    for entry in record["editions"]:
        offsets = entry["registration"]["offsets_vs_reference"]
        assert [o["name"] for o in offsets] == list(demo_expansion.PATCH_FRACTIONS)
        for offset in offsets:
            if not offset["distinct"]:
                assert offset["east_m"] is None and offset["north_m"] is None
        assert entry["registration"]["correction_applied"].startswith("none")


def test_output_stays_under_the_expansion_root(built):
    fixture, _, _ = built
    assert not (fixture.base / "build").exists()
    assert sorted(p.name for p in fixture.expansion_root.iterdir()) == sorted(
        [demo.PDF_RECORD_NAME, demo_expansion.RECORD_NAME, "pdf", "rasters", "tiles"]
    )


def test_raw_bytes_are_untouched_and_a_rerun_reuses_everything(built):
    fixture, _, raw_before = built
    before = digests(fixture.expansion_root)
    result = run_expansion(fixture, "--zoom-cap", str(TEST_ZOOM_CAP))
    assert result.exit_code == 0, result.output
    assert result.output.count(": reused ") == len(ADDED)
    assert digests(fixture.expansion_root) == before
    assert digests(fixture.raw_root) == raw_before


def test_expansion_rasters_refuses_the_live_manifest(tree, tmp_path):
    args = tree.paths_args()
    result = CliRunner().invoke(demo_expansion.cli, ["rasters", *args])
    assert result.exit_code != 0
    assert "version-2" in result.output or "version-2" in str(result.exception)


# --- the offset measurement itself ------------------------------------------------------


def test_phase_correlation_recovers_a_known_shift():
    rng = np.random.default_rng(57)
    base = np.zeros((128, 128))
    for _ in range(40):
        r, c = rng.integers(10, 118, size=2)
        base[r - 1 : r + 2, c - 12 : c + 12] = 200
        base[r - 12 : r + 12, c - 1 : c + 2] = 200
    moved = np.roll(base, shift=(-3, 5), axis=(0, 1))
    measured = warp_raster.phase_correlation(base, moved)
    # Content moved 5 px east and 3 px north (rows count down).
    assert measured["distinct"]
    assert abs(measured["dx_px"] - 5) < 0.5
    assert abs(measured["dy_px"] + 3) < 0.5


def test_phase_correlation_finds_no_offset_between_unrelated_patches():
    rng = np.random.default_rng(1)
    measured = warp_raster.phase_correlation(rng.random((128, 128)), rng.random((128, 128)))
    assert not measured["distinct"]
