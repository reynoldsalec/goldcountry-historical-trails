"""Coverage inventory validation contract (issue #12).

Every fixture here is synthetic and built in a tmp path: the grid, the index, the source
manifest, the AOI and the inventory. The committed inventory is only ever read, never
edited to make a case pass — a release-ready fixture is invented data about nothing.
"""

import csv
import json
from pathlib import Path

import coverage
import fetch_topoview
import pytest
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = REPO_ROOT / "data" / "sources"
SCHEMA = REPO_ROOT / "schema" / "coverage.schema.json"
GRID_SCHEMA = REPO_ROOT / "schema" / "coverage_grid.schema.json"

DECADES = [1950, 1960, 1970, 1980, 1990, 2000]
# Two cells per county, side by side, inside the synthetic AOI below.
AREAS = {
    "q7p5-1-1": (-121.0, 39.0, "06057"),
    "q7p5-2-1": (-120.875, 39.0, "06057"),
    "q7p5-1-2": (-121.0, 39.125, "06061"),
    "q7p5-2-2": (-120.875, 39.125, "06061"),
}
SIZE = 0.125
AOI_BOX = (-121.0, 39.0, -120.75, 39.25)
TOPO_ID = "CA_Synthetic_Quad_000001_1955_24000"


def polygon(west, south, east, north):
    return {
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
    }


def write_grid(tmp_path, areas=None):
    areas = AREAS if areas is None else areas
    features = [
        {
            "type": "Feature",
            "geometry": polygon(west, south, west + SIZE, south + SIZE),
            "properties": {"area_id": area_id, "county_geoids": [geoid]},
        }
        for area_id, (west, south, geoid) in sorted(areas.items())
    ]
    path = tmp_path / "grid.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


def write_aoi(tmp_path):
    path = tmp_path / "aoi.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": polygon(*AOI_BOX),
                        "properties": {},
                    }
                ],
            }
        )
    )
    return path


def write_index(tmp_path):
    row = {column: "" for column in fetch_topoview.COLUMNS}
    row.update(
        {
            "topo_id": TOPO_ID,
            "map_name": "Synthetic Quad",
            "west": "-121.0",
            "south": "39.0",
            "east": "-120.875",
            "north": "39.125",
            "date_on_map": "1955",
        }
    )
    path = tmp_path / "topo_index.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fetch_topoview.COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    return path


def write_sources(tmp_path):
    path = tmp_path / "sources.yml"
    path.write_text("sources:\n  - id: usgs-historical-topo\n  - id: ucsb-framefinder\n")
    return path


def cell(area_id, decade, **changes):
    record = {
        "area_id": area_id,
        "decade": decade,
        "source_refs": [],
        "search_ids": [],
        "review_ids": [],
        "batch_ids": [],
        "gap_codes": ["not_digitized", "not_examined", "unsearched"],
        "gap_note": None,
    }
    record.update(changes)
    return record


def inventory(**changes):
    """A complete grid of explicit unsearched gaps: nothing looked at, nothing claimed."""
    document = {
        "version": 1,
        "through_decade": DECADES[-1],
        "cells": [cell(area_id, decade) for area_id in sorted(AREAS) for decade in DECADES],
        "candidates": [],
        "searches": [],
        "reviews": [],
        "batches": [],
    }
    document.update(changes)
    return document


def candidate(candidate_id="frame-one", **changes):
    record = {
        "candidate_id": candidate_id,
        "kind": "aerial_frame",
        "collection_id": "ucsb-framefinder",
        "title": "Synthetic flight line, fixture only",
        "url": None,
        "date_start": "1975",
        "date_end": None,
        "west": -121.0,
        "south": 39.0,
        "east": -120.75,
        "north": 39.25,
        "rights": "public_domain",
        "sensitivity": "public",
        "attribution": None,
        "verification": "verified",
        "source_identifier": "SYNTHETIC-FRAME-0001",
        "access": "available",
    }
    record.update(changes)
    return record


