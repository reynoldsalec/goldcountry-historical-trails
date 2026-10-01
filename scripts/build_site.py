"""Assemble build/public/ for the Auburn map browser: app assets, sanitized edition
metadata and the nine tile pyramids, published atomically (AGENTS.md §2.5, D4a, #58).

Nothing is copied that is not named by an allowlist here, so a file added anywhere under
data/, docs/ or build/ cannot reach the public build by being in the way. Publication is
the last step: a failure leaves the previous build exactly as it was.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import demo
import demo_expansion
import demo_sources
import validate
import warp_raster
from demo import fail, read_json
from warp_raster import WarpError

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
DIST_DIRNAME = "dist"
DATA_DIR = REPO_ROOT / "data/authoritative"
SCHEMA_DIR = REPO_ROOT / "schema"

PUBLIC_DIRNAME = "public"
STAGING_DIRNAME = ".public-incoming"
PREVIOUS_DIRNAME = ".public-previous"
PUBLISH_DIRNAME = "publish"
PUBLISH_FILENAME = "demo-publish.json"
EDITIONS_FILENAME = "editions.json"
TILE_PREFIX = "tiles"
EXPANSION_DIRNAME = "expansion"
PUBLISHED_MANIFEST_VERSION = 2

# The viewer fetches ./editions.json and resolves tile templates against its own document,
# so every published path is relative and same-origin.
TILE_TEMPLATE = TILE_PREFIX + "/{edition_id}/{z}/{x}/{y}.png"

# What a static viewer is allowed to consist of. Source maps are excluded deliberately:
# they would republish the TypeScript sources as site content.
ALLOWED_APP_SUFFIXES = frozenset({".html", ".css", ".js", ".svg", ".png", ".woff2", ".ico"})
REQUIRED_APP_FILE = "index.html"

# Repository artifacts that must never appear under build/public/, by name and by kind.
PROHIBITED_NAMES = frozenset(
    {
        demo.PROCESSING_FILENAME,
        demo.PDF_RECORD_NAME,
        demo_expansion.RECORD_NAME,
        demo_sources.CATALOG_PATH.name,
        demo_sources.LEDGER_PATH.name,
        "demo-expansion-topo.json",
        "demo-editions.json",
        "retrievals.jsonl",
        "coverage.json",
        "coverage_grid.geojson",
        "topo_index.csv",
        "sources.yml",
        "trails.json",
        "alignments.geojson",
        "observations.geojson",
        "support.csv",
        PUBLISH_FILENAME,
    }
)
PROHIBITED_SUFFIXES = frozenset(
    {
        ".tif",
        ".tiff",
        ".jsonl",
        ".csv",
        ".geojson",
        ".points",
        ".yml",
        ".yaml",
        ".md",
        ".py",
        ".ts",
        ".pdf",
        ".map",
    }
)

# site/tests/assert-no-test-probe.mjs makes the same check on site/dist; the published
# bundle is what users get, so it is checked again here.
FORBIDDEN_BUNDLE_TOKEN = "__demoTestProbe"

# Internal-only manifest, receipt and processing-record keys, and anything naming this
# machine or this checkout. If one reaches editions.json it has stopped being display-only.
FORBIDDEN_METADATA_TOKENS = (
    "crop_wgs84",
    "raw_path",
    "sha256",
    "retrieved_at",
    "data/raw",
    "retrieval_url",
    "metadata_url",
    "size_bytes",
    "rendered_cog",
    "fingerprint",
    "us-topo/sha256",
    ".pdf",
    ".tif",
    "processing.json",
)

EDITION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REFERENCE_PATTERN = re.compile(r'(?:src|href)="([^"]*)"')
TILE_COMPONENT_PATTERN = re.compile(r"^(0|[1-9][0-9]{0,8})$")

# `native_max_zoom` is published as the top zoom actually cut for the edition: above it the
# viewer overzooms that level instead of asking for tiles that do not exist.
PUBLIC_EDITION_KEYS = (
    "id",
    "source_id",
    "kind",
    "source_kind",
    "label",
    "sheet_name",
    "scale",
    "citation",
    "source_url",
    "rights",
    "attribution",
    "printed_credit_note",
    "publication_date",
    "dates",
    "component_dates",
    "date_note",
    "native_resolution_metres",
    "native_max_zoom",
    "tile_url",
)
PUBLIC_MANIFEST_KEYS = (
    "version",
    "area_id",
    "edition_order",
    "initial_edition",
    "view_bounds_wgs84",
    "tile_zoom",
    "editions",
)


# --------------------------------------------------------------------------------------
# Sanitized public metadata
# --------------------------------------------------------------------------------------


def public_edition(edition: dict, edition_id: str, max_zoom: int) -> dict:
    """One edition reduced to the display fields, plus its relative tile template."""
    projected = {}
    for key in PUBLIC_EDITION_KEYS:
        if key == "tile_url":
            projected[key] = TILE_TEMPLATE.format(
                edition_id=edition_id, z="{z}", x="{x}", y="{y}"
            )
            continue
        if key == "native_max_zoom":
            projected[key] = max_zoom
            continue
        if key not in edition:
            fail(f"{edition_id}: the manifest has no {key}; the public card cannot be built.")
        projected[key] = edition[key]
    return projected


def sanitize_manifest(manifest: dict, tile_zoom: dict, edition_zoom: dict[str, int]) -> dict:
    """Project the internal manifest onto the display-only shape the viewer fetches.

    Mirrors `publicManifestFrom` in site/src/editions.ts, which the dev server uses, so
    the built site and `make demo-dev` read the same shape. `edition_zoom` is each edition's
    top cut zoom.
    """
    editions = manifest.get("editions")
    order = manifest.get("edition_order")
    if not isinstance(editions, list) or not isinstance(order, list) or not order:
        fail("The manifest has no edition_order/editions pair to publish.")
    by_id = {edition.get("id"): edition for edition in editions}
    if len(by_id) != len(editions):
        fail("The manifest holds two editions with the same id.")
    if manifest.get("initial_edition") not in order:
        fail(f"initial_edition {manifest.get('initial_edition')!r} is not in edition_order.")
    projected = []
    for edition_id in order:
        if edition_id not in by_id:
            fail(f"edition_order names unknown edition {edition_id!r}.")
        projected.append(
            public_edition(by_id[edition_id], edition_id, edition_zoom[edition_id])
        )
    payload = {
        "version": manifest["version"],
        "area_id": manifest["area_id"],
        "edition_order": list(order),
        "initial_edition": manifest["initial_edition"],
        "view_bounds_wgs84": list(manifest["view_bounds_wgs84"]),
        "tile_zoom": {"min": tile_zoom["min"], "max": tile_zoom["max"]},
        "editions": projected,
    }
    check_sanitized(payload)
    return payload


def check_sanitized(payload: dict) -> None:
    """Refuse to publish metadata carrying anything but the display shape."""
    if tuple(payload) != PUBLIC_MANIFEST_KEYS:
        fail(f"editions.json keys {tuple(payload)} are not the public set.")
    for edition in payload["editions"]:
        if tuple(edition) != PUBLIC_EDITION_KEYS:
            fail(f"{edition.get('id')}: editions.json keys {tuple(edition)} are not public.")
        template = edition["tile_url"]
        if template != TILE_TEMPLATE.format(
            edition_id=edition["id"], z="{z}", x="{x}", y="{y}"
        ):
            fail(f"{edition['id']}: tile_url is not the relative published template.")
        if "://" in template or template.startswith("/"):
            fail(f"{edition['id']}: tile_url is not a relative same-origin path.")
        zoom = payload["tile_zoom"]
        if not zoom["min"] <= edition["native_max_zoom"] <= zoom["max"]:
            fail(f"{edition['id']}: native_max_zoom is outside the published tile_zoom {zoom}.")
    blob = json.dumps(payload)
    leaked = [token for token in FORBIDDEN_METADATA_TOKENS if token in blob]
    # The host name and the checkout path say where the build ran; neither is site content.
    for token in (str(REPO_ROOT), platform.node()):
        if token and token in blob:
            leaked.append(token)
    if leaked:
        fail(f"editions.json carries internal detail: {', '.join(sorted(set(leaked)))}.")


# --------------------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------------------


def safe_destination(root: Path, relative: str) -> Path:
    """Resolve `relative` under `root`, rejecting traversal instead of normalising it."""
    candidate = Path(relative)
    parts = candidate.parts
    if candidate.is_absolute() or not parts or any(part in {"..", "."} for part in parts):
        fail(f"Refusing the unsafe published path {relative!r}.")
    destination = root / candidate
    root_resolved = root.resolve()
    if root_resolved not in destination.resolve().parents:
        fail(f"The published path {relative!r} escapes {root}.")
    return destination


def copy_file(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    digest, byte_count = warp_raster.sha256_file(destination)
    return {"sha256": digest, "byte_count": byte_count}


def source_files(root: Path, label: str) -> list[Path]:
    """Every regular file under `root`, with symlinks refused rather than dereferenced."""
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            fail(f"{label} holds the symlink {path.relative_to(root)}; refusing to follow it.")
        if path.is_file():
            found.append(path)
    return found


def copy_app_assets(dist: Path, staging: Path) -> list[dict]:
    """The built viewer, by extension allowlist. Anything else is a build to investigate."""
    if not dist.is_dir():
        fail(f"No built site at {dist}; run make demo-build (or 'npm run build' in site/).")
    inventory = []
    for path in source_files(dist, str(dist)):
        relative = path.relative_to(dist).as_posix()
        if path.suffix not in ALLOWED_APP_SUFFIXES:
            fail(f"{relative}: {path.suffix or 'no'} suffix is not an allowlisted app asset.")
        if path.suffix == ".js" and FORBIDDEN_BUNDLE_TOKEN in path.read_text(encoding="utf-8"):
            fail(f"{relative}: {FORBIDDEN_BUNDLE_TOKEN} reached the production bundle.")
        inventory.append(
            {"path": relative, **copy_file(path, safe_destination(staging, relative))}
        )
    names = {entry["path"] for entry in inventory}
    if REQUIRED_APP_FILE not in names:
        fail(f"The built site has no {REQUIRED_APP_FILE}; there is no page to publish.")
    if not any(name.endswith(".js") for name in names):
        fail("The built site has no JavaScript; the viewer would not start.")
    return inventory


def recorded_pyramids(
    build_root: Path, record: dict, manifest: dict, expansion_root: Path
) -> dict[str, dict]:
    """Every recorded pyramid, wherever it was cut, in one shape: where it is on disk, what
    its bytes must hash to, the zoom range it was cut over and the crop it was cut for.

    The four base pyramids come from demo-processing.json; the five added ones from the
    expansion record, which must describe this same manifest.
    """
    tiles = record.get("tiles")
    if not isinstance(tiles, dict) or not tiles.get("editions"):
        fail(
            f"{demo.PROCESSING_FILENAME} records no tile pyramids; run make demo-rasters first."
        )
    cogs = {entry["id"]: entry for entry in record.get("editions", [])}
    base_root = build_root / demo.TILE_DIRNAME / demo.TILE_SUBDIR
    found = {}
    for entry in tiles["editions"]:
        found[entry["id"]] = {
            "root": base_root,
            "source_id": entry["source_id"],
            "digest": entry["digest"],
            "tiles": entry["tiles"],
            "bytes": entry["bytes"],
            "transparent_tiles": entry["transparent_tiles"],
            "zoom": {"min": tiles["zoom"]["min"], "max": tiles["zoom"]["max"]},
            "crop_wgs84": cogs.get(entry["id"], {}).get("crop_wgs84"),
            "record": demo.PROCESSING_FILENAME,
        }
    added_path = expansion_root / demo_expansion.RECORD_NAME
    if not added_path.is_file():
        fail(f"No {demo_expansion.RECORD_NAME} at {added_path}; run make demo-rasters first.")
    added = read_json(added_path)
    if added.get("edition_order") != manifest["edition_order"] or added.get(
        "view_bounds_wgs84"
    ) != list(manifest["view_bounds_wgs84"]):
        fail(
            f"{demo_expansion.RECORD_NAME} was built for another edition set or view; "
            "re-run make demo-rasters."
        )
    for entry in added.get("editions", []):
        cut = entry["tiles"]
        if cut["path"] != f"{demo_expansion.TILE_DIRNAME}/{entry['id']}":
            fail(f"{entry['id']}: the recorded pyramid path {cut['path']!r} is not its own.")
        found[entry["id"]] = {
            "root": expansion_root / demo_expansion.TILE_DIRNAME,
            "source_id": entry["source"]["source_id"],
            "digest": cut["digest"],
            "tiles": cut["tiles"],
            "bytes": cut["bytes"],
            "transparent_tiles": cut["transparent_tiles"],
            "zoom": {"min": entry["zoom"]["min"], "max": entry["zoom"]["max"]},
            "crop_wgs84": entry["crop_wgs84"],
            "record": demo_expansion.RECORD_NAME,
        }
    return found


def check_edition_ids(order: list[str]) -> None:
    """Names are checked before any tree is read, so a traversing id cannot reach a copy."""
    for edition_id in order:
        if not isinstance(edition_id, str) or not EDITION_ID_PATTERN.fullmatch(edition_id):
            fail(f"Edition id {edition_id!r} is not a safe published directory name.")


def expected_zoom(edition: dict, tile_zoom: dict) -> dict:
    """The range an edition must have been cut over: from the shared minimum up to its own
    native zoom, or the build's top zoom when that is lower (a reduced test build)."""
    return {
        "min": tile_zoom["min"],
        "max": min(edition.get("native_max_zoom", tile_zoom["max"]), tile_zoom["max"]),
    }


