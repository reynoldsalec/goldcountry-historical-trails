"""Fetch, register and tile the map options added beyond the nine-edition contract.

An extra edition may cover its own area rather than the Auburn view, so each one carries a
crop and coverage bounds; none of them changes the nine checked by `demo.py check`.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import click
import demo
import numpy as np
import rasterio
import warp_raster
from pyproj import CRS, Transformer
from rasterio.control import GroundControlPoint
from rasterio.enums import Resampling
from rasterio.warp import reproject
from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.polygon import orient
from source_archive import check_record, load_receipts
from warp_raster import WarpError

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
CATALOG_PATH = SOURCES_DIR / "demo-extra-editions.json"
LEDGER_PATH = SOURCES_DIR / "demo-extra-retrievals.jsonl"
NINE_MANIFEST_PATH = SOURCES_DIR / "demo-editions.json"
INDEX_PATH = SOURCES_DIR / "topo_index.csv"
RECEIPTS_PATH = SOURCES_DIR / "retrievals.jsonl"
EXTRA_ROOT = REPO_ROOT / "build" / "extra"
RECORD_NAME = "demo-extra-processing.json"
RASTER_DIRNAME = "rasters"
TILE_DIRNAME = "tiles"
INCOMING_DIRNAME = ".incoming"
USER_AGENT = "foothill-trail-atlas/0.0 (OTCA historical map browser; contact via repo)"

# Polygons in EPSG:3310 keep metre arithmetic honest over the whole forest sheet.
METRIC_EPSG = 3310
# Township corners: (section number, which corner of that section, range offset, tier offset).
TOWNSHIP_CORNERS = {31: ("sw", 0, 0), 36: ("se", 1, 0), 6: ("nw", 0, 1), 1: ("ne", 1, 1)}
CORNER_SIGNS = {"sw": (-1, -1), "se": (1, -1), "nw": (-1, 1), "ne": (1, 1)}
PLSSID_PATTERN = re.compile(r"^(CA|NV)21(\d{3})0N(\d{3})0E0$")
PUBLISHER_CHUNK = 1 << 20


# --------------------------------------------------------------------------------------
# Catalog and receipts
# --------------------------------------------------------------------------------------


def load_catalog(path: Path = CATALOG_PATH) -> dict:
    catalog = demo.read_json(path)
    if catalog.get("version") != 1:
        demo.fail(f"{path.name}: unsupported version {catalog.get('version')!r}.")
    nine = demo.read_json(NINE_MANIFEST_PATH)["edition_order"]
    order = catalog["published_order"]
    ids = [edition["id"] for edition in catalog["editions"]]
    if len(set(order)) != len(order) or sorted(order) != sorted(nine + ids):
        demo.fail(f"{path.name}: published_order must name the nine editions plus {ids}.")
    if [eid for eid in order if eid in nine] != nine:
        demo.fail(f"{path.name}: published_order must keep the nine editions in their order.")
    downloads = {entry["download_id"]: entry for entry in catalog["downloads"]}
    for edition in catalog["editions"]:
        if edition["rights"] != "public_domain":
            demo.fail(f"{edition['id']}: only public-domain imagery is published (AGENTS 2.7).")
        processing = edition["processing"]
        if processing["method"] == "gcp_polynomial":
            for key in (processing["download_id"], processing["control"]["download_id"]):
                if key not in downloads:
                    demo.fail(f"{edition['id']}: unknown download {key!r}.")
        elif processing["method"] != "georeferenced_geotiff":
            demo.fail(f"{edition['id']}: unknown processing method {processing['method']!r}.")
    return catalog


def raw_relative(kind: str, digest: str, suffix: str) -> str:
    return f"{kind}/sha256/{digest[:2]}/{digest}{suffix}"


def load_ledger(path: Path = LEDGER_PATH) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not path.exists():
        return records
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        record = json.loads(line)
        if record["download_id"] in records:
            demo.fail(f"{path.name}:{number}: duplicate receipt for {record['download_id']}.")
        if record["path"] != raw_relative(record["kind"], record["sha256"], record["suffix"]):
            demo.fail(f"{path.name}:{number}: receipt path differs from its hash.")
        records[record["download_id"]] = record
    return records


def append_ledger(record: dict, path: Path = LEDGER_PATH) -> None:
    """Append-only under a lock; an existing receipt is never rewritten (AGENTS.md 2.2)."""
    with (path.parent / ".retrievals.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if record["download_id"] in load_ledger(path):
            demo.fail(f"A receipt for {record['download_id']} exists; the ledger is unchanged.")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def verify_receipt(record: dict, raw_root: Path) -> Path:
    """Full-file SHA-256 against the receipt; a mismatch is reported, never replaced."""
    target = raw_root / record["path"]
    if not target.is_file():
        demo.fail(f"{record['download_id']}: {record['path']} is missing under {raw_root}.")
    digest, size = warp_raster.sha256_file(target)
    if (digest, size) != (record["sha256"], record["size_bytes"]):
        demo.fail(f"{record['download_id']}: bytes on disk differ from the receipt.")
    return target


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def plss_document(entry: dict) -> bytes:
    """One deterministic document from the paged BLM section queries the catalog defines."""
    query = entry["plss_query"]
    low_t, high_t = query["townships_north"]
    low_r, high_r = query["ranges_east"]
    ids = [
        f"{state}{query['meridian_code']}{township:03d}0N{range_:03d}0E0"
        for state in query["states"]
        for township in range(low_t, high_t + 1)
        for range_ in range(low_r, high_r + 1)
    ]
    features = []
    for start in range(0, len(ids), 40):
        chunk = ids[start : start + 40]
        offset = 0
        while True:
            params = {
                "where": "PLSSID IN ({})".format(",".join(f"'{value}'" for value in chunk)),
                "outFields": query["out_fields"],
                "outSR": query["out_sr"],
                "geometryPrecision": query["geometry_precision"],
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": 2000,
                "f": "json",
            }
            url = entry["retrieval_url"] + "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=180) as response:
                page = json.load(response)
            if "error" in page:
                demo.fail(f"BLM PLSS query failed: {page['error']}")
            features.extend(
                {"attributes": item["attributes"], "rings": item["geometry"]["rings"]}
                for item in page["features"]
            )
            if not page.get("exceededTransferLimit"):
                break
            offset += len(page["features"])
    features.sort(
        key=lambda item: (item["attributes"]["PLSSID"], item["attributes"]["FRSTDIVNO"])
    )
    payload = {"service": entry["source_url"], "query": query, "features": features}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def query_document(entry: dict) -> bytes:
    url = entry["retrieval_url"] + "?" + urllib.parse.urlencode(entry["query"])
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
    if "error" in json.loads(body):
        demo.fail(f"{entry['download_id']}: the query returned an error.")
    return body


def fetch_download(entry: dict, raw_root: Path) -> tuple[dict, bool]:
    prior = load_ledger().get(entry["download_id"])
    if prior is not None:
        verify_receipt(prior, raw_root)
        return prior, False
    kind = "scans" if entry["kind"] == "scan_package" else "control"
    staging_dir = raw_root / kind / "sha256"
    staging_dir.mkdir(parents=True, exist_ok=True)
    started = now_utc()
    with tempfile.NamedTemporaryFile(dir=staging_dir, delete=False) as handle:
        staged = Path(handle.name)
        sha256, sha1 = hashlib.sha256(), hashlib.sha1()
        if entry["kind"] in ("plss_sections", "arcgis_query"):
            body = (
                plss_document(entry)
                if entry["kind"] == "plss_sections"
                else query_document(entry)
            )
            handle.write(body)
            sha256.update(body)
            sha1.update(body)
        else:
            request = urllib.request.Request(
                entry["retrieval_url"], headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=600) as response:
                while chunk := response.read(PUBLISHER_CHUNK):
                    handle.write(chunk)
                    sha256.update(chunk)
                    sha1.update(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    size = staged.stat().st_size
    expected_sha1 = entry.get("publisher_sha1")
    if expected_sha1 and (sha1.hexdigest(), size) != (
        expected_sha1,
        entry["publisher_size_bytes"],
    ):
        staged.unlink()
        demo.fail(f"{entry['download_id']}: the download does not match the publisher's SHA-1.")
    digest = sha256.hexdigest()
    relative = raw_relative(kind, digest, entry["suffix"])
    target = raw_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        staged.unlink()
        if warp_raster.sha256_file(target)[0] != digest:
            demo.fail(f"{relative} exists with other bytes; it is not replaced.")
    else:
        os.replace(staged, target)
    record = {
        "version": 1,
        "download_id": entry["download_id"],
        "kind": kind,
        "suffix": entry["suffix"],
        "source_url": entry["source_url"],
        "metadata_url": entry["metadata_url"],
        "retrieval_url": entry["retrieval_url"],
        "retrieval_started_at": started,
        "retrieved_at": now_utc(),
        "sha256": digest,
        "sha1": sha1.hexdigest(),
        "size_bytes": size,
        "path": relative,
    }
    append_ledger(record)
    return record, True


# --------------------------------------------------------------------------------------
# Ground control for a scanned sheet: printed township corners matched to BLM PLSS corners
# --------------------------------------------------------------------------------------


def township_corners(document: dict) -> dict[tuple[int, int], dict]:
    """BLM township corners keyed by (range line, township line), each from up to four
    sections that meet there. `spread_m` says how far those sections disagree."""
    forward = Transformer.from_crs(4326, METRIC_EPSG, always_xy=True)
    found: dict[tuple[int, int], list[tuple]] = {}
    for feature in document["features"]:
        attributes = feature["attributes"]
        number = int(attributes["FRSTDIVNO"]) if attributes["FRSTDIVNO"] else None
        if attributes["FRSTDIVTYP"] != "SN" or number not in TOWNSHIP_CORNERS:
            continue
        match = PLSSID_PATTERN.match(attributes["PLSSID"])
        if not match:
            continue
        corner, range_offset, tier_offset = TOWNSHIP_CORNERS[number]
        ring = np.asarray(feature["rings"][0], dtype=float)
        xs, ys = forward.transform(ring[:, 0], ring[:, 1])
        sx, sy = CORNER_SIGNS[corner]
        index = int(np.argmax(sx * xs + sy * ys))
        township, range_ = int(match.group(2)), int(match.group(3))
        key = (range_ - 1 + range_offset, township - 1 + tier_offset)
        found.setdefault(key, []).append(
            (xs[index], ys[index], ring[index, 0], ring[index, 1], attributes["PLSSID"], number)
        )
    corners = {}
    for key, items in found.items():
        values = np.array([item[:4] for item in items])
        corners[key] = {
            "x": float(values[:, 0].mean()),
            "y": float(values[:, 1].mean()),
            "lon": float(values[:, 2].mean()),
            "lat": float(values[:, 3].mean()),
            "spread_m": float(max(np.ptp(values[:, 0]), np.ptp(values[:, 1]))),
            "sections": sorted(f"{item[4]} sec {item[5]}" for item in items),
        }
    return corners


def ink(path: str) -> np.ndarray:
    """Darkness of black ink only: red roads and green boundaries stay light here."""
    with rasterio.open(path) as dataset:
        data = dataset.read()
    return (255 - data.max(axis=0)).astype(np.uint8)


def nearest_line(
    dark: np.ndarray, px: float, py: float, vertical: bool, radius: int, half_length: int = 260
):
    """The long printed line nearest (px, py) within `radius`. Integrating along the line
    over about a township keeps text and streams that cross it from winning."""
    height, width = dark.shape
    if vertical:
        along = np.arange(max(0, int(py - half_length)), min(height, int(py + half_length)), 2)
        across = np.arange(int(px - radius - 40), int(px + radius + 41))
        across = across[(across >= 0) & (across < width)]
        values = dark[along[:, None], across[None, :]]
        centre = px
    else:
        along = np.arange(max(0, int(px - half_length)), min(width, int(px + half_length)), 2)
        across = np.arange(int(py - radius - 40), int(py + radius + 41))
        across = across[(across >= 0) & (across < height)]
        values = dark[across[None, :], along[:, None]]
        centre = py
    if values.shape[0] < 60 or len(across) < 2 * radius:
        return None
    values = np.sort(values.astype(np.float32), axis=0)
    count = values.shape[0]
    profile = values[int(count * 0.15) : int(count * 0.85)].mean(axis=0)
    detail = profile - np.convolve(profile, np.ones(41) / 41, "same")
    noise = np.median(np.abs(detail)) * 1.4826 + 1e-6
    candidates = []
    for index in range(2, len(detail) - 2):
        if abs(across[index] - centre) > radius:
            continue
        window = detail[max(0, index - 12) : index + 13]
        if detail[index] > 4 * noise and detail[index] == window.max():
            left, mid, right = detail[index - 1], detail[index], detail[index + 1]
            shift = (left - right) / (2 * (left - 2 * mid + right) + 1e-9)
            candidates.append(float(across[index] + shift))
    if not candidates:
        return None
    return min(candidates, key=lambda value: abs(value - centre))


def grow_control(dark: np.ndarray, corners: dict, control: dict) -> dict:
    """Snap printed township corners outward from the committed seed, predicting each from
    the nearest accepted corners so the search never has to span a section (~100 px)."""
    accepted = {
        (corner["range_line"], corner["township_line"]): tuple(map(float, corner["pixel"]))
        for corner in control["seed"]["corners"]
    }
    scale = 1.0 / control["metres_per_pixel_guess"]
    radius = control["search_radius_px"]
    height, width = dark.shape

    def predict(key):
        target = corners[key]
        near = sorted(
            accepted,
            key=lambda other: (
                math.hypot(
                    corners[other]["x"] - target["x"], corners[other]["y"] - target["y"]
                ),
                other,
            ),
        )[:8]
        source = np.array([[corners[k]["x"], corners[k]["y"], 1.0] for k in near])
        if len(near) >= 3 and np.linalg.matrix_rank(source[:, :2] - source[:, :2].mean(0)) == 2:
            pixels = np.array([accepted[k] for k in near])
            solution, *_ = np.linalg.lstsq(source, pixels, rcond=None)
            return np.array([target["x"], target["y"], 1.0]) @ solution
        anchor = near[0]
        if len(near) == 2:
            # Two corners fix scale and rotation; ground y runs opposite to pixel rows.
            a, b = near
            ground = complex(
                corners[b]["x"] - corners[a]["x"], -(corners[b]["y"] - corners[a]["y"])
            )
            pixel = complex(accepted[b][0] - accepted[a][0], accepted[b][1] - accepted[a][1])
            offset = complex(target["x"] - corners[a]["x"], -(target["y"] - corners[a]["y"]))
            moved = offset * (pixel / ground)
            return np.array([accepted[a][0] + moved.real, accepted[a][1] + moved.imag])
        return np.array(
            [
                accepted[anchor][0] + (target["x"] - corners[anchor]["x"]) * scale,
                accepted[anchor][1] - (target["y"] - corners[anchor]["y"]) * scale,
            ]
        )

    while True:
        added = 0
        for key in sorted(corners):
            if key in accepted:
                continue
            neighbours = [
                (key[0] + a, key[1] + b) for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ]
            if not any(n in accepted for n in neighbours):
                continue
            guess = predict(key)
            if not (0 < guess[0] < width and 0 < guess[1] < height):
                continue
            x = nearest_line(dark, guess[0], guess[1], True, radius)
            y = nearest_line(dark, guess[0], guess[1], False, radius)
            if x is None or y is None:
                continue
            x = nearest_line(dark, x, y, True, 8) or x
            y = nearest_line(dark, x, y, False, 8) or y
            if math.hypot(x - guess[0], y - guess[1]) > 40:
                continue
            accepted[key] = (x, y)
            added += 1
        if not added:
            return accepted


def polynomial_terms(points: np.ndarray, centre: np.ndarray, order: int) -> np.ndarray:
    x, y = ((points - centre) / 5000.0).T
    columns = [np.ones_like(x), x, y]
    if order >= 2:
        columns += [x * x, x * y, y * y]
    return np.column_stack(columns)


def fit_control(points: list[dict], order: int) -> dict:
    """Pixel -> EPSG:3310 polynomial with iterative 3-sigma rejection (floor 400 m)."""
    pixels = np.array([[p["pixel_x"], p["pixel_y"]] for p in points])
    ground = np.array([[p["x"], p["y"]] for p in points])
    centre = pixels.mean(axis=0)
    keep = np.ones(len(points), dtype=bool)
    for _ in range(20):
        solution, *_ = np.linalg.lstsq(
            polynomial_terms(pixels[keep], centre, order), ground[keep], rcond=None
        )
        residual = np.hypot(*(polynomial_terms(pixels, centre, order) @ solution - ground).T)
        rms = float(np.sqrt((residual[keep] ** 2).mean()))
        updated = residual < max(3 * rms, 400.0)
        if (updated == keep).all():
            break
        keep = updated
    return {
        "keep": keep,
        "residual_m": residual,
        "rms_m": rms,
        "solution": solution,
        "centre": centre,
        "order": order,
    }


def derive_control(edition: dict, raw_root: Path) -> dict:
    """Regenerate the committed .points file and its report from raw bytes alone."""
    processing = edition["processing"]
    control = processing["control"]
    receipts = load_ledger()
    package = verify_receipt(receipts[processing["download_id"]], raw_root)
    plss_path = verify_receipt(receipts[control["download_id"]], raw_root)
    corners = township_corners(json.loads(plss_path.read_text(encoding="utf-8")))
    dark = ink(member_path(package, processing["member"]))
    accepted = grow_control(dark, corners, control)
    points, excluded = [], []
    for key in sorted(accepted):
        corner = corners[key]
        row = {
            "corner": f"range line {key[0]}, township line {key[1]}",
            "pixel_x": round(accepted[key][0], 2),
            "pixel_y": round(accepted[key][1], 2),
            "lon": round(corner["lon"], 6),
            "lat": round(corner["lat"], 6),
            "x": corner["x"],
            "y": corner["y"],
            "blm_sections": corner["sections"],
            "blm_spread_m": round(corner["spread_m"], 1),
        }
        if (
            corner["spread_m"] > control["max_source_spread_metres"]
            or len(corner["sections"]) < 2
        ):
            excluded.append({**row, "reason": "BLM sections disagree on this corner"})
        else:
            points.append(row)
    fit = fit_control(points, processing["polynomial_order"])
    kept = []
    for row, keep, residual in zip(points, fit["keep"], fit["residual_m"], strict=True):
        row["residual_m"] = round(float(residual), 1)
        if keep:
            kept.append(row)
        else:
            excluded.append({**row, "reason": "residual over max(3 x RMS, 400 m)"})
    residuals = np.array([row["residual_m"] for row in kept])
    final = fit_control(kept, processing["polynomial_order"])
    checkpoints = check_towns(control, receipts, raw_root, final)
    for row in kept + excluded:
        row.pop("x", None)
        row.pop("y", None)
    return {
        "points": kept,
        "excluded": excluded,
        "summary": {
            "polynomial_order": processing["polynomial_order"],
            "control_points": len(kept),
            "rms_m": round(fit["rms_m"], 1),
            "median_m": round(float(np.median(residuals)), 1),
            "max_m": round(float(residuals.max()), 1),
            "checkpoint_max_m": max(point["error_m"] for point in checkpoints),
        },
        "checkpoints": checkpoints,
    }


def check_towns(control: dict, receipts: dict, raw_root: Path, fit: dict) -> list[dict]:
    """Independent of the fit: printed town symbols against GNIS positions."""
    settings = control["checkpoints"]
    path = verify_receipt(receipts[settings["download_id"]], raw_root)
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    places = {item["attributes"]["gaz_name"]: item for item in features}
    forward = Transformer.from_crs(4326, METRIC_EPSG, always_xy=True)
    results = []
    for name, pixel in sorted(settings["pixels"].items()):
        if name not in places:
            demo.fail(f"checkpoint {name} is not in the GNIS response.")
        lon, lat = places[name]["geometry"]["points"][0]
        terms = polynomial_terms(np.array([pixel], dtype=float), fit["centre"], fit["order"])
        x, y = (terms @ fit["solution"])[0]
        gx, gy = forward.transform(lon, lat)
        error = round(math.hypot(x - gx, y - gy), 1)
        results.append(
            {
                "name": name,
                "gnis_id": places[name]["attributes"]["gaz_id"],
                "pixel": pixel,
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "error_m": error,
            }
        )
    worst = max(results, key=lambda item: item["error_m"])
    if worst["error_m"] > settings["max_error_metres"]:
        demo.fail(
            f"checkpoint {worst['name']} is {worst['error_m']:.0f} m off; the control has "
            "probably snapped a corner to the wrong section line."
        )
    return results


def write_points(path: Path, points: list[dict]) -> None:
    """QGIS georeferencer layout; sourceY is negative there by that tool's convention."""
    lines = ["#CRS: EPSG:4326", "mapX,mapY,sourceX,sourceY,enable,dX,dY,residual"]
    for row in points:
        lines.append(
            f"{row['lon']:.6f},{row['lat']:.6f},{row['pixel_x']:.2f},{-row['pixel_y']:.2f},1,0,0,0"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_points(path: Path) -> list[GroundControlPoint]:
    gcps = []
    for line in path.read_text(encoding="utf-8").splitlines()[2:]:
        lon, lat, sx, sy, enable, *_ = line.split(",")
        if enable == "1":
            gcps.append(
                GroundControlPoint(row=-float(sy), col=float(sx), x=float(lon), y=float(lat))
            )
    if len(gcps) < 12:
        demo.fail(
            f"{path.name}: {len(gcps)} control points cannot carry a reviewed polynomial."
        )
    return gcps


def member_path(package: Path, member: str) -> str:
    return f"/vsizip/{package}/{member}"


# --------------------------------------------------------------------------------------
# Rasters
# --------------------------------------------------------------------------------------


def native_zoom(resolution_m: float, latitude: float) -> int:
    """The first zoom whose pixel is no coarser than the source pixel."""
    equator = 2 * math.pi * 6378137 / warp_raster.TILE_SIZE
    return math.ceil(math.log2(equator * math.cos(math.radians(latitude)) / resolution_m))


def ring_wgs84(polygon: Polygon) -> dict:
    polygon = orient(polygon, sign=1.0)
    return {
        "type": "Polygon",
        "coordinates": [[[demo.q6(x), demo.q6(y)] for x, y in polygon.exterior.coords]],
    }


def scan_crop(edition: dict, gcps: list[GroundControlPoint], expected_rms: float) -> dict:
    """The printed neatline, carried to the ground through the same polynomial GDAL uses."""
    processing = edition["processing"]
    corners = processing["neatline_pixels"]
    samples = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1], strict=True):
        for t in np.linspace(0, 1, 32, endpoint=False):
            samples.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    pixels = np.array(samples)
    with rasterio.Env():
        from rasterio.transform import GCPTransformer

        with GCPTransformer(gcps, tps=False) as transformer:
            xs, ys = transformer.xy(pixels[:, 1], pixels[:, 0], offset="ul")
            # GDAL picks the polynomial order from the point count; prove it is the fit.
            gx, gy = transformer.xy([p.row for p in gcps], [p.col for p in gcps], offset="ul")
    forward = Transformer.from_crs(4326, METRIC_EPSG, always_xy=True)
    fitted = np.array(forward.transform(gx, gy))
    truth = np.array(forward.transform([p.x for p in gcps], [p.y for p in gcps]))
    rms = float(np.sqrt((np.hypot(*(fitted - truth)) ** 2).mean()))
    if abs(rms - expected_rms) > 5.0:
        raise WarpError(
            f"GDAL's GCP fit has RMS {rms:.1f} m, not the reviewed {expected_rms} m"
        )
    return ring_wgs84(Polygon(zip(xs, ys, strict=True)))