def search(search_id="search-one", **changes):
    record = {
        "search_id": search_id,
        "searched_at": "2026-09-16T17:04:00Z",
        "collection_id": "usgs-historical-topo",
        "area_ids": ["q7p5-1-1"],
        "decades": [1950],
        "query": "synthetic quad search",
        "outcome": "no_match",
        "source_refs": [],
        "note": None,
    }
    record.update(changes)
    return record


def review(review_id="review-one", **changes):
    record = {
        "review_id": review_id,
        "source_ref": "candidate:frame-one",
        "area_id": "q7p5-1-1",
        "county_geoid": "06057",
        "decade": 1950,
        "reviewed_at": "2026-09-16T18:00:00Z",
        "reviewer_id": "reviewer-one",
        "scope": "partial",
        "foot_trail_evidence": "yes",
        "dating": "resolved",
        "evidence_locator": "sheet quarter NE, fixture only",
        "note": None,
    }
    record.update(changes)
    return record


def batch(batch_id="batch-one", **changes):
    record = {
        "batch_id": batch_id,
        "county_geoid": "06057",
        "area_ids": ["q7p5-1-1"],
        "decade": 1950,
        "source_refs": ["candidate:frame-one"],
        "review_ids": ["review-one"],
        "tasks": ["digitize the reviewed foot trail"],
        "gap_note": None,
        "status": "ready",
        "alignment_ids": [],
    }
    record.update(changes)
    return record


def run(tmp_path, document, release_ready=False, areas=None):
    data = tmp_path / "coverage.json"
    data.write_text(json.dumps(document))
    args = [
        "validate",
        "--data",
        str(data),
        "--grid",
        str(write_grid(tmp_path, areas)),
        "--index",
        str(write_index(tmp_path)),
        "--sources",
        str(write_sources(tmp_path)),
        "--aoi",
        str(write_aoi(tmp_path)),
        "--schema",
        str(SCHEMA),
        "--grid-schema",
        str(GRID_SCHEMA),
    ]
    if release_ready:
        args.append("--release-ready")
    return CliRunner().invoke(coverage.cli, args)


def fails(tmp_path, document, fragment, release_ready=False):
    result = run(tmp_path, document, release_ready)
    assert result.exit_code == 1, result.output
    assert fragment in result.output, result.output
    return result


# --------------------------------------------------------------------------------------
# Explicit gaps pass
# --------------------------------------------------------------------------------------


def test_complete_grid_of_unsearched_gaps_passes(tmp_path):
    result = run(tmp_path, inventory())
    assert result.exit_code == 0, result.output


def test_committed_inventory_passes(tmp_path):
    result = CliRunner().invoke(coverage.cli, ["validate"])
    assert result.exit_code == 0, result.output


def test_committed_inventory_is_not_release_ready(tmp_path):
    result = CliRunner().invoke(coverage.cli, ["validate", "--release-ready"])
    assert result.exit_code == 1
    assert "FAIL [release]" in result.output


# --------------------------------------------------------------------------------------
# Cell coverage
# --------------------------------------------------------------------------------------


def test_missing_cell_fails(tmp_path):
    document = inventory()
    document["cells"] = [c for c in document["cells"] if c["decade"] != 1970]
    fails(tmp_path, document, "the inventory has no such cell")


def test_duplicate_cell_fails(tmp_path):
    document = inventory()
    document["cells"].append(cell("q7p5-1-1", 1950))
    fails(tmp_path, document, "area_id + decade appears twice")


def test_cell_outside_the_grid_fails(tmp_path):
    document = inventory()
    document["cells"].append(cell("q7p5-9-9", 1950))
    fails(tmp_path, document, "area_id is absent from the grid")


def test_cell_beyond_through_decade_fails(tmp_path):
    document = inventory()
    document["cells"].append(cell("q7p5-1-1", 2010))
    fails(tmp_path, document, "decade is outside 1950..2000")