def check_pyramids_agree(manifest: dict, pyramids: dict, tile_zoom: dict) -> dict[str, dict]:
    """Each pyramid was cut for this manifest's crop and over its edition's own zoom range,
    so no pyramid from an older manifest or a differently capped run can be mixed in."""
    zooms = {}
    for edition in manifest["editions"]:
        eid = edition["id"]
        entry = pyramids.get(eid)
        if entry is None:
            fail(f"{eid}: no pyramid recorded in {demo.PROCESSING_FILENAME} or the expansion.")
        if entry["crop_wgs84"] != edition["crop_wgs84"]:
            fail(
                f"{eid}: the pyramid in {entry['record']} was cut for another crop than the "
                "manifest declares; re-run make demo-rasters."
            )
        expected = expected_zoom(edition, tile_zoom)
        if entry["zoom"] != expected:
            fail(
                f"{eid}: the pyramid in {entry['record']} covers zoom {entry['zoom']}, not "
                f"{expected} for native zoom {edition.get('native_max_zoom')} under this "
                f"build's top zoom {tile_zoom['max']}; re-run make demo-rasters."
            )
        zooms[eid] = expected
    return zooms


def check_tile_names(root: Path, files: list[Path], zoom: dict, edition_id: str) -> None:
    """Every tile is <z>/<x>/<y>.png inside the recorded zoom range, and nothing else is."""
    for path in files:
        relative = path.relative_to(root)
        parts = relative.parts
        if len(parts) != 3 or path.suffix != f".{warp_raster.TILE_FORMAT}":
            fail(f"{edition_id}: {relative.as_posix()} is not a z/x/y.png tile.")
        z, x, y = parts[0], parts[1], parts[2][: -len(path.suffix)]
        if not all(TILE_COMPONENT_PATTERN.fullmatch(part) for part in (z, x, y)):
            fail(f"{edition_id}: {relative.as_posix()} is not an XYZ tile coordinate.")
        if not zoom["min"] <= int(z) <= zoom["max"]:
            fail(f"{edition_id}: zoom {z} is outside the built range {zoom}.")


