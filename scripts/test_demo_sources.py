import hashlib
import io
import json

import click
import demo_sources as ds
import pytest
import source_archive as archive
from click.testing import CliRunner

PDF = b"%PDF-1.7\n" + b"map bytes " * 200 + b"\n%%EOF\n"
SOURCE_ID = ds.PDF_SOURCE_IDS[0]
URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/USTopo/PDF/CA/fixture.pdf"


class Response(io.BytesIO):
    def __init__(self, body, headers=None, status=200, fail_after=None):
        super().__init__(body)
        self.headers = {"Content-Type": "application/pdf", "Content-Length": str(len(body))}
        self.headers.update(headers or {})
        self.status = status
        self.fail_after = fail_after

    def geturl(self):
        return URL

    def read(self, size=-1):
        if self.fail_after is not None and self.tell() >= self.fail_after:
            raise self.fail_after_exc
        return super().read(min(size, 64) if size and size > 0 else size)


class Interrupted(BaseException):
    pass


def opener_for(response):
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return response

    opener.calls = calls
    return opener


def refuse(request, timeout):
    raise AssertionError("network must not be touched")


@pytest.fixture
def entry():
    return {
        "source_id": SOURCE_ID,
        "edition_id": "auburn-2018",
        "download_url": URL,
        "metadata_url": "https://thor-f5.er.usgs.gov/fixture.xml",
    }