# --------------------------------------------------------------------------------------
# Dangling references, one case per reference kind
# --------------------------------------------------------------------------------------


def with_cell(document, area_id, decade, **changes):
    for item in document["cells"]:
        if item["area_id"] == area_id and item["decade"] == decade:
            item.update(changes)
            return document
    raise AssertionError(f"fixture has no cell {area_id}/{decade}")


def test_dangling_topo_ref_fails(tmp_path):
    document = with_cell(inventory(), "q7p5-1-1", 1950, source_refs=["topo:CA_Absent_1_1953"])
    fails(tmp_path, document, "is absent from topo_index.csv")


def test_dangling_candidate_ref_fails(tmp_path):
    document = with_cell(inventory(), "q7p5-1-1", 1950, source_refs=["candidate:frame-absent"])
    fails(tmp_path, document, "is absent from candidates")


def test_dangling_search_ref_fails(tmp_path):
    document = with_cell(inventory(), "q7p5-1-1", 1950, search_ids=["search-absent"])
    fails(tmp_path, document, "search search-absent does not exist")


def test_dangling_review_ref_fails(tmp_path):
    document = with_cell(inventory(), "q7p5-1-1", 1950, review_ids=["review-absent"])
    fails(tmp_path, document, "review review-absent does not exist")


def test_dangling_batch_ref_fails(tmp_path):
    document = with_cell(inventory(), "q7p5-1-1", 1950, batch_ids=["batch-absent"])
    fails(tmp_path, document, "batch batch-absent does not exist")


def test_dangling_batch_review_fails(tmp_path):
    document = inventory(batches=[batch(review_ids=["review-absent"], status="planned")])
    fails(tmp_path, document, "review review-absent does not exist")


def test_search_naming_an_unknown_area_fails(tmp_path):
    document = inventory(searches=[search(area_ids=["q7p5-9-9"])])
    fails(tmp_path, document, "area q7p5-9-9 is absent from the grid")


def test_review_naming_an_unknown_source_fails(tmp_path):
    document = inventory(
        candidates=[candidate()], reviews=[review(source_ref="candidate:frame-absent")]
    )
    fails(tmp_path, document, "is absent from candidates")


def test_unknown_candidate_collection_fails(tmp_path):
    document = inventory(candidates=[candidate(collection_id="not-a-collection")])
    fails(tmp_path, document, "collection not-a-collection is absent from sources.yml")


def test_unknown_search_collection_fails(tmp_path):
    document = inventory(searches=[search(collection_id="not-a-collection")])
    fails(tmp_path, document, "collection not-a-collection is absent from sources.yml")


# --------------------------------------------------------------------------------------
# A linked record must be about the cell that links it
# --------------------------------------------------------------------------------------


def test_cross_cell_review_fails(tmp_path):
    document = inventory(candidates=[candidate()], reviews=[review()])
    document = with_cell(document, "q7p5-2-1", 1960, review_ids=["review-one"])
    fails(tmp_path, document, "not this cell")


def test_cross_cell_search_fails(tmp_path):
    document = inventory(searches=[search()])
    document = with_cell(document, "q7p5-2-1", 1960, search_ids=["search-one"])
    fails(tmp_path, document, "covers another area or decade")


def test_review_county_outside_its_area_fails(tmp_path):
    document = inventory(candidates=[candidate()], reviews=[review(county_geoid="06061")])
    fails(tmp_path, document, "does not meet area q7p5-1-1")


def test_candidate_bounds_off_the_cell_fails(tmp_path):
    far = candidate(west=-119.0, south=37.0, east=-118.875, north=37.125)
    document = inventory(candidates=[far])
    document = with_cell(document, "q7p5-1-1", 1950, source_refs=["candidate:frame-one"])
    fails(tmp_path, document, "does not reach this area's footprint")


# --------------------------------------------------------------------------------------
# Gap flags need a record behind them
# --------------------------------------------------------------------------------------