def warp_scan(edition: dict, package: Path, gcps, grid: dict) -> tuple[np.ndarray, np.ndarray]:
    processing = edition["processing"]
    shape_out = (grid["height"], grid["width"])
    transform = warp_raster.grid_transform(grid)
    with rasterio.open(member_path(package, processing["member"])) as dataset:
        if [dataset.width, dataset.height] != processing["member_pixels"]:
            raise WarpError(f"{processing['member']} is not {processing['member_pixels']} px.")
        source = dataset.read()
    validity = np.zeros(source.shape[1:], dtype="uint8")
    from rasterio.features import rasterize

    validity = rasterize(
        [(mapping(Polygon(processing["neatline_pixels"])), 255)],
        out_shape=validity.shape,
        fill=0,
        dtype="uint8",
    )
    data = np.zeros((source.shape[0], *shape_out), dtype="uint8")
    options = {
        "gcps": gcps,
        "src_crs": "EPSG:4326",
        "dst_transform": transform,
        "dst_crs": f"EPSG:{warp_raster.TILE_CRS_EPSG}",
        "MAX_GCP_ORDER": processing["polynomial_order"],
    }
    for band in range(source.shape[0]):
        reproject(source[band], data[band], resampling=Resampling.nearest, **options)
    coverage = np.zeros(shape_out, dtype="uint8")
    reproject(validity, coverage, resampling=Resampling.nearest, **options)
    return data, coverage