def copy_tile_trees(
    staging: Path, order: list[str], pyramids: dict[str, dict], zooms: dict[str, dict]
) -> list[dict]:
    """The nine recorded pyramids, verified complete against their digests, and only those."""
    check_edition_ids(order)
    for edition_id in order:
        if edition_id not in pyramids:
            fail(f"{edition_id}: no pyramid recorded in {demo.PROCESSING_FILENAME}.")
    # Each tile root may hold only the editions recorded as cut there.
    roots: dict[Path, set[str]] = {}
    for edition_id in order:
        roots.setdefault(pyramids[edition_id]["root"], set()).add(edition_id)
    for tile_root, owned in roots.items():
        if not tile_root.is_dir():
            fail(f"No tiles at {tile_root}; run make demo-rasters first.")
        unexpected = sorted(path.name for path in tile_root.iterdir() if path.name not in owned)
        if unexpected:
            fail(
                f"{tile_root} holds unselected entries {unexpected}; the public build copies "
                f"only {sorted(owned)} from it. Remove them or run make clean."
            )
    inventory = []
    for edition_id in order:
        entry = pyramids[edition_id]
        zoom = zooms[edition_id]
        source = entry["root"] / edition_id
        if not source.is_dir():
            fail(f"{edition_id}: no tile pyramid at {source}; the layer would be missing.")
        files = source_files(source, f"{edition_id}'s pyramid")
        check_tile_names(source, files, zoom, edition_id)
        try:
            digest, tiles, byte_count = warp_raster.pyramid_digest(source)
        except WarpError as exc:
            fail(f"{edition_id}: {exc}")
        if (digest, tiles, byte_count) != (entry["digest"], entry["tiles"], entry["bytes"]):
            fail(
                f"{edition_id}: the pyramid on disk is {tiles} tiles / {byte_count} bytes, not "
                f"the recorded {entry['tiles']} / {entry['bytes']}; re-run make demo-rasters."
            )
        destination = safe_destination(staging, f"{TILE_PREFIX}/{edition_id}")
        shutil.copytree(source, destination, symlinks=False)
        inventory.append(
            {
                "id": edition_id,
                "source_id": entry["source_id"],
                "path": f"{TILE_PREFIX}/{edition_id}",
                "digest": digest,
                "tiles": tiles,
                "bytes": byte_count,
                "transparent_tiles": entry["transparent_tiles"],
                "zoom": {"min": zoom["min"], "max": zoom["max"]},
                "record": entry["record"],
            }
        )
    return inventory


