#!/usr/bin/env python3
"""Build the two AOIs from online sources. Nothing here is hand-drawn.

  fetch-aoi counties  -> data/sources/aoi_counties.geojson
      Placer + Nevada County, dissolved. The acquisition envelope: it bounds
      `make fetch-topo` and `make rasters`. Census TIGERweb, Census 2020 vintage.

  fetch-aoi tier1     -> data/sources/aoi_tier1.geojson
      Bear River Canal corridor, Crother Rd to Placer Hills Rd, plus the Bowman
      feeder. The digitizing bound (README §2). Derived from OpenStreetMap.

Both are written in EPSG:4326 truncated to 6 decimal places (AGENTS.md §3), and both
are idempotent: if the freshly built geometry matches what is committed, the file is
left alone so its retrieval date does not churn in git on every run.

Both sources are pinned to a fixed vintage rather than a rolling "current" view, so a
re-run reproduces the same geometry instead of drifting silently.

IMPORTANT: these files are scoping boundaries, not evidence. In particular the Tier 1
AOI is derived from OSM, which is not an authoritative record of historical trail
extent. An OSM way must never become an alignment in data/authoritative/ — alignments
come from cited observations only (AGENTS.md §2.1). This file decides *where we look*,
never *what is true*.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import click
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import linemerge, substring, transform, unary_union

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
COORD_DECIMALS = 6

# --- counties ---------------------------------------------------------------------
TIGERWEB = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer"
)
COUNTIES_LAYER = 55  # "Counties" under the Census 2020 group — pinned, archival
VINTAGE = "Census 2020"
STATE_FIPS = "06"
COUNTY_FIPS = ("061", "057")  # Placer, Nevada

# --- tier 1 -----------------------------------------------------------------------
OVERPASS = "https://overpass-api.de/api/interpreter"
# Attic query date. OSM is a live database; without this the AOI would drift as people
# edit. Bump deliberately, never incidentally.
OSM_DATE = "2026-08-30T00:00:00Z"
OSM_ATTRIBUTION = "© OpenStreetMap contributors, ODbL"
# Overpass rejects urllib's default User-Agent with HTTP 406.
USER_AGENT = "foothill-trail-atlas/0.0 (OTCA historical trail mapping; contact via repo)"

CANAL_NAME = "Bear River Canal"
TRAIL_NAME = "Bear River Canal Trail"
FEEDER_NAME = "Bowman Feeder Canal"
START_ROAD = "Crother Road"
END_ROAD = "Placer Hills Road"
CORRIDOR_BBOX = (38.94, -121.14, 39.07, -120.93)  # s, w, n, e

# Buffer around the corridor spine. Generous on purpose: a tight buffer around the
# modern trace would assume historical alignments followed it, which is exactly the
# inference AGENTS.md §2.1 forbids. It also has to leave enough margin to interpret and
# georeference a scanned sheet.
DEFAULT_BUFFER_M = 250

# UTM 10N. Buffering must happen in a projected CRS; a buffer in degrees at 39°N would
# come out ~30% wider east-west than north-south.
WORKING_CRS = "EPSG:26910"


def round_coords(obj):
    """Round to 6 dp, normalising tuples to lists.

    shapely's mapping() returns coordinate tuples, and dicts nest the coordinate list,
    so both cases have to be handled or the truncation silently does nothing and the
    idempotency comparison below never matches.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return round(float(obj), COORD_DECIMALS)
    if isinstance(obj, (list, tuple)):
        return [round_coords(item) for item in obj]
    if isinstance(obj, dict):
        return {key: round_coords(value) for key, value in obj.items()}
    return obj


def write_if_changed(out: Path, geometry: dict, properties: dict) -> bool:
    """Write the AOI unless the geometry already on disk is identical."""
    retrieved = date.today().isoformat()
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            feature = existing["features"][0]
            if feature["geometry"] == geometry:
                click.echo(f"  {out.name} already current, unchanged")
                return False
            retrieved = feature["properties"].get("retrieved", retrieved)
        except (KeyError, IndexError, json.JSONDecodeError):
            pass

    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {**properties, "retrieved": retrieved},
            }
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return True