def geotiff_crop(topo_row: dict, view: list[float]) -> dict:
    """The Auburn view, inside the sheet's nominal NAD27 neatline carried to WGS84."""
    west, south, east, north = (float(topo_row[k]) for k in ("west", "south", "east", "north"))
    to_wgs84 = Transformer.from_crs(4267, 4326, always_xy=True)
    edge = Polygon(
        [to_wgs84.transform(x, y) for x, y in box(west, south, east, north).exterior.coords]
    )
    clipped = edge.intersection(box(*view))
    if clipped.area < box(*view).area * demo.MIN_VIEW_COVERAGE:
        raise WarpError(
            "the sheet maps too little of the Auburn view for a view-cropped edition"
        )
    return ring_wgs84(clipped)


def process(
    edition: dict,
    catalog: dict,
    raw_root: Path,
    view: list[float],
    tile_min: int,
    staging: Path,
) -> dict:
    eid = edition["id"]
    processing = edition["processing"]
    top = edition["native_max_zoom"]
    centre_lat = (view[1] + view[3]) / 2
    if native_zoom(edition["native_resolution_metres"], centre_lat) != top:
        raise WarpError(f"native_max_zoom {top} does not follow from the source pixel size")
    zooms = list(range(tile_min, top + 1))
    entry = {
        "id": eid,
        "source_id": edition["source_id"],
        "method": processing["method"],
        "resampling": processing["resampling"],
    }
    if processing["method"] == "gcp_polynomial":
        receipts = load_ledger()
        package = verify_receipt(receipts[processing["download_id"]], raw_root)
        points_path = REPO_ROOT / processing["control"]["points_path"]
        gcps = read_points(points_path)
        report = demo.read_json(REPO_ROOT / processing["control"]["report_path"])
        crop = scan_crop(edition, gcps, report["summary"]["rms_m"])
        grid = warp_raster.common_grid(list(shape(crop).bounds), top)
        data, coverage = warp_scan(edition, package, gcps, grid)
        entry["source"] = {
            "download_id": processing["download_id"],
            "sha256": receipts[processing["download_id"]]["sha256"],
            "member": processing["member"],
            "points_sha256": warp_raster.sha256_file(points_path)[0],
        }
        entry["registration"] = report["summary"]
    else:
        rows = {
            row["topo_id"]: row for row in csv.DictReader(INDEX_PATH.open(encoding="utf-8"))
        }
        row = rows[processing["topo_id"]]
        check_index_dates(edition, row)
        record = topo_receipts().get(processing["topo_id"])
        if record is None:
            raise WarpError(f"{processing['topo_id']} has no receipt in {RECEIPTS_PATH.name}")
        check_record(record, raw_root)
        crop = geotiff_crop(row, view)
        grid = warp_raster.common_grid(list(shape(crop).bounds), top)
        source_path = raw_root / record["raw_path"]
        with warp_raster.open_source(source_path) as dataset:
            operation = warp_raster.select_operation(
                CRS.from_user_input(dataset.crs), tuple(view), []
            )
            data, coverage = warp_raster.warp(
                dataset, grid, processing["resampling"], operation["pipeline"]
            )
        entry["source"] = {"topo_id": processing["topo_id"], "sha256": record["sha256"]}
        entry["datum_transformation"] = {
            key: operation[key] for key in ("description", "accuracy_metres")
        }
    alpha = np.where(coverage > 0, warp_raster.crop_mask(crop, grid), 0).astype("uint8")
    if not alpha.any():
        raise WarpError("nothing of the source lands inside its crop")
    data[:, alpha == 0] = 0
    cog = staging / RASTER_DIRNAME / f"{eid}.tif"
    warp_raster.write_cog(cog, data, alpha, grid, processing["resampling"])
    digest, byte_count = warp_raster.sha256_file(cog)
    tiles = staging / TILE_DIRNAME / eid
    cut = warp_raster.cut_pyramid(cog, grid, zooms, processing["resampling"], tiles)
    samples = warp_raster.verify_tile_samples(
        cog, tiles, grid, top, demo.sample_points(shape(crop))
    )
    if not all(sample["opaque"] for sample in samples):
        raise WarpError("a sample point inside the crop is transparent in its tile")
    tile_digest, tile_count, tile_bytes = warp_raster.pyramid_digest(tiles)
    entry.update(
        {
            "crop_wgs84": crop,
            "coverage_bounds_wgs84": [demo.q6(v) for v in shape(crop).bounds],
            "grid": grid,
            "output": {
                "path": f"{RASTER_DIRNAME}/{eid}.tif",
                "sha256": digest,
                "byte_count": byte_count,
            },
            "tiles": {
                "path": f"{TILE_DIRNAME}/{eid}",
                "digest": tile_digest,
                "tiles": tile_count,
                "bytes": tile_bytes,
                "transparent_tiles": cut.get("transparent_tiles", 0),
                "sample_points": samples,
            },
            "zoom": {"min": zooms[0], "max": top},
        }
    )
    return entry


