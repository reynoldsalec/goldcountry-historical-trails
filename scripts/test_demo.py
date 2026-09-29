import copy
import csv
import hashlib
import json
import os
import socket

import demo
import fetch_topoview as topo
import numpy as np
import pytest
import rasterio
import yaml
from affine import Affine
from click.testing import CliRunner
from pyproj import CRS, Transformer
from shapely.geometry import shape

# The graticule corners of the Auburn 7.5-minute quadrangle, as labelled in the index.
SEED = (-121.125, 38.875, -121.0, 39.0)

POLYCONIC_WKT = (
    'PROJCS["unnamed",GEOGCS["NAD27",DATUM["North_American_Datum_1927",'
    'SPHEROID["Clarke 1866",6378206.4,294.978698213898,AUTHORITY["EPSG","7008"]],'
    'AUTHORITY["EPSG","6267"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4267"]],PROJECTION["Polyconic"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-121.062999999999],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)
LCC_WKT = (
    'PROJCS["unnamed",GEOGCS["NAD27",DATUM["North_American_Datum_1927",'
    'SPHEROID["Clarke 1866",6378206.4,294.978698213898,AUTHORITY["EPSG","7008"]],'
    'AUTHORITY["EPSG","6267"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4267"]],PROJECTION["Lambert_Conformal_Conic_2SP"],'
    'PARAMETER["latitude_of_origin",38.875],'
    'PARAMETER["central_meridian",-121.062999999999],'
    'PARAMETER["standard_parallel_1",33],PARAMETER["standard_parallel_2",45],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)

ATTRIBUTION = "Historical topographic maps: U.S. Geological Survey"

# Index columns that matter here, transcribed from data/sources/topo_index.csv.
INDEX_ROWS = {
    "CA_Auburn_288101_1953_24000": {
        "date_on_map": "1953",
        "content_year": "1953",
        "imprint_year": "1955",
        "aerial_photo_year": "1952",
        "photo_revision_year": "",
        "field_check_year": "1953",
        "projection": "Polyconic",
        "size_bytes": "12532400",
        "source_id": "5a8a2904e4b00f54eb3c61ca",
    },
    "CA_Auburn_288103_1953_24000": {
        "date_on_map": "1953",
        "content_year": "1973",
        "imprint_year": "1977",
        "aerial_photo_year": "1973",
        "photo_revision_year": "1973",
        "field_check_year": "1953",
        "projection": "Polyconic",
        "size_bytes": "11709311",
        "source_id": "5a8a2905e4b00f54eb3c61d1",
    },
    "CA_Auburn_288104_1975_24000": {
        "date_on_map": "1975",
        "content_year": "1975",
        "imprint_year": "1981",
        "aerial_photo_year": "1975",
        "photo_revision_year": "",
        "field_check_year": "",
        "projection": "Lambert Conformal Conic",
        "size_bytes": "14103396",
        "source_id": "5a8a2905e4b00f54eb3c61d4",
    },
    "CA_Auburn_288105_1953_24000": {
        "date_on_map": "1953",
        "content_year": "1981",
        "imprint_year": "1981",
        "aerial_photo_year": "1978",
        "photo_revision_year": "1981",
        "field_check_year": "1953",
        "projection": "Polyconic",
        "size_bytes": "12427061",
        "source_id": "5a8a2905e4b00f54eb3c61d9",
    },
}

DISPLAY = {
    "auburn-1953": ("Auburn 1953 topographic map", "1953 base sheet; aerial photography 1952."),
    "auburn-1973": (
        "Auburn 1973 photorevision",
        "1953 base sheet photorevised from 1973 photography; the revision was "
        "not field checked.",
    ),
    "auburn-1975": (
        "Auburn 1975 orthophotoquad",
        "Orthophotoquad from 1975-08-29 photography.",
    ),
    "auburn-1981": (
        "Auburn 1981 photorevision",
        "1953 base sheet photorevised from 1978 photography; the revision was "
        "not field checked.",
    ),
}


def index_row(topo_id):
    row = dict.fromkeys(topo.COLUMNS, "")
    row.update(
        topo_id=topo_id,
        map_name="Auburn",
        scale="24000",
        extent="7.5 x 7.5 minute",
        woodland_tint="Y",
        scanner_resolution="600 PPI",
        datum="NAD27",
        west=str(SEED[0]),
        south=str(SEED[1]),
        east=str(SEED[2]),
        north=str(SEED[3]),
        in_tier1="true",
        rights="public_domain",
        geotiff_url=(
            "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/"
            f"GeoTIFF/CA/{topo_id}_geo.tif"
        ),
        metadata_url=(
            "https://thor-f5.er.usgs.gov/ngtoc/metadata/waf/maps/historicaltopo/pdf/"
            f"CA/24000/{topo_id}_geo.xml"
        ),
        sciencebase_url=(
            f"https://www.sciencebase.gov/catalog/item/{INDEX_ROWS[topo_id]['source_id']}"
        ),
        **INDEX_ROWS[topo_id],
    )
    return row


def write_fixture_scan(path, wkt, *, pixel_size=10.0, margin_px=120):
    """A synthetic scan: white map inside a drawn neatline, grey decorative collar."""
    crs = CRS.from_wkt(wkt)
    forward = Transformer.from_crs(CRS.from_epsg(4267), crs, always_xy=True)
    corners = {
        name: forward.transform(lon, lat)
        for name, (lon, lat) in {
            "nw": (SEED[0], SEED[3]),
            "ne": (SEED[2], SEED[3]),
            "sw": (SEED[0], SEED[1]),
            "se": (SEED[2], SEED[1]),
        }.items()
    }
    x_west = (corners["nw"][0] + corners["sw"][0]) / 2
    x_east = (corners["ne"][0] + corners["se"][0]) / 2
    y_north = (corners["nw"][1] + corners["ne"][1]) / 2
    y_south = (corners["sw"][1] + corners["se"][1]) / 2
    quad_cols = round((x_east - x_west) / pixel_size)
    quad_rows = round((y_north - y_south) / pixel_size)
    width = quad_cols + 2 * margin_px + 1
    height = quad_rows + 2 * margin_px + 1
    transform = Affine(
        pixel_size,
        0.0,
        x_west - margin_px * pixel_size,
        0.0,
        -pixel_size,
        y_north + margin_px * pixel_size,
    )

    data = np.full((height, width), 200, dtype="uint8")
    left, right = margin_px, margin_px + quad_cols
    top, bottom = margin_px, margin_px + quad_rows
    data[top : bottom + 1, left : right + 1] = 255
    for centre, value in ((0, 40), (1, 0), (-1, 40)):
        data[:, left + centre] = value
        data[:, right + centre] = value
        data[top + centre, :] = value
        data[bottom + centre, :] = value

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        compress="deflate",
    ) as dataset:
        dataset.write(data, 1)
    return path


def receipt(topo_id, path, root):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "version": 1,
        "kind": "geotiff",
        "source": "usgs-historical-topo",
        "topo_id": topo_id,
        "source_id": INDEX_ROWS[topo_id]["source_id"],
        "indexed_url": index_row(topo_id)["geotiff_url"],
        "retrieval_url": None,
        "metadata_url": index_row(topo_id)["metadata_url"],
        "rights": "public_domain",
        "sha256": digest,
        "byte_count": path.stat().st_size,
        "raw_path": path.relative_to(root).as_posix(),
        "retrieved_at": None,
        "recorded_at": "2026-09-16T23:54:05Z",
        "basis": "existing_file",
    }


