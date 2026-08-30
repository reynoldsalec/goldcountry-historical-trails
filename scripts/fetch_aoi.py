#!/usr/bin/env python3
"""Fetch the acquisition AOI — Placer + Nevada County, California — from Census TIGERweb.

Writes data/sources/aoi_counties.geojson: the two county boundaries dissolved into one
polygon, in EPSG:4326 truncated to 6 decimal places (AGENTS.md §3).

This is the envelope for raster acquisition and clipping (make fetch-topo, make rasters).
It is NOT the digitizing bound — that is data/sources/aoi_tier1.geojson, which stays
scoped to the Bear River Canal corridor (README §2).

The boundaries come from the pinned Census 2020 vintage rather than TIGERweb's rolling
"current" layer, so a re-run years from now reproduces the same geometry.

Idempotent: if the fetched geometry matches what is already committed, the file is left
untouched so the retrieval date does not churn in git on every run.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import click
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parent.parent

SERVICE = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer"
COUNTIES_LAYER = 55  # "Counties" under the Census 2020 group — a pinned, archival vintage
VINTAGE = "Census 2020"

# Placer (06061) and Nevada (06057), California.
STATE_FIPS = "06"
COUNTY_FIPS = ("061", "057")

COORD_DECIMALS = 6


def fetch_counties(service: str, layer: int, timeout: int) -> dict:
    where = "STATE='{}' AND COUNTY IN ({})".format(
        STATE_FIPS, ",".join(f"'{c}'" for c in COUNTY_FIPS)
    )
    params = {
        "where": where,
        "outFields": "GEOID,BASENAME,STATE,COUNTY",
        "outSR": "4326",
        "f": "geojson",
    }
    url = f"{service}/{layer}/query?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed host
        payload = response.read().decode("utf-8")
    # TIGERweb occasionally emits raw control characters in text fields.
    return json.loads(payload, strict=False)


def round_coords(obj):
    """Round to 6 dp, normalising tuples to lists.

    shapely's mapping() returns coordinate tuples. The committed file round-trips
    through JSON as lists, so without normalising here the idempotency comparison
    below would never match and the AOI would rewrite on every run.
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


@click.command()
@click.option("--service", default=SERVICE, show_default=False, help="TIGERweb MapServer URL.")
@click.option("--layer", default=COUNTIES_LAYER, show_default=True, help="Counties layer id.")
@click.option("--timeout", default=120, show_default=True, help="HTTP timeout in seconds.")
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=REPO_ROOT / "data" / "sources" / "aoi_counties.geojson",
    show_default="data/sources/aoi_counties.geojson",
)
def main(service: str, layer: int, timeout: int, out: Path) -> None:
    """Fetch, dissolve and write the two-county acquisition AOI."""
    collection = fetch_counties(service, layer, timeout)
    features = collection.get("features") or []
    if len(features) != len(COUNTY_FIPS):
        click.echo(
            f"fetch-aoi: expected {len(COUNTY_FIPS)} counties, got {len(features)}; "
            "refusing to write a partial AOI",
            err=True,
        )
        sys.exit(1)

    names = sorted(f["properties"].get("BASENAME", "?") for f in features)
    geoids = sorted(f["properties"].get("GEOID", "?") for f in features)

    dissolved = unary_union([shape(f["geometry"]) for f in features])
    if not dissolved.is_valid:
        dissolved = dissolved.buffer(0)
    if not dissolved.is_valid:
        click.echo("fetch-aoi: dissolved AOI is not a valid geometry", err=True)
        sys.exit(1)

    geometry = round_coords(mapping(dissolved))

    # Rounding can in principle self-intersect a boundary; confirm it did not.
    if not shape(geometry).is_valid:
        click.echo(
            f"fetch-aoi: AOI became invalid after truncation to {COORD_DECIMALS} dp",
            err=True,
        )
        sys.exit(1)

    retrieved = date.today().isoformat()
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if existing["features"][0]["geometry"] == geometry:
                click.echo(f"fetch-aoi: {out.name} already current, unchanged")
                return
            retrieved = existing["features"][0]["properties"].get("retrieved", retrieved)
        except (KeyError, IndexError, json.JSONDecodeError):
            pass

    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "aoi_id": "acquisition-placer-nevada",
                    "role": (
                        "acquisition envelope for fetch-topo and rasters; "
                        "not a digitizing bound"
                    ),
                    "counties": names,
                    "geoids": geoids,
                    "source": "US Census Bureau TIGERweb",
                    "source_url": f"{service}/{layer}",
                    "vintage": VINTAGE,
                    "rights": "public_domain",
                    "retrieved": retrieved,
                },
            }
        ],
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    bounds = shape(geometry).bounds
    click.echo(
        f"fetch-aoi: wrote {out.relative_to(REPO_ROOT)} — {', '.join(names)} "
        f"({VINTAGE}), bbox {bounds[0]:.4f},{bounds[1]:.4f},{bounds[2]:.4f},{bounds[3]:.4f}"
    )


if __name__ == "__main__":
    main()
