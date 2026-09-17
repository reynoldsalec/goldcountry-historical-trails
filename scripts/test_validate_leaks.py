"""Leak-check contract tests (AGENTS.md §2.5).

Every fixture value is synthetic and planted under tmp_path; the repository's
build/public and data/authoritative are never read or written here.
"""

import copy
import csv
import json
import shutil
from pathlib import Path

import pytest
import validate
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]

TRAIL_ID = "fixture-leak"
ALIGNMENT_ID = "fixture-leak-1955"
PUBLIC_OBSERVATION_ID = "fixture-leak-obs-1955"
# Identifier patterns in the schemas are lowercase slugs, so the marker word carries
# the "this is a fixture" signal instead of the case.
RESTRICTED_OBSERVATION_ID = "fixture-leak-restricted-obs-1968"

FIXTURE_APN = "FIXTURE-APN-000-000-000"
FIXTURE_DECLARANT = "FIXTURE Declarant Nobody"
FIXTURE_DOCUMENT_PATH = "FIXTURE/unpublished/fixture-declaration.pdf"
FIXTURE_SCHEMA_NOTE = "FIXTURE-SCHEMA-ANNOTATED-VALUE"

SUPPORT_HEADER = ["alignment_id", "observation_id", "role", "confidence", "note"]

LEAK_GRAPH = {
    "trails": [
        {
            "trail_id": TRAIL_ID,
            "name": "FIXTURE Leak-Check Trail",
            "aka": [],
            "corridor": "other",
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
                "parcel_apns": [FIXTURE_APN],
            },
        }
    ],
    "observations": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-120.500000, 39.300000]},
            "properties": {
                "observation_id": PUBLIC_OBSERVATION_ID,
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
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-120.500000, 39.300000]},
            "properties": {
                "observation_id": RESTRICTED_OBSERVATION_ID,
                "obs_type": "declaration",
                "date_start": "1968",
                "date_end": None,
                "source_citation": "FIXTURE — synthetic declaration, not a real source.",
                "source_url": None,
                "rights": "restricted",
                "sensitivity": "restricted",
                "declarant_name": FIXTURE_DECLARANT,
                "document_path": FIXTURE_DOCUMENT_PATH,
            },
        },
    ],
    "support": [
        {
            "alignment_id": ALIGNMENT_ID,
            "observation_id": PUBLIC_OBSERVATION_ID,
            "role": "attests_existence",
            "confidence": "high",
            "note": "FIXTURE — synthetic support row.",
        }
    ],
}


def leak_graph():
    """A fresh deep copy, so a mutation in one case cannot reach another."""
    return copy.deepcopy(LEAK_GRAPH)


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


class LeakCase:
    """One isolated validate run: copied schemas, tmp graph, tmp public build."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.data_dir = tmp_path / "data-leak"
        self.schema_dir = tmp_path / "schema-leak"
        shutil.copytree(REPO_ROOT / "schema", self.schema_dir)
        # check_leak renders asset paths relative to build/public's grandparent, so the
        # tmp output has to mirror the real <root>/build/public layout.
        self.public_build = tmp_path / "build" / "public"

    def plant(self, relative, value):
        path = self.public_build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"note": value}) + "\n", encoding="utf-8")
        return path

    def annotate_schema(self, filename, prop, subschema):
        schema_path = self.schema_dir / filename
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["properties"][prop] = subschema
        schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    def run(self, graph):
        write_graph(self.data_dir, graph)
        result = CliRunner().invoke(
            validate.main,
            [
                "--data-dir",
                str(self.data_dir),
                "--schema-dir",
                str(self.schema_dir),
                "--public-build",
                str(self.public_build),
            ],
        )
        return result, result.output + result.stderr


@pytest.fixture
def case(tmp_path):
    return LeakCase(tmp_path)


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("parcel_apns", FIXTURE_APN),
        ("declarant_name", FIXTURE_DECLARANT),
        ("document_path", FIXTURE_DOCUMENT_PATH),
        ("restricted observation_id", RESTRICTED_OBSERVATION_ID),
    ],
)
def test_planted_restricted_value_is_caught(case, label, value):
    case.plant("tiles/data.json", value)
    result, output = case.run(leak_graph())
    assert result.exit_code != 0, output
    assert "[leak]" in output, output
    assert "build/public/tiles/data.json" in output, output
    assert value in output, output


def test_schema_annotated_property_is_caught(case):
    """A newly marked field comes under the scan without touching validate.py."""
    case.annotate_schema(
        "trail.schema.json",
        "test_restricted_note",
        {"type": "string", "minLength": 1, "x-sensitivity": "restricted"},
    )
    graph = leak_graph()
    graph["trails"][0]["test_restricted_note"] = FIXTURE_SCHEMA_NOTE
    case.plant("meta/trails.json", FIXTURE_SCHEMA_NOTE)
    result, output = case.run(graph)
    assert result.exit_code != 0, output
    assert "[leak]" in output, output
    assert "build/public/meta/trails.json" in output, output
    assert FIXTURE_SCHEMA_NOTE in output, output


def test_clean_nonempty_output_passes(case):
    case.plant("tiles/data.json", "FIXTURE — no restricted value here.")
    case.plant("index.html", "FIXTURE viewer shell.")
    result, output = case.run(leak_graph())
    assert result.exit_code == 0, output
    assert "scanned 2 file(s)" in result.output


def test_empty_output_directory_scans_nothing_and_passes(case):
    case.public_build.mkdir(parents=True)
    result, output = case.run(leak_graph())
    assert result.exit_code == 0, output
    assert "scanned 0 file(s)" in result.output


def test_missing_output_directory_reports_no_scan(case):
    # Passing here means the scanner found nothing to read, not that a release is safe:
    # no build exists, so no restricted value has been cleared.
    assert not case.public_build.exists()
    result, output = case.run(leak_graph())
    assert result.exit_code == 0, output
    assert "does not exist yet, nothing to scan" in result.output
    assert "restricted values are under watch" in result.output
