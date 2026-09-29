// The fixture world the browser tests run against (issue #44). Nothing here resembles the
// Auburn sources: the ids, labels, citations and years are invented on purpose, the bounds
// sit in the Gulf of Guinea, and the tiles are flat colour. A reader who mistakes this for
// evidence has only to look at it. The real manifest and the real pyramids are never served
// to the suite, so no source byte or receipt is touched by a test run.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { solidPng, type Rgba } from "./png.ts";

export const FIXTURE_MANIFEST_NAME = "fixture-editions.json";
export const TILE_SIZE = 256;

/** [west, south, east, north]. Half a degree square, so a zoom-12 pyramid stays tiny. */
export const FIXTURE_BOUNDS: [number, number, number, number] = [0, 0, 0.5, 0.5];
export const FIXTURE_ZOOM = { min: 10, max: 12 };

export interface FixtureEdition {
  id: string;
  label: string;
  colour: Rgba;
}

/**
 * Four editions in display order, shaped like the real set (a base sheet, two revisions and
 * one photographic product) so the card and notice logic is exercised, with invented values.
 */
export const FIXTURE_EDITIONS: FixtureEdition[] = [
  {
    id: "fixture-first",
    label: "Fixture sheet one (test data, 1899)",
    colour: { r: 220, g: 60, b: 60, a: 255 },
  },
  {
    id: "fixture-second",
    label: "Fixture sheet two (test data, 1899/1905)",
    colour: { r: 60, g: 140, b: 220, a: 255 },
  },
  {
    id: "fixture-third",
    label: "Fixture photo sheet (test data, 1911)",
    colour: { r: 90, g: 170, b: 90, a: 255 },
  },
  {
    id: "fixture-fourth",
    label: "Fixture sheet four (test data, 1899/1920)",
    colour: { r: 190, g: 140, b: 40, a: 255 },
  },
];

/** An unreachable host: a background request to it would be an obvious allowlist failure. */
export const FIXTURE_SOURCE_URL_HOST = "https://fixture-source-record.invalid";

function editionRecord(edition: FixtureEdition, index: number): Record<string, unknown> {
  const isPhoto = index === 2;
  const revisionYear = index === 1 ? 1905 : index === 3 ? 1920 : null;
  return {
    id: edition.id,
    source_id: `FIXTURE_SOURCE_${index + 1}_NOT_A_REAL_SCAN`,
    kind: isPhoto ? "orthophotoquad" : "topo",
    label: edition.label,
    citation: `Fixture citation ${index + 1}. Invented for the browser test suite.`,
    source_url: `${FIXTURE_SOURCE_URL_HOST}/${edition.id}`,
    rights: "public_domain",
    attribution: `Fixture attribution ${index + 1} (test data)`,
    dates: {
      map_year: isPhoto ? 1911 : 1899,
      base_year: isPhoto ? null : 1899,
      revision_year: revisionYear,
      base_photography: isPhoto ? null : "1898",
      revision_photography: revisionYear === null ? null : String(revisionYear - 2),
      photography: isPhoto ? "1911-07-04" : null,
      base_field_check_year: isPhoto ? null : 1899,
      revision_field_checked: revisionYear === null ? null : false,
    },
    date_note: `Fixture date note ${index + 1}. No real survey is described.`,
  };
}

/** The `data/sources/demo-editions.json` shape, as the dev server expects to read it. */
export function fixtureSourceManifest(): Record<string, unknown> {
  return {
    version: 1,
    area_id: "fixture-area",
    edition_order: FIXTURE_EDITIONS.map((edition) => edition.id),
    view_bounds_wgs84: FIXTURE_BOUNDS,
    tile_zoom: { ...FIXTURE_ZOOM },
    editions: FIXTURE_EDITIONS.map(editionRecord),
  };
}

function lonToX(lon: number, zoom: number): number {
  return ((lon + 180) / 360) * 2 ** zoom;
}

function latToY(lat: number, zoom: number): number {
  const radians = (lat * Math.PI) / 180;
  const mercator = Math.log(Math.tan(Math.PI / 4 + radians / 2));
  return (1 - mercator / Math.PI) * 2 ** (zoom - 1);
}

export interface TileCoordinate {
  z: number;
  x: number;
  y: number;
}

/** Every XYZ tile the fixture bounds touch, over the fixture zoom range. */
export function fixtureTiles(): TileCoordinate[] {
  const [west, south, east, north] = FIXTURE_BOUNDS;
  const tiles: TileCoordinate[] = [];
  for (let z = FIXTURE_ZOOM.min; z <= FIXTURE_ZOOM.max; z += 1) {
    const last = 2 ** z - 1;
    const xMin = Math.max(0, Math.floor(lonToX(west, z)));
    const xMax = Math.min(last, Math.ceil(lonToX(east, z)) - 1);
    const yMin = Math.max(0, Math.floor(latToY(north, z)));
    const yMax = Math.min(last, Math.ceil(latToY(south, z)) - 1);
    for (let x = xMin; x <= xMax; x += 1) {
      for (let y = yMin; y <= yMax; y += 1) {
        tiles.push({ z, x, y });
      }
    }
  }
  return tiles;
}

/**
 * Write the manifest and the four flat-colour pyramids under `root`. Deterministic: the same
 * bytes every run, so a test that waits for a tile is waiting on nothing but the browser.
 */
export function writeFixtures(root: string): { manifestPath: string; tileRoot: string } {
  const manifestPath = join(root, FIXTURE_MANIFEST_NAME);
  const tileRoot = join(root, "tiles");
  mkdirSync(root, { recursive: true });
  writeFileSync(manifestPath, `${JSON.stringify(fixtureSourceManifest(), null, 2)}\n`);

  const coordinates = fixtureTiles();
  for (const edition of FIXTURE_EDITIONS) {
    const png = solidPng(TILE_SIZE, edition.colour);
    for (const { z, x, y } of coordinates) {
      const path = join(tileRoot, edition.id, String(z), String(x), `${y}.png`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, png);
    }
  }
  return { manifestPath, tileRoot };
}