def build_manifest(reports):
    editions = []
    for eid in demo.EDITION_ORDER:
        expected = demo.EXPECTED_EDITIONS[eid]
        topo_id = expected["source_id"]
        label, note = DISPLAY[eid]
        editions.append(
            {
                "id": eid,
                "source_id": topo_id,
                "kind": expected["kind"],
                "label": label,
                "citation": f"U.S. Geological Survey, Auburn quadrangle ({topo_id})",
                "source_url": index_row(topo_id)["sciencebase_url"],
                "rights": "public_domain",
                "attribution": ATTRIBUTION,
                "dates": copy.deepcopy(expected["dates"]),
                "date_note": note,
                "crop_wgs84": reports[eid]["crop_wgs84"],
            }
        )
    crops = [shape(edition["crop_wgs84"]) for edition in editions]
    common = crops[0]
    for crop in crops[1:]:
        common = common.intersection(crop)
    return {
        "version": 1,
        "area_id": "auburn",
        "edition_order": list(demo.EDITION_ORDER),
        "view_bounds_wgs84": [demo.q6(value) for value in common.bounds],
        "tile_zoom": {"min": 10, "max": 16},
        "editions": editions,
    }


@pytest.fixture(scope="session")
def scans(tmp_path_factory):
    """Four synthetic scans plus the geometry demo.py derives from them."""
    root = tmp_path_factory.mktemp("scans")
    paths = {}
    for eid in demo.EDITION_ORDER:
        topo_id = demo.EXPECTED_EDITIONS[eid]["source_id"]
        wkt = (
            LCC_WKT
            if demo.EXPECTED_EDITIONS[eid]["kind"] == "orthophotoquad"
            else POLYCONIC_WKT
        )
        paths[eid] = write_fixture_scan(root / f"{topo_id}_geo.tif", wkt)
    reports = {
        eid: demo.inspect_source(
            paths[eid], index_row(demo.EXPECTED_EDITIONS[eid]["source_id"])
        )
        for eid in demo.EDITION_ORDER
    }
    return paths, reports