def topo_receipts() -> dict[str, dict]:
    return {record["topo_id"]: record for record in load_receipts(RECEIPTS_PATH)}


def check_index_dates(edition: dict, row: dict) -> None:
    """Card dates must be the index's, not retyped guesses."""

    def year(column):
        return int(row[column]) if row[column] else None

    dates, components = edition["dates"], edition["component_dates"]
    expected = {
        "map_year": year("date_on_map"),
        "base_photography": row["aerial_photo_year"] or None,
        "survey_year": year("survey_year"),
        "edit_year": year("edit_year"),
        "imprint_year": year("imprint_year"),
    }
    actual = {
        "map_year": dates["map_year"],
        "base_photography": dates["base_photography"],
        **{key: components[key] for key in ("survey_year", "edit_year", "imprint_year")},
    }
    if actual != expected:
        raise WarpError(f"card dates {actual} disagree with topo_index.csv {expected}")
    if int(row["scale"]) != edition["scale"] or edition["source_url"] != row["sciencebase_url"]:
        raise WarpError("scale or source_url disagrees with topo_index.csv")


def run_rasters(raw_root: Path, extra_root: Path = EXTRA_ROOT) -> dict:
    catalog = load_catalog()
    nine = demo.read_json(NINE_MANIFEST_PATH)
    view, tile_min = nine["view_bounds_wgs84"], nine["tile_zoom"]["min"]
    warp_raster.require_gdal()
    staging = extra_root / INCOMING_DIRNAME
    shutil.rmtree(staging, ignore_errors=True)
    previous = {}
    if (extra_root / RECORD_NAME).is_file():
        previous = {e["id"]: e for e in demo.read_json(extra_root / RECORD_NAME)["editions"]}
    versions = warp_raster.tool_versions()
    entries = []
    try:
        for edition in catalog["editions"]:
            eid = edition["id"]
            verify_inputs(edition, raw_root)
            fingerprint = input_fingerprint(edition, view, tile_min, versions)
            prior = previous.get(eid)
            if (
                prior
                and prior.get("fingerprint") == fingerprint
                and unchanged(prior, extra_root)
            ):
                (staging / RASTER_DIRNAME).mkdir(parents=True, exist_ok=True)
                shutil.copy2(
                    extra_root / prior["output"]["path"], staging / prior["output"]["path"]
                )
                shutil.copytree(
                    extra_root / prior["tiles"]["path"], staging / prior["tiles"]["path"]
                )
                entries.append(prior)
                continue
            try:
                entry = process(edition, catalog, raw_root, view, tile_min, staging)
            except WarpError as exc:
                demo.fail(f"{eid}: {exc}")
            entries.append({**entry, "fingerprint": fingerprint})
        # Nothing replaces the previous output until every edition is cut and checked.
        for dirname in (RASTER_DIRNAME, TILE_DIRNAME):
            shutil.rmtree(extra_root / dirname, ignore_errors=True)
            os.replace(staging / dirname, extra_root / dirname)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    record = {
        "version": 1,
        "published_order": catalog["published_order"],
        "view_bounds_wgs84": view,
        "tool_versions": versions,
        "editions": entries,
        "notes": {
            "inspection": "automated only; no human map review is asserted here",
            "registration": (
                "georeferenced GeoTIFFs keep their own georeferencing; the scanned sheet is "
                "placed by a polynomial through committed control points, and its residuals "
                "are published on its card"
            ),
        },
    }
    demo.write_record(extra_root / RECORD_NAME, record)
    return record


