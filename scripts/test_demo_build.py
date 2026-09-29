"""D4a: the allowlisted public assembly, on synthetic scans and a synthetic bundle only.

The four-edition fixture tree comes from test_demo.py, so this stage is checked against the
same synthetic sources as D2. Nothing here reads data/raw/, the committed receipt ledger or
a real npm build; `site/dist` is faked so the boundary tests cost a second, not a minute.
"""

import hashlib
import json
import shutil

import build_site
import click
import demo
import pytest
import test_demo
import test_demo_rasters
import validate

TEST_ZOOM = test_demo_rasters.TEST_ZOOM
SENTINEL = "SENTINEL-RESTRICTED-VALUE-45"

scans = test_demo.scans
tree = test_demo.tree


# --- fixtures --------------------------------------------------------------------------


def write_dist(root, *, js='window.viewer = "auburn";\n', extra=None):
    """A stand-in for site/dist: one page, one script, one stylesheet."""
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        '<!doctype html><html lang="en"><body>'
        '<script type="module" src="./assets/index.js"></script></body></html>\n',
        encoding="utf-8",
    )
    (root / "assets" / "index.js").write_text(js, encoding="utf-8")
    (root / "assets" / "index.css").write_text(".map { inset: 0; }\n", encoding="utf-8")
    for name, text in (extra or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


class Prepared:
    """A fixture tree with its pyramids cut, plus a built bundle ready to publish."""

    def __init__(self, tree, base):
        self.tree = tree
        self.build_root = base / "build"
        self.dist = write_dist(base / "dist")
        self.data_dir = build_site.DATA_DIR
        self.schema_dir = build_site.SCHEMA_DIR

    @property
    def public(self):
        return self.build_root / build_site.PUBLIC_DIRNAME

    @property
    def tile_root(self):
        return self.build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR

    @property
    def record_path(self):
        return self.build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME

    def record(self):
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    def write_record(self, payload):
        self.record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def rasters(self, zoom=TEST_ZOOM):
        return demo.run_rasters(
            self.tree.manifest_path,
            demo.SCHEMA_PATH,
            self.tree.index_path,
            self.tree.receipts_path,
            self.tree.sources_path,
            self.tree.raw_root,
            self.build_root,
            zoom,
        )

    def assemble(self, **overrides):
        return build_site.assemble_public(
            overrides.pop("build_root", self.build_root),
            overrides.pop("dist", self.dist),
            overrides.pop("manifest_path", self.tree.manifest_path),
            overrides.pop("data_dir", self.data_dir),
            overrides.pop("schema_dir", self.schema_dir),
        )


@pytest.fixture
def prepared(tree, tmp_path):
    fixture = Prepared(tree, tmp_path)
    fixture.rasters()
    return fixture


def published(root):
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


def digests(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def editions_json(public):
    return json.loads((public / build_site.EDITIONS_FILENAME).read_text(encoding="utf-8"))


def sentinel_data_dir(destination):
    """The committed fixture records with one restricted value replaced by a sentinel."""
    shutil.copytree(build_site.DATA_DIR, destination)
    path = destination / "observations.geojson"
    path.write_text(
        path.read_text(encoding="utf-8").replace("FIXTURE DECLARANT", SENTINEL),
        encoding="utf-8",
    )
    return destination


# --- a clean build ---------------------------------------------------------------------


def test_a_clean_build_holds_only_app_assets_metadata_and_the_four_tile_trees(prepared):
    result = prepared.assemble()
    files = published(prepared.public)
    assert "index.html" in files
    assert "editions.json" in files
    assert "assets/index.js" in files
    assert "assets/index.css" in files

    app = [name for name in files if not name.startswith("tiles/")]
    assert sorted(app) == ["assets/index.css", "assets/index.js", "editions.json", "index.html"]
    tiles = [name for name in files if name.startswith("tiles/")]
    assert tiles and all(name.endswith(".png") for name in tiles)
    assert sorted({name.split("/")[1] for name in tiles}) == sorted(demo.EDITION_ORDER)

    # No COG, no processing record, no receipt, no authoritative record came along.
    assert not any(name.endswith((".tif", ".jsonl", ".csv", ".geojson")) for name in files)
    assert result["inventory"]["totals"]["files"] == len(files)


def test_the_published_metadata_is_display_only_and_same_origin(prepared):
    prepared.assemble()
    payload = editions_json(prepared.public)

    assert tuple(payload) == build_site.PUBLIC_MANIFEST_KEYS
    assert payload["edition_order"] == list(demo.EDITION_ORDER)
    assert payload["view_bounds_wgs84"] == prepared.tree.manifest["view_bounds_wgs84"]
    # The zoom limits are the range actually cut, not the manifest's intended maximum.
    assert payload["tile_zoom"] == {"min": 10, "max": TEST_ZOOM}

    for edition in payload["editions"]:
        assert tuple(edition) == build_site.PUBLIC_EDITION_KEYS
        assert edition["tile_url"] == f"tiles/{edition['id']}/{{z}}/{{x}}/{{y}}.png"
        assert "://" not in edition["tile_url"]
        assert not edition["tile_url"].startswith("/")

    blob = (prepared.public / build_site.EDITIONS_FILENAME).read_text(encoding="utf-8")
    for token in ("crop_wgs84", "raw_path", "sha256", "retrieved_at", "data/raw"):
        assert token not in blob
    assert str(build_site.REPO_ROOT) not in blob
    assert str(prepared.tree.raw_root) not in blob


def test_the_published_template_is_the_one_the_dev_server_serves():
    """A drift between editions.ts and build_site.py would break the built app silently."""
    source = (build_site.SITE_DIR / "src" / "editions.ts").read_text(encoding="utf-8")
    assert 'export const TILE_URL_PREFIX = "tiles";' in source
    assert "`${TILE_URL_PREFIX}/${id}/{z}/{x}/{y}.png`" in source
    assert build_site.TILE_PREFIX == "tiles"


def test_the_inventory_records_the_real_output_bytes(prepared):
    result = prepared.assemble()
    inventory = result["inventory"]
    files = [path for path in prepared.public.rglob("*") if path.is_file()]

    assert inventory["totals"]["files"] == len(files)
    assert inventory["totals"]["bytes"] == sum(path.stat().st_size for path in files)
    recorded = {entry["id"]: entry for entry in prepared.record()["tiles"]["editions"]}
    for entry in inventory["editions"]:
        assert entry["tiles"] == recorded[entry["id"]]["tiles"]
        assert entry["bytes"] == recorded[entry["id"]]["bytes"]
        assert entry["digest"] == recorded[entry["id"]]["digest"]
    assert inventory["totals"]["tiles"] == sum(e["tiles"] for e in inventory["editions"])
    assert "automated only" in inventory["notes"]["inspection"]
    assert "#38" in inventory["notes"]["human_acceptance"]
    # The inventory is internal: it names source hashes and never sits inside build/public.
    assert result["inventory_path"].parent == prepared.build_root / build_site.PUBLISH_DIRNAME


def test_rebuilding_publishes_the_same_tree_and_leaves_no_temporary_directories(prepared):
    prepared.assemble()
    first = digests(prepared.public)
    prepared.assemble()
    assert digests(prepared.public) == first
    assert not (prepared.build_root / build_site.STAGING_DIRNAME).exists()
    assert not (prepared.build_root / build_site.PREVIOUS_DIRNAME).exists()


# --- missing and incomplete output -----------------------------------------------------


def test_a_missing_tile_tree_fails_and_publishes_nothing(prepared):
    shutil.rmtree(prepared.tile_root / demo.EDITION_ORDER[2])
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert demo.EDITION_ORDER[2] in str(error.value)
    assert not prepared.public.exists()


def test_an_incomplete_tile_tree_fails_against_the_recorded_digest(prepared):
    victim = sorted((prepared.tile_root / demo.EDITION_ORDER[0]).rglob("*.png"))[0]
    victim.unlink()
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "re-run make demo-rasters" in str(error.value)
    assert not prepared.public.exists()


def test_a_stray_file_inside_a_tile_tree_fails(prepared):
    (prepared.tile_root / demo.EDITION_ORDER[0] / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "not a z/x/y.png tile" in str(error.value)
    assert not prepared.public.exists()


def test_a_tile_outside_the_built_zoom_range_fails(prepared):
    stray = prepared.tile_root / demo.EDITION_ORDER[0] / str(TEST_ZOOM + 4) / "1" / "1.png"
    stray.parent.mkdir(parents=True)
    shutil.copyfile(
        sorted((prepared.tile_root / demo.EDITION_ORDER[0]).rglob("*.png"))[0], stray
    )
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "outside the built range" in str(error.value)


def test_missing_display_metadata_fails_before_anything_is_published(prepared):
    manifest = json.loads(json.dumps(prepared.tree.manifest))
    del manifest["editions"][1]["label"]
    prepared.tree.write_manifest(manifest)
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "has no label" in str(error.value)
    assert not prepared.public.exists()


def test_a_manifest_without_a_recorded_pyramid_fails(prepared):
    record = prepared.record()
    record["tiles"]["editions"] = record["tiles"]["editions"][:3]
    prepared.write_record(record)
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "no pyramid recorded" in str(error.value)


def test_a_build_root_without_a_processing_record_fails(prepared, tmp_path):
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(build_root=tmp_path / "empty-build")
    assert demo.PROCESSING_FILENAME in str(error.value)


# --- unselected sources, traversal and prohibited files --------------------------------


def test_an_unselected_tile_tree_is_rejected_and_never_copied(prepared):
    foreign = prepared.tile_root / "auburn-1999"
    (foreign / "10" / "1").mkdir(parents=True)
    (foreign / "10" / "1" / "1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "unselected entries ['auburn-1999']" in str(error.value)
    assert not prepared.public.exists()
    assert not (prepared.build_root / build_site.STAGING_DIRNAME).exists()


def test_a_traversing_edition_id_is_refused(prepared, tmp_path):
    manifest = json.loads(json.dumps(prepared.tree.manifest))
    manifest["edition_order"][0] = "../escape"
    manifest["editions"][0]["id"] = "../escape"
    prepared.tree.write_manifest(manifest)
    record = prepared.record()
    record["edition_order"] = list(manifest["edition_order"])
    prepared.write_record(record)

    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "not a safe published directory name" in str(error.value)
    assert not (tmp_path / "escape").exists()
    assert not prepared.public.exists()


def test_safe_destination_refuses_traversal_and_absolute_paths(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    assert build_site.safe_destination(root, "tiles/auburn-1953/10/1/1.png").is_relative_to(
        root
    )
    for unsafe in ("../escape", "tiles/../../escape", "/etc/passwd", "."):
        with pytest.raises(click.ClickException):
            build_site.safe_destination(root, unsafe)


def test_a_prohibited_file_in_the_bundle_is_refused(prepared, tmp_path):
    dist = write_dist(tmp_path / "dirty-dist", extra={demo.PROCESSING_FILENAME: "{}\n"})
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(dist=dist)
    assert "not an allowlisted app asset" in str(error.value)
    assert not prepared.public.exists()


def test_a_source_map_in_the_bundle_is_refused(prepared, tmp_path):
    dist = write_dist(tmp_path / "mapped-dist", extra={"assets/index.js.map": "{}\n"})
    with pytest.raises(click.ClickException):
        prepared.assemble(dist=dist)


def test_a_bundle_without_a_page_or_a_script_is_refused(prepared, tmp_path):
    dist = write_dist(tmp_path / "pageless")
    (dist / "index.html").unlink()
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(dist=dist)
    assert "no index.html" in str(error.value)


def test_a_root_absolute_asset_reference_is_refused(prepared, tmp_path):
    dist = write_dist(tmp_path / "rooted-dist")
    (dist / "index.html").write_text(
        '<!doctype html><html lang="en"><body>'
        '<script type="module" src="/assets/index.js"></script></body></html>\n',
        encoding="utf-8",
    )
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(dist=dist)
    assert "relative same-origin paths" in str(error.value)
    assert not prepared.public.exists()


def test_the_published_page_resolves_its_assets_relatively(prepared):
    prepared.assemble()
    references = [
        reference
        for reference in build_site.REFERENCE_PATTERN.findall(
            (prepared.public / "index.html").read_text(encoding="utf-8")
        )
        if not reference.startswith("data:")
    ]
    assert references
    assert all(not r.startswith("/") and "://" not in r for r in references)


def test_the_dev_test_probe_cannot_reach_the_published_bundle(prepared, tmp_path):
    dist = write_dist(tmp_path / "probe-dist", js="window.__demoTestProbe = {};\n")
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(dist=dist)
    assert "__demoTestProbe" in str(error.value)
    assert not prepared.public.exists()


def test_a_missing_bundle_is_refused(prepared, tmp_path):
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(dist=tmp_path / "never-built")
    assert "No built site" in str(error.value)


# --- stale output and atomic publication -----------------------------------------------


def test_stale_output_is_not_carried_into_a_fresh_build(prepared):
    stale = prepared.public / "stale" / "leftover.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("<p>old build</p>\n", encoding="utf-8")
    staged_stale = prepared.build_root / build_site.STAGING_DIRNAME / "injected.html"
    staged_stale.parent.mkdir(parents=True)
    staged_stale.write_text("<p>injected</p>\n", encoding="utf-8")

    prepared.assemble()
    assert not stale.exists()
    assert not (prepared.public / "injected.html").exists()
    assert "stale/leftover.html" not in published(prepared.public)


def test_a_failed_build_leaves_the_previous_build_intact(prepared):
    prepared.assemble()
    before = digests(prepared.public)
    sorted((prepared.tile_root / demo.EDITION_ORDER[1]).rglob("*.png"))[0].unlink()

    with pytest.raises(click.ClickException):
        prepared.assemble()
    assert digests(prepared.public) == before
    assert not (prepared.build_root / build_site.STAGING_DIRNAME).exists()
    assert not (prepared.build_root / build_site.PREVIOUS_DIRNAME).exists()


# --- the restricted-value scan ---------------------------------------------------------


def test_the_scanner_runs_against_the_staged_output_that_really_exists(prepared, monkeypatch):
    seen = {}
    original = validate.check_leak

    def spy(records, schemas, public_build):
        seen["path"] = public_build
        seen["files"] = sorted(
            path.relative_to(public_build).as_posix()
            for path in public_build.rglob("*")
            if path.is_file()
        )
        seen["restricted"] = len(validate.collect_restricted(records, schemas))
        return original(records, schemas, public_build)

    monkeypatch.setattr(validate, "check_leak", spy)
    prepared.assemble()

    assert seen["path"] == prepared.build_root / build_site.STAGING_DIRNAME
    assert "editions.json" in seen["files"]
    assert any(name.startswith("tiles/") for name in seen["files"])
    # A scan of an empty directory would watch the same values and find nothing.
    assert seen["restricted"] > 0


def test_the_scanner_refuses_a_directory_that_does_not_exist_or_is_empty(prepared, tmp_path):
    missing = tmp_path / "nowhere"
    with pytest.raises(click.ClickException) as error:
        build_site.scan_for_restricted(missing, prepared.data_dir, prepared.schema_dir)
    assert "does not exist" in str(error.value)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(click.ClickException) as error:
        build_site.scan_for_restricted(empty, prepared.data_dir, prepared.schema_dir)
    assert "holds no files" in str(error.value)


def test_a_restricted_sentinel_in_the_metadata_fails_the_build(prepared, tmp_path):
    data_dir = sentinel_data_dir(tmp_path / "authoritative")
    manifest = json.loads(json.dumps(prepared.tree.manifest))
    manifest["editions"][0]["label"] = f"Auburn 1953 topographic map ({SENTINEL})"
    prepared.tree.write_manifest(manifest)

    with pytest.raises(click.ClickException) as error:
        prepared.assemble(data_dir=data_dir)
    message = str(error.value)
    assert "Restricted values reached the staged public build" in message
    assert SENTINEL in message
    assert not prepared.public.exists()


def test_a_restricted_sentinel_in_an_app_asset_fails_the_build(prepared, tmp_path):
    data_dir = sentinel_data_dir(tmp_path / "authoritative")
    dist = write_dist(tmp_path / "leaky-dist", js=f'const note = "{SENTINEL}";\n')
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(dist=dist, data_dir=data_dir)
    assert SENTINEL in str(error.value)
    assert not prepared.public.exists()


def test_the_committed_fixture_records_do_not_leak_into_a_clean_build(prepared):
    prepared.assemble()
    records, failures = validate.load_records(prepared.data_dir)
    assert not failures
    schemas = {
        "trails": demo.read_json(prepared.schema_dir / "trail.schema.json"),
        "alignments": demo.read_json(prepared.schema_dir / "alignment.schema.json"),
        "observations": demo.read_json(prepared.schema_dir / "observation.schema.json"),
        "support": demo.read_json(prepared.schema_dir / "support.schema.json"),
    }
    leaks, note = validate.check_leak(records, schemas, prepared.public)
    assert leaks == []
    assert "scanned" in note


# --- the whole pipeline ----------------------------------------------------------------


def test_run_build_cuts_the_rasters_publishes_and_leaves_the_sources_untouched(tree, tmp_path):
    dist = write_dist(tmp_path / "dist")
    build_root = tmp_path / "build"
    before = test_demo_rasters.tree_digests(tree)

    result = build_site.run_build(
        tree.manifest_path,
        demo.SCHEMA_PATH,
        tree.index_path,
        tree.receipts_path,
        tree.sources_path,
        tree.raw_root,
        build_root,
        TEST_ZOOM,
        dist=dist,
        vite=False,
    )

    public = build_root / build_site.PUBLIC_DIRNAME
    assert (public / "editions.json").is_file()
    assert (public / "index.html").is_file()
    for edition_id in demo.EDITION_ORDER:
        assert any((public / "tiles" / edition_id).rglob("*.png"))
    cut = result["rasters"]["record"]["tiles"]["totals"]["tiles"]
    assert result["inventory"]["totals"]["tiles"] == cut
    # AGENTS.md §2.2: the scans and their receipts are exactly what they were.
    assert test_demo_rasters.tree_digests(tree) == before


def test_the_build_command_reports_the_inventory_it_published(tree, tmp_path):
    from click.testing import CliRunner

    dist = write_dist(tmp_path / "dist")
    build_root = tmp_path / "build"
    result = CliRunner().invoke(
        demo.cli,
        [
            "build",
            "--manifest",
            str(tree.manifest_path),
            "--schema",
            str(demo.SCHEMA_PATH),
            "--index",
            str(tree.index_path),
            "--receipts",
            str(tree.receipts_path),
            "--sources",
            str(tree.sources_path),
            "--raw-root",
            str(tree.raw_root),
            "--build-root",
            str(build_root),
            "--grid-zoom",
            str(TEST_ZOOM),
            "--dist",
            str(dist),
            "--no-vite",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "demo-build: published" in result.output
    assert "editions.json" in result.output
    for edition_id in demo.EDITION_ORDER:
        assert f"tiles/{edition_id}" in result.output
