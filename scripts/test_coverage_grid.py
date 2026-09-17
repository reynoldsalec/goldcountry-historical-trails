"""Coverage grid builder contract (issue #10).

Synthetic AOIs are built in memory. The committed grid is checked by regenerating it
from the committed AOI into a tmp path and comparing bytes, so the file in git can
never drift from `make coverage-grid`.
"""

import inspect
import json
import shutil
from pathlib import Path

import coverage
import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator
from shapely.geometry import shape
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = REPO_ROOT / "data" / "sources"
COMMITTED_AOI = SOURCES_DIR / "aoi_counties.geojson"
COMMITTED_PARTS = SOURCES_DIR / "aoi_county_parts.geojson"
COMMITTED_GRID = SOURCES_DIR / "coverage_grid.geojson"
GRID_SCHEMA = REPO_ROOT / "schema" / "coverage_grid.schema.json"

NEVADA = "06057"
PLACER = "06061"


def rect(west, south, east, north):
    return {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def write(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run(tmp_path, aoi_doc, counties_doc, out_name="grid.geojson"):
    aoi = write(tmp_path / "aoi.geojson", aoi_doc)
    counties = write(tmp_path / "counties.geojson", counties_doc)
    out = tmp_path / out_name
    result = CliRunner().invoke(
        coverage.cli,
        ["grid", "--aoi", str(aoi), "--counties", str(counties), "--out", str(out)],
    )
    return result, out


def split_counties(divide_lon, west, south, east, north):
    """Two counties meeting at `divide_lon`, so a cell spanning it carries both."""
    return collection(
        [
            {
                "type": "Feature",
                "geometry": rect(west, south, divide_lon, north),
                "properties": {"GEOID": NEVADA, "BASENAME": "Nevada"},
            },
            {
                "type": "Feature",
                "geometry": rect(divide_lon, south, east, north),
                "properties": {"GEOID": PLACER, "BASENAME": "Placer"},
            },
        ]
    )


def area_ids(out: Path):
    document = json.loads(out.read_text())
    return [f["properties"]["area_id"] for f in document["features"]]


def test_synthetic_aoi_spanning_a_grid_line_yields_the_expected_cells(tmp_path):
    # -121.0 and 39.0 are exact grid lines; the AOI crosses the line at -120.875.
    aoi = collection(
        [{"type": "Feature", "geometry": rect(-121.0, 39.0, -120.8, 39.1), "properties": {}}]
    )
    counties = split_counties(-120.9, -121.0, 39.0, -120.8, 39.1)
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 0, result.output

    document = json.loads(out.read_text())
    cells = {f["properties"]["area_id"]: f for f in document["features"]}
    assert set(cells) == {"q7p5-472-1032", "q7p5-473-1032"}
    assert cells["q7p5-472-1032"]["properties"]["county_geoids"] == [NEVADA, PLACER]
    assert cells["q7p5-473-1032"]["properties"]["county_geoids"] == [PLACER]
    assert cells["q7p5-472-1032"]["geometry"] == rect(-121.0, 39.0, -120.875, 39.125)


def test_edge_only_neighbours_are_excluded_and_the_aoi_is_fully_covered(tmp_path):
    aoi_geom = rect(-121.0, 39.0, -120.875, 39.125)  # exactly one cell
    aoi = collection([{"type": "Feature", "geometry": aoi_geom, "properties": {}}])
    counties = split_counties(-120.9, -121.0, 39.0, -120.875, 39.125)
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 0, result.output
    assert area_ids(out) == ["q7p5-472-1032"]

    covered = unary_union(
        [shape(f["geometry"]) for f in json.loads(out.read_text())["features"]]
    )
    assert shape(aoi_geom).difference(covered).area == 0


def test_cells_are_sorted_by_area_id_as_strings(tmp_path):
    aoi = collection(
        [{"type": "Feature", "geometry": rect(-121.0, 39.0, -119.5, 39.1), "properties": {}}]
    )
    counties = split_counties(-120.0, -121.0, 39.0, -119.5, 39.1)
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 0, result.output
    ids = area_ids(out)
    assert ids == sorted(ids)
    assert len(ids) > 9  # the run spans a 47x -> 48x id change, which sorts as strings


def test_invalid_aoi_geometry_is_rejected_not_repaired(tmp_path):
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [[-121.0, 39.0], [-120.8, 39.1], [-120.8, 39.0], [-121.0, 39.1], [-121.0, 39.0]]
        ],
    }
    aoi = collection([{"type": "Feature", "geometry": bowtie, "properties": {}}])
    counties = split_counties(-120.9, -121.0, 39.0, -120.8, 39.1)
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 1
    assert "invalid geometry" in result.output
    assert not out.exists()


