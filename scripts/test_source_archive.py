import errno
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import source_archive as archive
from click.testing import CliRunner
from test_fetch_topoview import row as row
from test_fetch_topoview import write_index


@pytest.fixture
def inventory(tmp_path, row):
    root = tmp_path / "raw"
    source = root / "topo" / f"{row['topo_id']}_geo.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source bytes for an integrity test")
    ledger = tmp_path / "retrievals.jsonl"
    record = archive.record_source(row, source, root, ledger)
    return root, source, ledger, record


def run(paths, *args):
    root, _, ledger, _ = paths
    return CliRunner().invoke(
        archive.cli,
        [
            "--raw-root",
            str(root),
            "--receipts",
            str(ledger),
            *map(str, args),
        ],
    )


def test_existing_receipt_has_unknown_retrieval_date(inventory, row):
    root, source, ledger, record = inventory
    assert record["retrieved_at"] is None
    assert record["retrieval_url"] is None
    assert record["recorded_at"].endswith("Z")
    assert record["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    before = ledger.read_bytes()
    archive.record_source(row, source, root, ledger)
    assert ledger.read_bytes() == before


def test_download_receipt_records_actual_retrieval(inventory, row):
    root, source, ledger, _ = inventory
    ledger = ledger.with_name("download.jsonl")
    archive.record_source(
        row,
        source,
        root,
        ledger,
        retrieved_at="2026-09-16T23:00:00Z",
        retrieval_url=row["geotiff_url"],
    )
    record = archive.load_receipts(ledger)[0]
    assert record["basis"] == "download"
    assert record["retrieved_at"] == "2026-09-16T23:00:00Z"


def test_changed_source_does_not_rebaseline_receipt(inventory, row):
    root, source, ledger, _ = inventory
    before = ledger.read_bytes()
    source.write_bytes(b"changed")
    with pytest.raises(archive.click.ClickException, match="ledger unchanged"):
        archive.record_source(row, source, root, ledger)
    assert ledger.read_bytes() == before
    assert run(inventory, "verify").exit_code != 0


@pytest.mark.parametrize("relative", ["topo/../../escape.tif", "/escape.tif"])
def test_unsafe_receipt_path_rejected(inventory, relative):
    _, _, ledger, record = inventory
    record["raw_path"] = relative
    ledger.write_text(json.dumps(record) + "\n")
    with pytest.raises(archive.click.ClickException, match="Invalid receipt"):
        archive.load_receipts(ledger)


def test_missing_copies_allowed_only_in_available_mode(inventory):
    _, source, _, _ = inventory
    source.unlink()
    assert run(inventory, "verify").exit_code != 0
    result = run(inventory, "verify", "--available")
    assert result.exit_code == 0
    assert "1 local copies absent" in result.output


def test_backup_and_restore_round_trip(inventory, tmp_path):
    root, source, ledger, record = inventory
    backup = tmp_path / "external backup"
    original = source.read_bytes()
    result = run(inventory, "backup", "--archive", backup)
    assert result.exit_code == 0, result.output
    archived = archive.object_path(backup / "objects", record["sha256"])
    assert archived.read_bytes() == original
    stamp = archived.stat().st_mtime_ns
    assert run(inventory, "backup", "--archive", backup).exit_code == 0
    assert archived.stat().st_mtime_ns == stamp
    snapshots = list((backup / "manifests").glob("*.jsonl"))
    assert len(snapshots) == 1
    assert archive.load_receipts(snapshots[0]) == archive.load_receipts(ledger)
    restored = tmp_path / "restored"
    result = CliRunner().invoke(
        archive.cli,
        [
            "--raw-root",
            str(restored),
            "--receipts",
            str(ledger),
            "restore",
            "--archive",
            str(backup),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (restored / record["raw_path"]).read_bytes() == original
    assert source.read_bytes() == original


def test_conflicting_backup_is_not_overwritten(inventory, tmp_path):
    backup = tmp_path / "external"
    assert run(inventory, "backup", "--archive", backup).exit_code == 0
    target = archive.object_path(backup / "objects", inventory[3]["sha256"])
    target.write_bytes(b"corrupted archive")
    result = run(inventory, "backup", "--archive", backup)
    assert result.exit_code != 0
    assert target.read_bytes() == b"corrupted archive"


def test_corrupt_backup_cannot_be_restored(inventory, tmp_path):
    backup = tmp_path / "external"
    assert run(inventory, "backup", "--archive", backup).exit_code == 0
    target = archive.object_path(backup / "objects", inventory[3]["sha256"])
    target.write_bytes(b"corrupted archive")
    inventory[1].unlink()
    assert run(inventory, "restore", "--archive", backup).exit_code != 0
    assert not inventory[1].exists()


def test_changed_local_file_is_not_overwritten_by_restore(inventory, tmp_path):
    backup = tmp_path / "external"
    assert run(inventory, "backup", "--archive", backup).exit_code == 0
    inventory[1].write_bytes(b"changed local source")
    assert run(inventory, "restore", "--archive", backup).exit_code != 0
    assert inventory[1].read_bytes() == b"changed local source"


def test_copy_on_filesystem_without_hardlinks(inventory, tmp_path, monkeypatch):
    def no_link(*args):
        raise OSError(errno.ENOTSUP, "No hard links")

    monkeypatch.setattr(archive.os, "link", no_link)
    backup = tmp_path / "external"
    result = run(inventory, "backup", "--archive", backup)
    assert result.exit_code == 0, result.output
    target = archive.object_path(backup / "objects", inventory[3]["sha256"])
    assert target.read_bytes() == inventory[1].read_bytes()


def test_catalog_is_idempotent_and_preserves_originals(inventory, tmp_path, row):
    index = tmp_path / "index.csv"
    write_index(index, [row])
    before = inventory[1].stat().st_mtime_ns
    receipt_before = inventory[2].read_bytes()
    result = run(inventory, "catalog", "--index", index)
    assert result.exit_code == 0, result.output
    assert inventory[1].stat().st_mtime_ns == before
    assert inventory[2].read_bytes() == receipt_before


def test_simultaneous_receipt_writes_are_not_lost(inventory):
    _, _, ledger, record = inventory

    def append(number):
        archive.append_receipt(dict(record, topo_id=f"test-{number}"), ledger)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(8)))
    assert len(archive.load_receipts(ledger)) == 9


def test_backup_root_may_be_symlinked(inventory, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    link = tmp_path / "backup-link"
    link.symlink_to(external, target_is_directory=True)
    result = run(inventory, "backup", "--archive", link)
    assert result.exit_code == 0, result.output


def test_unavailable_drive_fails_without_creating_mount(inventory, tmp_path):
    backup = tmp_path / "unmounted" / "archive"
    assert run(inventory, "backup", "--archive", backup).exit_code != 0
    assert not backup.parent.exists()
