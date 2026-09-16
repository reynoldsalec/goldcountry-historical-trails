"""Receipt, integrity, and local archive tools for public USGS source downloads."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import click
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO_ROOT / "data" / "raw"
RECEIPTS_PATH = REPO_ROOT / "data" / "sources" / "retrievals.jsonl"
RECEIPT_VALIDATOR = Draft202012Validator(
    json.loads((REPO_ROOT / "schema/retrieval.schema.json").read_text()),
    format_checker=FormatChecker(),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest_file(path: Path) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise click.ClickException(f"Expected a regular source file: {path}")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        after = os.fstat(handle.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise click.ClickException(f"Source changed while hashing: {path}")
    return digest, after.st_size


def resolve_raw(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or "\\" in relative or not parts.parts:
        raise click.ClickException(f"Unsafe source path: {relative}")
    path = root.resolve()
    for part in parts.parts:
        path /= part
        if path.is_symlink():
            raise click.ClickException(f"Source path contains a symbolic link: {path}")
    return path


def load_receipts(path: Path = RECEIPTS_PATH) -> list[dict]:
    if not path.exists():
        return []
    records = []
    keys = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
            RECEIPT_VALIDATOR.validate(record)
            relative = record["raw_path"]
            if ".." in PurePosixPath(relative).parts or "\\" in relative:
                raise ValueError("Unsafe raw path")
            if relative.startswith("topo/sha256/") and relative != (
                f"topo/sha256/{record['sha256'][:2]}/{record['sha256']}.tif"
            ):
                raise ValueError("Content-addressed path differs from receipt hash")
            key = (record["topo_id"], record["raw_path"])
            if key in keys:
                raise ValueError("Duplicate source receipt")
            keys.add(key)
        except (ValidationError, KeyError, TypeError, ValueError, AttributeError) as exc:
            raise click.ClickException(f"Invalid receipt at {path}:{line_number}") from exc
        records.append(record)
    return records


def check_record(record: dict, root: Path) -> Path:
    path = resolve_raw(root, record["raw_path"])
    actual = digest_file(path)
    if actual != (record["sha256"], record["byte_count"]):
        raise click.ClickException(f"Checksum mismatch; left unchanged: {path}")
    return path


def append_receipt(record: dict, path: Path = RECEIPTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".retrievals.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = load_receipts(path)
        for prior in records:
            if (prior["topo_id"], prior["raw_path"]) == (record["topo_id"], record["raw_path"]):
                if (prior["sha256"], prior["byte_count"]) != (
                    record["sha256"],
                    record["byte_count"],
                ):
                    raise click.ClickException("Existing receipt disagrees; ledger unchanged.")
                return
        content = path.read_bytes() if path.exists() else b""
        content += (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode()
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            staged = Path(handle.name)
            try:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                load_receipts(staged)
                staged.replace(path)
            finally:
                staged.unlink(missing_ok=True)


def record_source(
    row: dict,
    source: Path,
    root: Path,
    receipts: Path,
    *,
    retrieved_at: str | None = None,
    retrieval_url: str | None = None,
) -> dict:
    if row["rights"] != "public_domain":
        raise click.ClickException("This receipt workflow only handles public USGS GeoTIFFs.")
    digest, size = digest_file(source)
    record = {
        "version": 1,
        "kind": "geotiff",
        "source": "usgs-historical-topo",
        "topo_id": row["topo_id"],
        "source_id": row["source_id"] or None,
        "indexed_url": row["geotiff_url"],
        "retrieval_url": retrieval_url,
        "metadata_url": row["metadata_url"] or None,
        "rights": row["rights"],
        "sha256": digest,
        "byte_count": size,
        "raw_path": source.resolve().relative_to(root.resolve()).as_posix(),
        "retrieved_at": retrieved_at,
        "recorded_at": utc_now(),
        "basis": "download" if retrieved_at is not None else "existing_file",
    }
    append_receipt(record, receipts)
    return record


def object_path(root: Path, digest: str) -> Path:
    return resolve_raw(root, f"sha256/{digest[:2]}/{digest}.tif")


def publish_file(staged: Path, target: Path) -> None:
    try:
        os.link(staged, target)
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EXDEV}:
            raise
        with target.open("xb") as handle:
            try:
                with staged.open("rb") as reader:
                    shutil.copyfileobj(reader, handle, length=1 << 20)
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException:
                target.unlink()
                raise


def copy_verified(source: Path, target: Path, digest: str, size: int) -> None:
    if target.exists() or target.is_symlink():
        if digest_file(target) != (digest, size):
            raise click.ClickException(f"Archive conflict; left unchanged: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        staged = Path(handle.name)
        try:
            with source.open("rb") as reader:
                shutil.copyfileobj(reader, handle, length=1 << 20)
            handle.flush()
            os.fsync(handle.fileno())
            if digest_file(staged) != (digest, size):
                raise click.ClickException(f"Copy failed checksum verification: {source}")
            try:
                publish_file(staged, target)
            except FileExistsError:
                if digest_file(target) != (digest, size):
                    raise click.ClickException(
                        f"Concurrent archive conflict: {target}"
                    ) from None
            if digest_file(target) != (digest, size):
                raise click.ClickException(f"Published copy failed verification: {target}")
        finally:
            staged.unlink(missing_ok=True)


@click.group()
@click.option("--raw-root", type=click.Path(path_type=Path), default=RAW_ROOT)
@click.option("--receipts", type=click.Path(path_type=Path), default=RECEIPTS_PATH)
@click.pass_context
def cli(ctx, raw_root: Path, receipts: Path) -> None:
    ctx.obj = (raw_root, receipts)


@cli.command()
@click.option(
    "--index",
    "index_path",
    type=click.Path(path_type=Path),
    default=REPO_ROOT / "data/sources/topo_index.csv",
)
@click.pass_obj
def catalog(paths, index_path: Path) -> None:
    """Record checksums of legacy downloads without inventing retrieval dates."""
    from fetch_topoview import read_index

    root, ledger = paths
    rows = read_index(index_path)
    known = load_receipts(ledger)
    for record in known:
        check_record(record, root)
    cataloged = {record["raw_path"] for record in known}
    files = sorted((root / "topo").glob("*_geo.tif"))
    for source in files:
        topo_id = source.name.removesuffix("_geo.tif")
        if topo_id not in rows:
            raise click.ClickException(f"File is not in the source index: {source}")
        if source.relative_to(root).as_posix() not in cataloged:
            record_source(rows[topo_id], source, root, ledger)
    click.echo(f"catalog: {len(files)} legacy TIFFs inventoried; originals unchanged")


@cli.command()
@click.option(
    "--available", is_flag=True, help="Check present files; allow missing local copies."
)
@click.pass_obj
def verify(paths, available: bool) -> None:
    root, ledger = paths
    if not ledger.exists():
        raise click.ClickException("No retrieval ledger; run make catalog-sources first.")
    records = load_receipts(ledger)
    checked = missing = 0
    for record in records:
        path = resolve_raw(root, record["raw_path"])
        if available and not path.exists():
            missing += 1
            continue
        check_record(record, root)
        checked += 1
    click.echo(f"verify: {checked} sources match SHA-256; {missing} local copies absent")


def archive_root(path: Path, raw_root: Path) -> Path:
    path = path.resolve()
    if (
        path.is_relative_to(REPO_ROOT)
        or path.is_relative_to(raw_root.resolve())
        or raw_root.resolve().is_relative_to(path)
    ):
        raise click.ClickException(
            "Choose a dedicated archive outside the repository and raw directory."
        )
    if not path.parent.is_dir():
        raise click.ClickException(
            "Archive parent is unavailable; mount the backup drive first."
        )
    return path


@cli.command()
@click.option(
    "--archive", type=click.Path(path_type=Path), envvar="TRAIL_ARCHIVE_ROOT", required=True
)
@click.pass_obj
def backup(paths, archive: Path) -> None:
    """Copy verified sources and an immutable receipt snapshot to a separate archive."""
    root, ledger = paths
    archive = archive_root(archive, root)
    records = load_receipts(ledger)
    if not records:
        raise click.ClickException("No retrieval receipts; run make catalog-sources first.")
    snapshot = (
        "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records)
    ).encode()
    for record in records:
        source = check_record(record, root)
        target = object_path(archive / "objects", record["sha256"])
        copy_verified(source, target, record["sha256"], record["byte_count"])
    snapshots = archive / "manifests"
    snapshots.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=snapshots, delete=False) as handle:
        staged = Path(handle.name)
        try:
            handle.write(snapshot)
            handle.flush()
            digest = hashlib.sha256(snapshot).hexdigest()
            target = snapshots / f"{digest}.jsonl"
            copy_verified(staged, target, digest, len(snapshot))
        finally:
            staged.unlink(missing_ok=True)
    click.echo(f"backup: {len(records)} verified objects; receipt snapshot: {target}")


@cli.command()
@click.option(
    "--archive", type=click.Path(path_type=Path), envvar="TRAIL_ARCHIVE_ROOT", required=True
)
@click.pass_obj
def restore(paths, archive: Path) -> None:
    """Restore exact source bytes using the committed receipt ledger."""
    root, ledger = paths
    archive = archive_root(archive, root)
    records = load_receipts(ledger)
    if not records:
        raise click.ClickException("No retrieval receipts available for restore.")
    for record in records:
        source = object_path(archive / "objects", record["sha256"])
        target = resolve_raw(root, record["raw_path"])
        copy_verified(source, target, record["sha256"], record["byte_count"])
    click.echo(f"restore: {len(records)} source paths verified")


@cli.command(name="verify-backup")
@click.option(
    "--archive", type=click.Path(path_type=Path), envvar="TRAIL_ARCHIVE_ROOT", required=True
)
@click.pass_obj
def verify_backup(paths, archive: Path) -> None:
    root, ledger = paths
    archive = archive_root(archive, root)
    records = load_receipts(ledger)
    if not records:
        raise click.ClickException("No retrieval receipts to verify against.")
    for record in records:
        source = object_path(archive / "objects", record["sha256"])
        if digest_file(source) != (record["sha256"], record["byte_count"]):
            raise click.ClickException(f"Backup checksum mismatch: {source}")
    click.echo(f"verify-backup: {len(records)} archived sources match SHA-256")


if __name__ == "__main__":
    cli()