class Tree:
    def __init__(self, base, manifest):
        self.base = base
        self.manifest = manifest
        self.raw_root = base / "raw"
        self.manifest_path = base / "demo-editions.json"
        self.receipts_path = base / "retrievals.jsonl"
        self.index_path = base / "topo_index.csv"
        self.sources_path = base / "sources.yml"

    def write_manifest(self, manifest=None):
        payload = self.manifest if manifest is None else manifest
        self.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def write_receipts(self, records):
        self.receipts_path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
        )

    def run(self, *args):
        return CliRunner().invoke(
            demo.cli,
            [
                "check",
                "--manifest",
                str(self.manifest_path),
                "--schema",
                str(demo.SCHEMA_PATH),
                "--index",
                str(self.index_path),
                "--receipts",
                str(self.receipts_path),
                "--sources",
                str(self.sources_path),
                "--raw-root",
                str(self.raw_root),
                *args,
            ],
        )


@pytest.fixture
def tree(tmp_path, scans):
    paths, reports = scans
    base = tmp_path / "tree"
    (base / "raw" / "topo").mkdir(parents=True)
    fixture = Tree(base, build_manifest(reports))
    records = []
    for eid in demo.EDITION_ORDER:
        topo_id = demo.EXPECTED_EDITIONS[eid]["source_id"]
        target = base / "raw" / "topo" / f"{topo_id}_geo.tif"
        os.link(paths[eid], target)
        records.append(receipt(topo_id, target, base / "raw"))
    fixture.write_receipts(records)
    fixture.write_manifest()
    with fixture.index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=topo.COLUMNS)
        writer.writeheader()
        writer.writerows(index_row(t) for t in INDEX_ROWS)
    fixture.sources_path.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "usgs-historical-topo",
                        "rights": "public_domain",
                        "attribution": ATTRIBUTION,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return fixture


def failure(tree, mutate, *, args=()):
    manifest = copy.deepcopy(tree.manifest)
    mutate(manifest)
    tree.write_manifest(manifest)
    result = tree.run(*args)
    assert result.exit_code != 0, result.output
    return str(result.exception) + result.output


# --- the contract holds on a fresh tree of only the selected inputs -------------------


def test_fixture_tree_of_only_selected_inputs_passes(tree):
    result = tree.run()
    assert result.exit_code == 0, result.output
    for eid in demo.EDITION_ORDER:
        assert eid in result.output
    assert "4 public editions verified" in result.output


def test_check_reports_each_source_hash(tree):
    result = tree.run()
    assert result.exit_code == 0, result.output
    for record in demo.load_receipts(tree.receipts_path):
        assert record["sha256"] in result.output
        assert str(record["byte_count"]) in result.output


def test_check_writes_nothing_to_raw_or_receipts(tree):
    before = {
        path: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted((tree.raw_root / "topo").iterdir())
    }
    receipts_before = (
        tree.receipts_path.stat().st_mtime_ns,
        hashlib.sha256(tree.receipts_path.read_bytes()).hexdigest(),
    )
    assert tree.run().exit_code == 0
    after = {
        path: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted((tree.raw_root / "topo").iterdir())
    }
    assert after == before
    assert (
        tree.receipts_path.stat().st_mtime_ns,
        hashlib.sha256(tree.receipts_path.read_bytes()).hexdigest(),
    ) == receipts_before


