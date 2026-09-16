#!/usr/bin/env python3
"""USGS Historical Topographic Maps -> data/sources/topo_index.csv -> data/raw/topo/.

  fetch-topo index     query the TNM Access API over the acquisition AOI, harvest each
                       sheet's FGDC metadata, write data/sources/topo_index.csv
  fetch-topo download  pull the GeoTIFFs named in the index into data/raw/topo/
  fetch-topo docs      regenerate docs/topo-editions.md from the index

The index covers both Nevada and Placer Counties. The optional `in_tier1` column
and `download --tier1` filter retain the legacy corridor work area; they do not
restrict the project scope. Pre-1950 sheets are retained as background sources.

WHY THE METADATA HARVEST MATTERS. The TNM Access API dates a sheet by one year, and
that year does not resolve each feature's observation date. Scans of "Auburn, CA 1953"
include different revisions:
one is a 1961 imprint drawn from 1952 aerials, another is a 1981 imprint photo-revised
from 1978 aerials. They carry the same title and the same publicationDate. A trail that
appears only on the second must be dated from the relevant source evidence, not
automatically assigned to the map's printed year.

Every sheet's FGDC record carries the distinguishing dates as lineage process steps —
Date on Map, Imprint Year, Aerial Photo Year, Field Check Year, Photo Revision Year,
Edit Year — so the index harvests them and M3 can date an observation from the right
one. `date_on_map` is the sheet's nominal date. `content_year` is the maximum of
the map, aerial-photo, photo-revision, and field-check years: a sorting aid, not an
observation date for a trail. Both are recorded for human review.

Metadata URLs come from the API's `vendorMetaUrl` and are never constructed from the
filename — the naming is not consistent enough across scales to guess, and a guessed
URL that 404s silently would drop the dates that make the sheet usable.

Sheets are public domain (US federal government work); the FGDC `useconst` field reads
"None". They may be redistributed as tile layers (AGENTS.md 2.7).

IMPORTANT: a topo sheet is an observation, not an alignment. Downloading one asserts
nothing. What a sheet shows becomes evidence only when a human traces it in M3 and
writes a support row citing it.
"""

from __future__ import annotations

import csv
import http.client
import itertools
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import click
import rasterio
from shapely.geometry import box, shape

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
RAW_TOPO_DIR = REPO_ROOT / "data" / "raw" / "topo"
DOCS_DIR = REPO_ROOT / "docs"
INDEX_PATH = SOURCES_DIR / "topo_index.csv"
EDITIONS_DOC = DOCS_DIR / "topo-editions.md"

TNM_PRODUCTS = "https://tnmaccess.nationalmap.gov/api/v1/products"
TNM_DATASET = "Historical Topographic Maps"
TNM_PAGE = 1000
USER_AGENT = "foothill-trail-atlas/0.0 (OTCA historical trail mapping; contact via repo)"

# The API's sizeInBytes disagrees with the served object by a byte or two on some
# sheets — five of the 91 Tier 1 sheets, reproducibly, always by exactly one. It is
# recorded metadata, not a checksum, so it is advisory only: completeness is decided by
# the response's own Content-Length, and this tolerance keeps a good sheet from being
# discarded over a stale byte count.
SIZE_TOLERANCE = 16

# CA_Auburn_302316_1953_24000_geo.tif -> state, map name, scan id, year, scale.
FILENAME_RE = re.compile(r"^([A-Z]{2})_(.+)_(\d+)_(\d{4})_(\d+)_geo\.tif$", re.IGNORECASE)

# FGDC lineage process steps that carry a date rather than a description of work.
YEAR_STEPS = {
    "Date on Map": "date_on_map",
    "Imprint Year": "imprint_year",
    "Aerial Photo Year": "aerial_photo_year",
    "Field Check Year": "field_check_year",
    "Photo Revision Year": "photo_revision_year",
    "Edit Year": "edit_year",
    "Photo Inspection Year": "photo_inspection_year",
    "Survey Year": "survey_year",
}