@pytest.fixture
def paths(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    return root, tmp_path / "ledger.jsonl"


def receipt(body=PDF, source_id=SOURCE_ID, **changes):
    digest = hashlib.sha256(body).hexdigest()
    record = {
        "version": 1,
        "source_id": source_id,
        "source_url": URL,
        "retrieval_url": URL,
        "retrieved_at": "2026-09-30T00:00:00Z",
        "sha256": digest,
        "size_bytes": len(body),
        "path": ds.pdf_relative(digest),
        "metadata_url": "https://thor-f5.er.usgs.gov/fixture.xml",
    }
    record.update(changes)
    return record


def write_ledger(path, *records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def nothing_written(root, ledger):
    files = [p for p in root.rglob("*") if p.is_file()]
    assert files == [], files
    assert not ledger.exists() or ledger.read_text() == ""


def test_download_writes_content_addressed_pdf_and_one_receipt(entry, paths):
    root, ledger = paths
    opener = opener_for(Response(PDF))
    assert ds.fetch_one(entry, root, ledger, opener=opener) == "downloaded"
    digest = hashlib.sha256(PDF).hexdigest()
    target = root / "us-topo" / "sha256" / digest[:2] / f"{digest}.pdf"
    assert target.read_bytes() == PDF
    [record] = ds.load_ledger(ledger).values()
    assert record == {
        **receipt(),
        "retrieved_at": record["retrieved_at"],
    }
    assert record["retrieved_at"].endswith("Z")
    assert not list((root / "us-topo").glob(".*.part"))


def test_rerun_is_a_noop_without_network(entry, paths):
    root, ledger = paths
    ds.fetch_one(entry, root, ledger, opener=opener_for(Response(PDF)))
    before = ledger.read_bytes()
    assert ds.fetch_one(entry, root, ledger, opener=refuse) == "present"
    assert ledger.read_bytes() == before


@pytest.mark.parametrize(
    "response, message",
    [
        (
            Response(b"<html><body>Access denied</body></html>", {"Content-Type": "text/html"}),
            "text/html",
        ),
        (Response(b"<!DOCTYPE html><html></html>", {"Content-Type": ""}), "not a PDF"),
        (Response(b"II*\x00" + b"\x00" * 64), "not a PDF"),
        (Response(PDF[:100], {"Content-Length": str(len(PDF))}), "Truncated"),
        (Response(PDF[:-7]), "end-of-file"),
        (Response(PDF, {"Content-Length": ""}), "Content-Length"),
        (Response(PDF, status=206), "HTTP status 206"),
    ],
)
def test_bad_responses_leave_no_file_and_no_receipt(entry, paths, response, message):
    root, ledger = paths
    with pytest.raises(click.ClickException, match=message):
        ds.fetch_one(entry, root, ledger, opener=opener_for(response))
    nothing_written(root, ledger)


@pytest.mark.parametrize("exc", [ConnectionResetError("reset"), Interrupted()])
def test_interrupted_download_leaves_no_file_and_no_receipt(entry, paths, exc):
    root, ledger = paths
    response = Response(PDF, fail_after=128)
    response.fail_after_exc = exc
    with pytest.raises((click.ClickException, Interrupted)):
        ds.fetch_one(entry, root, ledger, opener=opener_for(response))
    nothing_written(root, ledger)


def test_receipt_hash_mismatch_is_never_replaced(entry, paths):
    root, ledger = paths
    record = receipt()
    write_ledger(ledger, record)
    target = root / record["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(PDF.replace(b"map", b"MAP"))
    before = target.read_bytes()
    with pytest.raises(click.ClickException, match="Checksum mismatch"):
        ds.fetch_one(entry, root, ledger, opener=refuse)
    assert target.read_bytes() == before


def test_missing_receipted_file_must_match_remote_bytes(entry, paths):
    root, ledger = paths
    write_ledger(ledger, receipt())
    other = PDF.replace(b"map", b"new")
    with pytest.raises(click.ClickException, match="differ from the receipt"):
        ds.fetch_one(entry, root, ledger, opener=opener_for(Response(other)))
    assert [p for p in root.rglob("*") if p.is_file()] == []
    assert ds.fetch_one(entry, root, ledger, opener=opener_for(Response(PDF))) == "restored"
    assert len(ds.load_ledger(ledger)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"path": "../../etc/passwd"},
        {"path": "us-topo/sha256/../../../x.pdf"},
        {"path": "/abs/us-topo/sha256/aa/" + "a" * 64 + ".pdf"},
        {"path": "us-topo/sha256/00/" + "0" * 64 + ".pdf"},
        {"sha256": "A" * 64},
        {"sha256": "abc"},
        {"size_bytes": 0},
        {"retrieved_at": "2026-09-30T00:00:00+02:00"},
        {"source_url": "http://insecure.example/x.pdf"},
        {"extra": "field"},
    ],
)
def test_ledger_rejects_unsafe_or_malformed_receipts(tmp_path, changes):
    ledger = tmp_path / "ledger.jsonl"
    write_ledger(ledger, receipt(**changes))
    with pytest.raises(click.ClickException):
        ds.load_ledger(ledger)


def test_ledger_rejects_duplicate_source_id(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    write_ledger(ledger, receipt(), receipt(body=PDF + b"x"))
    with pytest.raises(click.ClickException, match="Duplicate source_id"):
        ds.load_ledger(ledger)


def test_append_refuses_disagreeing_receipt(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    assert ds.append_ledger(receipt(), ledger)
    assert not ds.append_ledger(receipt(), ledger)
    before = ledger.read_bytes()
    with pytest.raises(click.ClickException, match="disagrees"):
        ds.append_ledger(receipt(body=PDF + b"x"), ledger)
    assert ledger.read_bytes() == before


def catalog_copy(tmp_path, mutate):
    document = json.loads(ds.CATALOG_PATH.read_text())
    mutate(document)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document))
    return path


def test_committed_catalog_names_exactly_the_two_us_topo_pdfs():
    entries = ds.load_catalog()
    assert list(entries) == list(ds.PDF_SOURCE_IDS)
    assert [e["edition_id"] for e in entries.values()] == ["auburn-2018", "auburn-2021"]
    for entry in entries.values():
        rights = entry["rights"]
        assert "commercial road data" in rights["use_constraints"]
        assert any("Census Roads" in s["srcinfo_title"] for s in rights["source_statements"])


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["sources"].append(dict(d["sources"][0])), "Duplicate source_id"),
        (lambda d: d["sources"].pop(), "exactly"),
        (lambda d: d["sources"][1].update(edition_id="auburn-2018"), "Duplicate edition_id"),
        (lambda d: d["sources"][0].update(source_id="5a8a53d1e4b00f54eb4106c4"), "exactly"),
        (lambda d: d["sources"][0].update(unknown=1), "Invalid"),
        (lambda d: d["sources"][0]["rights"].update(status="unknown"), "Invalid"),
    ],
)
def test_catalog_rejects_bad_documents(tmp_path, mutate, message):
    with pytest.raises(click.ClickException, match=message):
        ds.load_catalog(catalog_copy(tmp_path, mutate))


