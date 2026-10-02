"""D4a and #58: the allowlisted public assembly of the nine editions, on synthetic sources.

The nine-edition fixture tree comes from test_demo.py, so this stage is checked against the
same synthetic scans and rendered PDF pages as D2 and #57. Nothing here reads data/raw/, the
committed receipt ledgers or a real npm build; `site/dist` is faked.
"""

import copy
import hashlib
import json
import shutil

import build_site
import click
import demo
import demo_expansion
import demo_sources
import pytest
import test_demo
import test_demo_rasters
import validate

# The cheapest top zoom at which the regional sheets (native 14) stop below the others (15),
# so every per-edition zoom check below sees two different ranges.
TEST_ZOOM = 15
SMALL_ZOOM = test_demo_rasters.TEST_ZOOM
SENTINEL = "SENTINEL-RESTRICTED-VALUE-45"
ORDER = demo.EXPANDED_EDITION_ORDER
ADDED = [eid for eid in ORDER if eid not in demo.EDITION_ORDER]
EXPECTED_TOP = {
    eid: min(demo.EXPANDED_EXPECTED_EDITIONS[eid]["native_max_zoom"], TEST_ZOOM)
    for eid in ORDER
}

scans = test_demo.scans
tree = test_demo.tree
added_scans = test_demo.added_scans
expanded_manifest = test_demo.expanded_manifest
expanded_tree = test_demo.expanded_tree


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
    """A nine-edition fixture tree with its pyramids cut, plus a built bundle to publish.

    Everything lives under the tree's own directory, so a copy of it is a whole new world.
    """

    def __init__(self, tree):
        self.tree = tree
        self.build_root = tree.base / "build"
        self.dist = tree.base / "dist"
        if not self.dist.exists():
            write_dist(self.dist)
        self.data_dir = build_site.DATA_DIR
        self.schema_dir = build_site.SCHEMA_DIR

    @property
    def public(self):
        return self.build_root / build_site.PUBLIC_DIRNAME

    @property
    def tile_root(self):
        return self.build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR

    @property
    def expansion_root(self):
        return self.tree.expansion_root

    @property
    def added_tile_root(self):
        return self.expansion_root / demo_expansion.TILE_DIRNAME

    def tree_of(self, edition_id):
        root = self.tile_root if edition_id in demo.EDITION_ORDER else self.added_tile_root
        return root / edition_id

    @property
    def record_path(self):
        return self.build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME

    @property
    def added_record_path(self):
        return self.expansion_root / demo_expansion.RECORD_NAME

    def record(self):
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    def write_record(self, payload):
        self.record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def added_record(self):
        return json.loads(self.added_record_path.read_text(encoding="utf-8"))

    def write_added_record(self, payload):
        self.added_record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
            demo_sources.CATALOG_PATH,
            self.tree.ledger_path,
            self.expansion_root,
        )

    def assemble(self, **overrides):
        return build_site.assemble_public(
            overrides.pop("build_root", self.build_root),
            overrides.pop("dist", self.dist),
            overrides.pop("manifest_path", self.tree.manifest_path),
            overrides.pop("data_dir", self.data_dir),
            overrides.pop("schema_dir", self.schema_dir),
            overrides.pop("expansion_root", self.expansion_root),
        )


@pytest.fixture(scope="module")
def template(tmp_path_factory, scans, added_scans, expanded_manifest):
    """Cut once per module: nine pyramids at TEST_ZOOM take far longer than copying them."""
    base = tmp_path_factory.mktemp("build-template") / "tree"
    fixture = Prepared(
        test_demo.build_expanded_tree(
            base, scans, added_scans, copy.deepcopy(expanded_manifest)
        )
    )
    fixture.rasters()
    return fixture


@pytest.fixture
def prepared(template, tmp_path):
    base = tmp_path / "prepared"
    shutil.copytree(template.tree.base, base)
    tree = test_demo.Tree(base, copy.deepcopy(template.tree.manifest))
    tree.index_rows = copy.deepcopy(template.tree.index_rows)
    return Prepared(tree)


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