def test_check_opens_no_socket(tree, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("demo check must not use the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    result = tree.run()
    assert result.exit_code == 0, result.output


def test_check_reads_only_the_selected_bytes(tree):
    """91 sheets are indexed; a fresh build needs only the four selected files."""
    extra = tree.raw_root / "topo" / "CA_Auburn_100355_1953_24000_geo.tif"
    assert not extra.exists()
    assert len(list((tree.raw_root / "topo").iterdir())) == 4
    assert tree.run().exit_code == 0


# --- manifest shape ------------------------------------------------------------------


def test_missing_edition_rejected(tree):
    message = failure(tree, lambda m: m["editions"].pop())
    assert "schema" in message.lower()


def test_duplicate_edition_rejected(tree):
    def mutate(manifest):
        manifest["editions"][1]["id"] = manifest["editions"][0]["id"]

    assert "Duplicate edition id" in failure(tree, mutate)


def test_extra_edition_rejected(tree):
    def mutate(manifest):
        manifest["editions"].append(copy.deepcopy(manifest["editions"][0]))

    assert "schema" in failure(tree, mutate).lower()


def test_reordered_editions_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0], manifest["editions"][1] = (
            manifest["editions"][1],
            manifest["editions"][0],
        )

    assert "edition_order" in failure(tree, mutate)


def test_unknown_edition_field_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0]["access_right"] = "public may pass"

    assert "access_right" in failure(tree, mutate)


def test_unknown_top_level_field_rejected(tree):
    def mutate(manifest):
        manifest["deploy_host"] = "example.test"

    assert "deploy_host" in failure(tree, mutate)


def test_unknown_date_field_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0]["dates"]["start_year"] = 1953

    assert "start_year" in failure(tree, mutate)


def test_changed_tile_zoom_rejected(tree):
    def mutate(manifest):
        manifest["tile_zoom"]["max"] = 18

    assert "schema" in failure(tree, mutate).lower()


# --- dates ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1973-02-30", "1973-13-01", "1973-00-01"])
def test_impossible_calendar_date_rejected(tree, value):
    def mutate(manifest):
        manifest["editions"][1]["dates"]["revision_photography"] = value

    assert "calendar date" in failure(tree, mutate)


def test_photography_year_outside_range_rejected(tree):
    def mutate(manifest):
        manifest["editions"][2]["dates"]["photography"] = "1775"

    assert "calendar date" in failure(tree, mutate)


def test_wrong_map_year_rejected(tree):
    def mutate(manifest):
        manifest["editions"][3]["dates"]["map_year"] = 1981

    assert "differ from the fixed contract" in failure(tree, mutate)


def test_revision_claimed_field_checked_rejected(tree):
    def mutate(manifest):
        manifest["editions"][1]["dates"]["revision_field_checked"] = True

    assert "differ from the fixed contract" in failure(tree, mutate)


def test_date_note_must_disclose_unchecked_revision(tree):
    def mutate(manifest):
        manifest["editions"][3]["date_note"] = "1953 base sheet, revised 1981."

    assert "not field checked" in failure(tree, mutate)


def test_index_date_disagreement_rejected(tree):
    """A manifest that matches the contract but not the per-sheet index still fails."""
    rows = [index_row(t) for t in INDEX_ROWS]
    for row in rows:
        if row["topo_id"] == "CA_Auburn_288105_1953_24000":
            row["aerial_photo_year"] = "1979"
    with tree.index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=topo.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "aerial_photo_year" in result.output


# --- kind and rights ------------------------------------------------------------------


def test_orthophotoquad_kind_mismatch_rejected(tree):
    def mutate(manifest):
        manifest["editions"][2]["kind"] = "topo"

    assert "differs from the contract" in failure(tree, mutate)


def test_topo_kind_mismatch_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0]["kind"] = "orthophotoquad"

    assert "differs from the contract" in failure(tree, mutate)


def test_nonpublic_rights_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0]["rights"] = "cc_by_nc_sa"

    assert "schema" in failure(tree, mutate).lower()