def check_staging(staging: Path, order: list[str]) -> list[Path]:
    """Completeness and prohibited content, on the files actually staged."""
    if not staging.is_dir():
        fail(f"Nothing was staged at {staging}; there is no build to check.")
    files = source_files(staging, str(staging))
    if not files:
        fail(f"{staging} is empty; an empty build is never a successful one.")
    for path in files:
        relative = path.relative_to(staging).as_posix()
        if path.name in PROHIBITED_NAMES or path.suffix in PROHIBITED_SUFFIXES:
            fail(f"{relative} must not be published (AGENTS.md §2.5).")
    for required in (REQUIRED_APP_FILE, EDITIONS_FILENAME):
        if not (staging / required).is_file():
            fail(f"The staged build has no {required}.")
    for edition_id in order:
        tree = staging / TILE_PREFIX / edition_id
        if not tree.is_dir() or not any(tree.rglob(f"*.{warp_raster.TILE_FORMAT}")):
            fail(f"{edition_id}: the staged build has no tiles; its layer would be missing.")
    check_relative_references(staging)
    return files


def check_relative_references(staging: Path) -> None:
    """Published pages resolve against themselves, so a subpath deploy works unchanged."""
    for path in sorted(staging.rglob("*.html")):
        for reference in REFERENCE_PATTERN.findall(path.read_text(encoding="utf-8")):
            if reference.startswith(("data:", "#")) or not reference:
                continue
            if reference.startswith("/") or "://" in reference:
                fail(
                    f"{path.relative_to(staging).as_posix()} references {reference!r}; a "
                    "published page must use relative same-origin paths."
                )