def verify_inputs(edition: dict, raw_root: Path) -> None:
    """Raw bytes are checked on every run, reused output or not (AGENTS.md 2.2)."""
    processing = edition["processing"]
    if processing["method"] == "gcp_polynomial":
        receipts = load_ledger()
        for key in (processing["download_id"], processing["control"]["download_id"]):
            verify_receipt(receipts[key], raw_root)
    else:
        check_record(topo_receipts()[processing["topo_id"]], raw_root)


def input_fingerprint(edition: dict, view: list, tile_min: int, versions: dict) -> str:
    processing = edition["processing"]
    files = {}
    if processing["method"] == "gcp_polynomial":
        for key in ("points_path", "report_path"):
            files[key] = warp_raster.sha256_file(REPO_ROOT / processing["control"][key])[0]
        files["package"] = load_ledger()[processing["download_id"]]["sha256"]
    else:
        files["source"] = topo_receipts()[processing["topo_id"]]["sha256"]
    return warp_raster.fingerprint(
        {
            "edition": edition,
            "view": view,
            "tile_min": tile_min,
            "versions": versions,
            "processing_version": warp_raster.PROCESSING_VERSION,
            "tiling_version": warp_raster.TILING_VERSION,
            "files": files,
        }
    )


def unchanged(entry: dict, root: Path) -> bool:
    cog, tiles = root / entry["output"]["path"], root / entry["tiles"]["path"]
    if not cog.is_file() or not tiles.is_dir():
        return False
    if warp_raster.sha256_file(cog) != (
        entry["output"]["sha256"],
        entry["output"]["byte_count"],
    ):
        return False
    digest = warp_raster.pyramid_digest(tiles)
    return digest == (
        entry["tiles"]["digest"],
        entry["tiles"]["tiles"],
        entry["tiles"]["bytes"],
    )


