import hashlib
import json
import math

import demo_pdf
import demo_sources
import numpy as np
import pymupdf
import pytest
import rasterio
from pyproj import CRS, Transformer

PAGE_W, PAGE_H = 600.0, 720.0
# 25 m per point keeps a 7.5-minute box on a small page; the scale is irrelevant to the code.
METRES_PER_PT = 25.0
ROTATION_DEG = 1.2
DPI = 36
UTM = CRS.from_epsg(26910)
TO_UTM = Transformer.from_crs(UTM.geodetic_crs, UTM, always_xy=True)
TO_GEO = Transformer.from_crs(UTM, UTM.geodetic_crs, always_xy=True)
CENTRE = TO_UTM.transform(-121.0625, 38.9375)
CATALOG = json.loads(demo_sources.CATALOG_PATH.read_text(encoding="utf-8"))


def page_to_utm(x, y):
    c, s = math.cos(math.radians(ROTATION_DEG)), math.sin(math.radians(ROTATION_DEG))
    dx, dy = x - PAGE_W / 2, y - PAGE_H / 2
    return (
        CENTRE[0] + METRES_PER_PT * (c * dx + s * dy),
        CENTRE[1] + METRES_PER_PT * (s * dx - c * dy),
    )


def utm_to_page(east, north):
    c, s = math.cos(math.radians(ROTATION_DEG)), math.sin(math.radians(ROTATION_DEG))
    ex, ny = (east - CENTRE[0]) / METRES_PER_PT, (north - CENTRE[1]) / METRES_PER_PT
    return PAGE_W / 2 + c * ex + s * ny, PAGE_H / 2 + s * ex - c * ny


def pdf_string(text):
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def make_geopdf(
    path,
    credit,
    *,
    wkt=None,
    geo=True,
    lgi=False,
    bad_gpts=False,
):
    """A one-page US Topo lookalike: a /VP /Measure, layers, a neatline and a credit column."""
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    frame = doc.add_ocg("Map Frame", on=True)
    images = doc.add_ocg("Images", on=False)
    ortho = doc.add_ocg("Orthoimage", on=True)
    gate = doc.set_ocmd(ocgs=[ortho, images], policy="AllOn")
    box = demo_pdf.NOMINAL_BOX
    corners = [
        utm_to_page(*TO_UTM.transform(lon, lat))
        for lon, lat in (
            (box["west"], box["north"]),
            (box["east"], box["north"]),
            (box["west"], box["south"]),
            (box["east"], box["south"]),
        )
    ]
    quad = pymupdf.Quad(*[pymupdf.Point(*p) for p in corners])
    page.draw_rect(quad.rect, color=None, fill=(0, 1, 0), oc=frame)
    page.draw_rect(pymupdf.Rect(250, 300, 350, 400), color=None, fill=(1, 0, 0), oc=gate)
    page.draw_quad(quad, color=(0, 0, 0), width=1, oc=frame)
    y = quad.rect.y1 + 20
    for line in ["Produced by the United States Geological Survey"] + [
        s.strip().replace(" ... ", "........") for s in credit.split("|")[1:]
    ]:
        page.insert_text((20, y), line, fontsize=5)
        y += 7
    if geo:
        wkt = wkt or UTM.to_wkt("WKT1_ESRI")
        gcs = doc.get_new_xref()
        doc.update_object(gcs, f"<</Type/PROJCS/WKT{pdf_string(wkt)}>>")
        lpts, gpts = [], []
        for u, v in ((0, 1), (0, 0), (1, 0), (1, 1)):
            lon, lat = TO_GEO.transform(*page_to_utm(u * PAGE_W, v * PAGE_H))
            lpts += [u, v]
            gpts += [lat, lon]
        if bad_gpts:
            gpts[0] += 0.01
        measure = doc.get_new_xref()
        doc.update_object(
            measure,
            "<</Type/Measure/Subtype/GEO/Bounds[0 1 0 0 1 0 1 1]"
            f"/GPTS[{' '.join(repr(g) for g in gpts)}]"
            f"/LPTS[{' '.join(repr(float(p)) for p in lpts)}]/GCS {gcs} 0 R>>",
        )
        doc.xref_set_key(
            page.xref,
            "VP",
            f"[<</Type/Viewport/BBox[0 {PAGE_H} {PAGE_W} 0]/Name(Map Layers)"
            f"/Measure {measure} 0 R>>]",
        )
    if lgi:
        doc.xref_set_key(page.xref, "LGIDict", "<</Type/LGIDict/Version(2.1)>>")
    doc.save(path)
    return path


def receipt_for(entry, data):
    digest = hashlib.sha256(data).hexdigest()
    return {
        "version": 1,
        "source_id": entry["source_id"],
        "source_url": entry["download_url"],
        "retrieval_url": entry["download_url"],
        "retrieved_at": "2026-09-30T00:00:00Z",
        "sha256": digest,
        "size_bytes": len(data),
        "path": demo_sources.pdf_relative(digest),
        "metadata_url": entry["metadata_url"],
    }


