// Unit coverage for issues #42 and #43: order and default, endpoint limits, direct
// selection, the independent reset, the proof that a switch builds no second map and moves
// no camera, and the requested/displayed contract with its generation and viewport gating.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { afterAll, describe, expect, it } from "vitest";

import {
  EditionBrowser,
  type Bounds,
  type MapLike,
  type PublicEdition,
  type PublicManifest,
  boundsOverlap,
  cardRows,
  containsPoint,
  coverageNotice,
  detailLimitNotice,
  layerIdFor,
  noticeFor,
  publicManifestFrom,
  resamplingFor,
  scaleLabel,
  sourceIdFor,
} from "./editions";

// Every path under test is synchronous, so any rejection here is a defect, not a race.
const rejections: unknown[] = [];
process.on("unhandledRejection", (reason) => rejections.push(reason));
afterAll(() => {
  expect(rejections).toEqual([]);
});

const MANIFEST_PATH = fileURLToPath(
  new URL("../../data/sources/demo-editions.json", import.meta.url),
);

function realManifest(): PublicManifest {
  return publicManifestFrom(JSON.parse(readFileSync(MANIFEST_PATH, "utf8")));
}

/**
 * Records every property access, so an unexpected camera call fails the test instead of
 * being silently allowed. MapLibre's camera surface is much wider than MapLike.
 */
const CAMERA_METHODS = [
  "fitBounds",
  "jumpTo",
  "easeTo",
  "flyTo",
  "panTo",
  "panBy",
  "zoomTo",
  "zoomIn",
  "zoomOut",
  "setCenter",
  "setZoom",
  "setBearing",
  "setPitch",
  "setMaxBounds",
  "setPadding",
  "resetNorth",
  "rotateTo",
  "setMinZoom",
  "setMaxZoom",
] as const;

interface Camera {
  lng: number;
  lat: number;
  zoom: number;
}

interface FakeMap extends MapLike {
  calls: Array<{ method: string; args: unknown[] }>;
  visibility: Record<string, string>;
  opacity: Record<string, number>;
  tiles: Record<string, string[]>;
  /** Moved by every camera method, so an unwanted call shows up as a moved camera. */
  camera: Camera;
  /** What the user can actually see: visible and not fully transparent. */
  onScreen(): string[];
}

const START_CAMERA: Camera = { lng: -121.0725, lat: 38.8965, zoom: 13 };

let mapsBuilt = 0;

function buildMap(layerIds: string[], initialLayer: string): FakeMap {
  mapsBuilt += 1;
  const calls: Array<{ method: string; args: unknown[] }> = [];
  const visibility: Record<string, string> = {};
  const opacity: Record<string, number> = {};
  const tiles: Record<string, string[]> = {};
  // The style ships the initial edition visible at zero opacity: it is loading, not shown.
  for (const id of layerIds) {
    visibility[id] = id === initialLayer ? "visible" : "none";
    opacity[id] = 0;
  }
  const map = {
    calls,
    visibility,
    opacity,
    tiles,
    camera: { ...START_CAMERA },
    onScreen: () => layerIds.filter((id) => visibility[id] === "visible" && opacity[id] > 0),
    setSourceTiles(sourceId: string, next: string[]) {
      calls.push({ method: "setSourceTiles", args: [sourceId, next] });
      tiles[sourceId] = next;
    },
    setLayoutProperty(layerId: string, name: string, value: unknown) {
      calls.push({ method: "setLayoutProperty", args: [layerId, name, value] });
      if (name === "visibility") {
        visibility[layerId] = value as string;
      }
    },
    setPaintProperty(layerId: string, name: string, value: unknown) {
      calls.push({ method: "setPaintProperty", args: [layerId, name, value] });
      if (name === "raster-opacity") {
        opacity[layerId] = value as number;
      }
    },
  } as FakeMap;
  for (const method of CAMERA_METHODS) {
    (map as unknown as Record<string, unknown>)[method] = (...args: unknown[]) => {
      calls.push({ method, args });
      // A whole degree and a whole zoom level: any stray camera call fails the tolerance
      // assertions loudly instead of hiding inside them.
      map.camera = { lng: map.camera.lng + 1, lat: map.camera.lat + 1, zoom: 12 };
    };
  }
  return map;
}

/**
 * `ready` finishes the first edition's load, the state a user meets before touching a
 * control, and clears the recorder so a test sees only the calls it makes itself.
 */
function browserFor(
  manifest: PublicManifest,
  options: { ready?: boolean } = {},
): { browser: EditionBrowser; map: FakeMap } {
  const map = buildMap(
    manifest.edition_order.map(layerIdFor),
    layerIdFor(manifest.initial_edition),
  );
  const browser = new EditionBrowser({ manifest, map });
  if (options.ready !== false) {
    browser.confirmDisplayed(manifest.initial_edition, browser.state.generation);
    map.calls.length = 0;
  }
  return { browser, map };
}