def test_nonpublic_index_rights_rejected(tree):
    rows = [index_row(t) for t in INDEX_ROWS]
    rows[0]["rights"] = "unknown"
    with tree.index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=topo.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "not public_domain" in result.output


def test_attribution_must_match_sources_yml(tree):
    def mutate(manifest):
        manifest["editions"][0]["attribution"] = "Auburn Trails Council"

    assert "attribution" in failure(tree, mutate)


def test_unknown_source_id_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0]["source_id"] = "CA_Auburn_288100_1953_24000"

    assert "schema" in failure(tree, mutate).lower()


# --- bounds and crop ------------------------------------------------------------------


def test_inverted_longitude_bounds_rejected(tree):
    def mutate(manifest):
        west, south, east, north = manifest["view_bounds_wgs84"]
        manifest["view_bounds_wgs84"] = [east, south, west, north]

    assert "inverted in longitude" in failure(tree, mutate)


def test_inverted_latitude_bounds_rejected(tree):
    def mutate(manifest):
        west, south, east, north = manifest["view_bounds_wgs84"]
        manifest["view_bounds_wgs84"] = [west, north, east, south]

    assert "inverted in latitude" in failure(tree, mutate)


def test_bounds_wider_than_common_footprint_rejected(tree):
    def mutate(manifest):
        manifest["view_bounds_wgs84"][0] -= 0.01

    assert "common mapped footprint" in failure(tree, mutate)


def test_crop_outside_the_source_rejected(tree):
    def mutate(manifest):
        ring = manifest["editions"][0]["crop_wgs84"]["coordinates"][0]
        manifest["editions"][0]["crop_wgs84"]["coordinates"][0] = [
            [demo.q6(lon + 0.5), lat] for lon, lat in ring
        ]
        manifest["view_bounds_wgs84"] = manifest["view_bounds_wgs84"]

    assert "outside the georeferenced source footprint" in failure(tree, mutate)


def test_crop_off_the_neatline_rejected(tree):
    def mutate(manifest):
        ring = manifest["editions"][0]["crop_wgs84"]["coordinates"][0]
        manifest["editions"][0]["crop_wgs84"]["coordinates"][0] = [
            [demo.q6(lon + 0.002), lat] for lon, lat in ring
        ]

    assert "off the inspected neatline" in failure(tree, mutate)


def test_unclosed_crop_ring_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0]["crop_wgs84"]["coordinates"][0].pop()

    assert "not closed" in failure(tree, mutate)


def test_excess_coordinate_precision_rejected(tree):
    def mutate(manifest):
        ring = manifest["editions"][0]["crop_wgs84"]["coordinates"][0]
        ring[0] = [ring[0][0] + 1e-9, ring[0][1]]
        ring[-1] = list(ring[0])

    assert "decimal places" in failure(tree, mutate)


def test_scan_margin_is_excluded_from_the_crop(tree, scans):
    """The verified crop must sit inside the scan, not on its outer edge."""
    _, reports = scans
    for eid in demo.EDITION_ORDER:
        crop = shape(reports[eid]["crop_wgs84"])
        footprint = shape(reports[eid]["source_footprint_wgs84"])
        assert crop.within(footprint)
        assert crop.area < footprint.area
        for locator in reports[eid]["neatline_locators_px"].values():
            assert abs(locator["offset_from_graticule_px"]) <= 2
            assert locator["darkest_mean_value"] < locator["profile_median_value"]


def test_scan_without_a_neatline_cannot_be_verified(tmp_path, scans):
    crs = CRS.from_wkt(POLYCONIC_WKT)
    paths, _ = scans
    with rasterio.open(paths["auburn-1953"]) as source:
        profile = source.profile
    blank = tmp_path / "blank_geo.tif"
    with rasterio.open(blank, "w", **profile) as dataset:
        dataset.write(np.full((profile["height"], profile["width"]), 255, dtype="uint8"), 1)
    assert crs is not None
    with pytest.raises(Exception, match="no west neatline found"):
        demo.inspect_source(blank, index_row("CA_Auburn_288101_1953_24000"))