def registration_note(summary: dict) -> str:
    return (
        f"Placed by a second-order polynomial through {summary['control_points']} printed "
        f"township corners matched to BLM PLSS corners. The fit is off by about "
        f"{round(summary['rms_m'], -1):.0f} m on average and up to "
        f"{round(summary['max_m'], -1):.0f} m at a control corner, so features here can sit "
        "hundreds of metres from where the other maps put them."
    )


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def raw_root_option():
    return click.option(
        "--raw-root",
        type=click.Path(path_type=Path),
        default=lambda: Path(os.environ.get("DEMO_RAW_ROOT", REPO_ROOT / "data/raw")),
        show_default="DEMO_RAW_ROOT or data/raw",
    )


@click.group()
def cli() -> None:
    """Extra map options beyond the nine editions (scans and further USGS sheets)."""


@cli.command()
@raw_root_option()
def fetch(raw_root: Path) -> None:
    """Download each catalogued package once and record a receipt; reruns verify only."""
    for entry in load_catalog()["downloads"]:
        record, fetched = fetch_download(entry, raw_root)
        state = "fetched" if fetched else "verified"
        digest = record["sha256"][:12]
        click.echo(f"{entry['download_id']}: {state} {record['size_bytes']} bytes {digest}")


@cli.command()
@raw_root_option()
def control(raw_root: Path) -> None:
    """Regenerate each scan's .points file and control report from the raw inputs."""
    for edition in load_catalog()["editions"]:
        if edition["processing"]["method"] != "gcp_polynomial":
            continue
        derived = derive_control(edition, raw_root)
        settings = edition["processing"]["control"]
        write_points(REPO_ROOT / settings["points_path"], derived["points"])
        report = {
            "version": 1,
            "edition_id": edition["id"],
            "member": edition["processing"]["member"],
            "control_source": settings["download_id"],
            "seed": settings["seed"],
            "method": (
                "Township corners grown outward from the seed; each is the crossing of the "
                "nearest long printed lines to a prediction from accepted neighbours. Corners "
                "whose BLM sections disagree are excluded, then a polynomial fit rejects "
                "residual outliers."
            ),
            **derived,
        }
        path = REPO_ROOT / settings["report_path"]
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        click.echo(f"{edition['id']}: {derived['summary']}")


@cli.command()
@raw_root_option()
def check(raw_root: Path) -> None:
    """Verify catalog, receipts and raw bytes without writing anything."""
    catalog = load_catalog()
    receipts = load_ledger()
    for entry in catalog["downloads"]:
        if entry["download_id"] not in receipts:
            demo.fail(f"{entry['download_id']}: no receipt; run make extra-fetch.")
        verify_receipt(receipts[entry["download_id"]], raw_root)
    topo = topo_receipts()
    for edition in catalog["editions"]:
        topo_id = edition["processing"].get("topo_id")
        if topo_id:
            check_record(topo[topo_id], raw_root)
    click.echo(f"extra-check: {len(catalog['editions'])} editions, sources verified.")


@cli.command()
@raw_root_option()
def rasters(raw_root: Path) -> None:
    """Warp and tile every extra edition into build/extra/."""
    record = run_rasters(raw_root)
    for entry in record["editions"]:
        tiles = entry["tiles"]
        click.echo(
            f"{entry['id']}: zoom {entry['zoom']['min']}-{entry['zoom']['max']}, "
            f"{tiles['tiles']} tiles, {tiles['bytes']} bytes"
        )


if __name__ == "__main__":
    cli()
