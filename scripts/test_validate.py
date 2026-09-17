"""Contract tests for the trail schema. Authoritative data is copied, never mutated."""

import copy
import csv
import json
import shutil
from pathlib import Path

import pytest
import validate
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path):
    data_dir = tmp_path / "data"
    schema_dir = tmp_path / "schema"
    shutil.copytree(REPO_ROOT / "data" / "authoritative", data_dir)
    shutil.copytree(REPO_ROOT / "schema", schema_dir)
    return data_dir, schema_dir, tmp_path / "public"


def run(workspace):
    data_dir, schema_dir, public_build = workspace
    return CliRunner().invoke(
        validate.main,
        [
            "--data-dir",
            str(data_dir),
            "--schema-dir",
            str(schema_dir),
            "--public-build",
            str(public_build),
        ],
    )


def patch_first_trail(data_dir, **changes):
    path = data_dir / "trails.json"
    trails = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            trails[0].pop(key, None)
        else:
            trails[0][key] = value
    path.write_text(json.dumps(trails, indent=2) + "\n", encoding="utf-8")


def test_authoritative_fixtures_validate(workspace):
    result = run(workspace)
    assert result.exit_code == 0, result.output


def test_arbitrary_corridor_without_tier_passes(workspace):
    patch_first_trail(workspace[0], corridor="anywhere in placer county")
    result = run(workspace)
    assert result.exit_code == 0, result.output


def test_empty_corridor_fails(workspace):
    patch_first_trail(workspace[0], corridor="")
    result = run(workspace)
    assert result.exit_code == 1
    assert "corridor" in result.output + result.stderr


def test_tier_property_is_rejected(workspace):
    patch_first_trail(workspace[0], tier=1)
    result = run(workspace)
    assert result.exit_code == 1
    assert "tier" in result.output + result.stderr


def test_authoritative_trails_carry_no_tier():
    trails = json.loads(
        (REPO_ROOT / "data" / "authoritative" / "trails.json").read_text(encoding="utf-8")
    )
    assert [t["trail_id"] for t in trails] == ["fixture-alpha", "fixture-beta"]
    assert all("tier" not in trail for trail in trails)


# --------------------------------------------------------------------------------------
# Isolated regression cases: one minimal in-memory graph, mutated one way at a time.
# Nothing below reads or writes data/ or build/.
# --------------------------------------------------------------------------------------

TRAIL_ID = "fixture-min"
ALIGNMENT_ID = "fixture-min-1955"
OBSERVATION_ID = "fixture-min-obs-1955"

SUPPORT_HEADER = ["alignment_id", "observation_id", "role", "confidence", "note"]

MINIMAL_GRAPH = {
    "trails": [
        {
            "trail_id": TRAIL_ID,
            "name": "FIXTURE Minimal Trail",
            "aka": [],
            # Arbitrary label, no tier: corridor groups records, it does not bound them.
            "corridor": "eastern nevada county",
            "current_status": "unknown",
            "notes": "FIXTURE — synthetic record, not evidence of any trail.",
        }
    ],
    "alignments": [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-120.500000, 39.300000], [-120.499000, 39.301000]],
            },
            "properties": {
                "alignment_id": ALIGNMENT_ID,
                "trail_id": TRAIL_ID,
                "earliest_known_open": "1955",
                "latest_known_open": None,
                "earliest_known_closed": None,
                "latest_known_closed": None,
                "positional_confidence": "digitized_topo",
                "side": "na",
                "superseded_by": None,
                "parcel_apns": [],
            },
        }
    ],
    "observations": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-120.500000, 39.300000]},
            "properties": {
                "observation_id": OBSERVATION_ID,
                "obs_type": "topo_sheet",
                "date_start": "1955",
                "date_end": None,
                "source_citation": "FIXTURE — synthetic sheet, not a real source.",
                "source_url": None,
                "rights": "public_domain",
                "sensitivity": "public",
                "declarant_name": None,
                "document_path": None,
            },
        }
    ],
    "support": [
        {
            "alignment_id": ALIGNMENT_ID,
            "observation_id": OBSERVATION_ID,
            "role": "attests_existence",
            "confidence": "high",
            "note": "FIXTURE — synthetic support row.",
        }
    ],
}


def minimal_graph():
    """A fresh deep copy, so a mutation in one case cannot reach another."""
    return copy.deepcopy(MINIMAL_GRAPH)


