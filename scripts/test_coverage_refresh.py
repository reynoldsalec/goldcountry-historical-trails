"""Coverage inventory refresh contract (issue #11).

Grids and indexes are synthetic and built in memory. The committed inventory is checked
by regenerating it into a tmp path and comparing bytes, so the file in git can never
drift from `make coverage-refresh`.
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
COMMITTED_GRID = SOURCES_DIR / "coverage_grid.geojson"
COMMITTED_INDEX = SOURCES_DIR / "topo_index.csv"
COMMITTED_COVERAGE = SOURCES_DIR / "coverage.json"
SCHEMA = REPO_ROOT / "schema" / "coverage.schema.json"

COMMITTED_THROUGH_DECADE = 2020


def cell_feature(area_id, west, south, size=0.125):
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [west + size, south],
                    [west + size, south + size],
                    [west, south + size],
                    [west, south],
                ]
            ],
        },
        "properties": {"area_id": area_id, "county_geoids": ["06057"]},
    }


def write_grid(tmp_path, features=None):
    features = features or [
        cell_feature("q7p5-1-1", -121.0, 39.0),
        cell_feature("q7p5-2-2", -120.875, 39.125),
    ]
    path = tmp_path / "grid.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


def index_row(topo_id, **fields):
    row = {column: "" for column in fetch_topoview.COLUMNS}
    row["topo_id"] = topo_id
    row["map_name"] = topo_id
    row.update(fields)
    return row


def write_index(tmp_path, rows):
    path = tmp_path / "topo_index.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fetch_topoview.COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def inventory(**changes):
    document = {
        "version": 1,
        "through_decade": 1960,
        "cells": [],
        "candidates": [],
        "searches": [],
        "reviews": [],
        "batches": [],
    }
    document.update(changes)
    return document


def cell_record(area_id="q7p5-1-1", decade=1950, **changes):
    record = {
        "area_id": area_id,
        "decade": decade,
        "source_refs": [],
        "search_ids": [],
        "review_ids": [],
        "batch_ids": [],
        "gap_codes": [],
        "gap_note": None,
    }
    record.update(changes)
    return record


def candidate_record(candidate_id="rumsey-sheet-one", **changes):
    record = {
        "candidate_id": candidate_id,
        "kind": "modern_map",
        "collection_id": "usgs-historical-topo",
        "title": "Sheet as listed by the publisher",
        "url": None,
        "date_start": "1962",
        "date_end": None,
        "west": -121.0,
        "south": 39.0,
        "east": -120.875,
        "north": 39.125,
        "rights": "unknown",
        "sensitivity": "public",
        "attribution": None,
        "verification": "verified",
        "source_identifier": None,
        "access": "unknown",
    }
    record.update(changes)
    return record


def search_record(search_id="search-one", **changes):
    record = {
        "search_id": search_id,
        "searched_at": "2026-09-16T17:04:00Z",
        "collection_id": "usgs-historical-topo",
        "area_ids": ["q7p5-1-1"],
        "decades": [1950],
        "query": "topoview quad search",
        "outcome": "no_match",
        "source_refs": [],
        "note": None,
    }
    record.update(changes)
    return record


def review_record(review_id="review-one", **changes):
    record = {
        "review_id": review_id,
        "source_ref": "candidate:rumsey-sheet-one",
        "area_id": "q7p5-1-1",
        "county_geoid": "06057",
        "decade": 1950,
        "reviewed_at": "2026-09-16T18:00:00Z",
        "reviewer_id": "reviewer-one",
        "scope": "partial",
        "foot_trail_evidence": "uncertain",
        "dating": "unresolved",
        "evidence_locator": None,
        "note": None,
    }
    record.update(changes)
    return record


def batch_record(batch_id="batch-one", **changes):
    record = {
        "batch_id": batch_id,
        "county_geoid": "06057",
        "area_ids": ["q7p5-1-1"],
        "decade": 1950,
        "source_refs": [],
        "review_ids": [],
        "tasks": ["digitize located trails"],
        "gap_note": None,
        "status": "planned",
        "alignment_ids": [],
    }
    record.update(changes)
    return record


def run(grid, index, out, through_decade=1960):
    return CliRunner().invoke(
        coverage.cli,
        [
            "refresh",
            "--grid",
            str(grid),
            "--index",
            str(index),
            "--out",
            str(out),
            "--schema",
            str(SCHEMA),
            "--through-decade",
            str(through_decade),
        ],
    )


def refresh(tmp_path, rows=(), existing=None, features=None, through_decade=1960):
    grid = write_grid(tmp_path, features)
    index = write_index(tmp_path, rows)
    out = tmp_path / "coverage.json"
    if existing is not None:
        out.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    result = run(grid, index, out, through_decade)
    return result, out


def document_of(out: Path):
    return json.loads(out.read_text())


def refs_for(document, area_id, decade):
    for cell in document["cells"]:
        if cell["area_id"] == area_id and cell["decade"] == decade:
            return cell["source_refs"]
    raise AssertionError(f"no cell {area_id}/{decade}")


def test_empty_index_still_yields_every_area_by_decade_cell(tmp_path):
    result, out = refresh(tmp_path)
    assert result.exit_code == 0, result.output
    document = document_of(out)
    keys = [(cell["area_id"], cell["decade"]) for cell in document["cells"]]
    assert keys == [
        ("q7p5-1-1", 1950),
        ("q7p5-1-1", 1960),
        ("q7p5-2-2", 1950),
        ("q7p5-2-2", 1960),
    ]
    assert all(cell["source_refs"] == [] for cell in document["cells"])


def test_cell_count_is_areas_times_decades(tmp_path):
    features = [cell_feature(f"q7p5-{i}-1", -121.0 + i * 0.125, 39.0) for i in range(5)]
    result, out = refresh(tmp_path, features=features, through_decade=2000)
    assert result.exit_code == 0, result.output
    assert len(document_of(out)["cells"]) == 5 * 6


def test_new_cells_are_unsearched_and_not_examined(tmp_path):
    rows = [
        index_row(
            "CA_Test_1_1953_24000",
            date_on_map="1953",
            west="-121.0",
            south="39.0",
            east="-120.875",
            north="39.125",
        )
    ]
    result, out = refresh(tmp_path, rows)
    assert result.exit_code == 0, result.output
    found = [cell for cell in document_of(out)["cells"] if cell["source_refs"]]
    assert found, "the fixture sheet should attach somewhere"
    for cell in document_of(out)["cells"]:
        assert cell["gap_codes"] == ["not_digitized", "not_examined", "unsearched"]
        assert cell["review_ids"] == []
        assert cell["batch_ids"] == []
        assert cell["search_ids"] == []
        assert "partially_examined" not in cell["gap_codes"]


def test_revised_sheet_links_only_the_decades_it_dates(tmp_path):
    rows = [
        index_row(
            "CA_Test_1_1953_24000",
            date_on_map="1953",
            photo_revision_year="1981",
            west="-121.0",
            south="39.0",
            east="-120.875",
            north="39.125",
        )
    ]
    result, out = refresh(tmp_path, rows, through_decade=2000)
    assert result.exit_code == 0, result.output
    document = document_of(out)
    linked = {
        cell["decade"]
        for cell in document["cells"]
        if "topo:CA_Test_1_1953_24000" in cell["source_refs"]
    }
    assert linked == {1950, 1980}


def test_pre_1950_edition_establishes_nothing(tmp_path):
    rows = [
        index_row(
            "CA_Test_1_1901_125000",
            date_on_map="1901",
            survey_year="1899",
            west="-121.0",
            south="39.0",
            east="-120.875",
            north="39.125",
        )
    ]
    result, out = refresh(tmp_path, rows)
    assert result.exit_code == 0, result.output
    assert all(cell["source_refs"] == [] for cell in document_of(out)["cells"])


@pytest.mark.parametrize("field", ["imprint_year", "content_year"])
def test_imprint_and_content_year_alone_link_nothing(tmp_path, field):
    rows = [
        index_row(
            "CA_Test_1_1955_24000",
            west="-121.0",
            south="39.0",
            east="-120.875",
            north="39.125",
            **{field: "1955"},
        )
    ]
    result, out = refresh(tmp_path, rows)
    assert result.exit_code == 0, result.output
    assert all(cell["source_refs"] == [] for cell in document_of(out)["cells"])


def test_touching_footprint_is_not_coverage(tmp_path):
    rows = [
        index_row(
            "CA_Test_1_1953_24000",
            date_on_map="1953",
            west="-120.875",
            south="39.0",
            east="-120.75",
            north="39.125",
        )
    ]
    result, out = refresh(tmp_path, rows)
    assert result.exit_code == 0, result.output
    assert refs_for(document_of(out), "q7p5-1-1", 1950) == []


def test_sheet_without_bounds_links_nothing(tmp_path):
    rows = [index_row("CA_Test_1_1953_24000", date_on_map="1953")]
    result, out = refresh(tmp_path, rows)
    assert result.exit_code == 0, result.output
    assert all(cell["source_refs"] == [] for cell in document_of(out)["cells"])


def test_verified_candidate_with_bounds_and_date_links(tmp_path):
    existing = inventory(candidates=[candidate_record(date_start="1962")])
    result, out = refresh(tmp_path, existing=existing)
    assert result.exit_code == 0, result.output
    assert refs_for(document_of(out), "q7p5-1-1", 1960) == ["candidate:rumsey-sheet-one"]
    assert refs_for(document_of(out), "q7p5-1-1", 1950) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"verification": "unverified"},
        {"date_start": None, "date_end": None},
        {"west": None, "south": None, "east": None, "north": None},
    ],
)
def test_candidate_without_verified_bounds_or_date_is_not_linked(tmp_path, changes):
    existing = inventory(candidates=[candidate_record(**changes)])
    result, out = refresh(tmp_path, existing=existing)
    assert result.exit_code == 0, result.output
    assert all(cell["source_refs"] == [] for cell in document_of(out)["cells"])


def test_manual_records_and_cell_state_survive_refresh(tmp_path):
    existing = inventory(
        candidates=[candidate_record()],
        searches=[search_record()],
        reviews=[review_record()],
        batches=[batch_record()],
        cells=[
            cell_record(
                source_refs=["candidate:rumsey-sheet-one"],
                search_ids=["search-one"],
                review_ids=["review-one"],
                batch_ids=["batch-one"],
                gap_codes=["partially_examined"],
                gap_note="Only the northern half of the sheet was legible.",
            )
        ],
    )
    rows = [
        index_row(
            "CA_Test_1_1953_24000",
            date_on_map="1953",
            west="-121.0",
            south="39.0",
            east="-120.875",
            north="39.125",
        )
    ]
    result, out = refresh(tmp_path, rows, existing=existing)
    assert result.exit_code == 0, result.output
    document = document_of(out)
    assert document["candidates"] == existing["candidates"]
    assert document["searches"] == existing["searches"]
    assert document["reviews"] == existing["reviews"]
    assert document["batches"] == existing["batches"]
    kept = next(
        cell
        for cell in document["cells"]
        if (cell["area_id"], cell["decade"]) == ("q7p5-1-1", 1950)
    )
    assert kept["search_ids"] == ["search-one"]
    assert kept["review_ids"] == ["review-one"]
    assert kept["batch_ids"] == ["batch-one"]
    assert kept["gap_codes"] == ["partially_examined"]
    assert kept["gap_note"] == "Only the northern half of the sheet was legible."
    assert kept["source_refs"] == [
        "candidate:rumsey-sheet-one",
        "topo:CA_Test_1_1953_24000",
    ]


def test_orphaned_review_fails_without_replacing_the_file(tmp_path):
    existing = inventory(
        candidates=[candidate_record()],
        reviews=[review_record(area_id="q7p5-9-9")],
    )
    grid = write_grid(tmp_path)
    index = write_index(tmp_path, [])
    out = tmp_path / "coverage.json"
    before = json.dumps(existing, indent=2) + "\n"
    out.write_text(before, encoding="utf-8")
    result = run(grid, index, out)
    assert result.exit_code != 0
    assert "q7p5-9-9" in result.output
    assert out.read_text() == before


def test_orphaned_topo_reference_fails(tmp_path):
    existing = inventory(
        cells=[cell_record(source_refs=["topo:CA_Gone_1_1953_24000"])],
    )
    result, out = refresh(tmp_path, existing=existing)
    assert result.exit_code != 0
    assert "CA_Gone_1_1953_24000" in result.output


def test_cell_referencing_a_missing_batch_fails(tmp_path):
    existing = inventory(cells=[cell_record(batch_ids=["batch-gone"])])
    result, out = refresh(tmp_path, existing=existing)
    assert result.exit_code != 0
    assert "batch-gone" in result.output


def test_shrinking_the_horizon_keeps_recorded_work(tmp_path):
    existing = inventory(
        through_decade=1970,
        cells=[cell_record(decade=1970, gap_codes=["partially_examined"])],
    )
    result, out = refresh(tmp_path, existing=existing)
    assert result.exit_code != 0
    assert "reconcile" in result.output


def test_two_runs_are_byte_identical(tmp_path):
    rows = [
        index_row(
            "CA_Test_1_1953_24000",
            date_on_map="1953",
            photo_revision_year="1968",
            west="-121.0",
            south="39.0",
            east="-120.75",
            north="39.25",
        )
    ]
    result, out = refresh(tmp_path, rows)
    assert result.exit_code == 0, result.output
    first = out.read_bytes()
    grid = tmp_path / "grid.geojson"
    index = tmp_path / "topo_index.csv"
    assert run(grid, index, out).exit_code == 0
    assert out.read_bytes() == first


@pytest.mark.parametrize("through", ["1940", "1955"])
def test_unusable_through_decade_is_rejected(tmp_path, through):
    grid = write_grid(tmp_path)
    index = write_index(tmp_path, [])
    result = run(grid, index, tmp_path / "coverage.json", through)
    assert result.exit_code != 0


def test_committed_inventory_matches_a_fresh_build(tmp_path):
    out = tmp_path / "coverage.json"
    result = run(COMMITTED_GRID, COMMITTED_INDEX, out, COMMITTED_THROUGH_DECADE)
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == COMMITTED_COVERAGE.read_bytes()


def test_committed_inventory_records_no_examined_or_digitized_state(tmp_path):
    document = json.loads(COMMITTED_COVERAGE.read_text())
    assert document["reviews"] == []
    assert document["batches"] == []
    for cell in document["cells"]:
        assert cell["review_ids"] == []
        assert cell["batch_ids"] == []
        assert cell["gap_codes"] == ["not_digitized", "not_examined", "unsearched"]
