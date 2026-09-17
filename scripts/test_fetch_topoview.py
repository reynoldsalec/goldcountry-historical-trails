import csv
import hashlib
import io
import json
from pathlib import Path

import fetch_topoview as topo
import pytest
import rasterio
import yaml
from click.testing import CliRunner
from shapely.geometry import box


@pytest.fixture
def tiff_bytes():
    with rasterio.io.MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=rasterio.transform.from_origin(-121, 39, 0.01, 0.01),
        ):
            pass
        return memory.read()


@pytest.fixture
def row():
    record = dict.fromkeys(topo.COLUMNS, "")
    record.update(
        topo_id="CA_Test_1_1953_24000",
        map_name="Test",
        scale="24000",
        date_on_map="1953",
        content_year="1981",
        photo_revision_year="1981",
        aerial_photo_year="1978",
        in_tier1="false",
        size_bytes="64",
        rights="public_domain",
        geotiff_url="https://example.test/test.tif",
        metadata_url="https://example.test/test.xml",
        datum="NAD27",
        west="0",
        south="0",
        east="1",
        north="1",
    )
    return record


def write_index(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=topo.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def product(row):
    return {
        "urls": {"GeoTIFF": "https://example.test/CA_Test_1_1953_24000_geo.tif"},
        "boundingBox": {"minX": 0, "minY": 0, "maxX": 1, "maxY": 1},
        "vendorMetaUrl": row["metadata_url"],
        "sizeInBytes": 64,
    }


def invoke_download(tmp_path, row, monkeypatch, body, declared="64", extra=()):
    path = tmp_path / "index.csv"
    write_index(path, [row])

    def response(*args, **kwargs):
        stream = io.BytesIO(body)
        stream.headers = {} if declared is None else {"Content-Length": declared}
        stream.geturl = lambda: row["geotiff_url"]
        return stream

    monkeypatch.setattr(topo.urllib.request, "urlopen", response)
    return CliRunner().invoke(
        topo.cli,
        [
            "download",
            "--index",
            str(path),
            "--dest",
            str(tmp_path / "raw" / "topo"),
            "--receipts",
            str(tmp_path / "receipts.jsonl"),
            *extra,
        ],
    )


@pytest.mark.parametrize("blob", [b"not XML", b"<html>error</html>"])
def test_invalid_metadata_is_not_success(blob):
    with pytest.raises(ValueError):
        topo.parse_metadata(blob)


def test_lineage_dates_remain_distinct():
    result = topo.parse_metadata(b"""<metadata><dataqual><lineage>
        <procstep><procdesc>Date on Map</procdesc><procdate>1953</procdate></procstep>
        <procstep><procdesc>Photo Revision Year</procdesc><procdate>1981</procdate></procstep>
        <procstep><procdesc>Aerial Photo Year</procdesc><procdate>1978</procdate></procstep>
        </lineage></dataqual></metadata>""")
    assert result == {
        "date_on_map": "1953",
        "photo_revision_year": "1981",
        "aerial_photo_year": "1978",
        "datum": "",
        "projection": "",
    }
    assert topo.content_year(result) == "1981"


@pytest.mark.parametrize(
    "pages",
    [
        [{"error": "unavailable"}],
        [{"items": [{"id": 1}], "total": 2}, {"items": [], "total": 2}],
    ],
)
def test_incomplete_api_results_fail(monkeypatch, pages):
    responses = iter(pages)
    monkeypatch.setattr(topo, "get", lambda *args: json.dumps(next(responses)).encode())
    with pytest.raises(topo.click.ClickException):
        topo.query_products((0, 0, 1, 1), 1)


@pytest.mark.parametrize("bad_id", ["../escape", "nested/file", "nested\\file", ""])
def test_unsafe_index_ids_fail(tmp_path, row, bad_id):
    row["topo_id"] = bad_id
    path = tmp_path / "index.csv"
    write_index(path, [row])
    with pytest.raises(topo.click.ClickException):
        topo.read_index(path)


def test_duplicate_index_ids_fail(tmp_path, row):
    path = tmp_path / "index.csv"
    write_index(path, [row, row])
    with pytest.raises(topo.click.ClickException, match="Duplicate"):
        topo.read_index(path)


def test_metadata_failure_preserves_existing_index(tmp_path, row, monkeypatch):
    path = tmp_path / "index.csv"
    write_index(path, [row])
    before = path.read_bytes()
    monkeypatch.setattr(topo, "load_aoi", lambda name: box(0, 0, 2, 2))
    monkeypatch.setattr(topo, "query_products", lambda *args: [product(row)])
    monkeypatch.setattr(topo, "get", lambda *args: b"<html>error</html>")
    result = CliRunner().invoke(topo.cli, ["index", "--refresh", "--out", str(path)])
    assert result.exit_code != 0
    assert "index unchanged" in result.output
    assert path.read_bytes() == before


def test_countywide_index_filters_outside_sheets(tmp_path, row, monkeypatch):
    inside = product(row)
    outside = product(row)
    outside["boundingBox"] = {"minX": 10, "minY": 10, "maxX": 11, "maxY": 11}
    monkeypatch.setattr(topo, "load_aoi", lambda name: box(0, 0, 2, 2))
    monkeypatch.setattr(topo, "query_products", lambda *args: [inside, outside])
    monkeypatch.setattr(
        topo, "get", lambda *args: b"<metadata><horizdn>NAD27</horizdn></metadata>"
    )
    path = tmp_path / "index.csv"
    result = CliRunner().invoke(topo.cli, ["index", "--out", str(path)])
    assert result.exit_code == 0, result.output
    assert len(topo.read_index(path)) == 1
    assert b"\r\n" not in path.read_bytes()


def test_existing_raw_file_is_never_replaced(tmp_path, row, monkeypatch):
    raw = tmp_path / "raw" / "topo"
    raw.mkdir(parents=True)
    target = raw / f"{row['topo_id']}_geo.tif"
    target.write_bytes(b"original")
    result = invoke_download(tmp_path, row, monkeypatch, b"II*\x00" + bytes(60))
    assert result.exit_code != 0
    assert "left unchanged" in result.output
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize(
    "body,declared",
    [
        (b"II*\x00" + bytes(10), "64"),
        (b"<html>upstream error</html>", "27"),
        (b"II*\x00" + bytes(10), None),
        (b"II*\x00" + bytes(60), "64"),
    ],
)
def test_bad_download_is_not_published(tmp_path, row, monkeypatch, body, declared):
    result = invoke_download(tmp_path, row, monkeypatch, body, declared)
    assert result.exit_code != 0
    assert list((tmp_path / "raw" / "topo").iterdir()) == []


def test_valid_download_and_rerun(tmp_path, row, monkeypatch, tiff_bytes):
    body = tiff_bytes
    row["size_bytes"] = str(len(body))
    result = invoke_download(tmp_path, row, monkeypatch, body, declared=str(len(body)))
    assert result.exit_code == 0, result.output
    target = topo.archive.object_path(
        tmp_path / "raw" / "topo", hashlib.sha256(body).hexdigest()
    )
    before = target.stat().st_mtime_ns
    result = invoke_download(tmp_path, row, monkeypatch, b"must not be fetched")
    assert result.exit_code == 0, result.output
    assert "1 already present" in result.output
    assert target.read_bytes() == body
    assert target.stat().st_mtime_ns == before
    receipt = topo.archive.load_receipts(tmp_path / "receipts.jsonl")[0]
    assert receipt["retrieved_at"] is not None
    assert receipt["sha256"] == hashlib.sha256(body).hexdigest()


def test_concurrent_publication_does_not_replace_file(tmp_path, row, monkeypatch, tiff_bytes):
    real_link = topo.archive.os.link

    def collide(source, target):
        target.write_bytes(b"another process published this")
        return real_link(source, target)

    monkeypatch.setattr(topo.archive.os, "link", collide)
    row["size_bytes"] = str(len(tiff_bytes))
    result = invoke_download(
        tmp_path,
        row,
        monkeypatch,
        tiff_bytes,
        declared=str(len(tiff_bytes)),
    )
    assert result.exit_code != 0
    target = topo.archive.object_path(
        tmp_path / "raw" / "topo",
        hashlib.sha256(tiff_bytes).hexdigest(),
    )
    assert target.read_bytes() == b"another process published this"
    assert list(target.parent.glob("*.part")) == []


def test_same_size_corruption_is_rejected_on_reuse(tmp_path, row, monkeypatch, tiff_bytes):
    row["size_bytes"] = str(len(tiff_bytes))
    assert (
        invoke_download(
            tmp_path,
            row,
            monkeypatch,
            tiff_bytes,
            declared=str(len(tiff_bytes)),
        ).exit_code
        == 0
    )
    record = topo.archive.load_receipts(tmp_path / "receipts.jsonl")[0]
    target = tmp_path / "raw" / record["raw_path"]
    changed = tiff_bytes[:-1] + bytes([tiff_bytes[-1] ^ 1])
    target.write_bytes(changed)
    result = invoke_download(tmp_path, row, monkeypatch, tiff_bytes)
    assert result.exit_code != 0
    assert "Checksum mismatch" in result.output
    assert target.read_bytes() == changed


def test_remote_changed_bytes_do_not_replace_missing_recorded_source(
    tmp_path,
    row,
    monkeypatch,
    tiff_bytes,
):
    row["size_bytes"] = str(len(tiff_bytes))
    assert (
        invoke_download(
            tmp_path,
            row,
            monkeypatch,
            tiff_bytes,
            declared=str(len(tiff_bytes)),
        ).exit_code
        == 0
    )
    ledger = tmp_path / "receipts.jsonl"
    before = ledger.read_bytes()
    record = topo.archive.load_receipts(ledger)[0]
    target = tmp_path / "raw" / record["raw_path"]
    target.unlink()
    changed = tiff_bytes[:-1] + bytes([tiff_bytes[-1] ^ 1])
    result = invoke_download(tmp_path, row, monkeypatch, changed, declared=str(len(changed)))
    assert result.exit_code != 0
    assert "Remote bytes differ" in result.output
    assert not target.exists()
    assert ledger.read_bytes() == before


def test_dry_run_does_not_create_destination(tmp_path, row, monkeypatch):
    result = invoke_download(tmp_path, row, monkeypatch, b"", extra=("--dry-run",))
    assert result.exit_code == 0, result.output
    assert "1 sheets selected" in result.output
    assert not (tmp_path / "raw" / "topo").exists()


def test_docs_include_non_corridor_sheets_and_are_idempotent(tmp_path, row):
    index = tmp_path / "index.csv"
    out = tmp_path / "editions.md"
    write_index(index, [row])
    args = ["docs", "--index", str(index), "--out", str(out)]
    result = CliRunner().invoke(topo.cli, args)
    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert "Countywide editions — 1 sheets" in text
    assert row["geotiff_url"] in text
    before = out.stat().st_mtime_ns
    assert CliRunner().invoke(topo.cli, args).exit_code == 0
    assert out.stat().st_mtime_ns == before


def test_source_inventory_integrity():
    rows = topo.read_index(topo.INDEX_PATH)
    assert rows
    counties = topo.load_aoi("aoi_counties.geojson")
    legacy = topo.load_aoi("aoi_tier1.geojson")
    for row in rows.values():
        bounds = [float(row[key]) for key in ("west", "south", "east", "north")]
        assert bounds[0] < bounds[2] and bounds[1] < bounds[3]
        footprint = box(*bounds)
        assert footprint.intersects(counties)
        assert (row["in_tier1"] == "true") == footprint.intersects(legacy)
        assert row["content_year"] == topo.content_year(row)
        assert row["rights"] == "public_domain"
        assert int(row["size_bytes"]) > 0
        for key in ("geotiff_url", "metadata_url", "sciencebase_url"):
            assert topo.urllib.parse.urlsplit(row[key]).scheme == "https"
    sources = yaml.safe_load((topo.SOURCES_DIR / "sources.yml").read_text())["sources"]
    assert len({source["id"] for source in sources}) == len(sources)
    assert all(source["rights"] and source["attribution"] for source in sources)
    assert all(
        Path(topo.REPO_ROOT / path).stat().st_size < 25_000_000
        for path in (
            "data/sources/sources.yml",
            "data/sources/topo_index.csv",
        )
    )


def test_downloaded_raw_rasters_are_readable():
    rows = topo.read_index(topo.INDEX_PATH)
    files = sorted(topo.RAW_TOPO_DIR.glob("*_geo.tif"))
    if not files:
        pytest.skip("No locally downloaded rasters to inspect")
    for path in files:
        assert path.name.removesuffix("_geo.tif") in rows
        with rasterio.open(path) as dataset:
            assert dataset.crs
            assert dataset.count > 0 and dataset.width > 0 and dataset.height > 0


def second_row(row):
    other = dict(row)
    other.update(
        topo_id="CA_Test_2_1962_24000",
        map_name="Other",
        date_on_map="1962",
        geotiff_url="https://example.test/other.tif",
    )
    return other


def invoke_selection(tmp_path, rows, monkeypatch, body, requested, extra=()):
    path = tmp_path / "index.csv"
    write_index(path, rows)

    def response(request, *args, **kwargs):
        requested.append(request.full_url)
        stream = io.BytesIO(body)
        stream.headers = {"Content-Length": str(len(body))}
        stream.geturl = lambda: request.full_url
        return stream

    monkeypatch.setattr(topo.urllib.request, "urlopen", response)
    return CliRunner().invoke(
        topo.cli,
        [
            "download",
            "--index",
            str(path),
            "--dest",
            str(tmp_path / "raw" / "topo"),
            "--receipts",
            str(tmp_path / "receipts.jsonl"),
            *extra,
        ],
    )


def write_selection(tmp_path, topo_ids, **overrides):
    payload = {"version": 1, "topo_ids": topo_ids}
    payload.update(overrides)
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_selection_requests_only_the_named_editions(tmp_path, row, monkeypatch, tiff_bytes):
    other = second_row(row)
    third = dict(row, topo_id="CA_Test_3_1975_24000", geotiff_url="https://example.test/3.tif")
    for record in (row, other, third):
        record["size_bytes"] = str(len(tiff_bytes))
    requested = []
    selection = write_selection(tmp_path, [row["topo_id"], other["topo_id"]])
    result = invoke_selection(
        tmp_path,
        [row, other, third],
        monkeypatch,
        tiff_bytes,
        requested,
        extra=("--selection", str(selection)),
    )
    assert result.exit_code == 0, result.output
    assert sorted(requested) == sorted([row["geotiff_url"], other["geotiff_url"]])
    assert len(topo.archive.load_receipts(tmp_path / "receipts.jsonl")) == 2


def test_unknown_selection_id_blocks_every_download(tmp_path, row, monkeypatch, tiff_bytes):
    other = second_row(row)
    requested = []
    selection = write_selection(
        tmp_path, [row["topo_id"], other["topo_id"], "CA_Missing_9_1999_24000"]
    )
    result = invoke_selection(
        tmp_path,
        [row, other],
        monkeypatch,
        tiff_bytes,
        requested,
        extra=("--selection", str(selection)),
    )
    assert result.exit_code != 0
    assert "absent from the index" in result.output
    assert requested == []
    assert not (tmp_path / "receipts.jsonl").exists()
    assert not (tmp_path / "raw" / "topo").exists()


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"version": 1, "topo_ids": []}, "non-empty list"),
        ({"version": 1, "topo_ids": ["CA_Test_1_1953_24000"] * 2}, "Duplicate"),
        ({"version": 1, "topo_ids": [""]}, "non-empty strings"),
        ({"version": 1, "topo_ids": [7]}, "non-empty strings"),
        ({"version": 2, "topo_ids": ["CA_Test_1_1953_24000"]}, "version must be 1"),
        (
            {"version": 1, "topo_ids": ["CA_Test_1_1953_24000"], "scale": "24000"},
            "Unknown selection keys",
        ),
    ],
)
def test_malformed_selection_fails(tmp_path, row, monkeypatch, payload, message):
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    requested = []
    result = invoke_selection(
        tmp_path, [row], monkeypatch, b"", requested, extra=("--selection", str(path))
    )
    assert result.exit_code != 0
    assert message in result.output
    assert requested == []
    assert not (tmp_path / "raw" / "topo").exists()