def scan_for_restricted(staging: Path, data_dir: Path, schema_dir: Path) -> str:
    """Run the existing leak scanner over the staged files (AGENTS.md §2.5).

    `validate.check_leak` reports "nothing to scan" for a directory that does not exist, so
    the staging tree is proven to hold files before it is handed over.
    """
    if not staging.is_dir():
        fail(f"The leak scan was pointed at {staging}, which does not exist.")
    if not any(path.is_file() for path in staging.rglob("*")):
        fail(f"The leak scan was pointed at {staging}, which holds no files.")
    schemas = {
        "trails": read_json(schema_dir / "trail.schema.json"),
        "alignments": read_json(schema_dir / "alignment.schema.json"),
        "observations": read_json(schema_dir / "observation.schema.json"),
        "support": read_json(schema_dir / "support.schema.json"),
    }
    records, failures = validate.load_records(data_dir)
    if failures:
        fail(
            "The restricted-value scanner cannot read the authoritative records: "
            + "; ".join(failure.render() for failure in failures)
        )
    leaks, note = validate.check_leak(records, schemas, staging)
    if leaks:
        fail(
            "Restricted values reached the staged public build; nothing was published:\n"
            + "\n".join(failure.render() for failure in leaks)
        )
    return note


# --------------------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------------------