def test_a_clean_build_holds_only_app_assets_metadata_and_the_nine_tile_trees(prepared):
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
    assert sorted({name.split("/")[1] for name in tiles}) == sorted(ORDER)
    assert len(ORDER) == 9
    assert sorted(path.name for path in (prepared.public / "tiles").iterdir()) == sorted(ORDER)

    # No COG, PDF, processing record, receipt or authoritative record came along.
    assert not any(
        name.endswith((".tif", ".pdf", ".jsonl", ".csv", ".geojson")) for name in files
    )
    for name in (demo.PROCESSING_FILENAME, demo.PDF_RECORD_NAME, demo_expansion.RECORD_NAME):
        assert not any(path.endswith(name) for path in files)
    assert result["inventory"]["totals"]["files"] == len(files)


def test_each_edition_is_published_over_its_own_zoom_range(prepared):
    result = prepared.assemble()
    for edition_id in ORDER:
        levels = sorted(int(p.name) for p in (prepared.public / "tiles" / edition_id).iterdir())
        assert levels == list(range(10, EXPECTED_TOP[edition_id] + 1)), edition_id
    # The regional sheets stop below the build's top zoom; the viewer overzooms them.
    assert EXPECTED_TOP["sacramento-1891"] == EXPECTED_TOP["sacramento-1994"] == 14
    assert EXPECTED_TOP["auburn-1953"] == TEST_ZOOM
    inventory = {entry["id"]: entry for entry in result["inventory"]["editions"]}
    for edition_id in ORDER:
        assert inventory[edition_id]["zoom"] == {"min": 10, "max": EXPECTED_TOP[edition_id]}


def test_the_published_metadata_is_display_only_and_same_origin(prepared):
    prepared.assemble()
    payload = editions_json(prepared.public)

    assert tuple(payload) == build_site.PUBLIC_MANIFEST_KEYS
    assert payload["edition_order"] == list(ORDER)
    assert payload["initial_edition"] == "auburn-1953"
    assert payload["view_bounds_wgs84"] == prepared.tree.manifest["view_bounds_wgs84"]
    # The zoom limits are the range actually cut, not the manifest's intended maximum.
    assert payload["tile_zoom"] == {"min": 10, "max": TEST_ZOOM}

    for edition in payload["editions"]:
        assert tuple(edition) == build_site.PUBLIC_EDITION_KEYS
        assert edition["tile_url"] == f"tiles/{edition['id']}/{{z}}/{{x}}/{{y}}.png"
        assert "://" not in edition["tile_url"]
        assert not edition["tile_url"].startswith("/")
        assert edition["native_max_zoom"] == EXPECTED_TOP[edition["id"]]

    by_id = {edition["id"]: edition for edition in payload["editions"]}
    assert (by_id["sacramento-1891"]["sheet_name"], by_id["sacramento-1891"]["scale"]) == (
        "Sacramento",
        125000,
    )
    assert by_id["auburn-2021"]["printed_credit_note"].startswith("Produced by the United")

    blob = (prepared.public / build_site.EDITIONS_FILENAME).read_text(encoding="utf-8")
    for token in (
        "crop_wgs84",
        "raw_path",
        "sha256",
        "retrieved_at",
        "data/raw",
        "pdf_raw_path",
        "rendered_cog",
        "retrieval_url",
        "metadata_url",
        "size_bytes",
        ".pdf",
        ".tif",
    ):
        assert token not in blob
    assert set(build_site.FORBIDDEN_METADATA_TOKENS) >= {
        "crop_wgs84",
        "sha256",
        "data/raw",
        "retrieval_url",
        "metadata_url",
        "rendered_cog",
        ".pdf",
    }
    assert str(build_site.REPO_ROOT) not in blob
    assert str(prepared.tree.raw_root) not in blob


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("date_note", "rendered from data/raw/us-topo/sha256/ab/ab.pdf"),
        ("source_url", "https://prd-tnm.s3.amazonaws.com/x/CA_Auburn_20211230_TM_geo.pdf"),
        ("citation", "see demo-expansion-processing.json"),
    ],
)
def test_an_internal_value_in_a_public_field_is_refused(prepared, field, value):
    manifest = json.loads(json.dumps(prepared.tree.manifest))
    test_demo.by_id(manifest, "auburn-2021")[field] = value
    prepared.tree.write_manifest(manifest)
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "carries internal detail" in str(error.value)
    assert not prepared.public.exists()


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
    for entry in prepared.added_record()["editions"]:
        recorded[entry["id"]] = entry["tiles"]
    assert sorted(entry["id"] for entry in inventory["editions"]) == sorted(ORDER)
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


