import csv
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
        return stream

    monkeypatch.setattr(topo.urllib.request, "urlopen", response)
    return CliRunner().invoke(
        topo.cli,
        [
            "download",
            "--index",
            str(path),
            "--dest",
            str(tmp_path / "raw"),
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
    raw = tmp_path / "raw"
    raw.mkdir()
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
    assert list((tmp_path / "raw").iterdir()) == []


def test_valid_download_and_rerun(tmp_path, row, monkeypatch, tiff_bytes):
    body = tiff_bytes
    row["size_bytes"] = str(len(body))
    result = invoke_download(tmp_path, row, monkeypatch, body, declared=str(len(body)))
    assert result.exit_code == 0, result.output
    target = tmp_path / "raw" / f"{row['topo_id']}_geo.tif"
    before = target.stat().st_mtime_ns
    result = invoke_download(tmp_path, row, monkeypatch, b"must not be fetched")
    assert result.exit_code == 0, result.output
    assert "1 already present" in result.output
    assert target.read_bytes() == body
    assert target.stat().st_mtime_ns == before


def test_concurrent_publication_does_not_replace_file(tmp_path, row, monkeypatch, tiff_bytes):
    real_link = topo.os.link

    def collide(source, target):
        target.write_bytes(b"another process published this")
        return real_link(source, target)

    monkeypatch.setattr(topo.os, "link", collide)
    row["size_bytes"] = str(len(tiff_bytes))
    result = invoke_download(
        tmp_path,
        row,
        monkeypatch,
        tiff_bytes,
        declared=str(len(tiff_bytes)),
    )
    assert result.exit_code != 0
    target = tmp_path / "raw" / f"{row['topo_id']}_geo.tif"
    assert target.read_bytes() == b"another process published this"
    assert list(target.parent.glob("*.part")) == []


def test_dry_run_does_not_create_destination(tmp_path, row, monkeypatch):
    result = invoke_download(tmp_path, row, monkeypatch, b"", extra=("--dry-run",))
    assert result.exit_code == 0, result.output
    assert "1 sheets selected" in result.output
    assert not (tmp_path / "raw").exists()


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
