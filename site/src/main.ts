// One MapLibre map, four raster layers, edition controls and source cards. Readiness,
// failure and retry are decided by EditionBrowser; tileWatcher.ts feeds it map events
// (issues #42, #43). Nothing on this page reads or writes browser storage.

import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  type RasterLayerSpecification,
  type RasterSourceSpecification,
  type RasterTileSource,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  EditionBrowser,
  type BrowserState,
  type MapLike,
  type PublicManifest,
  cardRows,
  layerIdFor,
  noticeFor,
  resamplingFor,
  sourceIdFor,
} from "./editions.ts";
import { attachTileWatcher, type TileEventSource } from "./tileWatcher.ts";

const BACKGROUND_LAYER_ID = "outside-coverage";

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) {
    throw new Error(`missing element #${id}`);
  }
  return found as T;
}

/** Only the first edition is loading; a switch flips visibility, never the camera. */
function buildStyle(manifest: PublicManifest): StyleSpecification {
  const sources: Record<string, RasterSourceSpecification> = {};
  const layers: (RasterLayerSpecification | StyleSpecification["layers"][number])[] = [
    {
      id: BACKGROUND_LAYER_ID,
      type: "background",
      paint: { "background-color": "#f4f1ea" },
    },
  ];

  for (const [index, edition] of manifest.editions.entries()) {
    sources[sourceIdFor(edition.id)] = {
      type: "raster",
      tiles: [edition.tile_url],
      tileSize: 256,
      minzoom: manifest.tile_zoom.min,
      maxzoom: manifest.tile_zoom.max,
      bounds: manifest.view_bounds_wgs84,
      attribution: edition.attribution,
    };
    layers.push({
      id: layerIdFor(edition.id),
      type: "raster",
      source: sourceIdFor(edition.id),
      layout: { visibility: index === 0 ? "visible" : "none" },
      paint: {
        "raster-resampling": resamplingFor(edition.kind),
        "raster-fade-duration": 0,
        // The first edition loads at zero opacity too: no pixels appear before the card
        // that names them, and MapLibre fetches no tiles for a hidden layer (issue #43).
        "raster-opacity": 0,
        // No cross-fade: the swap is instant, so two editions are never blended.
        "raster-opacity-transition": { duration: 0, delay: 0 },
      },
    });
  }

  // glyphs/sprite are deliberately absent: no font or sprite is fetched from any origin.
  return { version: 8, sources, layers } as StyleSpecification;
}

function renderCard(browser: EditionBrowser): void {
  const displayed = browser.displayedEdition;
  if (displayed === null) {
    // No sheet is on screen, so no card may claim one is (issue #43).
    element("card").innerHTML =
      `<p class="card-note">No edition is on screen yet. The card appears once a sheet's ` +
      `tiles have loaded.</p>`;
    return;
  }
  const card = cardRows(displayed);
  const facts = card.rows
    .map((row) => `<dt>${escapeHtml(row.label)}</dt><dd>${escapeHtml(row.value)}</dd>`)
    .join("");

  element("card").innerHTML = [
    `<p class="card-label">${escapeHtml(card.label)}</p>`,
    `<dl class="card-facts">${facts}</dl>`,
    `<p class="card-note">${escapeHtml(card.dateNote)}</p>`,
    `<p class="card-citation">${escapeHtml(card.citation)}</p>`,
    `<p class="card-citation"><a href="${escapeHtml(card.sourceUrl)}" rel="noreferrer">` +
      `Original source record</a></p>`,
    `<p class="card-attribution">${escapeHtml(card.attribution)}</p>`,
    `<p class="card-caveat">${escapeHtml(CAVEAT)}</p>`,
  ].join("");
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!,
  );
}

/* The card describes what the sheet depicts. It asserts no right and no access. */
const CAVEAT =
  "These sheets record what the survey depicted on its stated dates. A line on a map " +
  "is not a statement about who may use it today.";