def test_unsupported_crs_member_is_rejected(tmp_path):
    aoi = collection(
        [{"type": "Feature", "geometry": rect(-121.0, 39.0, -120.8, 39.1), "properties": {}}]
    )
    aoi["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}}
    counties = split_counties(-120.9, -121.0, 39.0, -120.8, 39.1)
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 1
    assert "EPSG:4326 only" in result.output
    assert not out.exists()


def test_a_failed_run_leaves_an_existing_grid_intact(tmp_path):
    aoi = collection(
        [{"type": "Feature", "geometry": rect(-121.0, 39.0, -120.8, 39.1), "properties": {}}]
    )
    counties = split_counties(-120.9, -121.0, 39.0, -120.8, 39.1)
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 0, result.output
    before = out.read_bytes()

    broken = dict(aoi)
    broken["features"] = [{"type": "Feature", "geometry": None, "properties": {}}]
    result, _ = run(tmp_path, broken, counties)
    assert result.exit_code == 1
    assert out.read_bytes() == before


def test_rerunning_the_same_input_is_byte_identical(tmp_path):
    aoi = collection(
        [{"type": "Feature", "geometry": rect(-121.0, 39.0, -120.8, 39.1), "properties": {}}]
    )
    counties = split_counties(-120.9, -121.0, 39.0, -120.8, 39.1)
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 0, result.output
    first = out.read_bytes()
    result, out = run(tmp_path, aoi, counties)
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == first


def test_the_grid_never_reads_the_topo_index():
    """The refresh command reads the index (issue #11); the grid must not."""
    for function in (coverage.grid.callback, coverage.build_cells, coverage.load_geometries):
        assert "topo_index" not in inspect.getsource(function)
        assert "read_index" not in inspect.getsource(function)


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("grid")
    out = tmp / "coverage_grid.geojson"
    result = CliRunner().invoke(
        coverage.cli,
        [
            "grid",
            "--aoi",
            str(COMMITTED_AOI),
            "--counties",
            str(COMMITTED_PARTS),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    return out


def test_committed_grid_matches_a_fresh_build_from_the_committed_aoi(regenerated):
    assert COMMITTED_GRID.read_bytes() == regenerated.read_bytes()


def test_committed_grid_validates_against_its_schema():
    schema = json.loads(GRID_SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    document = json.loads(COMMITTED_GRID.read_text())
    errors = list(Draft202012Validator(schema).iter_errors(document))
    assert errors == [], [e.message for e in errors]


def test_committed_grid_covers_the_committed_aoi(regenerated):
    aoi = unary_union(
        [shape(f["geometry"]) for f in json.loads(COMMITTED_AOI.read_text())["features"]]
    )
    cells = unary_union(
        [shape(f["geometry"]) for f in json.loads(COMMITTED_GRID.read_text())["features"]]
    )
    assert aoi.difference(cells).area == 0


def test_removing_topo_index_rows_cannot_change_the_grid(tmp_path):
    index = SOURCES_DIR / "topo_index.csv"
    backup = shutil.copy(index, tmp_path / "topo_index.csv")
    out = tmp_path / "coverage_grid.geojson"
    try:
        lines = index.read_text().splitlines(keepends=True)
        index.write_text(lines[0], encoding="utf-8")
        result = CliRunner().invoke(
            coverage.cli,
            [
                "grid",
                "--aoi",
                str(COMMITTED_AOI),
                "--counties",
                str(COMMITTED_PARTS),
                "--out",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out.read_bytes() == COMMITTED_GRID.read_bytes()
    finally:
        shutil.copy(backup, index)
