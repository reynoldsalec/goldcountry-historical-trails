import copy
import csv
import hashlib
import json
import os
import socket

import demo
import demo_sources
import fetch_topoview as topo
import numpy as np
import pytest
import rasterio
import yaml
from affine import Affine
from click.testing import CliRunner
from pyproj import CRS, Transformer
from rasterio.transform import rowcol
from shapely.geometry import shape

# The graticule corners of the Auburn 7.5-minute quadrangle, as labelled in the index.
SEED = (-121.125, 38.875, -121.0, 39.0)

POLYCONIC_WKT = (
    'PROJCS["unnamed",GEOGCS["NAD27",DATUM["North_American_Datum_1927",'
    'SPHEROID["Clarke 1866",6378206.4,294.978698213898,AUTHORITY["EPSG","7008"]],'
    'AUTHORITY["EPSG","6267"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4267"]],PROJECTION["Polyconic"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-121.062999999999],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)
LCC_WKT = (
    'PROJCS["unnamed",GEOGCS["NAD27",DATUM["North_American_Datum_1927",'
    'SPHEROID["Clarke 1866",6378206.4,294.978698213898,AUTHORITY["EPSG","7008"]],'
    'AUTHORITY["EPSG","6267"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4267"]],PROJECTION["Lambert_Conformal_Conic_2SP"],'
    'PARAMETER["latitude_of_origin",38.875],'
    'PARAMETER["central_meridian",-121.062999999999],'
    'PARAMETER["standard_parallel_1",33],PARAMETER["standard_parallel_2",45],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)

ATTRIBUTION = "Historical topographic maps: U.S. Geological Survey"

# Index columns that matter here, transcribed from data/sources/topo_index.csv.
INDEX_ROWS = {
    "CA_Auburn_288101_1953_24000": {
        "date_on_map": "1953",
        "content_year": "1953",
        "imprint_year": "1955",
        "aerial_photo_year": "1952",
        "photo_revision_year": "",
        "field_check_year": "1953",
        "projection": "Polyconic",
        "size_bytes": "12532400",
        "source_id": "5a8a2904e4b00f54eb3c61ca",
    },
    "CA_Auburn_288103_1953_24000": {
        "date_on_map": "1953",
        "content_year": "1973",
        "imprint_year": "1977",
        "aerial_photo_year": "1973",
        "photo_revision_year": "1973",
        "field_check_year": "1953",
        "projection": "Polyconic",
        "size_bytes": "11709311",
        "source_id": "5a8a2905e4b00f54eb3c61d1",
    },
    "CA_Auburn_288104_1975_24000": {
        "date_on_map": "1975",
        "content_year": "1975",
        "imprint_year": "1981",
        "aerial_photo_year": "1975",
        "photo_revision_year": "",
        "field_check_year": "",
        "projection": "Lambert Conformal Conic",
        "size_bytes": "14103396",
        "source_id": "5a8a2905e4b00f54eb3c61d4",
    },
    "CA_Auburn_288105_1953_24000": {
        "date_on_map": "1953",
        "content_year": "1981",
        "imprint_year": "1981",
        "aerial_photo_year": "1978",
        "photo_revision_year": "1981",
        "field_check_year": "1953",
        "edit_year": "1981",
        "projection": "Polyconic",
        "size_bytes": "12427061",
        "source_id": "5a8a2905e4b00f54eb3c61d9",
    },
}

# The three regional sheets the version-2 manifest adds, transcribed from topo_index.csv.
REGIONAL_ROWS = {
    "CA_Sacramento_299588_1891_125000": {
        "map_name": "Sacramento",
        "scale": "125000",
        "extent": "30 x 30 minute",
        "date_on_map": "1891",
        "content_year": "1891",
        "survey_year": "1888",
        "woodland_tint": "N",
        "datum": "Unstated",
        "projection": "Unstated",
        "west": "-121.5",
        "south": "38.5",
        "east": "-121.0",
        "north": "39.0",
        "size_bytes": "4379097",
        "source_id": "5a8a53d1e4b00f54eb4106c4",
    },
    "CA_Auburn_296741_1944_62500": {
        "map_name": "Auburn",
        "scale": "62500",
        "extent": "15 x 15 minute",
        "date_on_map": "1944",
        "content_year": "1944",
        "survey_year": "1941",
        "projection": "Polyconic",
        "west": "-121.25",
        "south": "38.75",
        "east": "-121.0",
        "north": "39.0",
        "size_bytes": "8057515",
        "source_id": "5a8a3f95e4b00f54eb3ebcbc",
    },
    "CA_Sacramento_299157_1994_100000": {
        "map_name": "Sacramento",
        "scale": "100000",
        "extent": "30 x 60 minute",
        "date_on_map": "1994",
        "content_year": "1994",
        "imprint_year": "1994",
        "aerial_photo_year": "1987",
        "edit_year": "1994",
        "projection": "Universal Transverse Mercator",
        "west": "-122.0",
        "south": "38.5",
        "east": "-121.0",
        "north": "39.0",
        "size_bytes": "20019247",
        "source_id": "5a8a4dcee4b00f54eb404976",
    },
}


def regional_wkt(method: str, central_meridian: float) -> str:
    """A NAD27 projected CRS like the one each regional scan embeds."""
    return (
        'PROJCS["unnamed",GEOGCS["NAD27",DATUM["North_American_Datum_1927",'
        'SPHEROID["Clarke 1866",6378206.4,294.978698213898,AUTHORITY["EPSG","7008"]],'
        'AUTHORITY["EPSG","6267"]],PRIMEM["Greenwich",0],'
        'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
        f'AUTHORITY["EPSG","4267"]],PROJECTION["{method}"],'
        f'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",{central_meridian}],'
        + ('PARAMETER["scale_factor",1],' if method == "Transverse_Mercator" else "")
        + 'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
        'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
    )


# Embedded CRS and measured pixel size of each real regional scan (docs/demo-source-review.md).
REGIONAL_SCANS = {
    "sacramento-1891": (regional_wkt("Polyconic", -121.25), 10.5833),
    "auburn-1944": (regional_wkt("Polyconic", -121.125), 5.2917),
    "sacramento-1994": (regional_wkt("Transverse_Mercator", -121.5), 8.4667),
}

DISPLAY = {
    "auburn-1953": ("Auburn 1953 topographic map", "1953 base sheet; aerial photography 1952."),
    "auburn-1973": (
        "Auburn 1973 photorevision",
        "1953 base sheet photorevised from 1973 photography; the revision was "
        "not field checked.",
    ),
    "auburn-1975": (
        "Auburn 1975 orthophotoquad",
        "Orthophotoquad from 1975-08-29 photography.",
    ),
    "auburn-1981": (
        "Auburn 1981 photorevision",
        "1953 base sheet photorevised from 1978 photography; the revision was "
        "not field checked.",
    ),
}


def index_row(topo_id):
    if topo_id in REGIONAL_ROWS:
        values = REGIONAL_ROWS[topo_id]
        row = dict.fromkeys(topo.COLUMNS, "")
        row.update(
            topo_id=topo_id,
            woodland_tint="Y",
            scanner_resolution="600 PPI",
            datum="NAD27",
            in_tier1="true",
            rights="public_domain",
            geotiff_url=(
                "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/"
                f"GeoTIFF/CA/{topo_id}_geo.tif"
            ),
            metadata_url=(
                "https://thor-f5.er.usgs.gov/ngtoc/metadata/waf/maps/historicaltopo/pdf/"
                f"CA/{values['scale']}/{topo_id}_geo.xml"
            ),
            sciencebase_url=f"https://www.sciencebase.gov/catalog/item/{values['source_id']}",
        )
        row.update(values)
        return row
    row = dict.fromkeys(topo.COLUMNS, "")
    row.update(
        topo_id=topo_id,
        map_name="Auburn",
        scale="24000",
        extent="7.5 x 7.5 minute",
        woodland_tint="Y",
        scanner_resolution="600 PPI",
        datum="NAD27",
        west=str(SEED[0]),
        south=str(SEED[1]),
        east=str(SEED[2]),
        north=str(SEED[3]),
        in_tier1="true",
        rights="public_domain",
        geotiff_url=(
            "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/"
            f"GeoTIFF/CA/{topo_id}_geo.tif"
        ),
        metadata_url=(
            "https://thor-f5.er.usgs.gov/ngtoc/metadata/waf/maps/historicaltopo/pdf/"
            f"CA/24000/{topo_id}_geo.xml"
        ),
        sciencebase_url=(
            f"https://www.sciencebase.gov/catalog/item/{INDEX_ROWS[topo_id]['source_id']}"
        ),
        **INDEX_ROWS[topo_id],
    )
    return row


def write_fixture_scan(path, wkt, *, pixel_size=2.032, margin_px=120, seed=SEED):
    """A synthetic scan: white map inside a drawn neatline, grey decorative collar.

    The neatline is rasterised along the projected graticule, so the east and west sides
    lean with meridian convergence as they do on the real sheets (PR #47). A fixture with
    axis-aligned sides cannot tell a tilt-aware crop from a rectangle.
    """
    crs = CRS.from_wkt(wkt)
    forward = Transformer.from_crs(CRS.from_epsg(4267), crs, always_xy=True)
    corner_xy = {
        name: forward.transform(lon, lat)
        for name, (lon, lat) in {
            "nw": (seed[0], seed[3]),
            "ne": (seed[2], seed[3]),
            "sw": (seed[0], seed[1]),
            "se": (seed[2], seed[1]),
        }.items()
    }
    xs = [x for x, _ in corner_xy.values()]
    ys = [y for _, y in corner_xy.values()]
    width = round((max(xs) - min(xs)) / pixel_size) + 2 * margin_px + 1
    height = round((max(ys) - min(ys)) / pixel_size) + 2 * margin_px + 1
    transform = Affine(
        pixel_size,
        0.0,
        min(xs) - margin_px * pixel_size,
        0.0,
        -pixel_size,
        max(ys) + margin_px * pixel_size,
    )

    def edge(lons, lats):
        x, y = forward.transform(np.asarray(lons), np.asarray(lats))
        row, col = rowcol(transform, x, y, op=float)
        return np.asarray(row), np.asarray(col)

    samples = 512
    lats = np.linspace(seed[3], seed[1], samples)
    lons = np.linspace(seed[0], seed[2], samples)
    west_rows, west_cols = edge(np.full(samples, seed[0]), lats)
    east_rows, east_cols = edge(np.full(samples, seed[2]), lats)
    north_rows, north_cols = edge(lons, np.full(samples, seed[3]))
    south_rows, south_cols = edge(lons, np.full(samples, seed[1]))

    all_rows = np.arange(height, dtype=float)
    all_cols = np.arange(width, dtype=float)
    # np.interp holds the end value beyond each edge, so the lines run past the corners.
    west_at = np.interp(all_rows, west_rows, west_cols)
    east_at = np.interp(all_rows, east_rows, east_cols)
    north_at = np.interp(all_cols, north_cols, north_rows)
    south_at = np.interp(all_cols, south_cols, south_rows)

    data = np.full((height, width), 200, dtype="uint8")
    for row in range(height):
        inside = (
            (all_cols >= west_at[row])
            & (all_cols <= east_at[row])
            & (row >= north_at)
            & (row <= south_at)
        )
        data[row, inside] = 255
    for row in range(height):
        for centre in (west_at[row], east_at[row]):
            for offset, value in ((-1, 40), (0, 0), (1, 40)):
                column = int(round(centre)) + offset
                if 0 <= column < width:
                    data[row, column] = value
    for column in range(width):
        for centre in (north_at[column], south_at[column]):
            for offset, value in ((-1, 40), (0, 0), (1, 40)):
                row = int(round(centre)) + offset
                if 0 <= row < height:
                    data[row, column] = value

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        compress="deflate",
    ) as dataset:
        dataset.write(data, 1)
    return path


def drawn_corners_px(path):
    """Where the fixture actually drew its four neatline corners, in pixel coordinates.

    The two lines meeting at a corner are both rasterised through the projected graticule
    corner, so that projected point is the drawn intersection.
    """
    with rasterio.open(path) as dataset:
        crs = CRS.from_user_input(dataset.crs)
        forward = Transformer.from_crs(CRS.from_epsg(4267), crs, always_xy=True)
        corners = {}
        for name, (lon, lat) in {
            "nw": (SEED[0], SEED[3]),
            "ne": (SEED[2], SEED[3]),
            "sw": (SEED[0], SEED[1]),
            "se": (SEED[2], SEED[1]),
        }.items():
            x, y = forward.transform(lon, lat)
            corners[name] = rowcol(dataset.transform, x, y, op=float)
        return corners


def crop_corners_px(path, report):
    """The crop's four corners, brought back into the scan's pixel grid.

    The datum shift is undone with the very operation `demo` chose, so only the crop's
    geometry is under test here and not PROJ's choice of transformation.
    """
    ring = report["crop_wgs84"]["coordinates"][0]
    with rasterio.open(path) as dataset:
        crs = CRS.from_user_input(dataset.crs)
        geodetic = crs.geodetic_crs
        forward = Transformer.from_crs(geodetic, crs, always_xy=True)
        shift, _ = demo.datum_transformer(geodetic, SEED)
        corners = {}
        for name, index in demo.RING_CORNER_INDEX.items():
            lon, lat = shift.transform(*ring[index], direction="INVERSE")
            x, y = forward.transform(lon, lat)
            corners[name] = rowcol(dataset.transform, x, y, op=float)
        return corners


def receipt(topo_id, path, root):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "version": 1,
        "kind": "geotiff",
        "source": "usgs-historical-topo",
        "topo_id": topo_id,
        "source_id": index_row(topo_id)["source_id"],
        "indexed_url": index_row(topo_id)["geotiff_url"],
        "retrieval_url": None,
        "metadata_url": index_row(topo_id)["metadata_url"],
        "rights": "public_domain",
        "sha256": digest,
        "byte_count": path.stat().st_size,
        "raw_path": path.relative_to(root).as_posix(),
        "retrieved_at": None,
        "recorded_at": "2026-09-16T23:54:05Z",
        "basis": "existing_file",
    }


