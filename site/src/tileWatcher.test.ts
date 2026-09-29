// Deterministic coverage for issue #43: MapLibre source, error and move events are driven
// by hand, in every order that matters, with no timers and no real map.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { afterAll, describe, expect, it } from "vitest";

import {
  EditionBrowser,
  type MapLike,
  type PublicManifest,
  layerIdFor,
  publicManifestFrom,
  sourceIdFor,
} from "./editions";
import { attachTileWatcher, type TileEvent, type TileEventSource } from "./tileWatcher";

const rejections: unknown[] = [];
process.on("unhandledRejection", (reason) => rejections.push(reason));
afterAll(() => {
  expect(rejections).toEqual([]);
});

const MANIFEST_PATH = fileURLToPath(
  new URL("../../data/sources/demo-editions.json", import.meta.url),
);

function manifest(): PublicManifest {
  return publicManifestFrom(JSON.parse(readFileSync(MANIFEST_PATH, "utf8")));
}

interface FakeMap extends MapLike, TileEventSource {
  visibility: Record<string, string>;
  opacity: Record<string, number>;
  tiles: Record<string, string[]>;
  cameraCalls: number;
  loaded: Set<string>;
  listeners: Map<string, Set<(event: TileEvent) => void>>;
  emit(type: string, event?: TileEvent): void;
  onScreen(): string[];
}

function buildMap(layerIds: string[]): FakeMap {
  const visibility: Record<string, string> = {};
  const opacity: Record<string, number> = {};
  for (const [index, id] of layerIds.entries()) {
    visibility[id] = index === 0 ? "visible" : "none";
    opacity[id] = 0;
  }
  const listeners = new Map<string, Set<(event: TileEvent) => void>>();
  return {
    visibility,
    opacity,
    tiles: {},
    cameraCalls: 0,
    loaded: new Set<string>(),
    listeners,
    onScreen(): string[] {
      return layerIds.filter((id) => visibility[id] === "visible" && opacity[id] > 0);
    },
    setLayoutProperty(layerId, name, value) {
      if (name === "visibility") {
        visibility[layerId] = value as string;
      }
    },
    setPaintProperty(layerId, name, value) {
      if (name === "raster-opacity") {
        opacity[layerId] = value as number;
      }
    },
    fitBounds() {
      this.cameraCalls += 1;
    },
    setSourceTiles(sourceId, next) {
      this.tiles[sourceId] = next;
      // A refetched source has no settled tiles until the new requests come back.
      this.loaded.delete(sourceId);
    },
    isSourceLoaded(sourceId) {
      return this.loaded.has(sourceId);
    },
    on(type, listener) {
      const set = listeners.get(type) ?? new Set();
      set.add(listener);
      listeners.set(type, set);
    },
    off(type, listener) {
      listeners.get(type)?.delete(listener);
    },
    emit(type, event = {}) {
      for (const listener of [...(listeners.get(type) ?? [])]) {
        listener(event);
      }
    },
  };
}

function harness(): { browser: EditionBrowser; map: FakeMap } {
  const parsed = manifest();
  const map = buildMap(parsed.edition_order.map(layerIdFor));
  const browser = new EditionBrowser({ manifest: parsed, map });
  attachTileWatcher(browser, map);
  // The page's first edition finishes loading before the user can touch a control.
  map.loaded.add(sourceIdFor("auburn-1953"));
  map.emit("idle");
  return { browser, map };
}

function tileError(editionId: string, message: string): TileEvent {
  return { sourceId: sourceIdFor(editionId), error: { message } };
}

