"""Coverage report contract (issue #13).

Every fixture is synthetic and built in a tmp path, including a cell that straddles the
county boundary. The committed inventory is only ever read, never edited to make a case
pass. The report counts research bookkeeping; it never states anything about the ground.
"""

import json
import re
from pathlib import Path

import coverage
import pytest
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
COVERAGE_DOC = REPO_ROOT / "docs" / "coverage.md"

DECADES = [1950, 1960]
# q7p5-3-1 crosses the county line: it is counted in Nevada and in Placer.
AREAS = {
    "q7p5-1-1": ["06057"],
    "q7p5-2-1": ["06061"],
    "q7p5-3-1": ["06057", "06061"],
}
SIZE = 0.125


def polygon(west, south):
    east, north = west + SIZE, south + SIZE
    return {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }


def write_grid(tmp_path, areas=None):
    areas = AREAS if areas is None else areas
    features = [
        {
            "type": "Feature",
            "geometry": polygon(-121.0 + index * SIZE, 39.0),
            "properties": {"area_id": area_id, "county_geoids": list(geoids)},
        }
        for index, (area_id, geoids) in enumerate(sorted(areas.items()))
    ]
    path = tmp_path / "grid.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
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


def review(review_id, area_id, decade, county_geoid, scope):
    return {
        "review_id": review_id,
        "source_ref": "candidate:frame-one",
        "area_id": area_id,
        "county_geoid": county_geoid,
        "decade": decade,
        "reviewed_at": "2026-09-16T18:00:00Z",
        "reviewer_id": "reviewer-one",
        "scope": scope,
        "foot_trail_evidence": "uncertain",
        "dating": "resolved",
        "evidence_locator": None,
        "note": None,
    }


def batch(batch_id, county_geoid, decade, status, review_ids):
    return {
        "batch_id": batch_id,
        "county_geoid": county_geoid,
        "area_ids": ["q7p5-1-1"],
        "decade": decade,
        "source_refs": ["candidate:frame-one"],
        "review_ids": list(review_ids),
        "tasks": ["digitize the reviewed foot trail"],
        "gap_note": None,
        "status": status,
        "alignment_ids": [],
    }


def inventory(**changes):
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


def populated():
    """A fixture with located sources, a partial and a whole-footprint review, one ready
    batch, and one cell nobody has searched."""
    cells = []
    for area_id in sorted(AREAS):
        for decade in DECADES:
            if area_id == "q7p5-1-1" and decade == 1950:
                cells.append(
                    cell(
                        area_id,
                        decade,
                        source_refs=["candidate:frame-one"],
                        review_ids=["review-partial"],
                        batch_ids=["batch-ready"],
                        gap_codes=["not_digitized", "partially_examined"],
                    )
                )
            elif area_id == "q7p5-3-1" and decade == 1950:
                cells.append(
                    cell(
                        area_id,
                        decade,
                        source_refs=["candidate:frame-one"],
                        review_ids=["review-whole", "review-partial-shared"],
                        gap_codes=["not_digitized"],
                    )
                )
            elif area_id == "q7p5-2-1" and decade == 1960:
                cells.append(
                    cell(
                        area_id,
                        decade,
                        gap_codes=["not_digitized", "not_examined", "no_source_located"],
                    )
                )
            else:
                cells.append(cell(area_id, decade))
    return inventory(
        cells=cells,
        reviews=[
            review("review-partial", "q7p5-1-1", 1950, "06057", "partial"),
            review("review-partial-shared", "q7p5-3-1", 1950, "06061", "partial"),
            review("review-whole", "q7p5-3-1", 1950, "06057", "whole_source_footprint"),
        ],
        batches=[
            batch("batch-ready", "06057", 1950, "ready", ["review-partial"]),
            batch("batch-planned", "06061", 1960, "planned", []),
        ],
    )


def run(tmp_path, document, areas=None, out=None):
    data = tmp_path / "coverage.json"
    data.write_text(json.dumps(document))
    out = out or tmp_path / "coverage.md"
    result = CliRunner().invoke(
        coverage.cli,
        [
            "report",
            "--data",
            str(data),
            "--grid",
            str(write_grid(tmp_path, areas)),
            "--out",
            str(out),
        ],
    )
    return result, out


def row(text, label):
    for line in text.splitlines():
        if line.startswith(f"| {label} |"):
            return [part.strip() for part in line.strip("|").split("|")]
    raise AssertionError(f"no row labelled {label} in\n{text}")


def section(text, heading):
    body = text.split(f"## {heading}", 1)
    assert len(body) == 2, f"no section {heading}"
    return body[1].split("\n## ", 1)[0]


def gaps(text, heading):
    """The gap-code table of one county, which repeats the decade labels."""
    body = section(text, heading).split("Recorded gaps", 1)
    assert len(body) == 2, f"no gap table under {heading}"
    return body[1]


def test_empty_inventory_counts_every_cell_as_unexamined(tmp_path):
    result, out = run(tmp_path, inventory())
    assert result.exit_code == 0, result.output
    text = out.read_text()
    # Nevada holds q7p5-1-1 and the shared q7p5-3-1: 2 areas x 2 decades.
    nevada = row(section(text, "Nevada County (06057)"), "**all decades**")
    assert nevada[:6] == ["**all decades**", "4", "0", "0", "0", "4"]
    placer = row(section(text, "Placer County (06061)"), "**all decades**")
    assert placer[:6] == ["**all decades**", "4", "0", "0", "0", "4"]


