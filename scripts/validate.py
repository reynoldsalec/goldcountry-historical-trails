#!/usr/bin/env python3
"""Validate data/authoritative/ against schema/ and the integrity rules in AGENTS.md §5.3.

Six checks, in order:

  1. schema      JSON Schema conformance for all files in data/authoritative/.
  2. references  Referential integrity (support.csv -> alignments and observations,
                 alignments -> trails, superseded_by -> alignments).
  3. orphans     No alignment without at least one support row (AGENTS.md §2.4).
  4. temporal    earliest_known_open <= latest_known_open, and the closed pair likewise.
  5. geometry    Geometry validity, CRS, LineString-only alignments, 6dp coordinates.
  6. leak        No restricted-marked value anywhere under build/public/ (AGENTS.md §2.5).

Which fields are restricted is read from the "x-sensitivity" keyword in the schemas,
not from a list hardcoded here, so marking a new field restricted in a schema is enough
to bring it under the leak test.

Exits non-zero on any failure, naming the record and the check for each one.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import click
from jsonschema import Draft202012Validator
from shapely.geometry import shape

REPO_ROOT = Path(__file__).resolve().parent.parent

COORD_DECIMALS = 6

# GeoJSON is WGS84 by definition (RFC 7946). A legacy "crs" member is tolerated only
# if it names that same CRS.
ALLOWED_CRS_NAMES = {
    "urn:ogc:def:crs:OGC:1.3:CRS84",
    "urn:ogc:def:crs:EPSG::4326",
    "EPSG:4326",
}


@dataclass(frozen=True)
class Failure:
    check: str
    record: str
    message: str

    def render(self) -> str:
        return f"FAIL [{self.check}] {self.record}: {self.message}"


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def load_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_records(data_dir: Path) -> tuple[dict, list[Failure]]:
    """Read the four authoritative files. Returns ({}, failures) if any is unreadable."""
    failures: list[Failure] = []
    out: dict = {}

    expected = {
        "trails": data_dir / "trails.json",
        "alignments": data_dir / "alignments.geojson",
        "observations": data_dir / "observations.geojson",
        "support": data_dir / "support.csv",
    }

    for path in expected.values():
        if not path.exists():
            failures.append(Failure("schema", path.name, "file is missing"))
    if failures:
        return {}, failures

    try:
        trails = load_json(expected["trails"])
    except json.JSONDecodeError as exc:
        return {}, [Failure("schema", "trails.json", f"not valid JSON: {exc}")]
    if not isinstance(trails, list):
        return {}, [
            Failure(
                "schema", "trails.json", "must be a JSON array of trail objects (README §3)"
            )
        ]
    out["trails"] = trails

    for name in ("alignments", "observations"):
        path = expected[name]
        try:
            doc = load_json(path)
        except json.JSONDecodeError as exc:
            return {}, [Failure("schema", path.name, f"not valid JSON: {exc}")]
        if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
            return {}, [
                Failure("schema", path.name, 'top level must be a GeoJSON "FeatureCollection"')
            ]
        features = doc.get("features")
        if not isinstance(features, list):
            return {}, [Failure("schema", path.name, '"features" must be an array')]
        out[name] = features
        out[f"{name}_doc"] = doc

    with expected["support"].open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        expected_header = ["alignment_id", "observation_id", "role", "confidence", "note"]
        if reader.fieldnames != expected_header:
            return {}, [
                Failure(
                    "schema",
                    "support.csv",
                    f"header must be {','.join(expected_header)} (README §3), got "
                    f"{','.join(reader.fieldnames or [])}",
                )
            ]
        out["support"] = list(reader)

    return out, []


def record_id(name: str, record, index: int) -> str:
    """A human-usable identifier for error messages, even on malformed records."""
    if name == "trails" and isinstance(record, dict):
        ident = record.get("trail_id")
    elif name in ("alignments", "observations") and isinstance(record, dict):
        props = record.get("properties")
        key = "alignment_id" if name == "alignments" else "observation_id"
        ident = props.get(key) if isinstance(props, dict) else None
    elif name == "support" and isinstance(record, dict):
        a, o = record.get("alignment_id"), record.get("observation_id")
        ident = f"{a} -> {o}" if a and o else None
    else:
        ident = None
    label = {
        "trails": "trails.json",
        "alignments": "alignments.geojson",
        "observations": "observations.geojson",
        "support": "support.csv",
    }[name]
    if isinstance(ident, str) and ident:
        return f"{label}[{index}] {ident}"
    return f"{label}[{index}] <unidentified>"


# --------------------------------------------------------------------------------------
# Sensitivity, read from the schemas
# --------------------------------------------------------------------------------------


def restricted_paths(schema: dict, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every property path in a schema marked x-sensitivity: restricted.

    An x-sensitivity marking covers a node and everything beneath it, so the walk
    stops descending once it finds one.
    """
    found: list[tuple[str, ...]] = []
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, subschema in props.items():
            if not isinstance(subschema, dict):
                continue
            path = prefix + (key,)
            marking = subschema.get("x-sensitivity")
            if marking == "restricted":
                found.append(path)
            elif marking is None:
                found.extend(restricted_paths(subschema, path))
    return found