COLUMNS = [
    "topo_id",
    "map_name",
    "scale",
    "extent",
    "date_on_map",
    "content_year",
    "imprint_year",
    "aerial_photo_year",
    "photo_revision_year",
    "field_check_year",
    "edit_year",
    "photo_inspection_year",
    "survey_year",
    "woodland_tint",
    "scanner_resolution",
    "datum",
    "projection",
    "west",
    "south",
    "east",
    "north",
    "in_tier1",
    "size_bytes",
    "rights",
    "geotiff_url",
    "metadata_url",
    "sciencebase_url",
    "source_id",
]


def get(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def load_aoi(name: str):
    path = SOURCES_DIR / name
    if not path.exists():
        click.echo(
            f"fetch-topo: {path.relative_to(REPO_ROOT)} is missing. "
            "Run 'make fetch-aoi' first.",
            err=True,
        )
        sys.exit(1)
    return shape(json.loads(path.read_text(encoding="utf-8"))["features"][0]["geometry"])


def footprint(item: dict):
    b = item.get("boundingBox") or {}
    try:
        return box(b["minX"], b["minY"], b["maxX"], b["maxY"])
    except KeyError:
        return None


def query_products(bounds, timeout: int) -> list[dict]:
    """Page the whole result set. The API caps a page at TNM_PAGE items."""
    items: list[dict] = []
    offset = 0
    while True:
        params = {
            "datasets": TNM_DATASET,
            "bbox": ",".join(f"{v:.6f}" for v in bounds),
            "prodFormats": "GeoTIFF",
            "max": TNM_PAGE,
            "offset": offset,
            "outputFormat": "JSON",
        }
        payload = json.loads(get(f"{TNM_PRODUCTS}?{urllib.parse.urlencode(params)}", timeout))
        page = payload.get("items")
        total = payload.get("total")
        if not isinstance(page, list) or not isinstance(total, int) or total < 0:
            raise click.ClickException(
                "TNM response has no valid items/total; index unchanged."
            )
        if not page and offset < total:
            raise click.ClickException("TNM pagination ended early; index unchanged.")
        items.extend(page)
        click.echo(f"  fetched {len(items)}/{total}")
        offset += len(page)
        if not page or offset >= total:
            return items


def parse_metadata(blob: bytes) -> dict:
    """Pull the lineage year steps and scan notes out of one FGDC record."""
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(blob)
    except ET.ParseError as exc:
        raise ValueError("Invalid FGDC XML") from exc
    if root.tag != "metadata":
        raise ValueError("Response is not an FGDC metadata record")

    for step in root.iter("procstep"):
        column = YEAR_STEPS.get((step.findtext("procdesc") or "").strip())
        if column:
            out[column] = (step.findtext("procdate") or "").strip()

    # supplinf is a semicolon-delimited "Key: value" run with a JSON tail appended.
    supplinf = root.findtext(".//supplinf") or ""
    for chunk in supplinf.split(";"):
        key, _, value = chunk.partition(":")
        key, value = key.strip(), value.strip()
        if key == "Woodland Tint":
            out["woodland_tint"] = value
        elif key == "Scanner Resolution":
            out["scanner_resolution"] = value

    out["datum"] = (root.findtext(".//horizdn") or "").strip()
    out["projection"] = (root.findtext(".//mapprojn") or "").strip()
    return out


def content_year(row: dict) -> str:
    """Latest selected lineage year, for sorting; not a feature observation date."""
    years = [
        row.get(key)
        for key in (
            "date_on_map",
            "photo_revision_year",
            "aerial_photo_year",
            "field_check_year",
        )
    ]
    numeric = [int(y) for y in years if y and re.fullmatch(r"\d{4}", y)]
    return str(max(numeric)) if numeric else ""


def build_row(item: dict, tier1) -> dict | None:
    url = (item.get("urls") or {}).get("GeoTIFF")
    if not url:
        return None
    match = FILENAME_RE.match(url.rsplit("/", 1)[-1])
    if not match:
        click.echo(f"  skipping unparseable filename: {url.rsplit('/', 1)[-1]}", err=True)
        return None
    state, raw_name, scan_id, year, scale = match.groups()
    name = urllib.parse.unquote(raw_name).replace("_", " ")
    poly = footprint(item)
    return {
        # Percent-decoded, so the local filename is "CA_Lake_Combie_..." rather than
        # the upstream "CA_Lake%20Combie_...". A literal % in a path is a hazard for
        # the GDAL command lines M2 builds; geotiff_url keeps the real URL.
        "topo_id": f"{state}_{name.replace(' ', '_')}_{scan_id}_{year}_{scale}",
        "map_name": name,
        "scale": scale,
        "extent": item.get("extent", ""),
        "date_on_map": year,
        "west": poly.bounds[0] if poly else "",
        "south": poly.bounds[1] if poly else "",
        "east": poly.bounds[2] if poly else "",
        "north": poly.bounds[3] if poly else "",
        "in_tier1": "true" if poly is not None and poly.intersects(tier1) else "false",
        "size_bytes": item.get("sizeInBytes") or "",
        # US federal government work; the FGDC useconst field reads "None".
        "rights": "public_domain",
        "geotiff_url": url,
        "metadata_url": item.get("vendorMetaUrl") or "",
        "sciencebase_url": item.get("metaUrl") or "",
        "source_id": item.get("sourceId") or scan_id,
    }


def read_index(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise click.ClickException(f"Unexpected index columns in {path}")
        rows = {}
        for row in reader:
            topo_id = row["topo_id"]
            if not topo_id or topo_id in {".", ".."} or "/" in topo_id or "\\" in topo_id:
                raise click.ClickException(f"Unsafe topo_id in {path}")
            if topo_id in rows:
                raise click.ClickException(f"Duplicate topo_id {topo_id} in {path}")
            if None in row or any(value is None for value in row.values()):
                raise click.ClickException(f"Malformed index row {topo_id} in {path}")
            rows[topo_id] = row
        return rows


def sort_key(row: dict) -> tuple:
    return (int(row["scale"]), row["map_name"], row["date_on_map"], row["topo_id"])


@click.group()
def cli() -> None:
    """Index and download USGS historical topographic sheets."""


@cli.command(name="index")
@click.option("--timeout", default=120, show_default=True)
@click.option(
    "--refresh",
    is_flag=True,
    help="Re-harvest FGDC metadata for sheets already in the index.",
)
@click.option(
    "--workers",
    type=click.IntRange(min=1),
    default=4,
    show_default=True,
    help="Concurrent metadata fetches.",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=INDEX_PATH,
)
def index_cmd(timeout: int, refresh: bool, workers: int, out: Path) -> None:
    """Query the TNM Access API over the acquisition AOI and write the index."""
    counties = load_aoi("aoi_counties.geojson")
    tier1 = load_aoi("aoi_tier1.geojson")

    click.echo("fetch-topo index: querying TNM Access API over the acquisition AOI…")
    items = query_products(counties.bounds, timeout)

    # The API filters on the AOI's bounding box, which over two irregular counties pulls
    # in sheets that touch the box but not the counties. Re-test against the polygon.
    kept = []
    for item in items:
        poly = footprint(item)
        if poly is None:
            raise click.ClickException("A product has no footprint; index unchanged.")
        if poly.intersects(counties):
            kept.append(item)
    if not kept:
        raise click.ClickException("No usable countywide sheets returned; index unchanged.")
    click.echo(f"  {len(items)} sheets in the bbox, {len(kept)} intersect the counties")

    rows: dict[str, dict] = {}
    for item in kept:
        row = build_row(item, tier1)
        if row is None:
            raise click.ClickException(
                "A countywide product could not be indexed; index unchanged."
            )
        if row["topo_id"] in rows:
            raise click.ClickException("Duplicate TNM product; index unchanged.")
        rows[row["topo_id"]] = row

    existing = read_index(out)
    todo = [
        row
        for row in rows.values()
        if row["metadata_url"]
        and (
            refresh
            or row["topo_id"] not in existing
            or existing[row["topo_id"]].get("metadata_url") != row["metadata_url"]
            or not existing[row["topo_id"]].get("datum")
        )
    ]
    # Carry forward harvested metadata so a re-run does not re-fetch 600 XML records.
    for topo_id, row in rows.items():
        prior = existing.get(topo_id)
        if prior and not refresh and prior.get("metadata_url") == row["metadata_url"]:
            for column in (
                *YEAR_STEPS.values(),
                "woodland_tint",
                "scanner_resolution",
                "datum",
                "projection",
            ):
                if prior.get(column):
                    row[column] = prior[column]

    if todo:
        click.echo(f"  harvesting FGDC metadata for {len(todo)} sheets…")

        def harvest(row: dict) -> bool:
            try:
                row.update(parse_metadata(get(row["metadata_url"], timeout)))
                return True
            except (
                urllib.error.URLError,
                http.client.HTTPException,
                TimeoutError,
                OSError,
                ValueError,
            ):
                return False

        with ThreadPoolExecutor(max_workers=workers) as pool:
            failed = sum(1 for ok in pool.map(harvest, todo) if not ok)
        if failed:
            raise click.ClickException(
                f"{failed}/{len(todo)} metadata records failed; index unchanged. "
                "Re-run to retry."
            )
    else:
        click.echo("  metadata already harvested for every sheet")

    for row in rows.values():
        row["content_year"] = content_year(row)

    ordered = sorted(rows.values(), key=sort_key)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=out.parent,
        delete=False,
    ) as handle:
        staged = Path(handle.name)
        try:
            writer = csv.DictWriter(
                handle,
                fieldnames=COLUMNS,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in ordered:
                writer.writerow({column: row.get(column, "") for column in COLUMNS})
            handle.flush()
            staged.replace(out)
        finally:
            staged.unlink(missing_ok=True)

    tier1_rows = [r for r in ordered if r["in_tier1"] == "true"]
    total = sum(int(r["size_bytes"]) for r in ordered if str(r["size_bytes"]).isdigit())
    t1_total = sum(int(r["size_bytes"]) for r in tier1_rows if str(r["size_bytes"]).isdigit())
    click.echo(
        f"  wrote {out} — {len(ordered)} sheets "
        f"({total / 1e9:.1f} GB), {len(tier1_rows)} in legacy work area "
        f"({t1_total / 1e9:.1f} GB)"
    )
    revised = sum(
        1 for r in ordered if r.get("content_year") and r["content_year"] != r["date_on_map"]
    )
    click.echo(f"  {revised} sheets have lineage years later than their printed date")


@cli.command()
@click.option(
    "--tier1",
    "tier1_only",
    is_flag=True,
    help="Only sheets covering the legacy corridor work area.",
)
@click.option("--scale", multiple=True, help="Restrict to these scales, e.g. --scale 24000.")
@click.option("--dry-run", is_flag=True, help="Report what would be fetched, download nothing.")
@click.option(
    "--workers",
    type=click.IntRange(min=1),
    default=6,
    show_default=True,
    help="Concurrent downloads.",
)
@click.option("--timeout", default=600, show_default=True)
@click.option(
    "--index",
    "index_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=INDEX_PATH,
)
@click.option(
    "--dest",
    type=click.Path(file_okay=False, path_type=Path),
    default=RAW_TOPO_DIR,
)
def download(
    tier1_only: bool,
    scale: tuple[str, ...],
    dry_run: bool,
    workers: int,
    timeout: int,
    index_path: Path,
    dest: Path,
) -> None:
    """Download indexed GeoTIFFs into data/raw/topo/ (append-only, never overwritten)."""
    rows = list(read_index(index_path).values())
    if not rows:
        click.echo(
            f"fetch-topo download: {index_path} is empty or missing. "
            "Run 'fetch_topoview.py index' first.",
            err=True,
        )
        sys.exit(1)

    if tier1_only:
        rows = [r for r in rows if r["in_tier1"] == "true"]
    if scale:
        rows = [r for r in rows if r["scale"] in scale]
    rows.sort(key=sort_key)

    pending, have = [], 0
    for row in rows:
        target = dest / f"{row['topo_id']}_geo.tif"
        expected = int(row["size_bytes"]) if str(row["size_bytes"]).isdigit() else None
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or target.stat().st_size == 0:
                raise click.ClickException(
                    f"Existing target needs review; left unchanged: {target}"
                )
            if expected is not None and abs(target.stat().st_size - expected) > SIZE_TOLERANCE:
                raise click.ClickException(
                    f"Existing TIFF differs from index; left unchanged: {target}. "
                    "Check the source metadata and file before retrying."
                )
            have += 1
            continue
        pending.append((row, target, expected))

    todo_bytes = sum(e for _, _, e in pending if e)
    click.echo(
        f"fetch-topo download: {len(rows)} sheets selected, {have} already present, "
        f"{len(pending)} to fetch ({todo_bytes / 1e9:.1f} GB)"
    )
    if dry_run or not pending:
        return
    dest.mkdir(parents=True, exist_ok=True)

    counter = itertools.count(1)
    lock = threading.Lock()

    def fetch(job: tuple) -> bool:
        row, target, expected = job
        part = None
        try:
            request = urllib.request.Request(
                row["geotiff_url"], headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                declared = response.headers.get("Content-Length")
                served = int(declared) if declared and declared.isdigit() else None
                with tempfile.NamedTemporaryFile(
                    dir=dest, suffix=".part", delete=False
                ) as handle:
                    part = Path(handle.name)
                    shutil.copyfileobj(response, handle, length=1 << 20)
            size = part.stat().st_size
            if served is not None and size != served:
                raise ValueError(f"Truncated response: wrote {size} of {served} bytes")
            if served is None and (expected is None or abs(size - expected) > SIZE_TOLERANCE):
                raise ValueError("Cannot confirm download length")
            with part.open("rb") as handle:
                if handle.read(4) not in {b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"}:
                    raise ValueError("Response is not a TIFF")
            with rasterio.open(part) as dataset:
                if not dataset.crs or dataset.count < 1:
                    raise ValueError("Response is not a georeferenced raster")
            os.link(part, target)
        except (
            urllib.error.URLError,
            http.client.IncompleteRead,
            rasterio.errors.RasterioError,
            TimeoutError,
            OSError,
            ValueError,
        ) as exc:
            with lock:
                click.echo(f"  failed {target.name}: {exc}", err=True)
            return False
        finally:
            if part is not None:
                part.unlink(missing_ok=True)
        if expected is not None and abs(size - expected) > SIZE_TOLERANCE:
            with lock:
                click.echo(
                    f"  note {target.name}: {size} bytes, index says {expected}. Kept — "
                    "the server's Content-Length was satisfied. Re-run 'index --refresh'.",
                    err=True,
                )

        with lock:
            click.echo(
                f"  [{next(counter)}/{len(pending)}] {target.name} ({size / 1e6:.0f} MB)"
            )
        return True

    with ThreadPoolExecutor(max_workers=workers) as pool:
        failed = sum(1 for ok in pool.map(fetch, pending) if not ok)
    if failed:
        click.echo(
            f"fetch-topo download: {failed}/{len(pending)} sheets failed. "
            "Re-run to retry; sheets already present are skipped.",
            err=True,
        )
        sys.exit(1)


@cli.command(name="docs")
@click.option(
    "--index",
    "index_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=INDEX_PATH,
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=EDITIONS_DOC,
)
def docs_cmd(index_path: Path, out: Path) -> None:
    """Regenerate docs/topo-editions.md from the index."""
    rows = sorted(read_index(index_path).values(), key=sort_key)
    if not rows:
        click.echo(f"fetch-topo docs: {index_path} is empty or missing.", err=True)
        sys.exit(1)

    by_scale: dict[str, list[dict]] = {}
    for row in rows:
        by_scale.setdefault(row["scale"], []).append(row)

    def gb(subset: list[dict]) -> float:
        return sum(int(r["size_bytes"]) for r in subset if str(r["size_bytes"]).isdigit()) / 1e9

    lines = [
        "# USGS historical topographic editions",
        "",
        "<!-- Generated by `scripts/fetch_topoview.py docs`. Do not edit by hand; edit",
        "     the script or `data/sources/topo_index.csv` and regenerate with",
        "     `make topo-docs`. -->",
        "",
        "Every USGS historical topographic sheet whose footprint intersects the acquisition",
        "AOI (`data/sources/aoi_counties.geojson`), from the TNM Access API. The machine-",
        "readable form with full metadata is `data/sources/topo_index.csv`. Narrative and",
        "rights for this source live in `docs/sources.md`.",
        "",
        "All sheets are public domain (US federal government work) and may be published as",
        "tile layers with USGS attribution (AGENTS.md §2.7).",
        "",
        "## Reading the dates",
        "",
        "**`Date on map` is not when the sheet depicts.** USGS reprinted and photo-revised a",
        "quadrangle for decades without changing its printed date, so several scans share one",
        "date and show different ground. `Content year` is the maximum of the map date,",
        "photo-revision, aerial-photo, and field-check years. It is a sorting aid, not an",
        "observation date for every feature. Inspect the base and revision and retain",
        "uncertainty when dating a trail. Do not date an observation from the title alone.",
        "",
        "The study period is 1950 to the present across both counties. This inventory also",
        "retains pre-1950 background sheets; their presence does not establish later trail",
        "extent. Historical sheets alone do not supply coverage through the present.",
        "",
        "## Coverage over the acquisition AOI",
        "",
        "| Scale | Sheets | Size | Earliest | Latest |",
        "| --- | --- | --- | --- | --- |",
    ]
    for scale in sorted(by_scale, key=int):
        subset = by_scale[scale]
        years = sorted(r["date_on_map"] for r in subset if r["date_on_map"])
        lines.append(
            f"| 1:{int(scale):,} | {len(subset)} | {gb(subset):.1f} GB | "
            f"{years[0] if years else '?'} | {years[-1] if years else '?'} |"
        )
    lines.append(f"| **total** | **{len(rows)}** | **{gb(rows):.1f} GB** | | |")

    lines += [
        "",
        f"## Countywide editions — {len(rows)} sheets, {gb(rows):.1f} GB",
        "",
        "All indexed sheets intersect the countywide project boundary. The CSV retains",
        "`in_tier1` for the optional legacy work area; it does not limit digitizing.",
        "Use `make topo-plan` to preview pending downloads without fetching rasters.",
        "",
        "| Scale | Quad | Date on map | Content year | Imprint | Photo rev. | Aerial "
        "| Woodland | GeoTIFF |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        flag = "" if row["content_year"] == row["date_on_map"] else " ⚠"
        lines.append(
            f"| 1:{int(row['scale']):,} | {row['map_name']} | {row['date_on_map']} | "
            f"{row['content_year']}{flag} | {row['imprint_year'] or '—'} | "
            f"{row['photo_revision_year'] or '—'} | {row['aerial_photo_year'] or '—'} | "
            f"{row['woodland_tint'] or '—'} | [tif]({row['geotiff_url']}) |"
        )
    lines += [
        "",
        "⚠ marks a sheet whose selected lineage year is later than its printed date.",
        "",
        f"Generated {date.today().isoformat()} from `data/sources/topo_index.csv`.",
        "",
    ]

    # Keep the previous stamp when nothing but the stamp would change, so re-running
    # the target does not churn the file in git (same rule as fetch_aoi.py).
    body = "\n".join(lines[:-2])
    if out.exists():
        prior = out.read_text(encoding="utf-8")
        if prior.startswith(body):
            click.echo(f"  {out.name} already current, unchanged")
            return

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"  wrote {out} — {len(rows)} countywide editions listed")


if __name__ == "__main__":
    cli()