async function start(): Promise<void> {
  const response = await fetch("./editions.json", { cache: "no-store" });
  if (!response.ok) {
    element("notice").textContent = `Could not load editions.json (HTTP ${response.status}).`;
    return;
  }
  const manifest = (await response.json()) as PublicManifest;
  const bounds = manifest.view_bounds_wgs84;

  const map = new MapLibreMap({
    container: "map",
    style: buildStyle(manifest),
    bounds,
    fitBoundsOptions: { padding: 16 },
    minZoom: manifest.tile_zoom.min,
    maxZoom: manifest.tile_zoom.max,
    maxBounds: bounds,
    bearing: 0,
    pitch: 0,
    maxPitch: 0,
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
    touchZoomRotate: { around: "center" },
    renderWorldCopies: false,
    attributionControl: { compact: false },
    maplibreLogo: false,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new NavigationControl({ showCompass: false }), "top-left");
  map.addControl(new ScaleControl({ unit: "imperial" }), "bottom-left");

  // The browser only ever sees these four methods, so it cannot move the camera by
  // accident and `setSourceTiles` is the one path that refetches a failed pyramid.
  // MapLibre types each property name as a literal union; MapLike is deliberately the
  // narrower, string-keyed surface, so the two setters are adapted once here.
  type PropertySetter = (layerId: string, name: string, value: unknown) => void;
  const controls: MapLike = {
    setLayoutProperty: (map.setLayoutProperty as unknown as PropertySetter).bind(map),
    setPaintProperty: (map.setPaintProperty as unknown as PropertySetter).bind(map),
    fitBounds: (bounds, options) => map.fitBounds(bounds, options as never),
    setSourceTiles: (sourceId, tiles) =>
      (map.getSource(sourceId) as RasterTileSource | undefined)?.setTiles(tiles),
  };

  const browser = new EditionBrowser({ manifest, map: controls, resetPadding: 16 });
  attachTileWatcher(browser, map as unknown as TileEventSource);

  const select = element<HTMLSelectElement>("edition-select");
  select.append(
    ...manifest.editions.map((edition) => {
      const option = document.createElement("option");
      option.value = edition.id;
      option.textContent = edition.label;
      return option;
    }),
  );

  const previous = element<HTMLButtonElement>("previous");
  const next = element<HTMLButtonElement>("next");
  const retry = element<HTMLButtonElement>("retry");

  function render(state: BrowserState): void {
    select.value = state.requestedId;
    previous.disabled = !browser.canGoPrevious;
    next.disabled = !browser.canGoNext;
    retry.hidden = state.status !== "error";
    const notice = element("notice");
    notice.textContent = noticeFor(state, browser);
    notice.dataset.status = state.status;
    notice.dataset.warning = String(state.warningMessage !== null);
    renderCard(browser);
  }

  browser.subscribe(render);

  // No per-click waiter: the watcher is attached for the page's life and reads the
  // generation and viewport token off the state each time an event arrives.
  previous.addEventListener("click", () => browser.previous());
  next.addEventListener("click", () => browser.next());
  select.addEventListener("change", () => browser.select(select.value));
  retry.addEventListener("click", () => browser.retry());
  element("reset-view").addEventListener("click", () => browser.resetView());

  const toggle = element<HTMLButtonElement>("detail-toggle");
  toggle.addEventListener("click", () => {
    const details = element("details");
    const nowHidden = !details.hidden;
    details.hidden = nowHidden;
    toggle.setAttribute("aria-expanded", String(!nowHidden));
    toggle.textContent = nowHidden ? "Show source details" : "Hide source details";
  });

  render(browser.state);
}

// A rejection here would otherwise be unhandled and the page would sit silent (issue #43).
start().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  const notice = document.getElementById("notice");
  if (notice) {
    notice.textContent = `Could not start the viewer: ${message}`;
    notice.dataset.status = "error";
  }
});