describe("attachTileWatcher", () => {
  it("displays the first edition only once its source reports loaded", () => {
    const parsed = manifest();
    const map = buildMap(parsed.edition_order.map(layerIdFor));
    const browser = new EditionBrowser({ manifest: parsed, map });
    attachTileWatcher(browser, map);

    map.emit("idle");
    expect(browser.state.displayedId).toBeNull();
    expect(map.onScreen()).toEqual([]);

    map.loaded.add(sourceIdFor("auburn-1953"));
    map.emit("idle");
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("swaps only when the requested source is loaded", () => {
    const { browser, map } = harness();
    browser.select("auburn-1975");

    map.emit("idle");
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(browser.state.status).toBe("loading");

    map.loaded.add(sourceIdFor("auburn-1975"));
    map.emit("idle");
    expect(browser.state.displayedId).toBe("auburn-1975");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1975")]);
  });

  it("ignores sourcedata, which a raster source reports before it requests a tile", () => {
    const { browser, map } = harness();
    browser.select("auburn-1975");
    // The premature swap this replaced: the source called itself loaded with no request in
    // flight, so the 1975 card appeared over 1953 pixels.
    map.loaded.add(sourceIdFor("auburn-1975"));
    map.emit("sourcedata", { sourceId: sourceIdFor("auburn-1975") });
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(browser.state.status).toBe("loading");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("fails the in-flight switch on a tile error and keeps the old raster", () => {
    const { browser, map } = harness();
    browser.select("auburn-1973");

    map.emit("error", tileError("auburn-1973", "HTTP 404"));
    expect(browser.state.status).toBe("error");
    expect(browser.state.errorMessage).toBe("HTTP 404");
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
    expect(map.cameraCalls).toBe(0);
  });

  it("does not let a source-loaded event after an error reveal the failed edition", () => {
    const { browser, map } = harness();
    browser.select("auburn-1973");
    map.emit("error", tileError("auburn-1973", "HTTP 404"));

    // MapLibre also reports a source loaded once its tiles have settled as errored.
    map.loaded.add(sourceIdFor("auburn-1973"));
    map.emit("idle");
    map.emit("idle");
    expect(browser.state.status).toBe("error");
    expect(browser.state.displayedId).toBe("auburn-1953");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);
  });

  it("refuses to confirm a request that has already seen a tile error", () => {
    const { browser, map } = harness();
    browser.select("auburn-1973");
    map.loaded.add(sourceIdFor("auburn-1973"));
    // Error first, then readiness, inside one generation: the failure still wins.
    map.emit("error", tileError("auburn-1973", "HTTP 500"));
    map.emit("idle");
    expect(browser.state.status).toBe("error");
  });

  it("settles a retry that fails again, without waiting for the map to move", () => {
    const { browser, map } = harness();
    browser.select("auburn-1973");
    map.emit("error", tileError("auburn-1973", "HTTP 404"));

    browser.retry();
    expect(browser.state.status).toBe("loading");
    expect(map.tiles[sourceIdFor("auburn-1973")]).toEqual([
      "tiles/auburn-1973/{z}/{x}/{y}.png?reload=1",
    ]);

    map.emit("error", tileError("auburn-1973", "HTTP 404"));
    expect(browser.state.status).toBe("error");
    expect(browser.state.errorMessage).toBe("HTTP 404");
    expect(browser.state.displayedId).toBe("auburn-1953");
  });

  it("recovers on a retry whose tiles arrive", () => {
    const { browser, map } = harness();
    browser.select("auburn-1973");
    map.emit("error", tileError("auburn-1973", "HTTP 404"));

    browser.retry();
    map.loaded.add(sourceIdFor("auburn-1973"));
    map.emit("idle");
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.displayedId).toBe("auburn-1973");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1973")]);
  });

  it("ignores an out-of-order result from a superseded selection", () => {
    const { browser, map } = harness();
    browser.select("auburn-1973");
    browser.select("auburn-1981");

    // The abandoned source finishes late; nothing about it reaches the screen.
    map.loaded.add(sourceIdFor("auburn-1973"));
    map.emit("idle");
    map.emit("error", tileError("auburn-1973", "late HTTP 404"));
    expect(browser.state.status).toBe("loading");
    expect(browser.state.requestedId).toBe("auburn-1981");
    expect(browser.state.errorMessage).toBeNull();
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);

    map.loaded.add(sourceIdFor("auburn-1981"));
    map.emit("idle");
    expect(browser.state.displayedId).toBe("auburn-1981");
  });

  it("re-measures readiness for the viewport the camera ended on", () => {
    const { browser, map } = harness();
    browser.select("auburn-1975");
    map.loaded.add(sourceIdFor("auburn-1975"));

    // The pan starts before any readiness event: the old viewport proves nothing.
    map.emit("movestart");
    map.loaded.delete(sourceIdFor("auburn-1975"));
    map.emit("idle");
    expect(browser.state.status).toBe("loading");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1953")]);

    map.loaded.add(sourceIdFor("auburn-1975"));
    map.emit("idle");
    expect(browser.state.displayedId).toBe("auburn-1975");
    expect(map.cameraCalls).toBe(0);
  });

  it("warns instead of unsetting the layer when tiles fail after a later pan", () => {
    const { browser, map } = harness();
    browser.select("auburn-1981");
    map.loaded.add(sourceIdFor("auburn-1981"));
    map.emit("idle");

    map.emit("movestart");
    map.emit("error", tileError("auburn-1981", "HTTP 404"));
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.warningMessage).toBe("HTTP 404");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1981")]);

    // MapLibre counts an errored tile as settled, so the source reports itself loaded
    // again on the very next idle while the gap is still on screen (PR #51 review).
    map.emit("idle");
    expect(browser.state.warningMessage).toBe("HTTP 404");
    map.emit("idle");
    expect(browser.state.warningMessage).toBe("HTTP 404");

    // Panning back over the gap does not refetch the cached failure either.
    map.emit("movestart");
    map.emit("idle");
    expect(browser.state.warningMessage).toBe("HTTP 404");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1981")]);
  });

  it("retires the warning when the user retries the displayed edition and it loads", () => {
    const { browser, map } = harness();
    browser.select("auburn-1981");
    map.loaded.add(sourceIdFor("auburn-1981"));
    map.emit("idle");
    map.emit("error", tileError("auburn-1981", "HTTP 404"));
    expect(browser.state.warningMessage).toBe("HTTP 404");

    browser.retry();
    expect(map.tiles[sourceIdFor("auburn-1981")]).toEqual([
      "tiles/auburn-1981/{z}/{x}/{y}.png?reload=1",
    ]);
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.warningMessage).toBeNull();
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1981")]);

    map.loaded.add(sourceIdFor("auburn-1981"));
    map.emit("idle");
    expect(browser.state.warningMessage).toBeNull();
  });

  it("raises the warning again when the retried tiles fail again", () => {
    const { browser, map } = harness();
    browser.select("auburn-1981");
    map.loaded.add(sourceIdFor("auburn-1981"));
    map.emit("idle");
    map.emit("error", tileError("auburn-1981", "HTTP 404"));

    browser.retry();
    map.emit("error", tileError("auburn-1981", "HTTP 404"));
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.warningMessage).toBe("HTTP 404");
    expect(map.onScreen()).toEqual([layerIdFor("auburn-1981")]);
  });

  it("retires the warning when the displayed edition changes", () => {
    const { browser, map } = harness();
    map.emit("error", tileError("auburn-1953", "HTTP 404"));
    expect(browser.state.warningMessage).toBe("HTTP 404");

    browser.select("auburn-1975");
    map.loaded.add(sourceIdFor("auburn-1975"));
    map.emit("idle");
    expect(browser.state.displayedId).toBe("auburn-1975");
    expect(browser.state.warningMessage).toBeNull();
  });

  it("treats a source error with no source id as a failure of the switch in flight", () => {
    const { browser, map } = harness();
    browser.select("auburn-1975");
    map.emit("error", { error: { message: "network offline" } });
    expect(browser.state.status).toBe("error");
    expect(browser.state.errorMessage).toBe("network offline");
  });

  it("ignores an unrelated source error while nothing is loading", () => {
    const { browser, map } = harness();
    map.emit("error", tileError("auburn-1975", "HTTP 404"));
    expect(browser.state.status).toBe("displayed");
    expect(browser.state.warningMessage).toBeNull();
  });

  it("stops listening once detached", () => {
    const parsed = manifest();
    const map = buildMap(parsed.edition_order.map(layerIdFor));
    const browser = new EditionBrowser({ manifest: parsed, map });
    attachTileWatcher(browser, map).detach();

    map.loaded.add(sourceIdFor("auburn-1953"));
    map.emit("idle");
    expect(browser.state.displayedId).toBeNull();
    expect([...map.listeners.values()].every((set) => set.size === 0)).toBe(true);
  });
});