def test_committed_topo_receipts_are_reused_not_duplicated():
    records = archive.load_receipts()
    for topo_id in ds.TOPO_IDS:
        [record] = [r for r in records if r["topo_id"] == topo_id]
        assert record["basis"] == "existing_file"
        assert record["retrieved_at"] is None
        assert record["raw_path"] == f"topo/{topo_id}_geo.tif"


def test_the_active_manifest_carries_the_five_sources():
    ds.check_live(ds.CATALOG_PATH, ds.EDITIONS_PATH)
    assert ds.EXPANSION_ORDER[2:6] == (
        "auburn-1953",
        "auburn-1973",
        "auburn-1975",
        "auburn-1981",
    )


def test_a_manifest_missing_an_added_source_is_not_the_nine_edition_set(tmp_path):
    manifest = json.loads(ds.EDITIONS_PATH.read_text(encoding="utf-8"))
    manifest["editions"] = [e for e in manifest["editions"] if e["id"] != "auburn-2021"]
    path = tmp_path / "demo-editions.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(click.ClickException, match="missing auburn-2021"):
        ds.check_live(ds.CATALOG_PATH, path)


def topo_fixture(tmp_path, present=True, corrupt=False):
    root = tmp_path / "raw"
    receipts = tmp_path / "retrievals.jsonl"
    rows = []
    for topo_id in ds.TOPO_IDS:
        body = f"tiff bytes for {topo_id}".encode()
        path = root / "topo" / f"{topo_id}_geo.tif"
        if present:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body + (b"!" if corrupt else b""))
        digest = hashlib.sha256(body).hexdigest()
        rows.append(
            {
                "version": 1,
                "kind": "geotiff",
                "source": "usgs-historical-topo",
                "topo_id": topo_id,
                "source_id": None,
                "indexed_url": URL,
                "retrieval_url": None,
                "metadata_url": None,
                "rights": "public_domain",
                "sha256": digest,
                "byte_count": len(body),
                "raw_path": f"topo/{topo_id}_geo.tif",
                "retrieved_at": None,
                "recorded_at": "2026-09-16T00:00:00Z",
                "basis": "existing_file",
            }
        )
    write_ledger(receipts, *rows)
    return root, receipts


def geo_ok(path, driver):
    return f"{driver} georeferencing ok"


def no_geo(path, driver):
    raise ValueError("no embedded georeferencing")


@pytest.mark.parametrize(
    "present, corrupt, expected",
    [
        (True, False, "verified sha256"),
        (False, False, "blocked: receipted file absent"),
        (True, True, "blocked: Checksum mismatch"),
    ],
)
def test_topo_check_reports_full_file_status(tmp_path, present, corrupt, expected):
    root, receipts = topo_fixture(tmp_path, present, corrupt)
    results = ds.check_topo(root, receipts, ds.INDEX_PATH, ds.SELECTION_PATH, inspect=geo_ok)
    assert [r[0].split(" ")[0] for r in results] == list(ds.TOPO_IDS)
    assert all(expected in r[2] for r in results), results
    assert all(r[1] is (expected == "verified sha256") for r in results)


