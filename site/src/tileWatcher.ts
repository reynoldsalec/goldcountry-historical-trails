// Turns MapLibre source and error events into the EditionBrowser's readiness calls (#43).
// MapLibre events carry no request generation, so every outcome is re-read off the browser
// state at the moment the event arrives and gated by the browser's generation and viewport
// token. Kept MapLibre-free so a test can drive the same events by hand.

import { type EditionBrowser, sourceIdFor } from "./editions.ts";

export interface TileEvent {
  /** Present on source and tile errors; absent on style or worker errors. */
  sourceId?: string;
  error?: { message?: string } | undefined;
}

/** The slice of the MapLibre Map the watcher listens to. No camera method appears here. */
export interface TileEventSource {
  on(type: string, listener: (event: TileEvent) => void): void;
  off(type: string, listener: (event: TileEvent) => void): void;
  /** True once every tile the current viewport needs from this source has settled. */
  isSourceLoaded(sourceId: string): boolean;
}

// `idle` is the only readiness signal: it means every tile this viewport needs is loaded
// and drawn. `sourcedata` is not usable for this, because a raster source with no request
// in flight yet reports itself loaded, which swapped the card onto the old pixels.
const READY_EVENT = "idle";
/** Events that mean "the viewport is changing, so readiness must be measured again". */
const MOVE_EVENTS = ["movestart", "zoomstart"] as const;

export interface TileWatcher {
  detach(): void;
}

export function attachTileWatcher(browser: EditionBrowser, map: TileEventSource): TileWatcher {
  function evaluate(): void {
    const state = browser.state;
    // MapLibre also reports a source loaded once its tiles have settled as errored, so a
    // failed request must stay failed: only a request still loading can be confirmed.
    if (state.status === "loading") {
      if (map.isSourceLoaded(sourceIdFor(state.requestedId))) {
        browser.confirmDisplayed(state.requestedId, state.generation, state.viewportToken);
      }
      return;
    }
    // A blank stretch of a bounded pyramid is a transparent tile that loads normally, so a
    // clean pass over the displayed edition retires the warning; empty is not a failure.
    if (
      state.status === "displayed" &&
      state.displayedId !== null &&
      map.isSourceLoaded(sourceIdFor(state.displayedId))
    ) {
      browser.clearTileWarning();
    }
  }

  function onError(event: TileEvent): void {
    const state = browser.state;
    const message = event.error?.message ?? "tile request failed";
    const requestedSource = sourceIdFor(state.requestedId);
    const displayedSource = state.displayedId === null ? null : sourceIdFor(state.displayedId);

    if (state.status === "loading" && (event.sourceId ?? requestedSource) === requestedSource) {
      browser.failRequest(state.requestedId, state.generation, message);
      return;
    }
    if (event.sourceId !== undefined && event.sourceId === displayedSource) {
      browser.noteTileWarning(message);
    }
  }

  function onMove(): void {
    browser.noteCameraMove();
  }

  map.on(READY_EVENT, evaluate);
  for (const type of MOVE_EVENTS) {
    map.on(type, onMove);
  }
  map.on("error", onError);

  return {
    detach(): void {
      map.off(READY_EVENT, evaluate);
      for (const type of MOVE_EVENTS) {
        map.off(type, onMove);
      }
      map.off("error", onError);
    },
  };
}
