// Unit coverage for issue #42: order and default, endpoint limits, direct selection, the
// independent reset, and the proof that a switch builds no second map and moves no camera.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  EditionBrowser,
  type MapLike,
  type PublicManifest,
  cardRows,
  layerIdFor,
  publicManifestFrom,
  resamplingFor,
} from "./editions";

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

interface FakeMap extends MapLike {
  calls: Array<{ method: string; args: unknown[] }>;
  visibility: Record<string, string>;
  opacity: Record<string, number>;
  /** What the user can actually see: visible and not fully transparent. */
  onScreen(): string[];
}

let mapsBuilt = 0;

function buildMap(layerIds: string[]): FakeMap {
  mapsBuilt += 1;
  const calls: Array<{ method: string; args: unknown[] }> = [];
  const visibility: Record<string, string> = {};
  const opacity: Record<string, number> = {};
  for (const [index, id] of layerIds.entries()) {
    visibility[id] = index === 0 ? "visible" : "none";
    opacity[id] = 1;
  }
  const map = {
    calls,
    visibility,
    opacity,
    onScreen: () => layerIds.filter((id) => visibility[id] === "visible" && opacity[id] > 0),
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
    };
  }
  return map;
}

function browserForRealManifest(): { browser: EditionBrowser; map: FakeMap } {
  const manifest = realManifest();
  const map = buildMap(manifest.edition_order.map(layerIdFor));
  return { browser: new EditionBrowser({ manifest, map }), map };
}

const SYNTHETIC: PublicManifest = {
  version: 1,
  area_id: "fixture",
  edition_order: ["fixture-a", "fixture-b"],
  view_bounds_wgs84: [-121.1, 38.9, -121.0, 39.0],
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
      tile_url: "tiles/fixture-b/{z}/{x}/{y}.png",
    },
  ],
};

describe("publicManifestFrom", () => {
  it("keeps the four editions in display order and drops crop geometry", () => {
    const manifest = realManifest();
    expect(manifest.edition_order).toEqual([
      "auburn-1953",
      "auburn-1973",
      "auburn-1975",
      "auburn-1981",
    ]);
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
      "CA_Auburn_288101_1953_24000",
      "CA_Auburn_288103_1953_24000",
      "CA_Auburn_288104_1975_24000",
      "CA_Auburn_288105_1953_24000",
    ]);
  });
});

describe("resamplingFor", () => {
  it("resamples scanned sheets nearest and the orthophotoquad linearly", () => {
    const manifest = realManifest();
    const byKind = Object.fromEntries(
      manifest.editions.map((edition) => [edition.id, resamplingFor(edition.kind)]),
    );
    expect(byKind).toEqual({
      "auburn-1953": "nearest",
      "auburn-1973": "nearest",
      "auburn-1975": "linear",
      "auburn-1981": "nearest",
    });
  });
});

describe("order and default", () => {
  it("starts on the 1953 sheet with it displayed, not merely requested", () => {
    const { browser } = browserForRealManifest();
    expect(browser.state.requestedId).toBe("auburn-1953");
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(browser.state.status).toBe("displayed");
  });

  it("walks the fixed order forwards and back again", () => {
    const { browser } = browserForRealManifest();
    const seen = [browser.state.requestedId];
    while (browser.canGoNext) {
      const generation = browser.next();
      browser.confirmDisplayed(browser.state.requestedId, generation);
      seen.push(browser.state.displayedId);
    }
    expect(seen).toEqual(["auburn-1953", "auburn-1973", "auburn-1975", "auburn-1981"]);
    while (browser.canGoPrevious) {
      const generation = browser.previous();
      browser.confirmDisplayed(browser.state.requestedId, generation);
      seen.push(browser.state.displayedId);
    }
    expect(seen.slice(4)).toEqual(["auburn-1975", "auburn-1973", "auburn-1953"]);
  });
});

describe("endpoint disabling", () => {
  it("disables previous on the first edition and next on the last", () => {
    const { browser } = browserForRealManifest();
    expect(browser.canGoPrevious).toBe(false);
    expect(browser.canGoNext).toBe(true);

    browser.confirmDisplayed("auburn-1981", browser.select("auburn-1981"));
    expect(browser.canGoPrevious).toBe(true);
    expect(browser.canGoNext).toBe(false);
  });

  it("does not wrap when the disabled direction is invoked anyway", () => {
    const { browser } = browserForRealManifest();
    browser.previous();
    expect(browser.state.requestedId).toBe("auburn-1953");
    expect(browser.state.generation).toBe(0);

    browser.confirmDisplayed("auburn-1981", browser.select("auburn-1981"));
    const generation = browser.state.generation;
    browser.next();
    expect(browser.state.requestedId).toBe("auburn-1981");
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
    expect(browser.displayedEdition.id).toBe("auburn-1953");
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
    expect(browser.displayedEdition.id).toBe("auburn-1953");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("ignores a readiness signal that arrives after the same request failed", () => {
    const { browser, map } = browserForRealManifest();
    const generation = browser.select("auburn-1973");
    browser.failRequest("auburn-1973", generation, "tiles unavailable");

    expect(browser.confirmDisplayed("auburn-1973", generation)).toBe(false);
    expect(browser.displayedEdition.id).toBe("auburn-1953");
    expect(browser.state.status).toBe("error");
    expect(browser.state.errorMessage).toBe("tiles unavailable");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("ignores a late result from a superseded request", () => {
    const map = buildMap(SYNTHETIC.edition_order.map(layerIdFor));
    const browser = new EditionBrowser({ manifest: SYNTHETIC, map });
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
    for (const id of ["auburn-1973", "auburn-1975", "auburn-1981", "auburn-1953"]) {
      browser.confirmDisplayed(id, browser.select(id));
    }
    expect(mapsBuilt).toBe(before + 1);
  });

  it("touches only layer visibility and opacity while switching editions", () => {
    const { browser, map } = browserForRealManifest();
    for (const id of ["auburn-1973", "auburn-1975", "auburn-1981", "auburn-1953"]) {
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
        ...card.rows.map((r) => r.value),
      ].join("\n");
      expect(text).not.toMatch(forbidden);
    }
  });
});