def test_totals_match_the_populated_fixture(tmp_path):
    result, out = run(tmp_path, populated())
    assert result.exit_code == 0, result.output
    text = out.read_text()

    nevada = section(text, "Nevada County (06057)")
    # cells, located, partial, whole, unexamined, ready, digitized
    assert row(nevada, "1950s")[1:] == ["2", "2", "1", "1", "0", "1", "0"]
    assert row(nevada, "1960s")[1:] == ["2", "0", "0", "0", "2", "0", "0"]
    assert row(nevada, "**all decades**")[1:] == ["4", "2", "1", "1", "2", "1", "0"]

    placer = section(text, "Placer County (06061)")
    # The shared cell carries a whole-footprint review, so Placer counts it too.
    assert row(placer, "1950s")[1:] == ["2", "1", "0", "1", "1", "0", "0"]
    assert row(placer, "1960s")[1:] == ["2", "0", "0", "0", "2", "0", "0"]
    assert row(placer, "**all decades**")[1:] == ["4", "1", "0", "1", "3", "0", "0"]


def test_planned_batches_are_not_reported_as_ready_or_digitized(tmp_path):
    _, out = run(tmp_path, populated())
    text = out.read_text()
    for county in ("Nevada County (06057)", "Placer County (06061)"):
        totals = row(section(text, county), "**all decades**")
        assert totals[7] == "0", "digitized stays zero throughout M1"
    assert row(section(text, "Placer County (06061)"), "1960s")[6] == "0"


def test_gap_codes_are_counted_per_county_and_decade(tmp_path):
    _, out = run(tmp_path, populated())
    text = out.read_text()
    order = list(coverage.GAP_CODES)
    placer = row(gaps(text, "Placer County (06061)"), "1960s")
    counts = dict(zip(order, placer[1:], strict=True))
    assert counts["no_source_located"] == "1"
    assert counts["unsearched"] == "1"
    assert counts["not_digitized"] == "2"
    nevada = row(gaps(text, "Nevada County (06057)"), "1950s")
    assert dict(zip(order, nevada[1:], strict=True))["partially_examined"] == "1"


def test_shared_border_cells_are_labelled_and_not_summed(tmp_path):
    _, out = run(tmp_path, inventory())
    text = out.read_text()
    areas = section(text, "Grid areas")
    assert "1 of them" in areas
    assert "must not be summed as a unique total" in areas
    assert row(areas, "unique across both")[1:] == ["3", "2", "6"]
    assert row(areas, "Nevada County (06057)")[1] == "2"
    assert row(areas, "Placer County (06061)")[1] == "2"


def test_regeneration_is_byte_identical(tmp_path):
    _, out = run(tmp_path, populated())
    first = out.read_bytes()
    run(tmp_path, populated(), out=out)
    assert out.read_bytes() == first


def test_report_carries_no_wall_clock_value(tmp_path):
    _, out = run(tmp_path, populated())
    text = out.read_text()
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert not re.search(r"\d{2}:\d{2}", text)
    assert "Generated by `scripts/coverage.py report`" in text
    assert "make coverage-report" in text


def test_report_names_the_four_states_and_claims_no_absence(tmp_path):
    _, out = run(tmp_path, populated())
    text = out.read_text()
    for label in ("**Located**", "**Examined**", "**Digitized**", "**Unexamined**"):
        assert label in text
    assert "no trails" not in text.lower()
    assert "None of them states that a" in text
    assert "no_match" in text and "evidence of nothing" in text


def test_dangling_review_reference_stops_the_report(tmp_path):
    document = inventory()
    document["cells"][0]["review_ids"] = ["review-missing"]
    result, out = run(tmp_path, document)
    assert result.exit_code == 1
    assert "review-missing" in result.output
    assert not out.exists()


def test_cell_outside_the_grid_stops_the_report(tmp_path):
    document = inventory()
    document["cells"].append(cell("q7p5-9-9", 1950))
    result, _ = run(tmp_path, document)
    assert result.exit_code == 1
    assert "q7p5-9-9" in result.output


def test_schema_failure_stops_the_report(tmp_path):
    document = inventory()
    document["cells"][0]["gap_codes"] = ["not_a_gap_code"]
    result, out = run(tmp_path, document)
    assert result.exit_code == 1
    assert "make validate-coverage" in result.output
    assert not out.exists()


@pytest.mark.parametrize(
    "fragment",
    [
        "coverage-report:",
        "scripts/test_coverage_report.py",
        "$(MAKE) validate-coverage",
    ],
)
def test_makefile_wires_the_report_and_the_inventory_check(fragment):
    assert fragment in MAKEFILE.read_text()


def test_ci_runs_the_coverage_tests_without_dropping_earlier_checks():
    text = WORKFLOW.read_text()
    for target in ("make lint", "make validate", "make test-topo", "make test-validation"):
        assert target in text
    assert "make test-coverage" in text


def test_committed_report_matches_the_committed_inventory(tmp_path):
    """validate.yml runs on every push, so the generated doc must match the inventory."""
    regenerated = tmp_path / "coverage.md"
    result = CliRunner().invoke(coverage.cli, ["report", "--out", str(regenerated)])
    assert result.exit_code == 0, result.output
    assert regenerated.read_bytes() == COVERAGE_DOC.read_bytes(), (
        "docs/coverage.md is stale; run 'make coverage-report'"
    )
