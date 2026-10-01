"""D4b: the Make and CI wiring that decides what a release run actually executes.

Every check reads make's own dry-run expansion rather than the file text, so a target
that only looks right in the source cannot pass. Nothing here builds or validates.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"

MAKE = shutil.which("make")
pytestmark = pytest.mark.skipif(MAKE is None, reason="make is not on PATH")


def dry_run(*targets):
    """The commands `make` would run, in order, without running any of them."""
    result = subprocess.run(
        [MAKE, "--dry-run", "--no-print-directory", *targets],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def order(text, *needles):
    """Index of each needle, asserting every one appears and each follows the last."""
    at = -1
    found = []
    for needle in needles:
        index = text.find(needle, at + 1)
        assert index > at, f"{needle!r} missing or out of order in:\n{text}"
        at = index
        found.append(index)
    return found


# --- make demo-accept ------------------------------------------------------------------


def test_demo_accept_runs_tests_then_build_then_validation():
    text = dry_run("demo-accept")
    order(
        text,
        "scripts/test_demo_build.py",
        "scripts/demo.py build",
        "scripts/validate.py",
    )


def test_demo_accept_includes_the_frontend_and_browser_suites():
    text = dry_run("demo-accept")
    for command in ("run test", "test:browser", "test:browser:built"):
        assert command in text


def test_demo_build_renders_the_us_topo_pdfs_before_it_builds():
    # The two US Topo editions are checked and tiled from the renders expansion-pdf writes.
    order(dry_run("demo-build"), "scripts/demo_pdf.py run", "scripts/demo.py build")


def test_demo_test_runs_the_nine_edition_suites():
    text = dry_run("demo-test")
    for suite in (
        "scripts/test_demo_build.py",
        "scripts/test_demo_expansion.py",
        "scripts/test_demo_sources.py",
        "scripts/test_demo_pdf.py",
    ):
        assert suite in text


def test_expansion_check_verifies_the_active_manifest():
    text = dry_run("expansion-check")
    order(text, "scripts/demo_sources.py check", "scripts/demo.py check")
    assert "demo-editions-expanded.json" not in text


def test_demo_accept_validates_after_the_build_not_before():
    text = dry_run("demo-accept")
    assert text.count("scripts/validate.py") == 1
    build, validation = order(text, "scripts/demo.py build", "scripts/validate.py")
    assert build < validation


# --- bare make and the aliases ---------------------------------------------------------


def test_default_goal_builds_public_output_before_final_validation():
    text = dry_run()
    order(text, "scripts/demo.py build", "scripts/validate.py")


def test_build_public_is_the_demo_build():
    assert "scripts/demo.py build" in dry_run("build-public")


def test_dev_is_the_demo_dev_server():
    assert "run dev" in dry_run("dev")


# --- deferred and preserved targets ----------------------------------------------------


@pytest.mark.parametrize("target", ["tiles", "build-restricted", "rasters"])
def test_deferred_targets_fail_loudly_without_claiming_the_demo(target):
    result = subprocess.run(
        [MAKE, "--no-print-directory", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "deferred" in result.stdout


def test_coverage_ready_still_runs_the_countywide_release_gate():
    assert "coverage.py validate --release-ready" in dry_run("coverage-ready")


def test_setup_no_longer_requires_tippecanoe():
    recipe = subprocess.run(
        [MAKE, "--dry-run", "--no-print-directory", "setup"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "for tool in node" in recipe
    assert "brew install gdal tippecanoe node" not in recipe


# --- CI ---------------------------------------------------------------------------------


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def ci_steps():
    jobs = workflow()["jobs"]
    return [step for job in jobs.values() for step in job["steps"]]


def ci_commands():
    return "\n".join(step.get("run", "") for step in ci_steps())


@pytest.mark.parametrize(
    "target",
    [
        "make lint",
        "make validate",
        "make test-topo",
        "make test-validation",
        "make test-coverage",
    ],
)
def test_ci_keeps_every_existing_suite(target):
    assert target in ci_commands()


def test_ci_runs_the_offline_demo_suites():
    assert "make demo-test" in ci_commands()


def test_ci_installs_node_and_the_playwright_browser():
    steps = ci_steps()
    assert any("setup-node" in str(step.get("uses", "")) for step in steps)
    assert "make site-browsers" in ci_commands()


def test_ci_never_runs_the_real_source_build():
    commands = ci_commands()
    for forbidden in (
        "make demo-build",
        "make demo-check",
        "make demo-rasters",
        "make demo-accept",
    ):
        assert forbidden not in commands
    assert "DEMO_RAW_ROOT" not in commands