function browserForRealManifest(options: { ready?: boolean } = {}): {
  browser: EditionBrowser;
  map: FakeMap;
} {
  return browserFor(realManifest(), options);
}

/** The camera tolerance the acceptance criteria name. */
function expectSameCamera(before: Camera, after: Camera): void {
  expect(Math.abs(after.lng - before.lng)).toBeLessThan(1e-7);
  expect(Math.abs(after.lat - before.lat)).toBeLessThan(1e-7);
  expect(Math.abs(after.zoom - before.zoom)).toBeLessThan(1e-6);
}

const FIXTURE_FIELDS = {
  source_kind: "historical_geotiff",
  sheet_name: "Fixtureville",
  scale: 24000,
  printed_credit_note: null,
  publication_date: null,
  component_dates: { survey_year: null, edit_year: null, imprint_year: null },
  native_resolution_metres: 2.03,
  native_max_zoom: 16,
  coverage_bounds_wgs84: [-121.1, 38.9, -121.0, 39.0] as Bounds,
  registration_note: null,
} as const;

const SYNTHETIC: PublicManifest = {
  version: 2,
  area_id: "fixture",
  edition_order: ["fixture-a", "fixture-b"],
  initial_edition: "fixture-a",
  view_bounds_wgs84: [-121.1, 38.9, -121.0, 39.0],
  pan_bounds_wgs84: [-121.1, 38.9, -121.0, 39.0],
  tile_zoom: { min: 10, max: 16 },
  editions: [
    {
      id: "fixture-a",
      source_id: "FIXTURE_A",
      kind: "topo",
      label: "fixture A",
      citation: "fixture A citation",
      source_url: "https://example.invalid/a",
      rights: "public_domain",
      attribution: "fixture attribution",
      dates: {
        map_year: 1900,
        base_year: 1900,
        revision_year: null,
        base_photography: "1899",
        revision_photography: null,
        photography: null,
        base_field_check_year: 1900,
        revision_field_checked: null,
      },
      date_note: "fixture A note",
      ...FIXTURE_FIELDS,
      tile_url: "tiles/fixture-a/{z}/{x}/{y}.png",
    },
    {
      id: "fixture-b",
      source_id: "FIXTURE_B",
      kind: "orthophotoquad",
      label: "fixture B",
      citation: "fixture B citation",
      source_url: "https://example.invalid/b",
      rights: "public_domain",
      attribution: "fixture attribution",
      dates: {
        map_year: 1901,
        base_year: null,
        revision_year: null,
        base_photography: null,
        revision_photography: null,
        photography: "1901-05-04",
        base_field_check_year: null,
        revision_field_checked: null,
      },
      date_note: "fixture B note",
      ...FIXTURE_FIELDS,
      tile_url: "tiles/fixture-b/{z}/{x}/{y}.png",
    },
  ],
};

const NINE = [
  "sacramento-1891",
  "auburn-1944",
  "auburn-1953",
  "auburn-1973",
  "auburn-1975",
  "auburn-1981",
  "sacramento-1994",
  "auburn-2018",
  "auburn-2021",
];

describe("publicManifestFrom", () => {
  it("keeps the nine editions in display order and drops crop geometry", () => {
    const manifest = realManifest();
    expect(manifest.edition_order).toEqual(NINE);
    expect(manifest.initial_edition).toBe("auburn-1953");
    expect(manifest.editions.map((edition) => edition.id)).toEqual(manifest.edition_order);
    for (const edition of manifest.editions) {
      expect(edition).not.toHaveProperty("crop_wgs84");
      expect(edition.tile_url).toBe(`tiles/${edition.id}/{z}/{x}/{y}.png`);
      expect(edition.rights).toBe("public_domain");
    }
    expect(manifest.tile_zoom).toEqual({ min: 10, max: 16 });
    expect(manifest.view_bounds_wgs84).toHaveLength(4);
  });

  it("carries the exact source IDs the demo is pinned to", () => {
    expect(realManifest().editions.map((edition) => edition.source_id)).toEqual([
      "CA_Sacramento_299588_1891_125000",
      "CA_Auburn_296741_1944_62500",
      "CA_Auburn_288101_1953_24000",
      "CA_Auburn_288103_1953_24000",
      "CA_Auburn_288104_1975_24000",
      "CA_Auburn_288105_1953_24000",
      "CA_Sacramento_299157_1994_100000",
      "5d3aeb27e4b01d82ce8d133b",
      "61d7a9e2d34ed79294005276",
    ]);
  });

  it("carries each sheet's own top zoom, capped at the shared maximum", () => {
    const zooms = Object.fromEntries(
      realManifest().editions.map((edition) => [edition.id, edition.native_max_zoom]),
    );
    expect(zooms).toEqual({
      "sacramento-1891": 14,
      "auburn-1944": 15,
      "auburn-1953": 16,
      "auburn-1973": 16,
      "auburn-1975": 16,
      "auburn-1981": 16,
      "sacramento-1994": 14,
      "auburn-2018": 16,
      "auburn-2021": 16,
    });
    const source = JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
    source.tile_zoom.max = 15;
    const capped = publicManifestFrom(source);
    expect(capped.editions.map((edition) => edition.native_max_zoom)).toEqual([
      14, 15, 15, 15, 15, 15, 14, 15, 15,
    ]);
  });

  it("refuses an initial edition that is not in the order", () => {
    const source = JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
    source.initial_edition = "auburn-1999";
    expect(() => publicManifestFrom(source)).toThrow(/initial_edition/);
  });
});