def test_no_source_located_without_a_search_fails(tmp_path):
    document = with_cell(
        inventory(),
        "q7p5-1-1",
        1950,
        gap_codes=["no_source_located", "not_digitized", "not_examined"],
    )
    fails(tmp_path, document, "needs a linked search with outcome no_match")


def test_no_source_located_with_a_matching_search_passes(tmp_path):
    document = inventory(searches=[search()])
    document = with_cell(
        document,
        "q7p5-1-1",
        1950,
        search_ids=["search-one"],
        gap_codes=["no_source_located", "not_digitized", "not_examined"],
    )
    result = run(tmp_path, document)
    assert result.exit_code == 0, result.output


def test_access_blocked_without_a_search_fails(tmp_path):
    document = with_cell(
        inventory(),
        "q7p5-1-1",
        1950,
        gap_codes=["access_blocked", "not_digitized", "not_examined"],
    )
    fails(tmp_path, document, "needs a linked search with outcome access_blocked")


def test_clearing_not_digitized_without_a_digitized_batch_fails(tmp_path):
    document = with_cell(inventory(), "q7p5-1-1", 1950, gap_codes=["not_examined"])
    fails(tmp_path, document, "not_digitized was cleared without a digitized batch")


# --------------------------------------------------------------------------------------
# Batches
# --------------------------------------------------------------------------------------


def test_digitized_batch_is_rejected_in_m1(tmp_path):
    document = inventory(
        candidates=[candidate()], reviews=[review()], batches=[batch(status="digitized")]
    )
    fails(tmp_path, document, "status digitized is rejected until M3")


def test_batch_alignment_ids_are_rejected_in_m1(tmp_path):
    document = inventory(
        candidates=[candidate()],
        reviews=[review()],
        batches=[batch(alignment_ids=["alignment-one"])],
    )
    fails(tmp_path, document, "alignment_ids stays empty until M3")


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"tasks": []}, "no review tasks"),
        ({"source_refs": []}, "no source_refs"),
        ({"review_ids": []}, "without a dated, located foot-trail review"),
        ({"county_geoid": "06061"}, "no listed area meets county 06061"),
        ({"decade": 1960}, "without a dated, located foot-trail review"),
    ],
)
def test_unsupported_ready_batch_fails(tmp_path, changes, fragment):
    document = inventory(
        candidates=[candidate()], reviews=[review()], batches=[batch(**changes)]
    )
    fails(tmp_path, document, fragment)


@pytest.mark.parametrize(
    "changes",
    [
        {"dating": "unresolved"},
        {"foot_trail_evidence": "uncertain", "evidence_locator": None},
        {"area_id": "q7p5-2-1"},
    ],
)
def test_ready_batch_needs_a_qualifying_review(tmp_path, changes):
    document = inventory(
        candidates=[candidate()], reviews=[review(**changes)], batches=[batch()]
    )
    fails(tmp_path, document, "without a dated, located foot-trail review")


# --------------------------------------------------------------------------------------
# Dates and timestamps
# --------------------------------------------------------------------------------------


def test_impossible_candidate_date_fails(tmp_path):
    document = inventory(candidates=[candidate(date_start="1975-02-30")])
    fails(tmp_path, document, "is not a real calendar date")


def test_reversed_candidate_range_fails(tmp_path):
    document = inventory(candidates=[candidate(date_start="1975", date_end="1970")])
    fails(tmp_path, document, "precedes date_start")


def test_impossible_review_timestamp_fails(tmp_path):
    document = inventory(
        candidates=[candidate()], reviews=[review(reviewed_at="2026-13-01T00:00:00Z")]
    )
    fails(tmp_path, document, "is not a valid UTC instant")


# --------------------------------------------------------------------------------------
# --release-ready
# --------------------------------------------------------------------------------------


