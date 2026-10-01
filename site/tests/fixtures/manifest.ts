// The fixture world the browser tests run against (issues #44, #58). Nothing here resembles
// the Auburn sources: the ids, labels, citations and years are invented on purpose, the
// bounds sit in the Gulf of Guinea, and the tiles are flat colour. A reader who mistakes this
// for evidence has only to look at it. The real manifest and the real pyramids are never
// served to the suite, so no source byte or receipt is touched by a test run.

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
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
  /** The top zoom this edition's tiles are cut to; above it the viewer must overzoom. */
  nativeMaxZoom: number;
  sheetName: string;
  scale: number;
  sourceKind: "historical_geotiff" | "us_topo_pdf";
  kind: "topo" | "orthophotoquad";
  mapYear: number;
  revisionYear: number | null;
  publicationDate: string | null;
  creditNote: string | null;
  surveyYear: number | null;
}

const BASE: Omit<FixtureEdition, "id" | "label" | "colour"> = {
  nativeMaxZoom: FIXTURE_ZOOM.max,
  sheetName: "Fixtureville",
  scale: 24000,
  sourceKind: "historical_geotiff",
  kind: "topo",
  mapYear: 1899,
  revisionYear: null,
  publicationDate: null,
  creditNote: null,
  surveyYear: null,
};

/**
 * Nine editions in display order, shaped like the real set: two coarse regional sheets that
 * stop below the shared top zoom, a mid-scale sheet, four base-scale sheets (one of them a
 * photo product) and two modern products with printed credits. The third is the initial
 * edition, so the viewer opens in the middle of the order. All values are invented.
 */
export const FIXTURE_EDITIONS: FixtureEdition[] = [
  {
    ...BASE,
    id: "fixture-regional-early",
    label: "Fixture regional sheet 1:125,000 (test data, 1880)",
    colour: { r: 120, g: 60, b: 160, a: 255 },
    nativeMaxZoom: 10,
    sheetName: "Fixture Regional",
    scale: 125000,
    mapYear: 1880,
    surveyYear: 1877,
  },
  {
    ...BASE,
    id: "fixture-midscale",
    label: "Fixture sheet 1:62,500 (test data, 1890)",
    colour: { r: 40, g: 160, b: 160, a: 255 },
    nativeMaxZoom: 11,
    scale: 62500,
    mapYear: 1890,
  },
  {
    ...BASE,
    id: "fixture-first",
    label: "Fixture sheet one (test data, 1899)",
    colour: { r: 220, g: 60, b: 60, a: 255 },
  },
  {
    ...BASE,
    id: "fixture-second",
    label: "Fixture sheet two (test data, 1899/1905)",
    colour: { r: 60, g: 140, b: 220, a: 255 },
    revisionYear: 1905,
  },
  {
    ...BASE,
    id: "fixture-third",
    label: "Fixture photo sheet (test data, 1911)",
    colour: { r: 90, g: 170, b: 90, a: 255 },
    kind: "orthophotoquad",
    mapYear: 1911,
  },
  {
    ...BASE,
    id: "fixture-fourth",
    label: "Fixture sheet four (test data, 1899/1920)",
    colour: { r: 190, g: 140, b: 40, a: 255 },
    revisionYear: 1920,
  },
  {
    ...BASE,
    id: "fixture-regional-late",
    label: "Fixture regional sheet 1:100,000 (test data, 1930)",
    colour: { r: 200, g: 90, b: 150, a: 255 },
    nativeMaxZoom: 10,
    sheetName: "Fixture Regional",
    scale: 100000,
    mapYear: 1930,
  },
  {
    ...BASE,
    id: "fixture-modern-one",
    label: "Fixture modern map one (test data, 1940)",
    colour: { r: 70, g: 70, b: 70, a: 255 },
    sourceKind: "us_topo_pdf",
    mapYear: 1940,
    publicationDate: "1940-02-03",
    creditNote: "Fixture credit note one | Roads ... invented (test data)",
  },
  {
    ...BASE,
    id: "fixture-modern-two",
    label: "Fixture modern map two (test data, 1950)",
    colour: { r: 150, g: 150, b: 40, a: 255 },
    sourceKind: "us_topo_pdf",
    mapYear: 1950,
    publicationDate: "1950-06-07",
    creditNote: "Fixture credit note two | Names ... invented (test data)",
  },
];

