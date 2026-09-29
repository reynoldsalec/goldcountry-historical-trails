// The D3a shell: one MapLibre map, four raster layers, edition controls and source cards.
// Tile-readiness detection, retry behaviour and pan-during-load restart are only sketched
// here; issue #43 finishes them. Nothing on this page reads or writes browser storage.

import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  type RasterLayerSpecification,
  type RasterSourceSpecification,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  EditionBrowser,
  type BrowserState,
  type PublicManifest,
  cardRows,
  layerIdFor,
  resamplingFor,
  sourceIdFor,
} from "./editions.ts";

const BACKGROUND_LAYER_ID = "outside-coverage";

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) {
    throw new Error(`missing element #${id}`);
  }
  return found as T;
}

/** Only the first edition is visible; a switch flips visibility, never the camera. */
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
        "raster-opacity": 1,
        // No cross-fade: the swap is instant, so two editions are never blended.
        "raster-opacity-transition": { duration: 0, delay: 0 },
      },
    });
  }

  // glyphs/sprite are deliberately absent: no font or sprite is fetched from any origin.
  return { version: 8, sources, layers } as StyleSpecification;
}

function renderCard(browser: EditionBrowser): void {
  const card = cardRows(browser.displayedEdition);
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

function noticeFor(state: BrowserState, browser: EditionBrowser): string {
  if (state.status === "error") {
    return (
      `Could not load ${browser.requestedEdition.label}: ${state.errorMessage ?? "unknown error"}. ` +
      `Still showing ${browser.displayedEdition.label}.`
    );
  }
  if (state.status === "loading") {
    return `Loading ${browser.requestedEdition.label}; still showing ${browser.displayedEdition.label}.`;
  }
  return `Showing ${browser.displayedEdition.label}.`;
}

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

  const browser = new EditionBrowser({ manifest, map, resetPadding: 16 });

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
    renderCard(browser);
  }

  browser.subscribe(render);

  // Minimal readiness proxy for the shell: MapLibre reports idle once the tiles for the
  // current viewport are loaded and drawn. Issue #43 replaces this with per-request
  // viewport tracking, real retry and restart-on-camera-move.
  function awaitReady(generation: number): void {
    const id = browser.state.requestedId;
    if (browser.state.status !== "loading") {
      return;
    }
    map.once("idle", () => browser.confirmDisplayed(id, generation));
  }

  previous.addEventListener("click", () => awaitReady(browser.previous()));
  next.addEventListener("click", () => awaitReady(browser.next()));
  select.addEventListener("change", () => awaitReady(browser.select(select.value)));
  retry.addEventListener("click", () => awaitReady(browser.retry()));
  element("reset-view").addEventListener("click", () => browser.resetView());

  const toggle = element<HTMLButtonElement>("detail-toggle");
  toggle.addEventListener("click", () => {
    const details = element("details");
    const nowHidden = !details.hidden;
    details.hidden = nowHidden;
    toggle.setAttribute("aria-expanded", String(!nowHidden));
    toggle.textContent = nowHidden ? "Show source details" : "Hide source details";
  });

  // Only a failure that belongs to an in-flight switch is surfaced here. Warning on tile
  // errors that arrive during later pan and zoom is issue #43.
  map.on("error", (event) => {
    const state = browser.state;
    if (state.status !== "loading") {
      return;
    }
    browser.failRequest(
      state.requestedId,
      state.generation,
      String(event.error?.message ?? event),
    );
  });

  render(browser.state);
}

void start();