@pytest.mark.parametrize("conflict", [("--tier1",), ("--scale", "24000")])
def test_selection_rejects_conflicting_filters(tmp_path, row, monkeypatch, conflict):
    selection = write_selection(tmp_path, [row["topo_id"]])
    requested = []
    result = invoke_selection(
        tmp_path,
        [row],
        monkeypatch,
        b"",
        requested,
        extra=("--selection", str(selection), *conflict),
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    assert requested == []


def test_selection_dry_run_plans_without_network_or_writes(
    tmp_path, row, monkeypatch, tiff_bytes
):
    other = second_row(row)
    row["size_bytes"] = str(len(tiff_bytes))
    other["size_bytes"] = str(len(tiff_bytes))
    requested = []
    selection = write_selection(tmp_path, [row["topo_id"], other["topo_id"]])
    result = invoke_selection(
        tmp_path,
        [row, other],
        monkeypatch,
        tiff_bytes,
        requested,
        extra=("--selection", str(selection), "--dry-run"),
    )
    assert result.exit_code == 0, result.output
    assert requested == []
    assert not (tmp_path / "raw" / "topo").exists()
    assert not (tmp_path / "receipts.jsonl").exists()
    for record in (row, other):
        assert (
            f"{record['topo_id']}: missing (expects {len(tiff_bytes)} bytes)" in result.output
        )


def test_selection_rerun_reuses_the_raw_file(tmp_path, row, monkeypatch, tiff_bytes):
    row["size_bytes"] = str(len(tiff_bytes))
    selection = write_selection(tmp_path, [row["topo_id"]])
    extra = ("--selection", str(selection))
    requested = []
    assert (
        invoke_selection(tmp_path, [row], monkeypatch, tiff_bytes, requested, extra).exit_code
        == 0
    )
    target = topo.archive.object_path(
        tmp_path / "raw" / "topo", hashlib.sha256(tiff_bytes).hexdigest()
    )
    before = target.stat().st_mtime_ns
    ledger = (tmp_path / "receipts.jsonl").read_bytes()
    result = invoke_selection(
        tmp_path, [row], monkeypatch, b"must not be fetched", requested, extra
    )
    assert result.exit_code == 0, result.output
    assert "1 already present" in result.output
    assert requested == [row["geotiff_url"]]
    assert target.stat().st_mtime_ns == before
    assert target.read_bytes() == tiff_bytes
    assert (tmp_path / "receipts.jsonl").read_bytes() == ledger

    plan = invoke_selection(tmp_path, [row], monkeypatch, b"", requested, (*extra, "--dry-run"))
    assert plan.exit_code == 0, plan.output
    assert f"{row['topo_id']}: present" in plan.output


def test_selection_dry_run_reports_a_mismatch_without_replacing(tmp_path, row, monkeypatch):
    raw = tmp_path / "raw" / "topo"
    raw.mkdir(parents=True)
    target = raw / f"{row['topo_id']}_geo.tif"
    target.write_bytes(b"original")
    selection = write_selection(tmp_path, [row["topo_id"]])
    requested = []
    result = invoke_selection(
        tmp_path,
        [row],
        monkeypatch,
        b"",
        requested,
        extra=("--selection", str(selection), "--dry-run"),
    )
    assert result.exit_code != 0
    assert f"{row['topo_id']}: mismatch" in result.output
    assert requested == []
    assert target.read_bytes() == b"original"