def build_manifest(reports):
    editions = []
    for eid in demo.EDITION_ORDER:
        expected = demo.EXPECTED_EDITIONS[eid]
        topo_id = expected["source_id"]
        label, note = DISPLAY[eid]
        editions.append(
            {
                "id": eid,
                "source_id": topo_id,
                "kind": expected["kind"],
                "label": label,
                "citation": f"U.S. Geological Survey, Auburn quadrangle ({topo_id})",
                "source_url": index_row(topo_id)["sciencebase_url"],
                "rights": "public_domain",
                "attribution": ATTRIBUTION,
                "dates": copy.deepcopy(expected["dates"]),
                "date_note": note,
                "crop_wgs84": reports[eid]["crop_wgs84"],
            }
        )
    crops = [shape(edition["crop_wgs84"]) for edition in editions]
    common = crops[0]
    for crop in crops[1:]:
        common = common.intersection(crop)
    return {
        "version": 1,
        "area_id": "auburn",
        "edition_order": list(demo.EDITION_ORDER),
        "view_bounds_wgs84": [demo.q6(value) for value in common.bounds],
        "tile_zoom": {"min": 10, "max": 16},
        "editions": editions,
    }


@pytest.fixture(scope="session")
def scans(tmp_path_factory):
    """Four synthetic scans plus the geometry demo.py derives from them."""
    root = tmp_path_factory.mktemp("scans")
    paths = {}
    for eid in demo.EDITION_ORDER:
        topo_id = demo.EXPECTED_EDITIONS[eid]["source_id"]
        wkt = (
            LCC_WKT
            if demo.EXPECTED_EDITIONS[eid]["kind"] == "orthophotoquad"
            else POLYCONIC_WKT
        )
        paths[eid] = write_fixture_scan(root / f"{topo_id}_geo.tif", wkt)
    reports = {
        eid: demo.inspect_source(
            paths[eid], index_row(demo.EXPECTED_EDITIONS[eid]["source_id"])
        )
        for eid in demo.EDITION_ORDER
    }
    return paths, reports