describe("resamplingFor", () => {
  it("resamples scanned sheets nearest and the orthophotoquad linearly", () => {
    const manifest = realManifest();
    const byKind = Object.fromEntries(
      manifest.editions.map((edition) => [edition.id, resamplingFor(edition.kind)]),
    );
    expect(byKind).toEqual({
      "sacramento-1891": "nearest",
      "auburn-1944": "nearest",
      "auburn-1953": "nearest",
      "auburn-1973": "nearest",
      "auburn-1975": "linear",
      "auburn-1981": "nearest",
      "sacramento-1994": "nearest",
      "auburn-2018": "nearest",
      "auburn-2021": "nearest",
    });
  });
});

describe("order and default", () => {
  it("requests the 1953 sheet first and displays nothing until its tiles load", () => {
    const { browser, map } = browserForRealManifest({ ready: false });
    expect(browser.state.requestedId).toBe("auburn-1953");
    expect(browser.state.displayedId).toBeNull();
    expect(browser.state.status).toBe("loading");
    expect(map.onScreen()).toEqual([]);

    browser.confirmDisplayed("auburn-1953", browser.state.generation);
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(browser.state.status).toBe("displayed");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("walks the fixed order forwards and back again from the 1953 sheet", () => {
    const { browser } = browserForRealManifest();
    const seen = [browser.state.displayedId];
    while (browser.canGoNext) {
      const generation = browser.next();
      browser.confirmDisplayed(browser.state.requestedId, generation);
      seen.push(browser.state.displayedId);
    }
    expect(seen).toEqual(NINE.slice(2));
    while (browser.canGoPrevious) {
      const generation = browser.previous();
      browser.confirmDisplayed(browser.state.requestedId, generation);
      seen.push(browser.state.displayedId);
    }
    expect(seen.slice(NINE.length - 2)).toEqual([...NINE].reverse().slice(1));
  });

  it("starts on the initial edition even though it is not first in the order", () => {
    expect(() =>
      browserFor({ ...SYNTHETIC, initial_edition: "fixture-z" }, { ready: false }),
    ).toThrow(/initial edition/);
    const { browser } = browserFor({ ...SYNTHETIC, initial_edition: "fixture-b" });
    expect(browser.state.displayedId).toBe("fixture-b");
    expect(browser.canGoPrevious).toBe(true);
    expect(browser.canGoNext).toBe(false);
  });
});

describe("endpoint disabling", () => {
  it("disables previous on the first edition and next on the last", () => {
    const { browser } = browserForRealManifest();
    // 1953 sits in the middle of the order, so both directions start enabled.
    expect(browser.canGoPrevious).toBe(true);
    expect(browser.canGoNext).toBe(true);

    browser.confirmDisplayed("sacramento-1891", browser.select("sacramento-1891"));
    expect(browser.canGoPrevious).toBe(false);
    expect(browser.canGoNext).toBe(true);

    browser.confirmDisplayed("auburn-2021", browser.select("auburn-2021"));
    expect(browser.canGoPrevious).toBe(true);
    expect(browser.canGoNext).toBe(false);
  });

  it("does not wrap when the disabled direction is invoked anyway", () => {
    const { browser } = browserForRealManifest();
    browser.confirmDisplayed("sacramento-1891", browser.select("sacramento-1891"));
    const first = browser.state.generation;
    browser.previous();
    expect(browser.state.requestedId).toBe("sacramento-1891");
    expect(browser.state.generation).toBe(first);

    browser.confirmDisplayed("auburn-2021", browser.select("auburn-2021"));
    const generation = browser.state.generation;
    browser.next();
    expect(browser.state.requestedId).toBe("auburn-2021");
    expect(browser.state.generation).toBe(generation);
  });
});

describe("direct selection", () => {
  it("jumps straight to a non-adjacent edition", () => {
    const { browser, map } = browserForRealManifest();
    const generation = browser.select("auburn-1981");
    expect(browser.state.requestedId).toBe("auburn-1981");
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(browser.state.status).toBe("loading");

    browser.confirmDisplayed("auburn-1981", generation);
    expect(browser.state.displayedId).toBe("auburn-1981");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1981")]);
  });

  it("rejects an unknown edition id", () => {
    const { browser } = browserForRealManifest();
    expect(() => browser.select("auburn-1999")).toThrow(/unknown edition/);
  });
});

describe("requested versus displayed state", () => {
  it("holds the prior edition and its card while the request is loading", () => {
    const { browser, map } = browserForRealManifest();
    browser.select("auburn-1975");
    expect(browser.requestedEdition.id).toBe("auburn-1975");
    expect(browser.displayedEdition?.id).toBe("auburn-1953");
    // The requested layer is loading at zero opacity; only 1953 is on screen.
    expect(map.visibility[layerIdFor("auburn-1975")]).toBe("visible");
    expect(map.opacity[layerIdFor("auburn-1975")]).toBe(0);
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("keeps the last valid layer and card when a request fails", () => {
    const { browser, map } = browserForRealManifest();
    const generation = browser.select("auburn-1973");
    expect(browser.failRequest("auburn-1973", generation, "tiles unavailable")).toBe(true);
    expect(browser.state.status).toBe("error");
    expect(browser.state.errorMessage).toBe("tiles unavailable");
    expect(browser.displayedEdition?.id).toBe("auburn-1953");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("ignores a readiness signal that arrives after the same request failed", () => {
    const { browser, map } = browserForRealManifest();
    const generation = browser.select("auburn-1973");
    browser.failRequest("auburn-1973", generation, "tiles unavailable");

    expect(browser.confirmDisplayed("auburn-1973", generation)).toBe(false);
    expect(browser.displayedEdition?.id).toBe("auburn-1953");
    expect(browser.state.status).toBe("error");
    expect(browser.state.errorMessage).toBe("tiles unavailable");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("ignores a late result from a superseded request", () => {
    const { browser, map } = browserFor(SYNTHETIC);
    const stale = browser.select("fixture-b");
    const current = browser.select("fixture-a");
    expect(stale).not.toBe(current);
    expect(browser.confirmDisplayed("fixture-b", stale)).toBe(false);
    expect(browser.failRequest("fixture-b", stale, "late error")).toBe(false);
    expect(browser.state.displayedId).toBe("fixture-a");
    expect(browser.state.errorMessage).toBeNull();
    // The abandoned edition stops loading and never reaches the screen.
    expect(map.visibility[layerIdFor("fixture-b")]).toBe("none");
    expect(map.onScreen()).toEqual([layerIdFor("fixture-a")]);
  });

  it("re-requests under a fresh generation on retry", () => {
    const { browser } = browserForRealManifest();
    const first = browser.select("auburn-1973");
    browser.failRequest("auburn-1973", first, "tiles unavailable");
    const second = browser.retry();
    expect(second).toBeGreaterThan(first);
    expect(browser.state.status).toBe("loading");
    expect(browser.state.errorMessage).toBeNull();
    expect(browser.confirmDisplayed("auburn-1973", first)).toBe(false);
    expect(browser.confirmDisplayed("auburn-1973", second)).toBe(true);
  });
});

describe("one map, no camera movement on switch", () => {
  it("builds exactly one map for a full traversal", () => {
    const before = mapsBuilt;
    const { browser } = browserForRealManifest();
    expect(mapsBuilt).toBe(before + 1);
    for (const id of [...NINE, "auburn-1953"]) {
      browser.confirmDisplayed(id, browser.select(id));
    }
    expect(mapsBuilt).toBe(before + 1);
  });

  it("touches only layer visibility and opacity while switching editions", () => {
    const { browser, map } = browserForRealManifest();
    for (const id of [...NINE, "auburn-1953"]) {
      browser.confirmDisplayed(id, browser.select(id));
    }
    browser.previous();
    browser.next();
    expect(map.calls.length).toBeGreaterThan(0);
    expect([...new Set(map.calls.map((call) => call.method))].sort()).toEqual([
      "setLayoutProperty",
      "setPaintProperty",
    ]);
    expect(
      map.calls.every(
        (call) => call.args[1] === "visibility" || call.args[1] === "raster-opacity",
      ),
    ).toBe(true);
    expect(browser.resetViewCalls).toBe(0);
  });

  it("shows exactly one edition at every step of a switch", () => {
    const { browser, map } = browserForRealManifest();
    const generation = browser.select("auburn-1975");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
    browser.confirmDisplayed("auburn-1975", generation);
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1975")]);
    expect(map.calls.map((call) => call.args)).toEqual([
      [layerIdFor("auburn-1975"), "visibility", "visible"],
      [layerIdFor("auburn-1975"), "raster-opacity", 0],
      [layerIdFor("auburn-1975"), "raster-opacity", 1],
      [layerIdFor("auburn-1953"), "visibility", "none"],
    ]);
  });
});

describe("reset view is a separate action", () => {
  it("fits the shared bounds without changing the selected edition", () => {
    const { browser, map } = browserForRealManifest();
    browser.confirmDisplayed("auburn-1973", browser.select("auburn-1973"));
    map.calls.length = 0;

    browser.resetView();

    expect(browser.state.requestedId).toBe("auburn-1973");
    expect(browser.state.displayedId).toBe("auburn-1973");
    expect(map.calls.map((call) => call.method)).toEqual(["fitBounds"]);
    expect(map.calls[0].args[0]).toEqual(browser.manifest.view_bounds_wgs84);
    expect(map.calls[0].args[1]).toMatchObject({ bearing: 0, pitch: 0 });
    expect(browser.resetViewCalls).toBe(1);
  });

  it("is the only action that fits bounds", () => {
    const { browser, map } = browserForRealManifest();
    browser.next();
    browser.previous();
    browser.select("auburn-1981");
    expect(map.calls.filter((call) => call.method === "fitBounds")).toHaveLength(0);
  });
});

describe("source card content", () => {
  it("names the exact source id, url, product type and attribution", () => {
    const manifest = realManifest();
    for (const edition of manifest.editions) {
      const card = cardRows(edition);
      const values = card.rows.map((row) => row.value).join("\n");
      expect(values).toContain(edition.source_id);
      expect(card.sourceUrl).toBe(edition.source_url);
      expect(card.attribution).toBe(edition.attribution);
      expect(card.attribution).toContain("U.S. Geological Survey");
      expect(card.citation).toBe(edition.citation);
      expect(card.dateNote).toBe(edition.date_note);
      expect(card.rows.some((row) => row.label === "Product")).toBe(true);
    }
  });

  it("labels the 1975 sheet an orthophotoquad with its photography date and no revision", () => {
    const manifest = realManifest();
    const card = cardRows(manifest.editions.find((e) => e.id === "auburn-1975")!);
    const rows = Object.fromEntries(card.rows.map((row) => [row.label, row.value]));
    expect(rows.Product).toBe("Orthophotoquad");
    expect(rows.Photography).toBe("1975-08-29");
    expect(rows).not.toHaveProperty("Revision");
    expect(rows).not.toHaveProperty("Base sheet");
    expect(rows).not.toHaveProperty("Field check");
    expect(card.dateNote).toContain("1975-08-29");
  });

  it("separates the 1981 revision from its 1978 photography and the 1953 base", () => {
    const manifest = realManifest();
    const card = cardRows(manifest.editions.find((e) => e.id === "auburn-1981")!);
    const rows = Object.fromEntries(card.rows.map((row) => [row.label, row.value]));
    expect(rows.Product).toBe("Topographic map");
    expect(rows["Base sheet"]).toBe("1953 (photography 1952)");
    expect(rows.Revision).toBe("photorevised 1981 (photography 1978)");
    expect(rows["Field check"]).toBe("base field checked 1953; revision not field checked");
    expect(card.dateNote).toContain("other source data");
  });

  it("distinguishes the 1973 revision from the 1981 revision", () => {
    const manifest = realManifest();
    const rowsFor = (id: string) =>
      Object.fromEntries(
        cardRows(manifest.editions.find((e) => e.id === id)!).rows.map((r) => [
          r.label,
          r.value,
        ]),
      );
    expect(rowsFor("auburn-1973").Revision).toBe("photorevised 1973 (photography 1973)");
    expect(rowsFor("auburn-1981").Revision).toBe("photorevised 1981 (photography 1978)");
  });

  it("states no base, revision or field check for the 1953 sheet's missing revision", () => {
    const manifest = realManifest();
    const rows = Object.fromEntries(
      cardRows(manifest.editions.find((e) => e.id === "auburn-1953")!).rows.map((r) => [
        r.label,
        r.value,
      ]),
    );
    expect(rows["Base sheet"]).toBe("1953 (photography 1952)");
    expect(rows).not.toHaveProperty("Revision");
    expect(rows["Field check"]).toBe("base field checked 1953");
  });

  it("asserts nothing about present-day access", () => {
    const manifest = realManifest();
    const forbidden = /right of way|public access|easement|prescriptive|trespass|you may use/i;
    for (const edition of manifest.editions) {
      const card = cardRows(edition);
      const text = [
        card.citation,
        card.dateNote,
        card.attribution,
        card.credits ?? "",
        detailLimitNotice(edition, 16) ?? "",
        ...card.rows.map((r) => r.value),
      ].join("\n");
      expect(text).not.toMatch(forbidden);
    }
  });

  const rowsOf = (id: string) =>
    Object.fromEntries(
      cardRows(realManifest().editions.find((e) => e.id === id)!).rows.map((r) => [
        r.label,
        r.value,
      ]),
    );

  it("names the regional and 15-minute sheets by their own sheet and scale", () => {
    expect(rowsOf("sacramento-1891").Sheet).toBe("Sacramento 1:125,000");
    expect(rowsOf("sacramento-1994").Sheet).toBe("Sacramento 1:100,000");
    expect(rowsOf("auburn-1944").Sheet).toBe("Auburn 1:62,500");
    expect(rowsOf("auburn-1953").Sheet).toBe("Auburn 1:24,000");
    expect(scaleLabel(125000)).toBe("1:125,000");
    for (const id of ["sacramento-1891", "sacramento-1994"]) {
      const edition = realManifest().editions.find((e) => e.id === id)!;
      expect(edition.label).toContain("Sacramento");
      expect(edition.date_note).toContain("not an Auburn 7.5-minute map");
    }
  });

  it("gives the date basis each sheet records and omits what it does not", () => {
    const sacramento = rowsOf("sacramento-1891");
    expect(sacramento.Surveyed).toBe("1888");
    expect(sacramento["Map year on sheet"]).toBe("1891");
    expect(sacramento).not.toHaveProperty("Edited");
    expect(sacramento).not.toHaveProperty("Printed");
    expect(sacramento).not.toHaveProperty("Published");
    expect(sacramento).not.toHaveProperty("Revision");

    expect(rowsOf("sacramento-1994").Edited).toBe("1994");
    expect(rowsOf("auburn-1953").Printed).toBe("1955");
    expect(rowsOf("auburn-1953")).not.toHaveProperty("Surveyed");
  });

  it("names the US Topo products, their publication dates and printed credits", () => {
    const manifest = realManifest();
    for (const [id, published] of [
      ["auburn-2018", "2018-09-24"],
      ["auburn-2021", "2021-12-30"],
    ]) {
      const edition = manifest.editions.find((e) => e.id === id)!;
      const card = cardRows(edition);
      const rows = Object.fromEntries(card.rows.map((r) => [r.label, r.value]));
      expect(rows.Product).toBe("US Topo map");
      expect(rows.Published).toBe(published);
      expect(rows).not.toHaveProperty("Base sheet");
      expect(rows).not.toHaveProperty("Field check");
      expect(card.credits).toBe(edition.printed_credit_note);
      expect(card.credits).toContain("Produced by the United States Geological Survey");
      expect(card.attribution).toBe("US Topo maps: U.S. Geological Survey");
    }
    for (const edition of manifest.editions.filter((e) => e.source_kind !== "us_topo_pdf")) {
      expect(cardRows(edition).credits).toBeNull();
    }
  });

  it("states each sheet's detail limit", () => {
    expect(rowsOf("sacramento-1891")["Detail limit"]).toBe(
      "zoom 14 (source pixel about 10.58 m)",
    );
    expect(rowsOf("auburn-1953")["Detail limit"]).toBe("zoom 16 (source pixel about 2.03 m)");
  });
});

describe("detail-limit notice", () => {
  it("speaks only when the camera is past the edition's own top zoom", () => {
    const manifest = realManifest();
    const sacramento = manifest.editions.find((e) => e.id === "sacramento-1891")!;
    const auburn = manifest.editions.find((e) => e.id === "auburn-1953")!;
    expect(detailLimitNotice(sacramento, 14)).toBeNull();
    expect(detailLimitNotice(sacramento, 13.5)).toBeNull();
    const notice = detailLimitNotice(sacramento, 15.2);
    expect(notice).toContain("zoom 14");
    expect(notice).toContain(sacramento.label);
    expect(notice).toContain("no more detail");
    expect(detailLimitNotice(auburn, 16)).toBeNull();
  });

  it("never moves the camera to avoid the overzoom", () => {
    const { browser, map } = browserForRealManifest();
    map.camera = { ...map.camera, zoom: 16 };
    const before = { ...map.camera };
    browser.confirmDisplayed("sacramento-1891", browser.select("sacramento-1891"));
    browser.confirmDisplayed("auburn-1944", browser.select("auburn-1944"));
    browser.confirmDisplayed("auburn-2021", browser.select("auburn-2021"));
    expectSameCamera(before, map.camera);
    expect(map.calls.some((call) => CAMERA_METHODS.includes(call.method as never))).toBe(false);
  });
});

describe("first load with no prior valid edition", () => {
  it("keeps the map empty and names no edition when the first load fails", () => {
    const { browser, map } = browserForRealManifest({ ready: false });
    const before = { ...map.camera };

    expect(browser.failRequest("auburn-1953", browser.state.generation, "HTTP 404")).toBe(true);
    expect(browser.state.status).toBe("error");
    expect(browser.state.displayedId).toBeNull();
    expect(browser.displayedEdition).toBeNull();
    expect(map.onScreen()).toEqual([]);
    expect(noticeFor(browser.state, browser)).toContain("No edition is on screen yet");
    expect(noticeFor(browser.state, browser)).toContain("HTTP 404");
    expectSameCamera(before, map.camera);
  });

  it("recovers on retry from a failed first load", () => {
    const { browser, map } = browserForRealManifest({ ready: false });
    browser.failRequest("auburn-1953", browser.state.generation, "HTTP 404");

    const generation = browser.retry();
    expect(browser.state.status).toBe("loading");
    expect(browser.state.errorMessage).toBeNull();
    // The retry asks for tiles the browser cache has not already failed on.
    expect(map.tiles["edition-auburn-1953"]).toEqual([
      "tiles/auburn-1953/{z}/{x}/{y}.png?reload=1",
    ]);
    expect(browser.confirmDisplayed("auburn-1953", generation)).toBe(true);
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
    expect(noticeFor(browser.state, browser)).toBe(
      `Showing ${browser.edition("auburn-1953").label}.`,
    );
  });
});

describe("viewport changes during a load", () => {
  it("rejects readiness measured before the camera moved and accepts it afterwards", () => {
    const { browser, map } = browserForRealManifest();
    const before = { ...map.camera };
    const generation = browser.select("auburn-1975");
    const staleToken = browser.state.viewportToken;

    const token = browser.noteCameraMove();
    expect(token).toBeGreaterThan(staleToken);
    expect(browser.confirmDisplayed("auburn-1975", generation, staleToken)).toBe(false);
    expect(browser.state.status).toBe("loading");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);

    expect(browser.confirmDisplayed("auburn-1975", generation, token)).toBe(true);
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1975")]);
    expectSameCamera(before, map.camera);
  });

  it("keeps the selection and its generation across a camera move", () => {
    const { browser } = browserForRealManifest();
    const generation = browser.select("auburn-1981");
    browser.noteCameraMove();
    expect(browser.state.requestedId).toBe("auburn-1981");
    expect(browser.state.generation).toBe(generation);
  });
});

describe("rapid switching", () => {
  it("lets the last choice win and rejects every superseded result", () => {
    const { browser, map } = browserForRealManifest();
    const first = browser.select("auburn-1973");
    const second = browser.select("auburn-1975");
    const third = browser.select("auburn-1981");

    expect(browser.confirmDisplayed("auburn-1973", first)).toBe(false);
    expect(browser.failRequest("auburn-1975", second, "late error")).toBe(false);
    expect(browser.confirmDisplayed("auburn-1981", third)).toBe(true);
    expect(browser.state.displayedId).toBe("auburn-1981");
    expect(browser.state.errorMessage).toBeNull();
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1981")]);
    for (const abandoned of ["auburn-1973", "auburn-1975"]) {
      expect(map.visibility[layerIdFor(abandoned)]).toBe("none");
    }
  });

  it("stops loading an edition the user switched back away from", () => {
    const { browser, map } = browserForRealManifest();
    browser.select("auburn-1975");
    const back = browser.select("auburn-1953");
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(map.visibility[layerIdFor("auburn-1975")]).toBe("none");
    expect(browser.confirmDisplayed("auburn-1975", back)).toBe(false);
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });
});

describe("tile failures after a settled switch", () => {
  it("warns without unsetting the layer, and survives a later pan", () => {
    const { browser, map } = browserForRealManifest();
    browser.confirmDisplayed("auburn-1973", browser.select("auburn-1973"));

    browser.noteTileWarning("HTTP 404");
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.displayedId).toBe("auburn-1973");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1973")]);
    const notice = noticeFor(browser.state, browser);
    expect(notice).toContain(browser.edition("auburn-1973").label);
    expect(notice).toContain("HTTP 404");
    expect(notice).toContain("blank area");

    browser.noteCameraMove();
    expect(browser.state.warningMessage).toBe("HTTP 404");
  });

  it("keeps the warning until the user retries or the displayed edition changes", () => {
    const { browser, map } = browserForRealManifest();
    browser.confirmDisplayed("auburn-1973", browser.select("auburn-1973"));
    browser.noteTileWarning("HTTP 404");

    // No number of settled viewports retires it: MapLibre caches the errored tiles.
    browser.noteCameraMove();
    browser.noteCameraMove();
    expect(browser.state.warningMessage).toBe("HTTP 404");

    browser.retry();
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.displayedId).toBe("auburn-1973");
    expect(browser.state.warningMessage).toBeNull();
    // The refetch is the point of the retry: cached failures need a fresh URL.
    expect(map.tiles[sourceIdFor("auburn-1973")]).toEqual([
      "tiles/auburn-1973/{z}/{x}/{y}.png?reload=1",
    ]);
  });

  it("says nothing about failures when a bounded pyramid is simply empty here", () => {
    const { browser } = browserForRealManifest();
    browser.confirmDisplayed("auburn-1975", browser.select("auburn-1975"));
    browser.noteCameraMove();
    // A transparent tile loads normally: blank is not an error and gets no warning.
    expect(browser.state.warningMessage).toBeNull();
    expect(noticeFor(browser.state, browser)).toBe(
      `Showing ${browser.edition("auburn-1975").label}.`,
    );
  });

  it("retires the warning when a different edition reaches the screen", () => {
    const { browser } = browserForRealManifest();
    browser.noteTileWarning("HTTP 404");
    browser.confirmDisplayed("auburn-1981", browser.select("auburn-1981"));
    expect(browser.state.warningMessage).toBeNull();
  });

  it("keeps the failed switch's error separate from a warning", () => {
    const { browser } = browserForRealManifest();
    const generation = browser.select("auburn-1981");
    browser.failRequest("auburn-1981", generation, "HTTP 503");
    expect(browser.state.warningMessage).toBeNull();
    expect(noticeFor(browser.state, browser)).toBe(
      `Could not load ${browser.edition("auburn-1981").label}: HTTP 503. ` +
        `Still showing ${browser.edition("auburn-1953").label}.`,
    );
  });
});

describe("camera preservation across settled switches", () => {
  it("leaves centre and zoom untouched by every switch, failure and retry", () => {
    const { browser, map } = browserForRealManifest();
    const before = { ...map.camera };

    for (const id of ["auburn-1973", "auburn-1975", "auburn-1981", "auburn-1953"]) {
      const generation = browser.select(id);
      browser.noteCameraMove();
      browser.confirmDisplayed(id, generation, browser.state.viewportToken);
      expectSameCamera(before, map.camera);
    }

    const failing = browser.select("auburn-1975");
    browser.failRequest("auburn-1975", failing, "HTTP 404");
    expectSameCamera(before, map.camera);
    browser.confirmDisplayed("auburn-1975", browser.retry());
    expectSameCamera(before, map.camera);
    expect(map.calls.some((call) => CAMERA_METHODS.includes(call.method as never))).toBe(false);
  });
});

/** An extra edition shaped like the published 1916 scan: its own area and a placement note. */
function withScanEdition(): PublicManifest {
  const base = SYNTHETIC;
  const scan: PublicEdition = {
    ...base.editions[0],
    id: "fixture-scan",
    source_id: "SCAN_1",
    kind: "map",
    source_kind: "forest_service_scan",
    label: "fixture scan",
    scale: null,
    coverage_bounds_wgs84: [-120.9, 39.0, -120.0, 39.8],
    registration_note: "Placed by a fixture polynomial; off by about 400 m.",
    tile_url: "tiles/fixture-scan/{z}/{x}/{y}.png",
  };
  return {
    ...base,
    edition_order: [...base.edition_order, scan.id],
    pan_bounds_wgs84: [-121.1, 38.9, -120.0, 39.8],
    editions: [...base.editions, scan],
  };
}

describe("editions with their own coverage", () => {
  it("says when the edition on screen draws nothing in the viewport", () => {
    const scan = withScanEdition().editions[2];
    const auburn: Bounds = [-121.1, 38.9, -121.0, 39.0];
    expect(boundsOverlap(scan.coverage_bounds_wgs84, auburn)).toBe(false);
    expect(coverageNotice(scan, auburn)).toContain("does not cover the area on screen");
    expect(coverageNotice(scan, [-120.5, 39.2, -120.4, 39.3])).toBeNull();
    expect(containsPoint(scan.coverage_bounds_wgs84, -120.5, 39.5)).toBe(true);
  });

  it("switching to it leaves the camera alone; only the explicit action frames it", () => {
    const { browser, map } = browserFor(withScanEdition());
    browser.select("fixture-scan");
    expect(map.calls.filter((call) => call.method === "fitBounds")).toHaveLength(0);

    browser.showCoverage();

    const fits = map.calls.filter((call) => call.method === "fitBounds");
    expect(fits).toHaveLength(1);
    expect(fits[0].args[0]).toEqual([-120.9, 39.0, -120.0, 39.8]);
    expect(browser.state.requestedId).toBe("fixture-scan");
    expect(browser.showCoverageCalls).toBe(1);
    expect(browser.resetViewCalls).toBe(0);
  });

  it("cards an unprinted scale and the placement error instead of inventing them", () => {
    const card = cardRows(withScanEdition().editions[2]);
    const rows = Object.fromEntries(card.rows.map((row) => [row.label, row.value]));
    expect(rows.Product).toBe("Forest Service map (scan)");
    expect(rows.Sheet).toBe("Fixtureville (no printed scale found)");
    expect(rows.Placement).toContain("400 m");
    expect(resamplingFor("map")).toBe("nearest");
  });

  it("publishes no placement row for georeferenced sheets", () => {
    for (const edition of realManifest().editions) {
      expect(cardRows(edition).rows.some((row) => row.label === "Placement")).toBe(false);
    }
  });
});
