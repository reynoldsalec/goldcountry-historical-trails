"""Calendar validity and bound ordering in the temporal check (issue #6).

Authoritative data is copied into tmp_path, never mutated.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import validate
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]


def alignment(**props):
    base = {
        "alignment_id": "a-1",
        "earliest_known_open": None,
        "latest_known_open": None,
        "earliest_known_closed": None,
        "latest_known_closed": None,
    }
    base.update(props)
    return {"type": "Feature", "properties": base, "geometry": None}


def observation(**props):
    base = {"observation_id": "o-1", "date_start": None, "date_end": None}
    base.update(props)
    return {"type": "Feature", "properties": base, "geometry": None}


def temporal(alignments=(), observations=()):
    records = {"alignments": list(alignments), "observations": list(observations)}
    return validate.check_temporal(records)


def messages(failures):
    assert all(f.check == "temporal" for f in failures)
    return " | ".join(f.message for f in failures)


# --------------------------------------------------------------------------------------
# as_bound
# --------------------------------------------------------------------------------------


def test_bare_year_widens_to_whole_year():
    assert validate.as_bound("1954", upper=False) == date(1954, 1, 1)
    assert validate.as_bound("1954", upper=True) == date(1954, 12, 31)


def test_full_date_is_itself_on_both_sides():
    assert validate.as_bound("1954-06-01", upper=False) == date(1954, 6, 1)
    assert validate.as_bound("1954-06-01", upper=True) == date(1954, 6, 1)


@pytest.mark.parametrize("value", ["2000", "2000-02-29", "0001", "9999-12-31"])
def test_real_dates_parse(value):
    assert validate.as_bound(value, upper=False) is not None


@pytest.mark.parametrize(
    "value", ["2023-02-29", "2000-13-01", "2000-00-10", "2000-04-31", "0000", "10000"]
)
def test_impossible_dates_do_not_parse(value):
    assert validate.as_bound(value, upper=False) is None
    assert validate.as_bound(value, upper=True) is None


# --------------------------------------------------------------------------------------
# Calendar validity, field by field
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "earliest_known_open",
        "latest_known_open",
        "earliest_known_closed",
        "latest_known_closed",
    ],
)
@pytest.mark.parametrize(
    "value", ["2023-02-29", "2000-13-01", "2000-00-10", "2000-04-31", "0000"]
)
def test_impossible_alignment_date_fails_even_with_null_partner(field, value):
    failures = temporal(alignments=[alignment(**{field: value})])
    assert len(failures) == 1
    assert failures[0].record.startswith("alignments.geojson[0] a-1")
    assert field in failures[0].message
    assert "calendar" in messages(failures)


@pytest.mark.parametrize("field", ["date_start", "date_end"])
@pytest.mark.parametrize("value", ["2023-02-29", "2000-13-01", "0000"])
def test_impossible_observation_date_fails_even_with_null_partner(field, value):
    failures = temporal(observations=[observation(**{field: value})])
    assert len(failures) == 1
    assert failures[0].record.startswith("observations.geojson[0] o-1")
    assert field in failures[0].message


@pytest.mark.parametrize("value", ["2000", "2000-02-29"])
def test_real_dates_pass(value):
    assert temporal(alignments=[alignment(earliest_known_open=value)]) == []
    assert temporal(observations=[observation(date_start=value)]) == []


def test_every_bad_field_is_reported_not_just_the_first():
    failures = temporal(
        alignments=[
            alignment(
                earliest_known_open="2000-13-01",
                latest_known_open="2000-00-10",
                earliest_known_closed="2023-02-29",
                latest_known_closed="2000-04-31",
            )
        ]
    )
    assert len(failures) == 4


def test_wrong_shape_is_left_to_the_schema_check():
    # check_temporal runs after check_schema; a non-date string is already reported there.
    assert temporal(alignments=[alignment(earliest_known_open="sometime")]) == []
    assert temporal(alignments=[alignment(earliest_known_open="1954-06")]) == []


def test_non_string_date_does_not_raise():
    assert temporal(alignments=[alignment(earliest_known_open=1954)]) == []


# --------------------------------------------------------------------------------------
# Pairwise ordering
# --------------------------------------------------------------------------------------


def test_reversed_open_pair_fails():
    failures = temporal(
        alignments=[alignment(earliest_known_open="1970", latest_known_open="1960")]
    )
    assert len(failures) == 1
    assert "is after" in failures[0].message


def test_reversed_closed_pair_fails():
    failures = temporal(
        alignments=[alignment(earliest_known_closed="1990-01-02", latest_known_closed="1989")]
    )
    assert len(failures) == 1
    assert "is after" in failures[0].message


def test_reversed_observation_pair_fails():
    failures = temporal(
        observations=[observation(date_start="1975-06-01", date_end="1975-05-31")]
    )
    assert len(failures) == 1
    assert "is after" in failures[0].message


def test_null_bounds_constrain_nothing():
    assert temporal(alignments=[alignment()], observations=[observation()]) == []
    assert temporal(alignments=[alignment(latest_known_open="1960")]) == []


@pytest.mark.parametrize(
    ("lo", "hi"),
    [("1954-06-01", "1954"), ("1954", "1954-06-01"), ("1954", "1954"), ("1954", "1955")],
)
def test_mixed_precision_bounds_inside_the_same_year_pass(lo, hi):
    assert temporal(alignments=[alignment(earliest_known_open=lo, latest_known_open=hi)]) == []


# --------------------------------------------------------------------------------------
# No cross-pair rule (docs/open-questions.md, 2026-08-29)
# --------------------------------------------------------------------------------------


def test_open_then_closed_passes():
    assert (
        temporal(
            alignments=[
                alignment(
                    earliest_known_open="1962",
                    latest_known_open="1969",
                    earliest_known_closed="1988",
                    latest_known_closed="1993",
                )
            ]
        )
        == []
    )


def test_closed_before_open_passes_because_reopening_is_representable():
    assert (
        temporal(
            alignments=[
                alignment(
                    earliest_known_open="1988",
                    latest_known_open="1993",
                    earliest_known_closed="1962",
                    latest_known_closed="1969",
                )
            ]
        )
        == []
    )


# --------------------------------------------------------------------------------------
# End to end, through the CLI, on a copy of the authoritative graph
# --------------------------------------------------------------------------------------


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


def patch_first_alignment(data_dir, **changes):
    path = data_dir / "alignments.geojson"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["features"][0]["properties"].update(changes)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def test_fixture_graph_passes_temporal(workspace):
    assert run(workspace).exit_code == 0


def test_impossible_date_fails_the_cli(workspace):
    patch_first_alignment(workspace[0], earliest_known_open="2023-02-29")
    result = run(workspace)
    assert result.exit_code == 1
    assert "[temporal]" in result.output + result.stderr


def test_reopening_passes_the_cli(workspace):
    patch_first_alignment(
        workspace[0],
        earliest_known_open="1988",
        latest_known_open="1993",
        earliest_known_closed="1962",
        latest_known_closed="1969",
    )
    result = run(workspace)
    assert result.exit_code == 0, result.output
