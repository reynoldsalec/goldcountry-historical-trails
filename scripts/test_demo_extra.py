"""Offline tests for the extra map options (scripts/demo_extra.py) and their publication."""

from __future__ import annotations

import json
from pathlib import Path

import build_site
import click
import demo_extra
import numpy as np
import pytest

CATALOG = demo_extra.load_catalog()
SCAN = next(e for e in CATALOG["editions"] if e["processing"]["method"] == "gcp_polynomial")
REPORT = json.loads(
    (demo_extra.REPO_ROOT / SCAN["processing"]["control"]["report_path"]).read_text()
)


def square_section(plssid: str, number: int, west: float, south: float) -> dict:
    size = 0.0185  # roughly one mile at 39 N
    ring = [
        [west, south],
        [west + size, south],
        [west + size, south + size],
        [west, south + size],
    ]
    return {
        "attributes": {"PLSSID": plssid, "FRSTDIVNO": str(number), "FRSTDIVTYP": "SN"},
        "rings": [ring + [ring[0]]],
    }


def test_township_corners_key_shared_corners_once():
    document = {
        "features": [
            square_section("CA210130N0090E0", 31, -121.0, 38.9),
            square_section("CA210130N0080E0", 36, -121.0185, 38.9),
        ]
    }
    corners = demo_extra.township_corners(document)
    # T13N R9E sec 31 SW and T13N R8E sec 36 SE are the same corner: range line 8, tier 12.
    shared = corners[(8, 12)]
    assert len(shared["sections"]) == 2
    assert shared["spread_m"] < 1.0
    assert shared["lon"] == pytest.approx(-121.0)


def test_fit_rejects_a_corner_snapped_one_section_off():
    rng = np.random.default_rng(1)
    points = []
    for i in range(6):
        for j in range(6):
            x, y = i * 9600.0, j * 9600.0
            points.append(
                {"pixel_x": x / 16 + rng.normal(0, 3), "pixel_y": -y / 16, "x": x, "y": y}
            )
    points[10]["pixel_x"] += 100  # one section (~1.6 km) to the east
    fit = demo_extra.fit_control(points, 2)
    assert not fit["keep"][10]
    assert fit["keep"].sum() == len(points) - 1
    assert fit["rms_m"] < 100


def test_points_file_round_trips_through_gdal_gcps(tmp_path: Path):
    rows = [
        {"lon": -121.0 + i / 10, "lat": 39.0 + i / 20, "pixel_x": 10.0 * i, "pixel_y": 5.0 * i}
        for i in range(12)
    ]
    path = tmp_path / "x.points"
    demo_extra.write_points(path, rows)
    gcps = demo_extra.read_points(path)
    assert [(g.col, g.row, g.x, g.y) for g in gcps][3] == (30.0, 15.0, -120.7, 39.15)


def test_too_few_points_are_refused(tmp_path: Path):
    path = tmp_path / "x.points"
    demo_extra.write_points(path, [{"lon": 0, "lat": 0, "pixel_x": 0, "pixel_y": 0}] * 3)
    with pytest.raises(click.ClickException):
        demo_extra.read_points(path)


def test_committed_control_matches_its_report_and_passes_checkpoints():
    points = (demo_extra.REPO_ROOT / SCAN["processing"]["control"]["points_path"]).read_text()
    assert len(points.splitlines()) - 2 == REPORT["summary"]["control_points"]
    settings = SCAN["processing"]["control"]["checkpoints"]
    assert {c["name"] for c in REPORT["checkpoints"]} == set(settings["pixels"])
    assert max(c["error_m"] for c in REPORT["checkpoints"]) <= settings["max_error_metres"]


def test_catalog_keeps_the_nine_in_order_and_only_public_domain():
    nine = json.loads(demo_extra.NINE_MANIFEST_PATH.read_text())["edition_order"]
    order = CATALOG["published_order"]
    assert [eid for eid in order if eid in nine] == nine
    assert all(edition["rights"] == "public_domain" for edition in CATALOG["editions"])
    assert SCAN["scale"] is None


def test_registration_note_states_the_measured_error():
    note = demo_extra.registration_note({"control_points": 73, "rms_m": 380.6, "max_m": 1001.1})
    assert "73 printed township corners" in note
    assert "about 380 m" in note and "1000 m" in note


def test_native_zoom_matches_the_nine_edition_rule():
    assert demo_extra.native_zoom(2.03, 39.0) == 16
    assert demo_extra.native_zoom(5.29, 39.0) == 15
    assert demo_extra.native_zoom(10.58, 39.0) == 14
    assert demo_extra.native_zoom(16.2, 39.0) == 13


def test_public_editions_carry_coverage_and_no_internal_fields():
    manifest = json.loads(demo_extra.NINE_MANIFEST_PATH.read_text())
    zooms = {eid: 13 for eid in manifest["edition_order"]}
    payload = build_site.sanitize_manifest(manifest, manifest["tile_zoom"], zooms)
    assert payload["pan_bounds_wgs84"] == manifest["view_bounds_wgs84"]
    for edition in payload["editions"]:
        assert edition["coverage_bounds_wgs84"] == manifest["view_bounds_wgs84"]
        assert edition["registration_note"] is None
    for name in (
        demo_extra.CATALOG_PATH.name,
        demo_extra.LEDGER_PATH.name,
        demo_extra.RECORD_NAME,
    ):
        assert name in build_site.PROHIBITED_NAMES
