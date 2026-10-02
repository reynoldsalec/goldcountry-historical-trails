"""Catalog, fetch and verify the five map sources the nine-edition browser adds.

Historical TIFFs reuse retrievals.jsonl; the two US Topo PDFs have their own ledger
because their receipt contract differs from schema/retrieval.schema.json (#55).
"""

from __future__ import annotations

import fcntl
import http.client
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import warnings
from pathlib import Path

import click
import source_archive as archive
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
CATALOG_PATH = SOURCES_DIR / "demo-pdf-sources.json"
LEDGER_PATH = SOURCES_DIR / "demo-pdf-retrievals.jsonl"
SELECTION_PATH = SOURCES_DIR / "demo-expansion-topo.json"
INDEX_PATH = SOURCES_DIR / "topo_index.csv"
EDITIONS_PATH = SOURCES_DIR / "demo-editions.json"

PDF_SOURCE_IDS = ("5d3aeb27e4b01d82ce8d133b", "61d7a9e2d34ed79294005276")
TOPO_IDS = (
    "CA_Sacramento_299588_1891_125000",
    "CA_Auburn_296741_1944_62500",
    "CA_Sacramento_299157_1994_100000",
)
EXPANSION_ORDER = (
    "sacramento-1891",
    "auburn-1944",
    "auburn-1953",
    "auburn-1973",
    "auburn-1975",
    "auburn-1981",
    "sacramento-1994",
    "auburn-2018",
    "auburn-2021",
)
USER_AGENT = "foothill-trail-atlas/0.0 (OTCA historical trail mapping; contact via repo)"
PDF_MAGIC = b"%PDF-"
# Incremental-update PDFs may append a few bytes after the final marker.
EOF_WINDOW = 1024


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((REPO_ROOT / "schema" / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


CATALOG_VALIDATOR = _validator("demo-pdf-source.schema.json")
RECEIPT_VALIDATOR = _validator("demo-pdf-retrieval.schema.json")


def pdf_relative(digest: str) -> str:
    return f"us-topo/sha256/{digest[:2]}/{digest}.pdf"


def load_catalog(path: Path = CATALOG_PATH, expected=PDF_SOURCE_IDS) -> dict[str, dict]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        CATALOG_VALIDATOR.validate(document)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise click.ClickException(f"Invalid PDF source catalog {path}: {exc}") from None
    entries: dict[str, dict] = {}
    editions = set()
    for entry in document["sources"]:
        if entry["source_id"] in entries:
            raise click.ClickException(f"Duplicate source_id in catalog: {entry['source_id']}")
        if entry["edition_id"] in editions:
            raise click.ClickException(
                f"Duplicate edition_id in catalog: {entry['edition_id']}"
            )
        entries[entry["source_id"]] = entry
        editions.add(entry["edition_id"])
    if sorted(entries) != sorted(expected):
        raise click.ClickException(
            f"Catalog must name exactly {', '.join(expected)}; found {', '.join(entries)}"
        )
    return entries


def load_ledger(path: Path = LEDGER_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    paths = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
            RECEIPT_VALIDATOR.validate(record)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise click.ClickException(f"Invalid PDF receipt at {path}:{number}") from exc
        if record["path"] != pdf_relative(record["sha256"]):
            raise click.ClickException(
                f"PDF receipt path differs from its hash at {path}:{number}"
            )
        if record["source_id"] in records:
            raise click.ClickException(
                f"Duplicate source_id {record['source_id']} in {path}:{number}"
            )
        if record["path"] in paths:
            raise click.ClickException(f"Duplicate path {record['path']} in {path}:{number}")
        records[record["source_id"]] = record
        paths.add(record["path"])
    return records


def append_ledger(record: dict, path: Path = LEDGER_PATH) -> bool:
    """Append one receipt under the shared ledger lock; False when already recorded."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".retrievals.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = load_ledger(path).get(record["source_id"])
        if prior is not None:
            if (prior["sha256"], prior["size_bytes"]) != (
                record["sha256"],
                record["size_bytes"],
            ):
                raise click.ClickException("Existing PDF receipt disagrees; ledger unchanged.")
            return False
        content = path.read_bytes() if path.exists() else b""
        content += (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode()
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            staged = Path(handle.name)
            try:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                load_ledger(staged)
                staged.replace(path)
            finally:
                staged.unlink(missing_ok=True)
    return True


def check_pdf_bytes(path: Path, declared: int | None) -> None:
    size = path.stat().st_size
    if declared is None:
        raise ValueError("Cannot confirm download length: no Content-Length")
    if size != declared:
        raise ValueError(f"Truncated response: wrote {size} of {declared} bytes")
    with path.open("rb") as handle:
        head = handle.read(len(PDF_MAGIC))
        handle.seek(max(0, size - EOF_WINDOW))
        tail = handle.read()
    if head != PDF_MAGIC:
        raise ValueError(f"Response is not a PDF (starts with {head!r})")
    if b"%%EOF" not in tail:
        raise ValueError("PDF has no end-of-file marker; the body is incomplete")


def verify_receipted(record: dict, root: Path) -> Path:
    target = archive.resolve_raw(root, record["path"])
    if not (target.exists() or target.is_symlink()):
        raise FileNotFoundError(record["path"])
    if archive.digest_file(target) != (record["sha256"], record["size_bytes"]):
        raise click.ClickException(f"Checksum mismatch; left unchanged: {record['path']}")
    return target


def fetch_one(
    entry: dict,
    root: Path,
    ledger: Path,
    opener=urllib.request.urlopen,
    timeout: int = 600,
) -> str:
    """Download one catalog PDF into content-addressed raw storage; never replace bytes."""
    source_id = entry["source_id"]
    record = load_ledger(ledger).get(source_id)
    if record is not None:
        try:
            verify_receipted(record, root)
            return "present"
        except FileNotFoundError:
            pass
    incoming = archive.resolve_raw(root, "us-topo")
    incoming.mkdir(parents=True, exist_ok=True)
    part = None
    try:
        request = urllib.request.Request(
            entry["download_url"], headers={"User-Agent": USER_AGENT}
        )
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ValueError(f"HTTP status {status}")
            content_type = response.headers.get("Content-Type") or ""
            if "html" in content_type.lower():
                raise ValueError(f"Server returned {content_type}, not a PDF")
            retrieval_url = response.geturl()
            declared = response.headers.get("Content-Length")
            served = int(declared) if declared and declared.isdigit() else None
            with tempfile.NamedTemporaryFile(
                dir=incoming, prefix=".", suffix=".part", delete=False
            ) as handle:
                part = Path(handle.name)
                shutil.copyfileobj(response, handle, length=1 << 20)
                handle.flush()
                os.fsync(handle.fileno())
        retrieved_at = archive.utc_now()
        check_pdf_bytes(part, served)
        digest, size = archive.digest_file(part)
        if record is not None and (digest, size) != (record["sha256"], record["size_bytes"]):
            raise ValueError("Remote bytes differ from the receipt; nothing replaced")
        target = archive.resolve_raw(root, pdf_relative(digest))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            archive.publish_file(part, target)
        except FileExistsError:
            if archive.digest_file(target) != (digest, size):
                raise ValueError(f"Existing file differs; left unchanged: {target}") from None
        if record is not None:
            return "restored"
        append_ledger(
            {
                "version": 1,
                "source_id": source_id,
                "source_url": entry["download_url"],
                "retrieval_url": retrieval_url,
                "retrieved_at": retrieved_at,
                "sha256": digest,
                "size_bytes": size,
                "path": pdf_relative(digest),
                "metadata_url": entry["metadata_url"],
            },
            ledger,
        )
        return "downloaded"
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        raise click.ClickException(f"{source_id}: {exc}; no receipt written") from None
    finally:
        if part is not None:
            part.unlink(missing_ok=True)


def describe_crs(crs) -> str:
    epsg = crs.to_epsg()
    if epsg:
        return f"EPSG:{epsg}"
    return crs.to_proj4()


def inspect_raster(path: Path, driver: str) -> str:
    """Report embedded georeferencing through the bundled GDAL; raise if unreadable."""
    import rasterio
    from rasterio.errors import RasterioIOError

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            dataset = rasterio.open(path)
        except RasterioIOError as exc:
            if driver == "PDF" and "not recognized" in str(exc):
                raise ValueError(
                    f"the GDAL {rasterio.__gdal_version__} bundled with rasterio cannot "
                    "read PDFs (no Poppler/PDFium backend); a PDF-capable GDAL is needed"
                ) from None
            raise
        with dataset:
            if dataset.driver != driver:
                raise ValueError(f"GDAL opened it as {dataset.driver}, not {driver}")
            if dataset.crs is None:
                raise ValueError("no embedded georeferencing")
            detail = f"embedded CRS {describe_crs(dataset.crs)}"
            if driver == "PDF":
                layers = [k for k in dataset.tags(ns="LAYERS") if k.startswith("LAYER_")]
                neatline = "present" if dataset.tags().get("NEATLINE") else "absent"
                detail += f", NEATLINE {neatline}, {len(layers)} PDF layers"
            return detail + "; registration not reviewed"


def verified_detail(digest: str, size: int) -> str:
    return f"verified sha256 {digest} ({size} bytes)"


def check_topo(
    root: Path, receipts: Path, index: Path, selection: Path, inspect=inspect_raster
) -> list[tuple]:
    """(label, verified, detail, open blockers) per reused historical TIFF."""
    from fetch_topoview import read_index, read_selection

    rows = read_index(index)
    selected = read_selection(selection, rows)
    if tuple(selected) != TOPO_IDS:
        raise click.ClickException(f"{selection} must list exactly {', '.join(TOPO_IDS)}")
    known = archive.load_receipts(receipts)
    results = []
    for topo_id in selected:
        row = rows[topo_id]
        label = f"{topo_id} ({row['map_name']} 1:{int(row['scale']):,}, {row['date_on_map']})"
        matches = [r for r in known if r["topo_id"] == topo_id]
        if len(matches) != 1:
            why = "no receipt" if not matches else f"{len(matches)} ambiguous receipts"
            results.append((label, False, f"blocked: {why} in retrievals.jsonl", []))
            continue
        record = matches[0]
        path = archive.resolve_raw(root, record["raw_path"])
        if not (path.exists() or path.is_symlink()):
            detail = f"blocked: receipted file absent: {record['raw_path']}"
            results.append((label, False, detail, []))
            continue
        try:
            archive.check_record(record, root)
        except click.ClickException as exc:
            results.append((label, False, f"blocked: {exc.format_message()}", []))
            continue
        detail = (
            f"{verified_detail(record['sha256'], record['byte_count'])}; receipt basis "
            f"{record['basis']}, retrieved_at {json.dumps(record['retrieved_at'])}"
        )
        blockers = []
        try:
            detail += f"; {inspect(path, 'GTiff')}"
        except Exception as exc:  # an unreadable raster is an open blocker, not a crash
            blockers.append(f"georeferencing not inspected: {exc}")
        results.append((label, True, detail, blockers))
    return results


def check_pdfs(root: Path, catalog: Path, ledger: Path, inspect=inspect_raster) -> list[tuple]:
    """(label, verified, detail, open blockers) per catalog PDF."""
    entries = load_catalog(catalog)
    records = load_ledger(ledger)
    results = []
    for source_id, entry in entries.items():
        label = f"{entry['edition_id']} {source_id} ({entry['title']})"
        record = records.get(source_id)
        if record is None:
            detail = "blocked: no PDF receipt; run make expansion-fetch"
            results.append((label, False, detail, []))
            continue
        try:
            path = verify_receipted(record, root)
        except FileNotFoundError:
            detail = f"blocked: receipted file absent: {record['path']}"
            results.append((label, False, detail, []))
            continue
        except click.ClickException as exc:
            results.append((label, False, f"blocked: {exc.format_message()}", []))
            continue
        detail = verified_detail(record["sha256"], record["size_bytes"])
        blockers = []
        try:
            detail += f"; {inspect(path, 'PDF')}"
        except Exception as exc:  # an unreadable PDF is an open blocker, not a crash
            blockers.append(f"georeferencing not inspected: {exc}")
        if entry["rights"]["status"] != "public_domain":
            blockers.append("publication rights unresolved; see the catalog rights entry")
        results.append((label, True, detail, blockers))
    return results


def check_live(catalog: Path, editions: Path) -> None:
    """The active manifest carries exactly these five sources, each under its own edition."""
    live = json.loads(editions.read_text(encoding="utf-8"))
    pairs = {(e["id"], e["source_id"]) for e in live["editions"]}
    expected = {(e["edition_id"], source_id) for source_id, e in load_catalog(catalog).items()}
    topo = {e["source_id"] for e in live["editions"] if e.get("source_kind") != "us_topo_pdf"}
    missing = sorted(f"{eid} {sid}" for eid, sid in expected - pairs)
    missing += sorted(set(TOPO_IDS) - topo)
    if list(live.get("edition_order", [])) != list(EXPANSION_ORDER) or missing:
        raise click.ClickException(
            "The active manifest is not the nine-edition set"
            + (f"; missing {', '.join(missing)}" if missing else "")
        )


@click.group()
@click.option(
    "--raw-root",
    type=click.Path(file_okay=False, path_type=Path),
    envvar="DEMO_RAW_ROOT",
    default=archive.RAW_ROOT,
)
@click.option("--catalog", type=click.Path(path_type=Path), default=CATALOG_PATH)
@click.option("--ledger", type=click.Path(path_type=Path), default=LEDGER_PATH)
@click.option("--receipts", type=click.Path(path_type=Path), default=archive.RECEIPTS_PATH)
@click.pass_context
def cli(ctx, raw_root: Path, catalog: Path, ledger: Path, receipts: Path) -> None:
    ctx.obj = {"root": raw_root, "catalog": catalog, "ledger": ledger, "receipts": receipts}


@cli.command()
@click.pass_obj
def check(paths) -> None:
    """Offline: verify full-file hashes of all five candidates against their receipts."""
    check_live(paths["catalog"], EDITIONS_PATH)
    results = check_topo(paths["root"], paths["receipts"], INDEX_PATH, SELECTION_PATH)
    results += check_pdfs(paths["root"], paths["catalog"], paths["ledger"])
    for label, _, detail, blockers in results:
        click.echo(f"  {label}: {detail}")
        for blocker in blockers:
            click.echo(f"    open: {blocker}")
    verified = sum(ok for _, ok, _, _ in results)
    pending = sum(bool(b) for _, _, _, b in results)
    click.echo(
        f"expansion-check: {verified} of {len(results)} candidates verified by full-file "
        f"SHA-256; {pending} with open processing blockers"
    )
    if verified != len(results):
        raise click.ClickException(f"{len(results) - verified} candidate(s) blocked")


@cli.command()
@click.option("--timeout", default=600, show_default=True)
@click.pass_obj
def fetch(paths, timeout: int) -> None:
    """Download the catalog PDFs once; reruns verify and skip."""
    root = paths["root"]
    if not root.is_dir():
        raise click.ClickException(f"Raw root is not a directory: {root}")
    for source_id, entry in load_catalog(paths["catalog"]).items():
        status = fetch_one(entry, root, paths["ledger"], timeout=timeout)
        click.echo(f"  {entry['edition_id']} {source_id}: {status}")


if __name__ == "__main__":
    cli()