def test_topo_check_reports_receipt_basis_and_georeferencing(tmp_path):
    root, receipts = topo_fixture(tmp_path)
    results = ds.check_topo(root, receipts, ds.INDEX_PATH, ds.SELECTION_PATH, inspect=geo_ok)
    for _, ok, detail, blockers in results:
        assert ok and blockers == []
        assert "basis existing_file, retrieved_at null" in detail
        assert "GTiff georeferencing ok" in detail


def test_topo_check_blocks_missing_receipt(tmp_path):
    root, receipts = topo_fixture(tmp_path)
    receipts.write_text("")
    results = ds.check_topo(root, receipts, ds.INDEX_PATH, ds.SELECTION_PATH, inspect=refuse)
    assert all(r[2] == "blocked: no receipt in retrievals.jsonl" for r in results)


def test_tiff_without_georeferencing_is_an_open_blocker(tmp_path):
    root, receipts = topo_fixture(tmp_path)
    results = ds.check_topo(root, receipts, ds.INDEX_PATH, ds.SELECTION_PATH, inspect=no_geo)
    assert all(r[1] and "no embedded georeferencing" in r[3][0] for r in results)


def pdf_fixture(tmp_path, rights="public_domain"):
    root = tmp_path / "raw"
    ledger = tmp_path / "ledger.jsonl"
    catalog = catalog_copy(
        tmp_path, lambda d: [s["rights"].update(status=rights) for s in d["sources"]]
    )
    records = []
    for source_id in ds.PDF_SOURCE_IDS:
        body = PDF + source_id.encode()
        record = receipt(body=body, source_id=source_id)
        (root / record["path"]).parent.mkdir(parents=True, exist_ok=True)
        (root / record["path"]).write_bytes(body)
        records.append(record)
    write_ledger(ledger, *records)
    return root, catalog, ledger


def test_pdf_check_verifies_full_file_and_georeferencing(tmp_path):
    root, catalog, ledger = pdf_fixture(tmp_path)
    results = ds.check_pdfs(root, catalog, ledger, inspect=geo_ok)
    for _, ok, detail, blockers in results:
        assert ok and blockers == []
        assert "verified sha256" in detail and "PDF georeferencing ok" in detail


def test_pdf_check_lists_georeferencing_and_rights_blockers(tmp_path):
    root, catalog, ledger = pdf_fixture(tmp_path, rights="blocked")
    results = ds.check_pdfs(root, catalog, ledger, inspect=no_geo)
    for _, ok, _, blockers in results:
        assert ok
        assert "no embedded georeferencing" in blockers[0]
        assert "rights unresolved" in blockers[1]


def test_pdf_check_blocks_tampered_bytes(tmp_path):
    root, catalog, ledger = pdf_fixture(tmp_path)
    for record in ds.load_ledger(ledger).values():
        (root / record["path"]).write_bytes(PDF)
    results = ds.check_pdfs(root, catalog, ledger, inspect=refuse)
    assert all(not ok and "Checksum mismatch" in d for _, ok, d, _ in results)


def test_pdf_check_blocks_without_receipt(tmp_path):
    root, catalog, ledger = pdf_fixture(tmp_path)
    ledger.write_text("")
    results = ds.check_pdfs(root, catalog, ledger, inspect=refuse)
    assert all(not ok and "no PDF receipt" in d for _, ok, d, _ in results)


def test_check_command_exits_nonzero_when_blocked(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    result = CliRunner().invoke(
        ds.cli,
        ["--raw-root", str(root), "--ledger", str(tmp_path / "none.jsonl"), "check"],
    )
    assert result.exit_code == 1
    assert "0 of 5 candidates verified" in result.output


def test_unreadable_pdf_reports_precise_reason(tmp_path):
    path = tmp_path / "x.pdf"
    path.write_bytes(PDF)
    with pytest.raises(Exception, match="georeferenc|PDF"):
        ds.inspect_raster(path, "PDF")