@pytest.mark.parametrize("edition_id", ["auburn-1975", "sacramento-1994"])
def test_a_missing_tile_tree_fails_and_publishes_nothing(prepared, edition_id):
    shutil.rmtree(prepared.tree_of(edition_id))
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert edition_id in str(error.value)
    assert not prepared.public.exists()


@pytest.mark.parametrize("edition_id", ["auburn-1953", "auburn-2018"])
def test_an_incomplete_tile_tree_fails_against_the_recorded_digest(prepared, edition_id):
    victim = sorted(prepared.tree_of(edition_id).rglob("*.png"))[0]
    victim.unlink()
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "re-run make demo-rasters" in str(error.value)
    assert not prepared.public.exists()


def test_a_stray_file_inside_a_tile_tree_fails(prepared):
    (prepared.tree_of("auburn-1944") / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "not a z/x/y.png tile" in str(error.value)
    assert not prepared.public.exists()


@pytest.mark.parametrize(
    ("edition_id", "zoom"),
    [
        ("auburn-1953", TEST_ZOOM + 4),
        # Inside the build's range, but above this sheet's own native zoom of 14.
        ("sacramento-1891", 15),
    ],
)
def test_a_tile_outside_the_editions_own_zoom_range_fails(prepared, edition_id, zoom):
    root = prepared.tree_of(edition_id)
    stray = root / str(zoom) / "1" / "1.png"
    stray.parent.mkdir(parents=True)
    shutil.copyfile(sorted(root.rglob("*.png"))[0], stray)
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "outside the built range" in str(error.value)
    assert edition_id in str(error.value)
    assert not prepared.public.exists()


def test_a_pyramid_recorded_over_another_zoom_range_is_refused(prepared):
    """A pyramid from a differently capped run must not be mixed into this build."""
    record = prepared.added_record()
    entry = next(e for e in record["editions"] if e["id"] == "sacramento-1891")
    entry["zoom"]["max"] = TEST_ZOOM
    prepared.write_added_record(record)
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "sacramento-1891" in str(error.value)
    assert "covers zoom" in str(error.value)
    assert not prepared.public.exists()


def test_a_pyramid_cut_for_another_crop_is_refused(prepared):
    manifest = json.loads(json.dumps(prepared.tree.manifest))
    ring = test_demo.by_id(manifest, "auburn-2018")["crop_wgs84"]["coordinates"][0]
    ring[1] = [demo.q6(ring[1][0] + 0.001), ring[1][1]]
    prepared.tree.write_manifest(manifest)
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "auburn-2018" in str(error.value)
    assert "another crop" in str(error.value)
    assert not prepared.public.exists()


def test_a_missing_expansion_record_fails(prepared):
    prepared.added_record_path.unlink()
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert demo_expansion.RECORD_NAME in str(error.value)
    assert not prepared.public.exists()


def test_an_expansion_record_for_another_edition_set_fails(prepared):
    record = prepared.added_record()
    record["edition_order"] = record["edition_order"][::-1]
    prepared.write_added_record(record)
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "another edition set" in str(error.value)


def test_the_four_edition_manifest_is_not_published(prepared, tree):
    with pytest.raises(click.ClickException) as error:
        prepared.assemble(manifest_path=tree.manifest_path)
    assert "version-2 nine-edition manifest" in str(error.value)
    assert not prepared.public.exists()


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


@pytest.mark.parametrize("where", ["base", "added"])
def test_an_unselected_tile_tree_is_rejected_and_never_copied(prepared, where):
    root = prepared.tile_root if where == "base" else prepared.added_tile_root
    foreign = root / "auburn-1999"
    (foreign / "10" / "1").mkdir(parents=True)
    (foreign / "10" / "1" / "1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "unselected entries ['auburn-1999']" in str(error.value)
    assert not prepared.public.exists()
    assert not (prepared.build_root / build_site.STAGING_DIRNAME).exists()


def test_an_added_edition_left_in_the_base_tile_root_is_rejected(prepared):
    """A pyramid in the wrong root is a mixed build, not a spare copy to ignore."""
    shutil.copytree(prepared.tree_of("auburn-2021"), prepared.tile_root / "auburn-2021")
    with pytest.raises(click.ClickException) as error:
        prepared.assemble()
    assert "unselected entries ['auburn-2021']" in str(error.value)


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
    sorted(prepared.tree_of("auburn-1944").rglob("*.png"))[0].unlink()

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


def raw_digests(tree):
    return {
        path.relative_to(tree.base).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(tree.raw_root.rglob("*"))
        if path.is_file()
    } | {
        name: hashlib.sha256((tree.base / name).read_bytes()).hexdigest()
        for name in (tree.receipts_path.name, tree.ledger_path.name)
    }


def test_run_build_cuts_the_rasters_publishes_and_leaves_the_sources_untouched(
    expanded_tree, tmp_path
):
    dist = write_dist(tmp_path / "dist")
    build_root = tmp_path / "build"
    before = raw_digests(expanded_tree)

    result = build_site.run_build(
        expanded_tree.manifest_path,
        demo.SCHEMA_PATH,
        expanded_tree.index_path,
        expanded_tree.receipts_path,
        expanded_tree.sources_path,
        expanded_tree.raw_root,
        build_root,
        SMALL_ZOOM,
        dist=dist,
        vite=False,
        catalog_path=demo_sources.CATALOG_PATH,
        ledger_path=expanded_tree.ledger_path,
        expansion_root=expanded_tree.expansion_root,
    )

    public = build_root / build_site.PUBLIC_DIRNAME
    assert (public / "editions.json").is_file()
    assert (public / "index.html").is_file()
    assert sorted(path.name for path in (public / "tiles").iterdir()) == sorted(ORDER)
    for edition_id in ORDER:
        assert any((public / "tiles" / edition_id).rglob("*.png"))
    cut = result["rasters"]["record"]["tiles"]["totals"]["tiles"]
    cut += result["rasters"]["expansion"]["record"]["tiles"]["totals"]["tiles"]
    assert result["inventory"]["totals"]["tiles"] == cut
    # AGENTS.md §2.2: the scans, the PDFs and their receipts are exactly what they were.
    assert raw_digests(expanded_tree) == before


def test_the_build_command_reports_the_inventory_it_published(expanded_tree, tmp_path):
    from click.testing import CliRunner

    dist = write_dist(tmp_path / "dist")
    build_root = tmp_path / "build"
    result = CliRunner().invoke(
        demo.cli,
        [
            "build",
            *expanded_tree.paths_args(),
            "--build-root",
            str(build_root),
            "--grid-zoom",
            str(SMALL_ZOOM),
            "--dist",
            str(dist),
            "--no-vite",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "demo-build: published" in result.output
    assert "editions.json" in result.output
    for edition_id in ORDER:
        assert f"tiles/{edition_id}" in result.output