def place(root, entry, data):
    receipt = receipt_for(entry, data)
    target = root / receipt["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return receipt


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    receipts = {}
    for entry in CATALOG["sources"]:
        fixture = make_geopdf(
            tmp_path / f"{entry['edition_id']}.pdf", entry["rights"]["credit_note"]
        )
        receipt = place(root, entry, fixture.read_bytes())
        demo_sources.append_ledger(receipt, ledger)
        receipts[entry["edition_id"]] = receipt
    return {
        "root": root,
        "catalog": catalog,
        "ledger": ledger,
        "out": tmp_path / "out",
        "receipts": receipts,
        "tmp": tmp_path,
    }


def run(ws, echo=lambda _: None):
    return demo_pdf.run(ws["root"], ws["catalog"], ws["ledger"], ws["out"], DPI, echo=echo)


def process(tmp_path, pdf_bytes, entry=None, receipt=None):
    entry = entry or CATALOG["sources"][0]
    root = tmp_path / "raw"
    receipt = receipt or place(root, entry, pdf_bytes)
    versions = demo_pdf.tool_versions()
    return demo_pdf.process_source(entry, receipt, root, tmp_path / "out", DPI, versions)


def raw_hashes(root):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.pdf"))}


def test_georeferencing_comes_from_the_measure_dictionary(workspace):
    record = run(workspace)
    source = record["sources"][0]
    geo = source["georeferencing"]
    assert geo["epsg"] == 26910
    # PDF writers round /GPTS to ~1e-6 degrees, a decimetre on the ground.
    assert geo["max_residual_m"] < 0.5
    origin_x, a, b, origin_y, d, e = geo["geotransform"]
    scale = DPI / 72
    for col, row in ((0, 0), (37, 91), (300, 360)):
        expected = page_to_utm(col / scale, row / scale)
        got = (origin_x + a * col + b * row, origin_y + d * col + e * row)
        assert math.dist(expected, got) < 0.5
    assert geo["rotation_deg"] == pytest.approx(ROTATION_DEG, abs=1e-3)
    assert source["nominal_offset"]["max_distance_m"] < 0.5
    assert source["registration_status"].startswith("offset reported")
    with rasterio.open(workspace["tmp"] / "out" / "pdf" / "auburn-2018.tif") as cog:
        assert cog.crs.to_epsg() == 26910
        assert cog.count == 3
        assert cog.transform.almost_equals(rasterio.Affine(a, b, origin_x, d, e, origin_y))
        assert (cog.width, cog.height) == (
            source["raster"]["width"],
            source["raster"]["height"],
        )


def test_default_hidden_layers_stay_hidden(workspace):
    source = run(workspace)["sources"][0]
    layers = {layer["name"]: layer["default_visible"] for layer in source["layers"]}
    assert layers == {"Map Frame": True, "Images": False, "Orthoimage": True}
    hidden = [g["members"] for g in source["content_groups"] if not g["default_visible"]]
    assert hidden == [["Orthoimage", "Images"]]
    assert source["layer_policy"]["toggled"] == []
    with rasterio.open(workspace["tmp"] / "out" / "pdf" / "auburn-2018.tif") as cog:
        pixels = np.moveaxis(cog.read(), 0, 2)
    red = (pixels[..., 0] > 200) & (pixels[..., 1] < 60) & (pixels[..., 2] < 60)
    green = (pixels[..., 1] > 200) & (pixels[..., 0] < 60)
    assert not red.any()
    assert green.sum() > 1000


def test_credit_and_margin_text_are_recorded(workspace):
    source = run(workspace)["sources"][0]
    assert all(segment["found"] for segment in source["credit_note"]["catalog_segments"])
    assert source["credit_note"]["printed"].startswith(demo_pdf.CREDIT_ANCHOR)
    assert source["neatline"]["layer"] == "Map Frame"


def test_rerun_reuses_verified_outputs_and_keeps_raw_bytes(workspace):
    before = raw_hashes(workspace["root"])
    first = run(workspace)
    record_bytes = (workspace["out"] / demo_pdf.RECORD_NAME).read_bytes()
    messages = []
    second = run(workspace, echo=messages.append)
    assert second == first
    assert (workspace["out"] / demo_pdf.RECORD_NAME).read_bytes() == record_bytes
    assert all("reused" in m for m in messages)
    assert raw_hashes(workspace["root"]) == before


def test_rerender_is_byte_identical(workspace):
    first = run(workspace)
    (workspace["out"] / demo_pdf.RECORD_NAME).unlink()
    second = run(workspace)
    assert [s["raster"]["sha256"] for s in second["sources"]] == [
        s["raster"]["sha256"] for s in first["sources"]
    ]


def test_tampered_output_is_rewritten_not_reused(workspace):
    first = run(workspace)
    cog = workspace["out"] / "pdf" / "auburn-2018.tif"
    cog.write_bytes(b"tampered")
    messages = []
    second = run(workspace, echo=messages.append)
    assert any("auburn-2018: wrote" in m for m in messages)
    assert second["sources"][0]["raster"]["sha256"] == first["sources"][0]["raster"]["sha256"]


def test_hash_mismatch_stops_before_any_output(workspace):
    receipt = workspace["receipts"]["auburn-2018"]
    target = workspace["root"] / receipt["path"]
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(demo_pdf.PdfImportError, match="Checksum mismatch"):
        run(workspace)
    assert not workspace["out"].exists()


def test_pdf_without_georeferencing_is_rejected(tmp_path):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    data = make_geopdf(tmp_path / "plain.pdf", credit, geo=False).read_bytes()
    with pytest.raises(demo_pdf.PdfImportError, match="no embedded georeferencing"):
        process(tmp_path, data)


def test_lgidict_only_pdf_is_rejected_by_name(tmp_path):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    data = make_geopdf(tmp_path / "lgi.pdf", credit, geo=False, lgi=True).read_bytes()
    with pytest.raises(demo_pdf.PdfImportError, match="LGIDict"):
        process(tmp_path, data)


def test_unsupported_crs_is_rejected(tmp_path):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    albers = CRS.from_epsg(3310).to_wkt("WKT1_ESRI")
    data = make_geopdf(tmp_path / "albers.pdf", credit, wkt=albers).read_bytes()
    with pytest.raises(demo_pdf.PdfImportError, match="unsupported CRS"):
        process(tmp_path, data)


def test_unreadable_wkt_is_rejected(tmp_path):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    data = make_geopdf(tmp_path / "bad.pdf", credit, wkt="PROJCS[nonsense").read_bytes()
    with pytest.raises(demo_pdf.PdfImportError, match="unsupported CRS"):
        process(tmp_path, data)


def test_inconsistent_control_points_are_rejected(tmp_path):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    data = make_geopdf(tmp_path / "skew.pdf", credit, bad_gpts=True).read_bytes()
    with pytest.raises(demo_pdf.PdfImportError, match="do not fit one affine"):
        process(tmp_path, data)


@pytest.mark.parametrize("damage", ["garbage", "truncated"])
def test_corrupt_pdf_is_rejected(tmp_path, damage):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    good = make_geopdf(tmp_path / "good.pdf", credit).read_bytes()
    data = (
        b"%PDF-1.7\n" + bytes(range(256)) * 8 if damage == "garbage" else good[: len(good) // 2]
    )
    with pytest.raises(demo_pdf.PdfImportError, match="corrupt|cannot open|no embedded"):
        process(tmp_path, data)
    assert not (tmp_path / "out" / "pdf").exists()


def test_blank_render_is_a_rendering_failure(tmp_path, monkeypatch):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    data = make_geopdf(tmp_path / "geo.pdf", credit).read_bytes()
    monkeypatch.setattr(demo_pdf.pdfium_c, "FPDF_RenderPageBitmap", lambda *args: None)
    with pytest.raises(demo_pdf.PdfImportError, match="rendering failed"):
        process(tmp_path, data)
    assert not (tmp_path / "out" / "pdf").exists()


def test_renderer_exception_is_a_rendering_failure(tmp_path, monkeypatch):
    credit = CATALOG["sources"][0]["rights"]["credit_note"]
    data = make_geopdf(tmp_path / "geo.pdf", credit).read_bytes()

    def boom(*args):
        raise RuntimeError("renderer crashed")

    monkeypatch.setattr(demo_pdf.pdfium_c, "FPDF_RenderPageBitmap", boom)
    with pytest.raises(demo_pdf.PdfImportError, match="rendering failed: renderer crashed"):
        process(tmp_path, data)


def test_missing_credit_is_rejected(tmp_path):
    data = make_geopdf(
        tmp_path / "geo.pdf", "Produced by the USGS | Roads ... none"
    ).read_bytes()
    with pytest.raises(demo_pdf.PdfImportError, match="credit not found"):
        process(tmp_path, data)


def test_blocked_rights_are_rejected(tmp_path):
    entry = json.loads(json.dumps(CATALOG["sources"][0]))
    entry["rights"]["status"] = "blocked"
    data = make_geopdf(tmp_path / "geo.pdf", entry["rights"]["credit_note"]).read_bytes()
    with pytest.raises(demo_pdf.PdfImportError, match="rights are unresolved"):
        process(tmp_path, data, entry=entry)


def test_renderer_probe_passes_with_pinned_pdfium():
    demo_pdf.check_renderer()