def release_fixture(**changes):
    """Four ready county/decade batches and one obtainable aerial frame, all invented."""
    reviews = []
    batches = []
    plan = [
        ("06057", "q7p5-1-1", 1950),
        ("06057", "q7p5-2-1", 2000),
        ("06061", "q7p5-1-2", 1960),
        ("06061", "q7p5-2-2", 2000),
    ]
    for index, (county, area_id, decade) in enumerate(plan, start=1):
        review_id = f"review-{index}"
        reviews.append(review(review_id, area_id=area_id, county_geoid=county, decade=decade))
        batches.append(
            batch(
                f"batch-{index}",
                county_geoid=county,
                area_ids=[area_id],
                decade=decade,
                review_ids=[review_id],
            )
        )
    document = inventory(candidates=[candidate()], reviews=reviews, batches=batches)
    for item in document["cells"]:
        for (_, area_id, decade), record in zip(plan, batches, strict=True):
            if item["area_id"] == area_id and item["decade"] == decade:
                item["review_ids"] = record["review_ids"]
                item["batch_ids"] = [record["batch_id"]]
                item["source_refs"] = ["candidate:frame-one"]
    document.update(changes)
    return document


def test_release_ready_accepts_the_synthetic_fixture(tmp_path):
    result = run(tmp_path, release_fixture(), release_ready=True)
    assert result.exit_code == 0, result.output


def test_release_ready_rejects_a_grid_of_gaps_with_every_missing_criterion(tmp_path):
    result = run(tmp_path, inventory(), release_ready=True)
    assert result.exit_code == 1
    assert "no verified, available, dated aerial_frame candidate" in result.output
    for county in ("06057", "06061"):
        assert f"FAIL [release] county {county}: needs two decades" in result.output
        assert f"FAIL [release] county {county}: no status ready batch in a decade before" in (
            result.output
        )
        assert f"FAIL [release] county {county}: no status ready batch in a decade from" in (
            result.output
        )


def test_release_ready_ignores_planned_batches(tmp_path):
    document = release_fixture()
    for item in document["batches"]:
        item["status"] = "planned"
    result = run(tmp_path, document, release_ready=True)
    assert result.exit_code == 1
    assert "needs two decades of status ready batches" in result.output


def test_release_ready_needs_one_decade_from_2000_onward(tmp_path):
    document = release_fixture()
    for item in document["batches"]:
        if item["batch_id"] == "batch-4":
            item["status"] = "planned"
    result = run(tmp_path, document, release_ready=True)
    assert result.exit_code == 1
    assert "county 06061: no status ready batch in a decade from 2000 onward" in result.output


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"verification": "unverified"}, "verification is not verified"),
        ({"source_identifier": None}, "no publisher source_identifier"),
        ({"access": "blocked"}, "access is blocked"),
        ({"rights": "unknown"}, "rights unknown is not a redistribution permission"),
        (
            {"west": None, "south": None, "east": None, "north": None},
            "bounds are not fully known",
        ),
        ({"date_start": "1948", "date_end": "1952"}, "date range straddles 1950"),
        ({"date_start": "1948"}, "date_start 1948 precedes 1950"),
        ({"kind": "modern_map"}, "no verified, available, dated aerial_frame candidate"),
    ],
)
def test_release_ready_aerial_prerequisites(tmp_path, changes, fragment):
    document = release_fixture(candidates=[candidate(**changes)])
    fails(tmp_path, document, fragment, release_ready=True)


def test_release_ready_aerial_outside_the_aoi_fails(tmp_path):
    far = candidate(west=-119.0, south=37.0, east=-118.875, north=37.125)
    document = release_fixture(candidates=[far])
    # The cell references would now point off the footprint, so drop them.
    for item in document["cells"]:
        item["source_refs"] = []
    for item in document["batches"]:
        item["source_refs"] = ["topo:" + TOPO_ID]
    for item in document["reviews"]:
        item["source_ref"] = "topo:" + TOPO_ID
    fails(tmp_path, document, "bounds do not reach the county AOI", release_ready=True)