def write_graph(data_dir, graph):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "trails.json").write_text(
        json.dumps(graph["trails"], indent=2) + "\n", encoding="utf-8"
    )
    for name in ("alignments", "observations"):
        document = {"type": "FeatureCollection", "features": graph[name]}
        (data_dir / f"{name}.geojson").write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
    rows = graph["support"]
    header = list(rows[0]) if rows else SUPPORT_HEADER
    with (data_dir / "support.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return data_dir


@pytest.fixture
def run_graph(tmp_path):
    """Validate a graph written under tmp_path only; schemas are copied, not read in place."""
    schema_dir = tmp_path / "schema-minimal"
    shutil.copytree(REPO_ROOT / "schema", schema_dir)
    data_dir = tmp_path / "minimal"

    def _run(graph):
        write_graph(data_dir, graph)
        result = CliRunner().invoke(
            validate.main,
            [
                "--data-dir",
                str(data_dir),
                "--schema-dir",
                str(schema_dir),
                "--public-build",
                str(tmp_path / "public-minimal"),
            ],
        )
        return result, result.output + result.stderr

    return _run


def test_minimal_graph_passes(run_graph):
    result, output = run_graph(minimal_graph())
    assert result.exit_code == 0, output
    assert "all six checks passed" in result.output


def test_orphan_alignment_is_rejected(run_graph):
    graph = minimal_graph()
    graph["support"] = []
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[orphans]" in output
    assert f"alignments.geojson[0] {ALIGNMENT_ID}" in output


def test_unknown_trail_reference_is_rejected(run_graph):
    graph = minimal_graph()
    graph["alignments"][0]["properties"]["trail_id"] = "fixture-missing-trail"
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[references]" in output
    assert f"alignments.geojson[0] {ALIGNMENT_ID}" in output


def test_unknown_observation_reference_is_rejected(run_graph):
    graph = minimal_graph()
    graph["support"][0]["observation_id"] = "fixture-missing-obs"
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[references]" in output
    assert "support.csv[0]" in output


def test_duplicate_trail_id_is_rejected(run_graph):
    graph = minimal_graph()
    graph["trails"].append(copy.deepcopy(graph["trails"][0]))
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[references]" in output
    assert f"trails.json[1] {TRAIL_ID}" in output


def test_duplicate_alignment_id_is_rejected(run_graph):
    graph = minimal_graph()
    graph["alignments"].append(copy.deepcopy(graph["alignments"][0]))
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[references]" in output
    assert f"alignments.geojson[1] {ALIGNMENT_ID}" in output


def test_duplicate_observation_id_is_rejected(run_graph):
    graph = minimal_graph()
    graph["observations"].append(copy.deepcopy(graph["observations"][0]))
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[references]" in output
    assert f"observations.geojson[1] {OBSERVATION_ID}" in output


def test_self_referential_superseded_by_is_rejected(run_graph):
    graph = minimal_graph()
    graph["alignments"][0]["properties"]["superseded_by"] = ALIGNMENT_ID
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[references]" in output
    assert f"alignments.geojson[0] {ALIGNMENT_ID}" in output
    assert "points at itself" in output


def test_unknown_property_is_rejected(run_graph):
    graph = minimal_graph()
    graph["trails"][0]["tier"] = 1
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[schema]" in output
    assert f"trails.json[0] {TRAIL_ID}" in output


def test_extra_support_column_is_rejected_at_load(run_graph):
    graph = minimal_graph()
    graph["support"][0]["sensitivity"] = "restricted"
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[schema] support.csv" in output


def test_required_field_set_to_null_is_rejected(run_graph):
    graph = minimal_graph()
    graph["trails"][0]["name"] = None
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[schema]" in output
    assert f"trails.json[0] {TRAIL_ID}" in output


def test_null_geometry_is_rejected(run_graph):
    # Schema and geometry both own this, so only the record is pinned.
    graph = minimal_graph()
    graph["alignments"][0]["geometry"] = None
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert f"alignments.geojson[0] {ALIGNMENT_ID}" in output


def test_multilinestring_alignment_is_rejected(run_graph):
    graph = minimal_graph()
    graph["alignments"][0]["geometry"] = {
        "type": "MultiLineString",
        "coordinates": [[[-120.500000, 39.300000], [-120.499000, 39.301000]]],
    }
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert f"alignments.geojson[0] {ALIGNMENT_ID}" in output


def test_out_of_range_longitude_is_rejected(run_graph):
    graph = minimal_graph()
    graph["alignments"][0]["geometry"]["coordinates"][0][0] = 200.0
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert f"alignments.geojson[0] {ALIGNMENT_ID}" in output


def test_excessive_coordinate_precision_is_rejected(run_graph):
    graph = minimal_graph()
    graph["alignments"][0]["geometry"]["coordinates"][0][0] = -120.5000001
    result, output = run_graph(graph)
    assert result.exit_code != 0
    assert "[geometry]" in output
    assert f"alignments.geojson[0] {ALIGNMENT_ID}" in output