def test_scan_without_a_crs_cannot_be_verified(tmp_path):
    path = tmp_path / "nocrs_geo.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=8, height=8, count=1, dtype="uint8"
    ) as dataset:
        dataset.write(np.zeros((8, 8), dtype="uint8"), 1)
    with pytest.raises(Exception, match="no CRS"):
        demo.inspect_source(path, index_row("CA_Auburn_288101_1953_24000"))


def test_datum_transformation_is_named_and_not_ballpark(scans):
    _, reports = scans
    for report in reports.values():
        note = report["datum_transformation"]
        assert note["description"]
        assert "ballpark" not in note["description"].lower()
        assert note["accuracy_metres"] >= 0


# --- receipts and bytes ---------------------------------------------------------------


def test_missing_receipt_rejected(tree):
    records = [
        record
        for record in demo.load_receipts(tree.receipts_path)
        if record["topo_id"] != "CA_Auburn_288104_1975_24000"
    ]
    tree.write_receipts(records)
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "no retrieval receipt" in result.output


def test_ambiguous_receipts_rejected(tree):
    records = demo.load_receipts(tree.receipts_path)
    duplicate = dict(records[0])
    digest = duplicate["sha256"]
    duplicate["raw_path"] = f"topo/sha256/{digest[:2]}/{digest}.tif"
    tree.write_receipts([*records, duplicate])
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "ambiguous receipts" in result.output


def test_missing_selected_bytes_rejected(tree):
    (tree.raw_root / "topo" / "CA_Auburn_288103_1953_24000_geo.tif").unlink()
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "selected source bytes are missing" in result.output


def test_checksum_mismatch_rejected(tree):
    target = tree.raw_root / "topo" / "CA_Auburn_288101_1953_24000_geo.tif"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF
    target.unlink()
    target.write_bytes(bytes(data))
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "Checksum mismatch" in result.output


def test_byte_count_mismatch_rejected(tree):
    target = tree.raw_root / "topo" / "CA_Auburn_288101_1953_24000_geo.tif"
    data = target.read_bytes()
    target.unlink()
    target.write_bytes(data + b"\x00")
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "Checksum mismatch" in result.output


def test_missing_ledger_rejected(tree):
    tree.receipts_path.unlink()
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "retrieval ledger" in result.output


# --- the committed manifest -----------------------------------------------------------


def test_committed_manifest_meets_the_contract():
    """Runs without data/raw: schema, allowlist, dates, rights and ring geometry."""
    manifest = demo.read_json(demo.MANIFEST_PATH)
    crops = demo.check_metadata(manifest, demo.SCHEMA_PATH, demo.INDEX_PATH, demo.SOURCES_PATH)
    assert sorted(crops) == sorted(demo.EDITION_ORDER)


def real_raw_root():
    root = os.environ.get("DEMO_RAW_ROOT")
    return demo.RAW_ROOT if root is None else type(demo.RAW_ROOT)(root)


def selected_real_paths():
    root = real_raw_root()
    paths = {}
    for eid in demo.EDITION_ORDER:
        topo_id = demo.EXPECTED_EDITIONS[eid]["source_id"]
        candidate = root / "topo" / f"{topo_id}_geo.tif"
        if not candidate.exists():
            return None
        paths[eid] = candidate
    return paths


needs_real_bytes = pytest.mark.skipif(
    selected_real_paths() is None,
    reason="selected source bytes are not present; set DEMO_RAW_ROOT or run make fetch-topo",
)


@needs_real_bytes
def test_committed_manifest_matches_the_real_sources():
    result = CliRunner().invoke(
        demo.cli, ["check", "--raw-root", str(real_raw_root())], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    assert "4 public editions verified" in result.output


@needs_real_bytes
def test_real_tree_with_only_the_selected_inputs(tmp_path):
    """A fresh checkout holding only the four selected scans passes unchanged."""
    paths = selected_real_paths()
    raw_root = tmp_path / "raw"
    (raw_root / "topo").mkdir(parents=True)
    for source in paths.values():
        target = raw_root / "topo" / source.name
        try:
            os.link(source, target)
        except OSError:
            target.write_bytes(source.read_bytes())
    assert len(list((raw_root / "topo").iterdir())) == 4
    result = CliRunner().invoke(
        demo.cli, ["check", "--raw-root", str(raw_root)], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
