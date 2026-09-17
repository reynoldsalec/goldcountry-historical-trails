"""Coverage inventory schema contract (issue #9).

Every document here is built in memory. The only file read is the committed initial
inventory, which must stay empty until real research is recorded.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schema"
COVERAGE_JSON = REPO_ROOT / "data" / "sources" / "coverage.json"


def load(name):
    return json.loads((SCHEMA_DIR / name).read_text())


@pytest.fixture(scope="module")
def coverage():
    schema = load("coverage.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def grid():
    schema = load("coverage_grid.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def cell(**changes):
    base = {
        "area_id": "q7p5-12-34",
        "decade": 1960,
        "source_refs": ["topo:CA_Alleghany_287897_1949_24000", "candidate:rumsey-0001"],
        "search_ids": ["s-0001"],
        "review_ids": ["r-0001"],
        "batch_ids": ["b-0001"],
        "gap_codes": ["not_digitized"],
        "gap_note": None,
    }
    base.update(changes)
    return base


def candidate(**changes):
    base = {
        "candidate_id": "rumsey-0001",
        "kind": "topo_sheet",
        "collection_id": "usgs-historical-topo",
        "title": "Alleghany quadrangle",
        "url": None,
        "date_start": "1949",
        "date_end": None,
        "west": None,
        "south": None,
        "east": None,
        "north": None,
        "rights": "public_domain",
        "sensitivity": "public",
        "attribution": None,
        "verification": "unverified",
        "source_identifier": None,
        "access": "unknown",
    }
    base.update(changes)
    return base


def search(**changes):
    base = {
        "search_id": "s-0001",
        "searched_at": "2026-09-16T12:00:00Z",
        "collection_id": "usgs-historical-topo",
        "area_ids": ["q7p5-12-34"],
        "decades": [1960],
        "query": "Alleghany 1:24000",
        "outcome": "located",
        "source_refs": ["candidate:rumsey-0001"],
        "note": None,
    }
    base.update(changes)
    return base


def review(**changes):
    base = {
        "review_id": "r-0001",
        "source_ref": "candidate:rumsey-0001",
        "area_id": "q7p5-12-34",
        "county_geoid": "06057",
        "decade": 1960,
        "reviewed_at": "2026-09-16T13:00:00Z",
        "reviewer_id": "reviewer-a",
        "scope": "partial",
        "foot_trail_evidence": "no",
        "dating": "unresolved",
        "evidence_locator": None,
        "note": None,
    }
    base.update(changes)
    return base


def batch(**changes):
    base = {
        "batch_id": "b-0001",
        "county_geoid": "06057",
        "area_ids": ["q7p5-12-34"],
        "decade": 1960,
        "source_refs": ["candidate:rumsey-0001"],
        "review_ids": ["r-0001"],
        "tasks": ["digitize the north spur"],
        "gap_note": None,
        "status": "planned",
        "alignment_ids": [],
    }
    base.update(changes)
    return base


def document(**changes):
    base = {
        "version": 1,
        "through_decade": 2020,
        "cells": [cell()],
        "candidates": [candidate()],
        "searches": [search()],
        "reviews": [review()],
        "batches": [batch()],
    }
    base.update(changes)
    return base


def errors(validator, instance):
    return [e.message for e in validator.iter_errors(instance)]


def test_minimal_valid_document_is_accepted(coverage):
    assert errors(coverage, document()) == []


def test_empty_document_is_accepted(coverage):
    empty = document(cells=[], candidates=[], searches=[], reviews=[], batches=[])
    assert errors(coverage, empty) == []


def test_committed_initial_inventory_validates_and_is_empty(coverage):
    data = json.loads(COVERAGE_JSON.read_text())
    assert errors(coverage, data) == []
    assert data["version"] == 1
    for key in ("cells", "candidates", "searches", "reviews", "batches"):
        assert data[key] == [], f"{key} must hold no invented records"


@pytest.mark.parametrize("key", ["version", "through_decade", "cells", "batches"])
def test_missing_top_level_key_is_rejected(coverage, key):
    doc = document()
    del doc[key]
    assert errors(coverage, doc)


def test_unknown_top_level_field_is_rejected(coverage):
    assert errors(coverage, document(notes="free text"))


@pytest.mark.parametrize(
    "maker,extra",
    [
        (cell, "county_geoid"),
        (candidate, "frame_id"),
        (search, "searcher_id"),
        (review, "confidence"),
        (batch, "owner"),
    ],
)
def test_unknown_record_field_is_rejected(coverage, maker, extra):
    record = maker(**{extra: "x"})
    key = {
        cell: "cells",
        candidate: "candidates",
        search: "searches",
        review: "reviews",
        batch: "batches",
    }[maker]
    assert errors(coverage, document(**{key: [record]}))


@pytest.mark.parametrize("value", [1955, 1940, 2020.5, "1960"])
def test_non_decade_through_decade_is_rejected(coverage, value):
    assert errors(coverage, document(through_decade=value))


def test_version_is_pinned(coverage):
    assert errors(coverage, document(version=2))


@pytest.mark.parametrize(
    "field,value",
    [
        ("gap_codes", ["fully_examined"]),
        ("gap_codes", ["unsearched", "unsearched"]),
        ("area_id", "q7p5-12"),
        ("area_id", "Q7P5-12-34"),
        ("decade", 1965),
        ("gap_note", ""),
        ("source_refs", ["scan:0001"]),
        ("source_refs", ["candidate:Rumsey_0001"]),
        ("search_ids", ["s-0001", "s-0001"]),
        ("review_ids", [""]),
    ],
)
def test_bad_cell_field_is_rejected(coverage, field, value):
    assert errors(coverage, document(cells=[cell(**{field: value})]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "postcard"),
        ("rights", "cc0"),
        ("sensitivity", "internal"),
        ("verification", "probably"),
        ("access", "maybe"),
        ("candidate_id", "Rumsey 0001"),
        ("collection_id", ""),
        ("title", ""),
        ("date_start", "1949-13"),
        ("date_start", "49"),
        ("url", ""),
        ("source_identifier", ""),
    ],
)
def test_bad_candidate_field_is_rejected(coverage, field, value):
    assert errors(coverage, document(candidates=[candidate(**{field: value})]))


@pytest.mark.parametrize(
    "rights", ["public_domain", "cc_by_nc_sa", "odbl", "restricted", "unknown"]
)
def test_every_rights_value_is_accepted(coverage, rights):
    assert errors(coverage, document(candidates=[candidate(rights=rights)])) == []


@pytest.mark.parametrize(
    "bounds",
    [
        {"west": -121.0},
        {"west": -121.0, "south": 39.0},
        {"west": -121.0, "south": 39.0, "east": -120.0},
    ],
)
def test_partial_bounds_are_rejected(coverage, bounds):
    assert errors(coverage, document(candidates=[candidate(**bounds)]))


def test_full_bounds_are_accepted(coverage):
    full = candidate(west=-121.0, south=39.0, east=-120.875, north=39.125)
    assert errors(coverage, document(candidates=[full])) == []


@pytest.mark.parametrize("field,value", [("west", -181.0), ("north", 91.0)])
def test_out_of_range_bounds_are_rejected(coverage, field, value):
    full = candidate(west=-121.0, south=39.0, east=-120.875, north=39.125)
    full[field] = value
    assert errors(coverage, document(candidates=[full]))


def test_date_end_without_date_start_is_rejected(coverage):
    assert errors(coverage, document(candidates=[candidate(date_start=None, date_end="1955")]))


def test_date_range_with_both_ends_is_accepted(coverage):
    ranged = candidate(date_start="1949-06-01", date_end="1955")
    assert errors(coverage, document(candidates=[ranged])) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("searched_at", "2026-09-16"),
        ("searched_at", "2026-09-16T12:00:00+00:00"),
        ("searched_at", "2026-09-16 12:00:00Z"),
        ("outcome", "found"),
        ("area_ids", []),
        ("decades", []),
        ("decades", [1960, 1960]),
        ("query", ""),
        ("search_id", "S0001"),
        ("source_refs", ["candidate:rumsey-0001", "candidate:rumsey-0001"]),
    ],
)
def test_bad_search_field_is_rejected(coverage, field, value):
    assert errors(coverage, document(searches=[search(**{field: value})]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("county_geoid", "06000"),
        ("county_geoid", 6057),
        ("scope", "some"),
        ("foot_trail_evidence", "maybe"),
        ("dating", "partly"),
        ("reviewed_at", "2026-09-16T13:00Z"),
        ("reviewer_id", ""),
        ("source_ref", "rumsey-0001"),
        ("evidence_locator", ""),
    ],
)
def test_bad_review_field_is_rejected(coverage, field, value):
    assert errors(coverage, document(reviews=[review(**{field: value})]))


def test_positive_evidence_requires_a_locator(coverage):
    without = review(foot_trail_evidence="yes", evidence_locator=None)
    assert errors(coverage, document(reviews=[without]))
    withloc = review(
        foot_trail_evidence="yes", evidence_locator="NE quarter, trail east of the ridge"
    )
    assert errors(coverage, document(reviews=[withloc])) == []


@pytest.mark.parametrize("value", ["no", "uncertain"])
def test_null_locator_is_fine_without_positive_evidence(coverage, value):
    assert errors(coverage, document(reviews=[review(foot_trail_evidence=value)])) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "done"),
        ("county_geoid", "06057 "),
        ("tasks", [""]),
        ("tasks", ["a", 1]),
        ("alignment_ids", ["a-1", "a-1"]),
        ("area_ids", ["q7p5-12-34", "q7p5-12-34"]),
        ("decade", 195),
    ],
)
def test_bad_batch_field_is_rejected(coverage, field, value):
    assert errors(coverage, document(batches=[batch(**{field: value})]))


def feature(**changes):
    props = {"area_id": "q7p5-12-34", "county_geoids": ["06057"]}
    props.update(changes.pop("properties", {}))
    base = {
        "type": "Feature",
        "properties": props,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-121.0, 39.0],
                    [-120.875, 39.0],
                    [-120.875, 39.125],
                    [-121.0, 39.0],
                ]
            ],
        },
    }
    base.update(changes)
    return base


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def test_minimal_grid_is_accepted(grid):
    assert errors(grid, collection(feature())) == []


def test_empty_grid_is_accepted(grid):
    assert errors(grid, collection()) == []


def test_both_counties_on_one_cell_are_accepted(grid):
    assert (
        errors(grid, collection(feature(properties={"county_geoids": ["06057", "06061"]})))
        == []
    )


@pytest.mark.parametrize(
    "props",
    [
        {"county_geoids": []},
        {"county_geoids": ["06057", "06057"]},
        {"county_geoids": ["06067"]},
        {"county_geoids": "06057"},
        {"area_id": "q7p5-12"},
        {"area_id": "cell-1"},
    ],
)
def test_bad_grid_properties_are_rejected(grid, props):
    assert errors(grid, collection(feature(properties=props)))


def test_extra_grid_property_is_rejected(grid):
    assert errors(grid, collection(feature(properties={"acres": 1200})))


def test_missing_grid_property_is_rejected(grid):
    bad = feature()
    del bad["properties"]["county_geoids"]
    assert errors(grid, collection(bad))


def test_non_polygon_geometry_is_rejected(grid):
    bad = feature()
    bad["geometry"] = {"type": "LineString", "coordinates": [[-121.0, 39.0], [-120.0, 39.0]]}
    assert errors(grid, collection(bad))


def test_null_geometry_is_rejected(grid):
    assert errors(grid, collection(feature(geometry=None)))


def test_unclosed_short_ring_is_rejected(grid):
    bad = feature()
    bad["geometry"]["coordinates"] = [[[-121.0, 39.0], [-120.875, 39.0], [-121.0, 39.0]]]
    assert errors(grid, collection(bad))


def test_three_dimensional_coordinates_are_rejected(grid):
    bad = feature()
    bad["geometry"]["coordinates"][0][0] = [-121.0, 39.0, 800.0]
    assert errors(grid, collection(bad))


def test_fixtures_are_not_mutated_between_cases(coverage):
    doc = document()
    snapshot = deepcopy(doc)
    coverage.is_valid(doc)
    assert doc == snapshot