export const INITIAL_INDEX = 2;
export const INITIAL_EDITION = FIXTURE_EDITIONS[INITIAL_INDEX];

/** An unreachable host: a background request to it would be an obvious allowlist failure. */
export const FIXTURE_SOURCE_URL_HOST = "https://fixture-source-record.invalid";

function editionRecord(edition: FixtureEdition, index: number): Record<string, unknown> {
  const isPhoto = edition.kind === "orthophotoquad";
  const isModern = edition.sourceKind === "us_topo_pdf";
  const revisionYear = edition.revisionYear;
  return {
    id: edition.id,
    source_id: `FIXTURE_SOURCE_${index + 1}_NOT_A_REAL_SCAN`,
    kind: edition.kind,
    source_kind: edition.sourceKind,
    sheet_name: edition.sheetName,
    scale: edition.scale,
    label: edition.label,
    citation: `Fixture citation ${index + 1}. Invented for the browser test suite.`,
    source_url: `${FIXTURE_SOURCE_URL_HOST}/${edition.id}`,
    rights: "public_domain",
    attribution: `Fixture attribution ${index + 1} (test data)`,
    printed_credit_note: edition.creditNote,
    publication_date: edition.publicationDate,
    dates: {
      map_year: edition.mapYear,
      base_year: isPhoto || isModern ? null : edition.mapYear,
      revision_year: revisionYear,
      base_photography: isPhoto || isModern ? null : String(edition.mapYear - 1),
      revision_photography: revisionYear === null ? null : String(revisionYear - 2),
      photography: isPhoto ? "1911-07-04" : null,
      base_field_check_year: isPhoto || isModern ? null : edition.mapYear,
      revision_field_checked: revisionYear === null ? null : false,
    },
    component_dates: { survey_year: edition.surveyYear, edit_year: null, imprint_year: null },
    date_note: `Fixture date note ${index + 1}. No real survey is described.`,
    native_resolution_metres: edition.nativeMaxZoom === FIXTURE_ZOOM.max ? 2.0 : 9.5,
    native_max_zoom: edition.nativeMaxZoom,
  };
}

/** The `data/sources/demo-editions.json` shape, as the dev server expects to read it. */
export function fixtureSourceManifest(): Record<string, unknown> {
  return {
    version: 2,
    area_id: "fixture-area",
    edition_order: FIXTURE_EDITIONS.map((edition) => edition.id),
    initial_edition: INITIAL_EDITION.id,
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

/** Every XYZ tile the fixture bounds touch, from the fixture minimum up to `maxZoom`. */
export function fixtureTiles(maxZoom: number = FIXTURE_ZOOM.max): TileCoordinate[] {
  const [west, south, east, north] = FIXTURE_BOUNDS;
  const tiles: TileCoordinate[] = [];
  for (let z = FIXTURE_ZOOM.min; z <= maxZoom; z += 1) {
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
 * Write the manifest and the nine flat-colour pyramids under `root`. Deterministic: the same
 * bytes every run, so a test that waits for a tile is waiting on nothing but the browser.
 */
export function writeFixtures(root: string): { manifestPath: string; tileRoot: string } {
  const manifestPath = join(root, FIXTURE_MANIFEST_NAME);
  const tileRoot = join(root, "tiles");
  mkdirSync(root, { recursive: true });
  // A pyramid left from an earlier fixture could hold zooms this one no longer cuts.
  rmSync(tileRoot, { recursive: true, force: true });
  writeFileSync(manifestPath, `${JSON.stringify(fixtureSourceManifest(), null, 2)}\n`);
  writeFixtureTiles(tileRoot);
  return { manifestPath, tileRoot };
}

/**
 * The nine flat-colour pyramids under `tileRoot`, laid out as `<id>/<z>/<x>/<y>.png`. Each
 * stops at its own native zoom, as the real regional pyramids do: a request above it is a
 * 404, so a viewer that failed to overzoom would fail loudly rather than look fine.
 */
export function writeFixtureTiles(tileRoot: string): void {
  for (const edition of FIXTURE_EDITIONS) {
    const png = solidPng(TILE_SIZE, edition.colour);
    for (const { z, x, y } of fixtureTiles(edition.nativeMaxZoom)) {
      const path = join(tileRoot, edition.id, String(z), String(x), `${y}.png`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, png);
    }
  }
}