def publish(staging: Path, public: Path) -> None:
    """Swap the staged tree in as build/public/ with two renames, never a partial copy."""
    previous = public.parent / PREVIOUS_DIRNAME
    shutil.rmtree(previous, ignore_errors=True)
    had_previous = public.exists()
    if had_previous:
        os.replace(public, previous)
    try:
        os.replace(staging, public)
    except OSError as exc:
        if had_previous:
            os.replace(previous, public)
        fail(f"Could not publish {staging} as {public}: {exc}")
    shutil.rmtree(previous, ignore_errors=True)


def write_editions(staging: Path, payload: dict) -> dict:
    path = safe_destination(staging, EDITIONS_FILENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Not sorted: the file keeps the contract's key and edition order, which is the order
    # the viewer pages through.
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    digest, byte_count = warp_raster.sha256_file(path)
    return {"path": EDITIONS_FILENAME, "sha256": digest, "byte_count": byte_count}


def publish_notes() -> dict:
    return {
        "inspection": "automated only; no human build review is asserted here",
        "human_acceptance": "deferred to the acceptance tracker (issue #38)",
        "allowlist": (
            "app assets by extension from site/dist, one sanitized editions.json, and the "
            "recorded tile pyramids; nothing under data/ or docs/ is copied"
        ),
        "paths": "relative and same-origin; no host, origin or absolute path is published",
        "zoom": (
            "each edition is published up to its own cut zoom; editions.json names it as "
            "native_max_zoom and the viewer overzooms that level beyond it"
        ),
        "atomicity": (
            "staged under build/.public-incoming and swapped in by rename, so a failure "
            "leaves the previous build/public in place"
        ),
    }


# --------------------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------------------


def check_record_agrees(manifest: dict, record: dict) -> dict:
    """The tiles on disk have to be the ones this manifest describes."""
    if record.get("edition_order") != manifest["edition_order"]:
        fail(
            f"{demo.PROCESSING_FILENAME} was built for {record.get('edition_order')}, not "
            f"{manifest['edition_order']}; re-run make demo-rasters."
        )
    tiles = record["tiles"]
    if tiles["bounds_wgs84"] != list(manifest["view_bounds_wgs84"]):
        fail("The built pyramids cover different bounds than the manifest declares.")
    zoom, declared = tiles["zoom"], manifest["tile_zoom"]
    if zoom["min"] != declared["min"] or zoom["max"] > declared["max"]:
        fail(f"The built zoom range {zoom} does not sit inside the manifest's {declared}.")
    # Published zoom limits are the range actually cut, so a reduced build advertises
    # exactly the tiles it ships rather than the manifest's intended maximum.
    return zoom


def assemble_public(
    build_root: Path,
    dist: Path,
    manifest_path: Path,
    data_dir: Path = DATA_DIR,
    schema_dir: Path = SCHEMA_DIR,
    expansion_root: Path | None = None,
) -> dict:
    """Stage, check, scan and publish. Returns the output inventory it also records."""
    manifest = read_json(manifest_path)
    if manifest.get("version") != PUBLISHED_MANIFEST_VERSION:
        fail(
            f"The public build publishes the version-{PUBLISHED_MANIFEST_VERSION} nine-edition "
            f"manifest, not version {manifest.get('version')!r}."
        )
    expansion_root = expansion_root or build_root / EXPANSION_DIRNAME
    check_edition_ids(manifest["edition_order"])
    record_path = build_root / demo.RASTER_DIRNAME / demo.PROCESSING_FILENAME
    if not record_path.is_file():
        fail(f"No {demo.PROCESSING_FILENAME} at {record_path}; run make demo-rasters first.")
    record = read_json(record_path)
    zoom = check_record_agrees(manifest, record)
    pyramids = recorded_pyramids(build_root, record, manifest, expansion_root)
    zooms = check_pyramids_agree(manifest, pyramids, zoom)

    staging = build_root / STAGING_DIRNAME
    public = build_root / PUBLIC_DIRNAME
    # A tree left behind by an interrupted run is never reused.
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        assets = copy_app_assets(dist, staging)
        metadata = write_editions(
            staging,
            sanitize_manifest(manifest, zoom, {eid: z["max"] for eid, z in zooms.items()}),
        )
        published = copy_tile_trees(staging, manifest["edition_order"], pyramids, zooms)
        files = check_staging(staging, manifest["edition_order"])
        leak_note = scan_for_restricted(staging, data_dir, schema_dir)
        staged_bytes = sum(path.stat().st_size for path in files)
        staged_files = len(files)
        publish(staging, public)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    inventory = {
        "version": 1,
        "published_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "area_id": manifest["area_id"],
        "edition_order": list(manifest["edition_order"]),
        "initial_edition": manifest["initial_edition"],
        "root": f"{build_root.name}/{PUBLIC_DIRNAME}",
        "tile_template": TILE_TEMPLATE,
        "zoom": {"min": zoom["min"], "max": zoom["max"]},
        "view_bounds_wgs84": list(manifest["view_bounds_wgs84"]),
        "tool_versions": record["tool_versions"],
        "app_assets": assets,
        "metadata": metadata,
        "editions": published,
        "totals": {
            "files": staged_files,
            "bytes": staged_bytes,
            "tiles": sum(entry["tiles"] for entry in published),
            "tile_bytes": sum(entry["bytes"] for entry in published),
        },
        "leak_scan": leak_note,
        "notes": publish_notes(),
    }
    inventory_path = build_root / PUBLISH_DIRNAME / PUBLISH_FILENAME
    demo.write_record(inventory_path, inventory)
    return {"inventory": inventory, "inventory_path": inventory_path, "public": public}


def build_frontend(site_dir: Path, npm: str = "npm") -> Path:
    """`npm run build` in site/, which type-checks and bundles into site/dist."""
    if not (site_dir / "node_modules").is_dir():
        fail(f"No dependencies in {site_dir}; run make site-deps first.")
    try:
        finished = subprocess.run(
            [npm, "run", "build"],
            cwd=site_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        fail(f"Cannot run {npm} in {site_dir}: {exc}")
    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout).strip().splitlines()[-12:]
        fail("The site build failed; nothing was published:\n" + "\n".join(tail))
    return site_dir / DIST_DIRNAME


def run_build(
    manifest_path: Path,
    schema_path: Path,
    index_path: Path,
    receipts_path: Path,
    sources_path: Path,
    raw_root: Path,
    build_root: Path,
    zoom: int | None = None,
    site_dir: Path = SITE_DIR,
    dist: Path | None = None,
    data_dir: Path = DATA_DIR,
    schema_dir: Path = SCHEMA_DIR,
    npm: str = "npm",
    vite: bool = True,
    catalog_path: Path | None = None,
    ledger_path: Path | None = None,
    expansion_root: Path | None = None,
) -> dict:
    """Preflight, rasters, site build, allowlisted staging, leak scan, atomic publish."""
    expansion_root = expansion_root or build_root / EXPANSION_DIRNAME
    rasters = demo.run_rasters(
        manifest_path,
        schema_path,
        index_path,
        receipts_path,
        sources_path,
        raw_root,
        build_root,
        zoom,
        catalog_path,
        ledger_path,
        expansion_root,
    )
    built = build_frontend(site_dir, npm) if vite else (dist or site_dir / DIST_DIRNAME)
    published = assemble_public(
        build_root, built, manifest_path, data_dir, schema_dir, expansion_root
    )
    return {**published, "rasters": rasters, "dist": built}