def unmarked_paths(schema: dict, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Data-bearing property paths carrying no x-sensitivity.

    A node with a marking is satisfied and is not descended into. A node without one
    but with its own "properties" map is a structural container (the Feature-level
    "properties" object), so the walk descends through it. Anything else is a field
    someone forgot to annotate, which would silently escape the leak test.
    """
    missing: list[tuple[str, ...]] = []
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, subschema in props.items():
            if not isinstance(subschema, dict):
                continue
            path = prefix + (key,)
            if "x-sensitivity" in subschema:
                continue
            if isinstance(subschema.get("properties"), dict):
                missing.extend(unmarked_paths(subschema, path))
            else:
                missing.append(path)
    return missing


def values_at(record, path: tuple[str, ...]) -> list[str]:
    """Non-empty string values at a property path, flattening arrays."""
    current = [record]
    for key in path:
        nxt = []
        for item in current:
            if isinstance(item, dict) and key in item:
                nxt.append(item[key])
        current = nxt
    flat = []
    for value in current:
        flat.extend(value if isinstance(value, list) else [value])
    return [v for v in flat if isinstance(v, str) and v.strip()]


# --------------------------------------------------------------------------------------
# Check 1 — schema conformance
# --------------------------------------------------------------------------------------


def check_schema(records: dict, validators: dict) -> list[Failure]:
    failures: list[Failure] = []
    for name, validator in validators.items():
        for index, record in enumerate(records.get(name, [])):
            for error in sorted(validator.iter_errors(record), key=lambda e: list(e.path)):
                field = ".".join(str(p) for p in error.absolute_path) or "<record root>"
                failures.append(
                    Failure(
                        "schema",
                        record_id(name, record, index),
                        f"{field}: {error.message}",
                    )
                )
    return failures


# --------------------------------------------------------------------------------------
# Check 2 — referential integrity
# --------------------------------------------------------------------------------------


def check_references(records: dict) -> list[Failure]:
    failures: list[Failure] = []

    trail_ids: set[str] = set()
    for index, trail in enumerate(records["trails"]):
        tid = trail.get("trail_id") if isinstance(trail, dict) else None
        if not isinstance(tid, str):
            continue
        if tid in trail_ids:
            failures.append(
                Failure(
                    "references",
                    record_id("trails", trail, index),
                    f"duplicate trail_id {tid!r}",
                )
            )
        trail_ids.add(tid)

    alignment_ids: set[str] = set()
    for index, feature in enumerate(records["alignments"]):
        props = feature.get("properties") if isinstance(feature, dict) else None
        aid = props.get("alignment_id") if isinstance(props, dict) else None
        if not isinstance(aid, str):
            continue
        if aid in alignment_ids:
            failures.append(
                Failure(
                    "references",
                    record_id("alignments", feature, index),
                    f"duplicate alignment_id {aid!r}",
                )
            )
        alignment_ids.add(aid)

    observation_ids: set[str] = set()
    for index, feature in enumerate(records["observations"]):
        props = feature.get("properties") if isinstance(feature, dict) else None
        oid = props.get("observation_id") if isinstance(props, dict) else None
        if not isinstance(oid, str):
            continue
        if oid in observation_ids:
            failures.append(
                Failure(
                    "references",
                    record_id("observations", feature, index),
                    f"duplicate observation_id {oid!r}",
                )
            )
        observation_ids.add(oid)

    for index, feature in enumerate(records["alignments"]):
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if not isinstance(props, dict):
            continue
        rid = record_id("alignments", feature, index)
        tid = props.get("trail_id")
        if isinstance(tid, str) and tid not in trail_ids:
            failures.append(
                Failure(
                    "references", rid, f"trail_id {tid!r} has no matching trail in trails.json"
                )
            )
        sup = props.get("superseded_by")
        if isinstance(sup, str) and sup not in alignment_ids:
            failures.append(
                Failure(
                    "references",
                    rid,
                    f"superseded_by {sup!r} has no matching alignment in alignments.geojson",
                )
            )
        if isinstance(sup, str) and sup == props.get("alignment_id"):
            failures.append(Failure("references", rid, "superseded_by points at itself"))

    for index, row in enumerate(records["support"]):
        rid = record_id("support", row, index)
        aid = row.get("alignment_id")
        oid = row.get("observation_id")
        if isinstance(aid, str) and aid not in alignment_ids:
            failures.append(
                Failure(
                    "references",
                    rid,
                    f"alignment_id {aid!r} has no matching alignment in alignments.geojson",
                )
            )
        if isinstance(oid, str) and oid not in observation_ids:
            failures.append(
                Failure(
                    "references",
                    rid,
                    f"observation_id {oid!r} has no matching observation in "
                    "observations.geojson",
                )
            )

    return failures


# --------------------------------------------------------------------------------------
# Check 3 — orphan alignments
# --------------------------------------------------------------------------------------


def check_orphans(records: dict) -> list[Failure]:
    """AGENTS.md §2.4: no alignment may exist without at least one support row.

    There is deliberately no --allow-orphans escape hatch.
    """
    supported = {
        row.get("alignment_id")
        for row in records["support"]
        if isinstance(row.get("alignment_id"), str)
    }
    failures: list[Failure] = []
    for index, feature in enumerate(records["alignments"]):
        props = feature.get("properties") if isinstance(feature, dict) else {}
        aid = props.get("alignment_id") if isinstance(props, dict) else None
        if isinstance(aid, str) and aid not in supported:
            failures.append(
                Failure(
                    "orphans",
                    record_id("alignments", feature, index),
                    f"orphan alignment: {aid!r} has no row in support.csv "
                    "(provenance is mandatory, AGENTS.md §2.4)",
                )
            )
    return failures


# --------------------------------------------------------------------------------------
# Check 4 — temporal coherence
# --------------------------------------------------------------------------------------


def as_bound(value: str, *, upper: bool) -> tuple[int, int, int] | None:
    """Comparable bound for an ISO YYYY or YYYY-MM-DD date.

    A bare year is widened to the whole year, so "1954-06-01" <= "1954" holds rather
    than failing on a spurious month/day comparison.
    """
    parts = value.split("-")
    try:
        if len(parts) == 1:
            year = int(parts[0])
            return (year, 12, 31) if upper else (year, 1, 1)
        if len(parts) == 3:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    return None


def check_temporal(records: dict) -> list[Failure]:
    failures: list[Failure] = []

    def compare(rid: str, lo_name: str, lo_raw, hi_name: str, hi_raw) -> None:
        if not isinstance(lo_raw, str) or not isinstance(hi_raw, str):
            return  # null means unobserved, which constrains nothing (AGENTS.md §2.3)
        lo, hi = as_bound(lo_raw, upper=False), as_bound(hi_raw, upper=True)
        if lo is None or hi is None:
            return  # malformed dates are the schema check's business
        if lo > hi:
            failures.append(
                Failure(
                    "temporal",
                    rid,
                    f"{lo_name} ({lo_raw}) is after {hi_name} ({hi_raw})",
                )
            )

    for index, feature in enumerate(records["alignments"]):
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if not isinstance(props, dict):
            continue
        rid = record_id("alignments", feature, index)
        compare(
            rid,
            "earliest_known_open",
            props.get("earliest_known_open"),
            "latest_known_open",
            props.get("latest_known_open"),
        )
        compare(
            rid,
            "earliest_known_closed",
            props.get("earliest_known_closed"),
            "latest_known_closed",
            props.get("latest_known_closed"),
        )

    for index, feature in enumerate(records["observations"]):
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if not isinstance(props, dict):
            continue
        compare(
            record_id("observations", feature, index),
            "date_start",
            props.get("date_start"),
            "date_end",
            props.get("date_end"),
        )

    return failures


# --------------------------------------------------------------------------------------
# Check 5 — geometry validity and CRS
# --------------------------------------------------------------------------------------


def coordinate_values(coords) -> list[float]:
    if isinstance(coords, (int, float)):
        return [float(coords)]
    if isinstance(coords, list):
        out: list[float] = []
        for item in coords:
            out.extend(coordinate_values(item))
        return out
    return []


def decimals(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return COORD_DECIMALS + 1  # scientific notation is never 6dp-truncated output
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def check_geometry(records: dict) -> list[Failure]:
    failures: list[Failure] = []

    for name in ("alignments", "observations"):
        doc = records[f"{name}_doc"]
        crs = doc.get("crs")
        if crs is not None:
            named = None
            if isinstance(crs, dict):
                named = (crs.get("properties") or {}).get("name")
            if named not in ALLOWED_CRS_NAMES:
                failures.append(
                    Failure(
                        "geometry",
                        f"{name}.geojson",
                        f'"crs" member names {named!r}; GeoJSON is EPSG:4326 only '
                        "(RFC 7946, AGENTS.md §3)",
                    )
                )

        for index, feature in enumerate(records[name]):
            rid = record_id(name, feature, index)
            geom = feature.get("geometry") if isinstance(feature, dict) else None

            if geom is None:
                failures.append(
                    Failure(
                        "geometry",
                        rid,
                        "null geometry is not permitted; a record without geometry belongs "
                        "in a CSV (AGENTS.md §3)",
                    )
                )
                continue
            if not isinstance(geom, dict):
                failures.append(Failure("geometry", rid, "geometry is not an object"))
                continue

            gtype = geom.get("type")
            if name == "alignments" and gtype != "LineString":
                failures.append(
                    Failure(
                        "geometry",
                        rid,
                        f"alignment geometry is {gtype!r}; LineString only, split a "
                        "MultiLineString into separate alignments (AGENTS.md §3)",
                    )
                )
                continue

            try:
                shp = shape(geom)
            except Exception as exc:  # noqa: BLE001 - any malformed geometry is a failure
                failures.append(Failure("geometry", rid, f"unreadable geometry: {exc}"))
                continue

            if shp.is_empty:
                failures.append(Failure("geometry", rid, "geometry is empty"))
                continue
            if not shp.is_valid:
                from shapely.validation import explain_validity

                failures.append(
                    Failure("geometry", rid, f"invalid geometry: {explain_validity(shp)}")
                )

            values = coordinate_values(geom.get("coordinates"))
            over = [v for v in values if decimals(v) > COORD_DECIMALS]
            if over:
                failures.append(
                    Failure(
                        "geometry",
                        rid,
                        f"coordinate(s) carry more than {COORD_DECIMALS} decimal places "
                        f"(e.g. {over[0]}); truncate on write (AGENTS.md §3)",
                    )
                )

            lons, lats = values[0::2], values[1::2]
            if any(abs(v) > 180 for v in lons) or any(abs(v) > 90 for v in lats):
                failures.append(
                    Failure(
                        "geometry",
                        rid,
                        "coordinate out of EPSG:4326 range; is this file in a projected CRS?",
                    )
                )

            if gtype == "LineString" and len(set(map(tuple, geom["coordinates"]))) < 2:
                failures.append(
                    Failure("geometry", rid, "LineString has fewer than 2 distinct positions")
                )

    return failures


# --------------------------------------------------------------------------------------
# Check 6 — restricted-field leakage in build/public/
# --------------------------------------------------------------------------------------


def collect_restricted(records: dict, schemas: dict) -> list[tuple[str, str]]:
    """(record id, restricted value) pairs, driven by x-sensitivity in the schemas."""
    out: list[tuple[str, str]] = []
    for name, schema in schemas.items():
        paths = restricted_paths(schema)
        for index, record in enumerate(records.get(name, [])):
            rid = record_id(name, record, index)
            for path in paths:
                for value in values_at(record, path):
                    out.append((f"{rid} .{'.'.join(path)}", value))

    # AGENTS.md §2.5: a restricted observation does not reach the public build at all,
    # so its identifier is restricted too even though its fields are individually public.
    for index, feature in enumerate(records.get("observations", [])):
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if isinstance(props, dict) and props.get("sensitivity") == "restricted":
            oid = props.get("observation_id")
            if isinstance(oid, str) and oid.strip():
                source = record_id("observations", feature, index)
                out.append((f"{source} .properties.observation_id", oid))
    return out


def check_leak(records: dict, schemas: dict, public_build: Path) -> tuple[list[Failure], str]:
    restricted = collect_restricted(records, schemas)

    if not public_build.exists():
        return [], (
            f"leak: {public_build} does not exist yet, nothing to scan "
            f"({len(restricted)} restricted values are under watch)"
        )

    files = sorted(p for p in public_build.rglob("*") if p.is_file())
    failures: list[Failure] = []
    for path in files:
        try:
            blob = path.read_bytes()
        except OSError as exc:
            failures.append(
                Failure("leak", str(path), f"unreadable file in public build: {exc}")
            )
            continue
        for source, value in restricted:
            if value.encode("utf-8") in blob:
                failures.append(
                    Failure(
                        "leak",
                        source,
                        f"restricted value {value!r} appears in "
                        f"{path.relative_to(public_build.parent.parent)} "
                        "(AGENTS.md §2.5)",
                    )
                )

    return failures, (
        f"leak: scanned {len(files)} file(s) under {public_build} "
        f"for {len(restricted)} restricted value(s)"
    )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


@click.command()
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=REPO_ROOT / "data" / "authoritative",
    show_default="data/authoritative",
    help="Directory holding the four authoritative files.",
)
@click.option(
    "--schema-dir",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=REPO_ROOT / "schema",
    show_default="schema",
    help="Directory holding the four JSON Schemas.",
)
@click.option(
    "--public-build",
    type=click.Path(file_okay=False, path_type=Path),
    default=REPO_ROOT / "build" / "public",
    show_default="build/public",
    help="Public build output to scan for restricted values.",
)
def main(data_dir: Path, schema_dir: Path, public_build: Path) -> None:
    """Run the six checks in AGENTS.md §5.3. Exits non-zero on any failure."""
    schemas = {
        "trails": load_json(schema_dir / "trail.schema.json"),
        "alignments": load_json(schema_dir / "alignment.schema.json"),
        "observations": load_json(schema_dir / "observation.schema.json"),
        "support": load_json(schema_dir / "support.schema.json"),
    }
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        missing = unmarked_paths(schema)
        if missing:
            joined = ", ".join(".".join(p) for p in missing)
            click.echo(
                f"FAIL [schema] {name}.schema.json: property without an x-sensitivity "
                f"annotation: {joined}",
                err=True,
            )
            sys.exit(1)

    records, failures = load_records(data_dir)
    notes: list[str] = []

    if not failures:
        validators = {n: Draft202012Validator(s) for n, s in schemas.items()}
        failures += check_schema(records, validators)
        failures += check_references(records)
        failures += check_orphans(records)
        failures += check_temporal(records)
        failures += check_geometry(records)
        leak_failures, leak_note = check_leak(records, schemas, public_build)
        failures += leak_failures
        notes.append(leak_note)

    if failures:
        for failure in failures:
            click.echo(failure.render(), err=True)
        by_check: dict[str, int] = {}
        for failure in failures:
            by_check[failure.check] = by_check.get(failure.check, 0) + 1
        summary = ", ".join(f"{check}={count}" for check, count in sorted(by_check.items()))
        click.echo(f"\nvalidate: {len(failures)} failure(s) [{summary}]", err=True)
        sys.exit(1)

    counts = " ".join(
        f"{len(records[n])} {n}" for n in ("trails", "alignments", "observations", "support")
    )
    for note in notes:
        click.echo(note)
    click.echo(f"validate: OK — {counts}; all six checks passed")


if __name__ == "__main__":
    main()