def finish(geom_projected, to_wgs84, out: Path, properties: dict, label: str) -> None:
    geometry = round_coords(mapping(transform(to_wgs84, geom_projected)))
    if not shape(geometry).is_valid:
        click.echo(
            f"{label}: geometry invalid after truncation to {COORD_DECIMALS} dp", err=True
        )
        sys.exit(1)
    changed = write_if_changed(out, geometry, properties)
    bounds = shape(geometry).bounds
    if changed:
        click.echo(
            f"  wrote {out.relative_to(REPO_ROOT)} — bbox "
            f"{bounds[0]:.4f},{bounds[1]:.4f},{bounds[2]:.4f},{bounds[3]:.4f}"
        )


@click.group()
def cli() -> None:
    """Build the acquisition and digitizing AOIs from online sources."""


@cli.command()
@click.option("--timeout", default=120, show_default=True)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "aoi_counties.geojson",
)
def counties(timeout: int, out: Path) -> None:
    """Placer + Nevada County, dissolved — the acquisition envelope."""
    from pyproj import Transformer

    where = "STATE='{}' AND COUNTY IN ({})".format(
        STATE_FIPS, ",".join(f"'{c}'" for c in COUNTY_FIPS)
    )
    params = {
        "where": where,
        "outFields": "GEOID,BASENAME,STATE,COUNTY",
        "outSR": "4326",
        "f": "geojson",
    }
    url = f"{TIGERWEB}/{COUNTIES_LAYER}/query?{urllib.parse.urlencode(params)}"
    click.echo("fetch-aoi counties: querying Census TIGERweb…")
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed host
        collection = json.loads(response.read().decode("utf-8"), strict=False)

    features = collection.get("features") or []
    if len(features) != len(COUNTY_FIPS):
        click.echo(
            f"fetch-aoi counties: expected {len(COUNTY_FIPS)} counties, got {len(features)}; "
            "refusing to write a partial AOI",
            err=True,
        )
        sys.exit(1)

    names = sorted(f["properties"].get("BASENAME", "?") for f in features)
    dissolved = unary_union([shape(f["geometry"]) for f in features])
    if not dissolved.is_valid:
        dissolved = dissolved.buffer(0)

    identity = Transformer.from_crs("EPSG:4326", "EPSG:4326", always_xy=True).transform
    finish(
        dissolved,
        identity,
        out,
        {
            "aoi_id": "acquisition-placer-nevada",
            "role": "acquisition envelope for fetch-topo and rasters; not a digitizing bound",
            "counties": names,
            "geoids": sorted(f["properties"].get("GEOID", "?") for f in features),
            "source": "US Census Bureau TIGERweb",
            "source_url": f"{TIGERWEB}/{COUNTIES_LAYER}",
            "vintage": VINTAGE,
            "rights": "public_domain",
            "attribution": "County boundaries: US Census Bureau TIGER/Line",
        },
        "fetch-aoi counties",
    )


