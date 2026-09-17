"""Contract tests for the trail schema. Authoritative data is copied, never mutated."""

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