class Tree:
    def __init__(self, base, manifest):
        self.base = base
        self.manifest = manifest
        self.raw_root = base / "raw"
        self.manifest_path = base / "demo-editions.json"
        self.receipts_path = base / "retrievals.jsonl"
        self.index_path = base / "topo_index.csv"
        self.sources_path = base / "sources.yml"
        self.ledger_path = base / "demo-pdf-retrievals.jsonl"
        self.expansion_root = base / "expansion"
        self.index_rows = []

    def write_manifest(self, manifest=None):
        payload = self.manifest if manifest is None else manifest
        self.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def write_receipts(self, records):
        self.receipts_path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
        )

    def write_index(self, rows=None):
        rows = self.index_rows if rows is None else rows
        with self.index_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=topo.COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def write_sources(self):
        self.sources_path.write_text(
            yaml.safe_dump(
                {
                    "sources": [
                        {
                            "id": "usgs-historical-topo",
                            "rights": "public_domain",
                            "attribution": ATTRIBUTION,
                        },
                        {
                            "id": "usgs-us-topo",
                            "rights": "public_domain",
                            "attribution": US_TOPO_ATTRIBUTION,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    def paths_args(self):
        return [
            "--manifest",
            str(self.manifest_path),
            "--schema",
            str(demo.SCHEMA_PATH),
            "--index",
            str(self.index_path),
            "--receipts",
            str(self.receipts_path),
            "--sources",
            str(self.sources_path),
            "--raw-root",
            str(self.raw_root),
            "--catalog",
            str(demo_sources.CATALOG_PATH),
            "--ledger",
            str(self.ledger_path),
            "--expansion-root",
            str(self.expansion_root),
        ]

    def run(self, *args):
        return CliRunner().invoke(demo.cli, ["check", *self.paths_args(), *args])


@pytest.fixture
def tree(tmp_path, scans):
    paths, reports = scans
    base = tmp_path / "tree"
    (base / "raw" / "topo").mkdir(parents=True)
    fixture = Tree(base, build_manifest(reports))
    records = []
    for eid in demo.EDITION_ORDER:
        topo_id = demo.EXPECTED_EDITIONS[eid]["source_id"]
        target = base / "raw" / "topo" / f"{topo_id}_geo.tif"
        os.link(paths[eid], target)
        records.append(receipt(topo_id, target, base / "raw"))
    fixture.write_receipts(records)
    fixture.write_manifest()
    fixture.index_rows = [index_row(t) for t in INDEX_ROWS]
    fixture.write_index()
    fixture.write_sources()
    return fixture


# --- the staged nine-edition tree (version 2, #57) --------------------------------------

US_TOPO_ATTRIBUTION = "US Topo maps: U.S. Geological Survey"
# Coarser than the real 2.03 m render to keep the fixture small, and still native zoom 16.
PDF_PIXEL_METRES = 3.5
PDF_CORNERS = {
    "upper_left": (SEED[0], SEED[3]),
    "upper_right": (SEED[2], SEED[3]),
    "lower_left": (SEED[0], SEED[1]),
    "lower_right": (SEED[2], SEED[1]),
}


def write_fixture_pdf_cog(path, *, pixel_size=PDF_PIXEL_METRES, margin_px=60):
    """A rendered US Topo page in NAD83 UTM 10N, with its neatline on the nominal box."""
    crs = CRS.from_epsg(26910)
    forward = Transformer.from_crs(CRS.from_epsg(4269), crs, always_xy=True)
    xy = {name: forward.transform(*lonlat) for name, lonlat in PDF_CORNERS.items()}
    xs = [x for x, _ in xy.values()]
    ys = [y for _, y in xy.values()]
    transform = Affine(
        pixel_size,
        0.0,
        min(xs) - margin_px * pixel_size,
        0.0,
        -pixel_size,
        max(ys) + margin_px * pixel_size,
    )
    width = round((max(xs) - min(xs)) / pixel_size) + 2 * margin_px
    height = round((max(ys) - min(ys)) / pixel_size) + 2 * margin_px
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs="EPSG:26910",
        transform=transform,
        compress="deflate",
    ) as dataset:
        dataset.write(np.full((height, width), 250, dtype="uint8"), 1)
    corners = {}
    for name, (x, y) in xy.items():
        col, row = ~transform * (x, y)
        corners[name] = {"pixel": [round(col, 2), round(row, 2)]}
    return path, transform, corners


def pdf_render_record(edition_id, source_id, pdf_receipt, cog_path, transform, corners):
    """The fields of an E2 demo-pdf-processing.json entry that the expansion reads."""
    digest = hashlib.sha256(cog_path.read_bytes()).hexdigest()
    a, b, c, d, e, f = transform[:6]
    return {
        "edition_id": edition_id,
        "source_id": source_id,
        "source": {
            "path": pdf_receipt["path"],
            "sha256": pdf_receipt["sha256"],
            "size_bytes": pdf_receipt["size_bytes"],
        },
        "georeferencing": {
            "epsg": 26910,
            "geotransform": [c, a, b, f, d, e],
            "max_residual_m": 0.0,
        },
        "neatline": {"corners": corners},
        "nominal_box": {"west": SEED[0], "south": SEED[1], "east": SEED[2], "north": SEED[3]},
        "nominal_offset": {"max_distance_m": 0.0},
        "raster": {
            "path": f"build/expansion/pdf/{edition_id}.tif",
            "sha256": digest,
            "byte_count": cog_path.stat().st_size,
            "dpi": 300,
        },
    }


@pytest.fixture(scope="session")
def added_scans(tmp_path_factory):
    """Synthetic regional scans and rendered US Topo pages for the five added editions."""
    root = tmp_path_factory.mktemp("added")
    paths, pdfs = {}, {}
    for eid, (wkt, pixel) in REGIONAL_SCANS.items():
        topo_id = demo.EXPANDED_EXPECTED_EDITIONS[eid]["source_id"]
        paths[eid] = write_fixture_scan(
            root / f"{topo_id}_geo.tif",
            wkt,
            pixel_size=pixel,
            seed=demo.seed_of(index_row(topo_id)),
        )
    for eid in ("auburn-2018", "auburn-2021"):
        pdfs[eid] = write_fixture_pdf_cog(root / f"{eid}.tif")
    return paths, pdfs


def build_expanded_tree(base, scans, added_scans, manifest=None):
    """A version-2 tree: seven receipted scans, two receipted PDFs and their E2 renders."""
    paths, reports = scans
    regional, pdfs = added_scans
    (base / "raw" / "topo").mkdir(parents=True)
    fixture = Tree(base, manifest)
    records = []
    for eid in demo.EXPANDED_EDITION_ORDER:
        contract = demo.EXPANDED_EXPECTED_EDITIONS[eid]
        if contract["source_kind"] != "historical_geotiff":
            continue
        topo_id = contract["source_id"]
        target = base / "raw" / "topo" / f"{topo_id}_geo.tif"
        os.link(paths[eid] if eid in paths else regional[eid], target)
        records.append(receipt(topo_id, target, base / "raw"))
    fixture.write_receipts(records)
    real_receipts = demo_sources.load_ledger()
    ledger, rendered = [], []
    (fixture.expansion_root / "pdf").mkdir(parents=True)
    for eid, (cog, transform, corners) in pdfs.items():
        source_id = demo.EXPANDED_EXPECTED_EDITIONS[eid]["source_id"]
        data = f"%PDF-1.7\n% fixture stand-in for {eid}\n%%EOF\n".encode()
        digest = hashlib.sha256(data).hexdigest()
        target = base / "raw" / demo_sources.pdf_relative(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record = {
            **real_receipts[source_id],
            "sha256": digest,
            "size_bytes": len(data),
            "path": demo_sources.pdf_relative(digest),
        }
        ledger.append(record)
        linked = fixture.expansion_root / "pdf" / f"{eid}.tif"
        os.link(cog, linked)
        rendered.append(pdf_render_record(eid, source_id, record, linked, transform, corners))
    fixture.ledger_path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in ledger), encoding="utf-8"
    )
    (fixture.expansion_root / demo.PDF_RECORD_NAME).write_text(
        json.dumps({"version": 1, "sources": rendered}, indent=2), encoding="utf-8"
    )
    fixture.index_rows = [index_row(t) for t in [*INDEX_ROWS, *REGIONAL_ROWS]]
    fixture.write_index()
    fixture.write_sources()
    if manifest is None:
        fixture.manifest = build_expanded_manifest(fixture, reports)
    fixture.write_manifest()
    return fixture


def build_expanded_manifest(fixture, reports):
    """The committed version-2 text, with every derived value re-derived from the fixture."""
    view = build_manifest(reports)
    derived = demo.derive_added_editions(
        view,
        fixture.index_path,
        fixture.receipts_path,
        fixture.raw_root,
        fixture.ledger_path,
        fixture.expansion_root,
    )
    manifest = demo.read_json(demo.EXPANDED_MANIFEST_PATH)
    manifest["view_bounds_wgs84"] = view["view_bounds_wgs84"]
    crops = {edition["id"]: edition["crop_wgs84"] for edition in view["editions"]}
    for edition in manifest["editions"]:
        if edition["id"] in crops:
            edition["crop_wgs84"] = crops[edition["id"]]
        else:
            edition["crop_wgs84"] = derived[edition["id"]]["crop_wgs84"]
            edition["native_resolution_metres"] = derived[edition["id"]][
                "native_resolution_metres"
            ]
    return manifest


@pytest.fixture(scope="session")
def expanded_manifest(tmp_path_factory, scans, added_scans):
    base = tmp_path_factory.mktemp("expanded-template") / "tree"
    return build_expanded_tree(base, scans, added_scans).manifest


@pytest.fixture
def expanded_tree(tmp_path, scans, added_scans, expanded_manifest):
    return build_expanded_tree(
        tmp_path / "expanded", scans, added_scans, copy.deepcopy(expanded_manifest)
    )


@pytest.fixture(params=["four", "nine"])
def contract_tree(request):
    """The live four-edition tree and the staged nine-edition tree, for shared negatives."""
    return request.getfixturevalue("tree" if request.param == "four" else "expanded_tree")


def by_id(manifest, edition_id):
    return next(e for e in manifest["editions"] if e["id"] == edition_id)


def failure(tree, mutate, *, args=()):
    manifest = copy.deepcopy(tree.manifest)
    mutate(manifest)
    tree.write_manifest(manifest)
    result = tree.run(*args)
    assert result.exit_code != 0, result.output
    return str(result.exception) + result.output


# --- the contract holds on a fresh tree of only the selected inputs -------------------


def test_fixture_tree_of_only_selected_inputs_passes(tree):
    result = tree.run()
    assert result.exit_code == 0, result.output
    for eid in demo.EDITION_ORDER:
        assert eid in result.output
    assert "4 public editions verified" in result.output


def test_check_reports_each_source_hash(tree):
    result = tree.run()
    assert result.exit_code == 0, result.output
    for record in demo.load_receipts(tree.receipts_path):
        assert record["sha256"] in result.output
        assert str(record["byte_count"]) in result.output


def test_check_writes_nothing_to_raw_or_receipts(tree):
    before = {
        path: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted((tree.raw_root / "topo").iterdir())
    }
    receipts_before = (
        tree.receipts_path.stat().st_mtime_ns,
        hashlib.sha256(tree.receipts_path.read_bytes()).hexdigest(),
    )
    assert tree.run().exit_code == 0
    after = {
        path: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted((tree.raw_root / "topo").iterdir())
    }
    assert after == before
    assert (
        tree.receipts_path.stat().st_mtime_ns,
        hashlib.sha256(tree.receipts_path.read_bytes()).hexdigest(),
    ) == receipts_before


def test_check_opens_no_socket(tree, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("demo check must not use the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    result = tree.run()
    assert result.exit_code == 0, result.output


def test_check_reads_only_the_selected_bytes(tree):
    """91 sheets are indexed; a fresh build needs only the four selected files."""
    extra = tree.raw_root / "topo" / "CA_Auburn_100355_1953_24000_geo.tif"
    assert not extra.exists()
    assert len(list((tree.raw_root / "topo").iterdir())) == 4
    assert tree.run().exit_code == 0


# --- manifest shape ------------------------------------------------------------------


def test_missing_edition_rejected(contract_tree):
    message = failure(contract_tree, lambda m: m["editions"].pop())
    assert "schema" in message.lower()


def test_duplicate_edition_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1973")["id"] = by_id(manifest, "auburn-1953")["id"]

    assert "Duplicate edition id" in failure(contract_tree, mutate)


def test_extra_edition_rejected(contract_tree):
    def mutate(manifest):
        manifest["editions"].append(copy.deepcopy(manifest["editions"][0]))

    assert "schema" in failure(contract_tree, mutate).lower()


def test_reordered_editions_rejected(contract_tree):
    def mutate(manifest):
        manifest["editions"][0], manifest["editions"][1] = (
            manifest["editions"][1],
            manifest["editions"][0],
        )

    assert "edition_order" in failure(contract_tree, mutate)


def test_unknown_edition_field_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1953")["access_right"] = "public may pass"

    assert "access_right" in failure(contract_tree, mutate)


def test_unknown_top_level_field_rejected(contract_tree):
    def mutate(manifest):
        manifest["deploy_host"] = "example.test"

    assert "deploy_host" in failure(contract_tree, mutate)


def test_unknown_date_field_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1953")["dates"]["start_year"] = 1953

    assert "start_year" in failure(contract_tree, mutate)


def test_changed_tile_zoom_rejected(contract_tree):
    def mutate(manifest):
        manifest["tile_zoom"]["max"] = 18

    assert "schema" in failure(contract_tree, mutate).lower()


# --- dates ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1973-02-30", "1973-13-01", "1973-00-01"])
def test_impossible_calendar_date_rejected(contract_tree, value):
    def mutate(manifest):
        by_id(manifest, "auburn-1973")["dates"]["revision_photography"] = value

    assert "calendar date" in failure(contract_tree, mutate)


def test_photography_year_outside_range_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1975")["dates"]["photography"] = "1775"

    assert "calendar date" in failure(contract_tree, mutate)


def test_wrong_map_year_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1981")["dates"]["map_year"] = 1981

    assert "differ from the fixed contract" in failure(contract_tree, mutate)


def test_revision_claimed_field_checked_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1973")["dates"]["revision_field_checked"] = True

    assert "differ from the fixed contract" in failure(contract_tree, mutate)


def test_date_note_must_disclose_unchecked_revision(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1981")["date_note"] = "1953 base sheet, revised 1981."

    assert "not field checked" in failure(contract_tree, mutate)


def test_index_date_disagreement_rejected(contract_tree):
    """A manifest that matches the contract but not the per-sheet index still fails."""
    rows = copy.deepcopy(contract_tree.index_rows)
    for row in rows:
        if row["topo_id"] == "CA_Auburn_288105_1953_24000":
            row["aerial_photo_year"] = "1979"
    contract_tree.write_index(rows)
    result = contract_tree.run()
    assert result.exit_code != 0, result.output
    assert "aerial_photo_year" in result.output


# --- kind and rights ------------------------------------------------------------------


def test_orthophotoquad_kind_mismatch_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1975")["kind"] = "topo"

    assert "differs from the contract" in failure(contract_tree, mutate)


def test_topo_kind_mismatch_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1953")["kind"] = "orthophotoquad"

    assert "differs from the contract" in failure(contract_tree, mutate)


def test_nonpublic_rights_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1953")["rights"] = "cc_by_nc_sa"

    assert "schema" in failure(contract_tree, mutate).lower()


def test_nonpublic_index_rights_rejected(contract_tree):
    rows = copy.deepcopy(contract_tree.index_rows)
    rows[0]["rights"] = "unknown"
    contract_tree.write_index(rows)
    result = contract_tree.run()
    assert result.exit_code != 0, result.output
    assert "not public_domain" in result.output


def test_attribution_must_match_sources_yml(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1953")["attribution"] = "Auburn Trails Council"

    assert "attribution" in failure(contract_tree, mutate)


def test_unknown_source_id_rejected(contract_tree):
    def mutate(manifest):
        by_id(manifest, "auburn-1953")["source_id"] = "CA_Auburn_288100_1953_24000"

    assert "schema" in failure(contract_tree, mutate).lower()


# --- bounds and crop ------------------------------------------------------------------


def test_inverted_longitude_bounds_rejected(tree):
    def mutate(manifest):
        west, south, east, north = manifest["view_bounds_wgs84"]
        manifest["view_bounds_wgs84"] = [east, south, west, north]

    assert "inverted in longitude" in failure(tree, mutate)


def test_inverted_latitude_bounds_rejected(tree):
    def mutate(manifest):
        west, south, east, north = manifest["view_bounds_wgs84"]
        manifest["view_bounds_wgs84"] = [west, north, east, south]

    assert "inverted in latitude" in failure(tree, mutate)


def test_bounds_wider_than_common_footprint_rejected(tree):
    def mutate(manifest):
        manifest["view_bounds_wgs84"][0] = demo.q6(manifest["view_bounds_wgs84"][0] - 0.01)

    assert "common mapped footprint" in failure(tree, mutate)


def test_crop_outside_the_source_rejected(tree):
    def mutate(manifest):
        ring = manifest["editions"][0]["crop_wgs84"]["coordinates"][0]
        manifest["editions"][0]["crop_wgs84"]["coordinates"][0] = [
            [demo.q6(lon + 0.5), lat] for lon, lat in ring
        ]
        manifest["view_bounds_wgs84"] = manifest["view_bounds_wgs84"]

    assert "outside the georeferenced source footprint" in failure(tree, mutate)


def test_crop_off_the_neatline_rejected(tree):
    def mutate(manifest):
        ring = manifest["editions"][0]["crop_wgs84"]["coordinates"][0]
        manifest["editions"][0]["crop_wgs84"]["coordinates"][0] = [
            [demo.q6(lon + 0.002), lat] for lon, lat in ring
        ]

    assert "off the inspected neatline" in failure(tree, mutate)


def test_unclosed_crop_ring_rejected(tree):
    def mutate(manifest):
        manifest["editions"][0]["crop_wgs84"]["coordinates"][0].pop()

    assert "not closed" in failure(tree, mutate)


def test_excess_coordinate_precision_rejected(tree):
    def mutate(manifest):
        ring = manifest["editions"][0]["crop_wgs84"]["coordinates"][0]
        ring[0] = [ring[0][0] + 1e-9, ring[0][1]]
        ring[-1] = list(ring[0])

    assert "decimal places" in failure(tree, mutate)


def test_scan_margin_is_excluded_from_the_crop(tree, scans):
    """The verified crop must sit inside the scan, not on its outer edge."""
    paths, reports = scans
    for eid in demo.EDITION_ORDER:
        crop = shape(reports[eid]["crop_wgs84"])
        footprint = shape(reports[eid]["source_footprint_wgs84"])
        assert crop.within(footprint)
        assert crop.area < footprint.area
        drawn = drawn_corners_px(paths[eid])
        cropped = crop_corners_px(paths[eid], reports[eid])
        for name, (row, col) in drawn.items():
            assert abs(cropped[name][0] - row) <= 1, (eid, name)
            assert abs(cropped[name][1] - col) <= 1, (eid, name)
        for edge in reports[eid]["neatline_locators_px"].values():
            for end in (value for key, value in edge.items() if key.endswith("_end")):
                assert abs(end["residual_px"]) <= 1
                assert end["darkest_mean_value"] < end["profile_median_value"]


def test_fixture_neatline_leans_the_way_the_real_scans_do(scans):
    """Guards the guard: a fixture with straight sides could not catch a rectangular crop."""
    paths, _ = scans
    for eid in demo.EDITION_ORDER:
        drawn = drawn_corners_px(paths[eid])
        lean = abs((drawn["nw"][1] - drawn["sw"][1]) - (drawn["ne"][1] - drawn["se"][1]))
        assert lean > 4, (eid, lean)


def test_axis_aligned_crop_is_rejected(tree, scans):
    """The crop that the pre-#47 code produced: corner columns and rows averaged."""
    paths, reports = scans
    eid = demo.EDITION_ORDER[0]
    drawn = drawn_corners_px(paths[eid])
    with rasterio.open(paths[eid]) as dataset:
        crs = CRS.from_user_input(dataset.crs)
        geodetic = crs.geodetic_crs
        inverse = Transformer.from_crs(crs, geodetic, always_xy=True)
        shift, _ = demo.datum_transformer(geodetic, SEED)
        west = dataset.xy(0, round((drawn["nw"][1] + drawn["sw"][1]) / 2))[0]
        east = dataset.xy(0, round((drawn["ne"][1] + drawn["se"][1]) / 2))[0]
        north = dataset.xy(round((drawn["nw"][0] + drawn["ne"][0]) / 2), 0)[1]
        south = dataset.xy(round((drawn["sw"][0] + drawn["se"][0]) / 2), 0)[1]
    ring = demo._ring(west, south, east, north)
    lons, lats = inverse.transform(*zip(*ring, strict=True))
    lons, lats = shift.transform(lons, lats)
    rectangle = [[demo.q6(lon), demo.q6(lat)] for lon, lat in zip(lons, lats, strict=True)]
    assert rectangle != reports[eid]["crop_wgs84"]["coordinates"][0]

    def mutate(manifest):
        manifest["editions"][0]["crop_wgs84"]["coordinates"][0] = rectangle

    assert "off the inspected neatline" in failure(tree, mutate)


def write_shifted_scan(source_path, path, shift_px):
    """A fixture scan whose georeferencing is moved east by `shift_px`.

    The drawn ink stays put, so the labelled graticule lands off the line by that many
    pixels: the only way to exercise the residual limit itself (PR #47).
    """
    with rasterio.open(source_path) as source:
        data = source.read(1)
        profile = source.profile
        profile["transform"] = source.transform @ Affine.translation(shift_px, 0)
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(data, 1)
    return path


def test_neatline_off_the_graticule_is_rejected(tmp_path, scans):
    paths, _ = scans
    shifted = write_shifted_scan(paths["auburn-1953"], tmp_path / "shifted_geo.tif", 4)
    with pytest.raises(Exception, match=r"over the 3\.0 px limit"):
        demo.inspect_source(shifted, index_row("CA_Auburn_288101_1953_24000"))


def test_an_unenforced_edge_off_the_graticule_is_measured_not_rejected(tmp_path, scans):
    """An east shift moves only the west and east lines, so only they exceed the limit."""
    paths, _ = scans
    shifted = write_shifted_scan(paths["auburn-1953"], tmp_path / "unenforced_geo.tif", 4)
    row = index_row("CA_Auburn_288101_1953_24000")
    report = demo.inspect_source(shifted, row, enforced={"north", "south"})
    assert report["neatline_locators_px"]["west"]["enforced"] is False
    assert report["max_abs_neatline_residual_px_all_edges"] > demo.NEATLINE_TOLERANCE_PX
    assert report["max_abs_neatline_residual_px"] <= demo.NEATLINE_TOLERANCE_PX
    assert report["enforced_edges"] == ["north", "south"]
    with pytest.raises(Exception, match=r"over the 3\.0 px limit"):
        demo.inspect_source(shifted, row, enforced={"east"})


def test_neatline_within_the_residual_limit_is_accepted(tmp_path, scans):
    """Pins the other side of the limit, so the rejection above is not a blanket failure."""
    paths, _ = scans
    shifted = write_shifted_scan(paths["auburn-1953"], tmp_path / "near_geo.tif", 2)
    report = demo.inspect_source(shifted, index_row("CA_Auburn_288101_1953_24000"))
    residual = report["max_abs_neatline_residual_px"]
    assert 1.0 < residual <= demo.NEATLINE_TOLERANCE_PX, residual


def test_scan_without_a_neatline_cannot_be_verified(tmp_path, scans):
    crs = CRS.from_wkt(POLYCONIC_WKT)
    paths, _ = scans
    with rasterio.open(paths["auburn-1953"]) as source:
        profile = source.profile
    blank = tmp_path / "blank_geo.tif"
    with rasterio.open(blank, "w", **profile) as dataset:
        dataset.write(np.full((profile["height"], profile["width"]), 255, dtype="uint8"), 1)
    assert crs is not None
    with pytest.raises(Exception, match="no west neatline found"):
        demo.inspect_source(blank, index_row("CA_Auburn_288101_1953_24000"))


def test_scan_without_a_crs_cannot_be_verified(tmp_path):
    path = tmp_path / "nocrs_geo.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=8, height=8, count=1, dtype="uint8"
    ) as dataset:
        dataset.write(np.zeros((8, 8), dtype="uint8"), 1)
    with pytest.raises(Exception, match="no CRS"):
        demo.inspect_source(path, index_row("CA_Auburn_288101_1953_24000"))


def test_datum_transformation_is_named_and_not_ballpark(scans):
    _, reports = scans
    for report in reports.values():
        note = report["datum_transformation"]
        assert note["description"]
        assert "ballpark" not in note["description"].lower()
        assert note["accuracy_metres"] >= 0


# --- receipts and bytes ---------------------------------------------------------------


def test_missing_receipt_rejected(tree):
    records = [
        record
        for record in demo.load_receipts(tree.receipts_path)
        if record["topo_id"] != "CA_Auburn_288104_1975_24000"
    ]
    tree.write_receipts(records)
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "no retrieval receipt" in result.output


def test_ambiguous_receipts_rejected(tree):
    records = demo.load_receipts(tree.receipts_path)
    duplicate = dict(records[0])
    digest = duplicate["sha256"]
    duplicate["raw_path"] = f"topo/sha256/{digest[:2]}/{digest}.tif"
    tree.write_receipts([*records, duplicate])
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "ambiguous receipts" in result.output


def test_missing_selected_bytes_rejected(tree):
    (tree.raw_root / "topo" / "CA_Auburn_288103_1953_24000_geo.tif").unlink()
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "selected source bytes are missing" in result.output


def test_checksum_mismatch_rejected(tree):
    target = tree.raw_root / "topo" / "CA_Auburn_288101_1953_24000_geo.tif"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF
    target.unlink()
    target.write_bytes(bytes(data))
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "Checksum mismatch" in result.output


def test_byte_count_mismatch_rejected(tree):
    target = tree.raw_root / "topo" / "CA_Auburn_288101_1953_24000_geo.tif"
    data = target.read_bytes()
    target.unlink()
    target.write_bytes(data + b"\x00")
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "Checksum mismatch" in result.output


def test_missing_ledger_rejected(tree):
    tree.receipts_path.unlink()
    result = tree.run()
    assert result.exit_code != 0, result.output
    assert "retrieval ledger" in result.output


# --- the committed manifest -----------------------------------------------------------


def test_committed_manifest_meets_the_contract():
    """Runs without data/raw: schema, allowlist, dates, rights and ring geometry."""
    manifest = demo.read_json(demo.MANIFEST_PATH)
    assert manifest["version"] == 2
    crops = demo.check_metadata(manifest, demo.SCHEMA_PATH, demo.INDEX_PATH, demo.SOURCES_PATH)
    assert list(crops) == demo.EXPANDED_EDITION_ORDER


def real_raw_root():
    root = os.environ.get("DEMO_RAW_ROOT")
    return demo.RAW_ROOT if root is None else type(demo.RAW_ROOT)(root)


def selected_real_paths():
    """The seven scans and two PDFs, or None. The PDFs also need their E2 renders."""
    root = real_raw_root()
    paths = {}
    for eid in demo.EXPANDED_EDITION_ORDER:
        contract = demo.EXPANDED_EXPECTED_EDITIONS[eid]
        if contract["source_kind"] == "us_topo_pdf":
            receipt = demo_sources.load_ledger().get(contract["source_id"])
            candidate = None if receipt is None else root / receipt["path"]
        else:
            candidate = root / "topo" / f"{contract['source_id']}_geo.tif"
        if candidate is None or not candidate.exists():
            return None
        paths[eid] = candidate
    if not (demo.EXPANSION_ROOT / demo.PDF_RECORD_NAME).is_file():
        return None
    return paths


needs_real_bytes = pytest.mark.skipif(
    selected_real_paths() is None,
    reason="selected source bytes or their PDF renders are not present; set DEMO_RAW_ROOT "
    "and run make expansion-pdf",
)


@needs_real_bytes
def test_committed_manifest_matches_the_real_sources():
    result = CliRunner().invoke(
        demo.cli, ["check", "--raw-root", str(real_raw_root())], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    assert "9 public editions verified" in result.output


@needs_real_bytes
def test_real_tree_with_only_the_selected_inputs(tmp_path):
    """A fresh raw root holding only the seven selected scans and two PDFs passes unchanged."""
    paths = selected_real_paths()
    raw_root = tmp_path / "raw"
    real = real_raw_root()
    for source in paths.values():
        target = raw_root / source.relative_to(real)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            target.write_bytes(source.read_bytes())
    assert len([path for path in raw_root.rglob("*") if path.is_file()]) == 9
    result = CliRunner().invoke(
        demo.cli, ["check", "--raw-root", str(raw_root)], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