def overpass_ways(query_body: str, timeout: int) -> list[dict]:
    query = f'[out:json][timeout:180][date:"{OSM_DATE}"];\n{query_body}\nout tags geom;'
    request = urllib.request.Request(
        OVERPASS, data=query.encode("utf-8"), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed host
        return json.loads(response.read().decode("utf-8"), strict=False).get("elements", [])


def named_lines(elements: list[dict], name: str, to_utm) -> object:
    lines = [
        LineString([(p["lon"], p["lat"]) for p in element["geometry"]])
        for element in elements
        if element.get("tags", {}).get("name") == name
        and len(element.get("geometry") or []) > 1
    ]
    if not lines:
        return None
    return transform(to_utm, unary_union(lines))


@cli.command()
@click.option(
    "--buffer",
    "buffer_m",
    default=DEFAULT_BUFFER_M,
    show_default=True,
    help="Corridor buffer in metres.",
)
@click.option("--timeout", default=180, show_default=True)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=SOURCES_DIR / "aoi_tier1.geojson",
)
def tier1(buffer_m: int, timeout: int, out: Path) -> None:
    """Bear River Canal corridor, Crother Rd to Placer Hills Rd, plus the Bowman feeder."""
    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", WORKING_CRS, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(WORKING_CRS, "EPSG:4326", always_xy=True).transform

    south, west, north, east = CORRIDOR_BBOX
    bbox = f"({south},{west},{north},{east})"
    names = "|".join((CANAL_NAME, FEEDER_NAME))
    body = (
        "(\n"
        f'  way["waterway"="canal"]["name"~"^({names})$"]{bbox};\n'
        f'  way["highway"]["name"="{TRAIL_NAME}"]{bbox};\n'
        f'  way["highway"]["name"~"^({START_ROAD}|{END_ROAD})$"]{bbox};\n'
        ");"
    )
    click.echo(f"fetch-aoi tier1: querying Overpass (OSM snapshot {OSM_DATE})…")
    elements = overpass_ways(body, timeout)

    canal = named_lines(elements, CANAL_NAME, to_utm)
    trail = named_lines(elements, TRAIL_NAME, to_utm)
    feeder = named_lines(elements, FEEDER_NAME, to_utm)
    start_road = named_lines(elements, START_ROAD, to_utm)
    end_road = named_lines(elements, END_ROAD, to_utm)

    missing = [
        label
        for label, geom in (
            (CANAL_NAME, canal),
            (TRAIL_NAME, trail),
            (START_ROAD, start_road),
            (END_ROAD, end_road),
        )
        if geom is None
    ]
    if missing:
        click.echo(
            "fetch-aoi tier1: OSM returned nothing for: "
            + ", ".join(missing)
            + ". Refusing to guess the corridor.",
            err=True,
        )
        sys.exit(1)

    spine_canal = linemerge(canal)
    if spine_canal.geom_type != "LineString":
        click.echo(
            f"fetch-aoi tier1: {CANAL_NAME} did not merge into a single line "
            f"({spine_canal.geom_type}); the corridor cannot be cut by chainage.",
            err=True,
        )
        sys.exit(1)

    def crossings(road) -> list[float]:
        inter = spine_canal.intersection(road)
        if inter.is_empty:
            return []
        parts = (
            [inter]
            if inter.geom_type == "Point"
            else [g for g in getattr(inter, "geoms", []) if g.geom_type == "Point"]
        )
        return sorted(spine_canal.project(p) for p in parts)

    starts, ends = crossings(start_road), crossings(end_road)
    if not starts or not ends:
        click.echo(
            f"fetch-aoi tier1: {CANAL_NAME} does not cross "
            f"{START_ROAD if not starts else END_ROAD} in the OSM snapshot.",
            err=True,
        )
        sys.exit(1)

    # A long road can cross the canal several times. Pick the crossing pair that best
    # brackets the named trail, so the cut is anchored to the mapped corridor rather
    # than to whichever crossing happens to come first.
    trail_pts = [
        spine_canal.project(Point(c))
        for geom in (trail.geoms if hasattr(trail, "geoms") else [trail])
        for c in geom.coords
    ]
    trail_lo, trail_hi = min(trail_pts), max(trail_pts)
    pair = min(
        ((s, e) for s in starts for e in ends if s < e),
        key=lambda se: abs(se[0] - trail_lo) + abs(se[1] - trail_hi),
        default=None,
    )
    if pair is None:
        click.echo(
            f"fetch-aoi tier1: no {START_ROAD} crossing precedes a {END_ROAD} crossing.",
            err=True,
        )
        sys.exit(1)

    segment = substring(spine_canal, pair[0], pair[1])
    parts = [segment, trail] + ([feeder] if feeder is not None else [])
    spine = unary_union(parts)
    aoi = spine.buffer(buffer_m)
    if not aoi.is_valid:
        aoi = aoi.buffer(0)

    click.echo(
        f"  corridor {segment.length / 1609.34:.2f} mi "
        f"(chainage {pair[0] / 1609.34:.2f}–{pair[1] / 1609.34:.2f} mi), "
        f"spine {spine.length / 1609.34:.2f} mi, "
        f"buffer {buffer_m} m, area {aoi.area / 2.59e6:.2f} sq mi"
    )
    if feeder is None:
        click.echo(f"  note: {FEEDER_NAME} absent from the snapshot; corridor built without it")

    finish(
        aoi,
        to_wgs84,
        out,
        {
            "aoi_id": "tier1-bear-river-canal-corridor",
            "role": "digitizing bound for Tier 1; not evidence and not an alignment",
            "derived_from": [CANAL_NAME, TRAIL_NAME]
            + ([FEEDER_NAME] if feeder is not None else []),
            "endpoints": [START_ROAD, END_ROAD],
            "corridor_miles": round(segment.length / 1609.34, 2),
            "buffer_m": buffer_m,
            "source": "OpenStreetMap via Overpass API",
            "source_url": OVERPASS,
            "osm_snapshot": OSM_DATE,
            "rights": "odbl",
            "attribution": OSM_ATTRIBUTION,
        },
        "fetch-aoi tier1",
    )


if __name__ == "__main__":
    cli()
