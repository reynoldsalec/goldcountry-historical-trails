// Edition selection and layer/card pairing for the Auburn browser shell (issue #42).
// DOM-free and MapLibre-free on purpose: the map is injected as MapLike so a test can
// prove a switch touches no camera method and builds no second map.

export type EditionKind = "topo" | "orthophotoquad" | "map";
/** Which publisher product the raster came from; the card names it (issue #58). */
export type SourceKind = "historical_geotiff" | "us_topo_pdf" | "forest_service_scan";

/** west, south, east, north in WGS84 degrees. */
export type Bounds = [number, number, number, number];

export interface EditionDates {
  map_year: number;
  base_year: number | null;
  revision_year: number | null;
  base_photography: string | null;
  revision_photography: string | null;
  photography: string | null;
  base_field_check_year: number | null;
  revision_field_checked: boolean | null;
}

/** Per-sheet index years that `dates` does not carry. Null means the index has none. */
export interface ComponentDates {
  survey_year: number | null;
  edit_year: number | null;
  imprint_year: number | null;
}

/** One edition as the viewer needs it. Crop geometry and receipts stay server-side. */
export interface PublicEdition {
  id: string;
  source_id: string;
  kind: EditionKind;
  source_kind: SourceKind;
  label: string;
  sheet_name: string;
  /** Denominator of the printed scale: 125000 for a 1:125,000 sheet. Null when unprinted. */
  scale: number | null;
  citation: string;
  source_url: string;
  rights: string;
  attribution: string;
  /** The publisher's printed credit note, verbatim, or null where none is transcribed. */
  printed_credit_note: string | null;
  publication_date: string | null;
  dates: EditionDates;
  component_dates: ComponentDates;
  date_note: string;
  native_resolution_metres: number;
  /** The top zoom this edition's own tiles exist at. Above it the map enlarges that level. */
  native_max_zoom: number;
  tile_url: string;
  /** The area this edition's tiles cover; an extra edition may lie outside the Auburn view. */
  coverage_bounds_wgs84: Bounds;
  /** How a scanned sheet was placed and how far off it can be; null for USGS georeferencing. */
  registration_note: string | null;
}

export interface TileZoom {
  min: number;
  max: number;
}

export interface PublicManifest {
  version: number;
  area_id: string;
  edition_order: string[];
  /** The edition requested on first load; not necessarily the first in order. */
  initial_edition: string;
  view_bounds_wgs84: Bounds;
  /** The union of every edition's coverage: how far the camera may pan. */
  pan_bounds_wgs84: Bounds;
  tile_zoom: TileZoom;
  editions: PublicEdition[];
}

export const TILE_URL_PREFIX = "tiles";

/**
 * Project `data/sources/demo-editions.json` onto the display-only shape the browser
 * fetches. Card text must come from the manifest, never retyped (issue #42). Mirrors
 * `sanitize_manifest` in scripts/build_site.py, which writes the published editions.json.
 */
export function publicManifestFrom(source: unknown): PublicManifest {
  const raw = source as Record<string, unknown>;
  const order = raw.edition_order as string[];
  const editions = raw.editions as Record<string, unknown>[];
  const byId = new Map(editions.map((edition) => [edition.id as string, edition]));
  const tileZoom = { ...(raw.tile_zoom as TileZoom) };
  const view = (raw.view_bounds_wgs84 as number[]).slice(0, 4) as Bounds;
  const initial = raw.initial_edition as string;
  if (!order.includes(initial)) {
    throw new Error(`demo-editions.json: initial_edition ${initial} is not in edition_order`);
  }

  const projected = order.map((id) => {
    const edition = byId.get(id);
    if (!edition) {
      throw new Error(`demo-editions.json: edition_order names unknown edition ${id}`);
    }
    return {
      id,
      source_id: edition.source_id as string,
      kind: edition.kind as EditionKind,
      source_kind: edition.source_kind as SourceKind,
      label: edition.label as string,
      sheet_name: edition.sheet_name as string,
      scale: edition.scale as number,
      citation: edition.citation as string,
      source_url: edition.source_url as string,
      rights: edition.rights as string,
      attribution: edition.attribution as string,
      printed_credit_note: edition.printed_credit_note as string | null,
      publication_date: edition.publication_date as string | null,
      dates: edition.dates as EditionDates,
      component_dates: edition.component_dates as ComponentDates,
      date_note: edition.date_note as string,
      native_resolution_metres: edition.native_resolution_metres as number,
      // The published file carries the zoom actually cut; the source manifest carries the
      // sheet's own limit, which the shared maximum caps the same way.
      native_max_zoom: Math.min(edition.native_max_zoom as number, tileZoom.max),
      tile_url: `${TILE_URL_PREFIX}/${id}/{z}/{x}/{y}.png`,
      // The dev server serves only the nine, which are all cut to the Auburn view.
      coverage_bounds_wgs84: view,
      registration_note: null,
    };
  });

  return {
    version: raw.version as number,
    area_id: raw.area_id as string,
    edition_order: [...order],
    initial_edition: initial,
    view_bounds_wgs84: view,
    pan_bounds_wgs84: view,
    tile_zoom: tileZoom,
    editions: projected,
  };
}

/**
 * Retry appends a reload counter so the request misses the browser's cached failure. The
 * dev server and a static host both ignore the query string when resolving the file.
 */
export function tileUrlFor(edition: PublicEdition, reload: number): string {
  return reload === 0 ? edition.tile_url : `${edition.tile_url}?reload=${reload}`;
}

export function layerIdFor(editionId: string): string {
  return `edition-${editionId}`;
}

export function sourceIdFor(editionId: string): string {
  return `edition-${editionId}`;
}

/** MapLibre resamples scanned line work nearest and photography linearly (AGENTS.md §3). */
export function resamplingFor(kind: EditionKind): "nearest" | "linear" {
  // Scanned maps ("map") are line work too, so they stay nearest.
  return kind === "orthophotoquad" ? "linear" : "nearest";
}

export interface CardRow {
  label: string;
  value: string;
}

export interface SourceCard {
  editionId: string;
  label: string;
  citation: string;
  sourceUrl: string;
  attribution: string;
  /** The publisher's printed credit note, verbatim, when one is transcribed. */
  credits: string | null;
  dateNote: string;
  rows: CardRow[];
}

const PRODUCT_LABEL: Record<EditionKind, string> = {
  topo: "Topographic map",
  orthophotoquad: "Orthophotoquad",
  map: "Map",
};

const SOURCE_PRODUCT_LABEL: Record<SourceKind, string | null> = {
  historical_geotiff: null,
  us_topo_pdf: "US Topo map",
  forest_service_scan: "Forest Service map (scan)",
};

/** "1:125,000", grouped the way the sheets print it, whatever the browser locale. */
export function scaleLabel(scale: number): string {
  return `1:${String(scale).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
}

/**
 * Card fields, built from the manifest so nothing is retyped (issue #42). A row is omitted
 * rather than filled with a placeholder when the manifest says null: the card describes
 * what the sheet records and claims nothing about present-day access (AGENTS.md §2.6).
 */
export function cardRows(edition: PublicEdition): SourceCard {
  const dates = edition.dates;
  const rows: CardRow[] = [
    {
      label: "Product",
      value: SOURCE_PRODUCT_LABEL[edition.source_kind] ?? PRODUCT_LABEL[edition.kind],
    },
    // The regional sheets must read as Sacramento sheets, never as Auburn 7.5-minute maps.
    {
      label: "Sheet",
      value:
        edition.scale === null
          ? `${edition.sheet_name} (no printed scale found)`
          : `${edition.sheet_name} ${scaleLabel(edition.scale)}`,
    },
    { label: "Source ID", value: edition.source_id },
  ];

  if (edition.publication_date !== null) {
    rows.push({ label: "Published", value: edition.publication_date });
  }

  if (dates.base_year !== null) {
    rows.push({
      label: "Base sheet",
      value:
        dates.base_photography !== null
          ? `${dates.base_year} (photography ${dates.base_photography})`
          : `${dates.base_year} (photography not stated)`,
    });
  }

  if (dates.revision_year !== null) {
    rows.push({
      label: "Revision",
      value:
        dates.revision_photography !== null
          ? `photorevised ${dates.revision_year} (photography ${dates.revision_photography})`
          : `photorevised ${dates.revision_year} (photography not stated)`,
    });
  }

  if (dates.photography !== null) {
    rows.push({ label: "Photography", value: dates.photography });
  }

  const fieldCheck: string[] = [];
  if (dates.base_field_check_year !== null) {
    fieldCheck.push(`base field checked ${dates.base_field_check_year}`);
  }
  if (dates.revision_field_checked === false) {
    fieldCheck.push("revision not field checked");
  } else if (dates.revision_field_checked === true) {
    fieldCheck.push("revision field checked");
  }
  if (fieldCheck.length > 0) {
    rows.push({ label: "Field check", value: fieldCheck.join("; ") });
  }

  const components = edition.component_dates;
  if (components.survey_year !== null) {
    rows.push({ label: "Surveyed", value: String(components.survey_year) });
  }
  if (components.edit_year !== null) {
    rows.push({ label: "Edited", value: String(components.edit_year) });
  }
  if (components.imprint_year !== null) {
    rows.push({ label: "Printed", value: String(components.imprint_year) });
  }

  rows.push({ label: "Map year on sheet", value: String(dates.map_year) });
  rows.push({
    label: "Detail limit",
    value:
      `zoom ${edition.native_max_zoom} ` +
      `(source pixel about ${edition.native_resolution_metres} m)`,
  });

  if (edition.registration_note !== null) {
    rows.push({ label: "Placement", value: edition.registration_note });
  }

  return {
    editionId: edition.id,
    label: edition.label,
    citation: edition.citation,
    sourceUrl: edition.source_url,
    attribution: edition.attribution,
    credits: edition.printed_credit_note,
    dateNote: edition.date_note,
    rows,
  };
}

/**
 * Said only while the camera is past the edition's own top zoom: the map is then enlarging
 * that level, and the extra size is not extra detail (issue #58). Null otherwise.
 */
export function detailLimitNotice(edition: PublicEdition, zoom: number): string | null {
  if (zoom <= edition.native_max_zoom + 1e-6) {
    return null;
  }
  return (
    `This view is closer than ${edition.label} was tiled for (zoom ` +
    `${edition.native_max_zoom}). Its zoom-${edition.native_max_zoom} image is enlarged ` +
    `here; it shows no more detail than at that zoom.`
  );
}

/** True when the two boxes share any area. */
export function boundsOverlap(a: Bounds, b: Bounds): boolean {
  return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
}

export function containsPoint(bounds: Bounds, lng: number, lat: number): boolean {
  return bounds[0] <= lng && lng <= bounds[2] && bounds[1] <= lat && lat <= bounds[3];
}

/**
 * Said when the edition on screen draws nothing in the viewport: a blank map then means
 * "outside this sheet", never "nothing was here". Null otherwise.
 */
export function coverageNotice(edition: PublicEdition, viewport: Bounds): string | null {
  return boundsOverlap(edition.coverage_bounds_wgs84, viewport)
    ? null
    : `${edition.label} does not cover the area on screen. Use "Show this map's area" to go to it.`;
}

/**
 * The status line. It says what is on screen and what is only requested, never merging the
 * two, and it never names a blank stretch of map as empty ground (issue #43).
 */
export function noticeFor(state: BrowserState, browser: EditionBrowser): string {
  const displayed = browser.displayedEdition;
  const requested = browser.requestedEdition.label;

  if (state.status === "error") {
    const reason = state.errorMessage ?? "unknown error";
    return displayed === null
      ? `Could not load ${requested}: ${reason}. No edition is on screen yet.`
      : `Could not load ${requested}: ${reason}. Still showing ${displayed.label}.`;
  }
  if (state.status === "loading") {
    return displayed === null
      ? `Loading ${requested}.`
      : `Loading ${requested}; still showing ${displayed.label}.`;
  }
  const label = displayed === null ? requested : displayed.label;
  return state.warningMessage === null
    ? `Showing ${label}.`
    : `Showing ${label}. Some tiles did not load: ${state.warningMessage}. ` +
        `A blank area here may be a missing tile rather than a blank sheet.`;
}

/** The subset of the MapLibre Map the browser is allowed to use for a switch. */
export interface MapLike {
  setLayoutProperty(layerId: string, name: string, value: unknown): void;
  setPaintProperty(layerId: string, name: string, value: unknown): void;
  fitBounds(bounds: [number, number, number, number], options?: unknown): void;
  /** Re-point a raster source at fresh tile URLs. Retry needs it; see `retry` (issue #43). */
  setSourceTiles(sourceId: string, tiles: string[]): void;
}

export type RequestStatus = "displayed" | "loading" | "error";

export interface BrowserState {
  /** The edition the user asked for. May differ from what is on screen. */
  readonly requestedId: string;
  /** The edition whose tiles and card are shown. Null before any edition has loaded. */
  readonly displayedId: string | null;
  /** Monotonic id so a late load or error from an older request cannot win. */
  readonly generation: number;
  /** Monotonic id of the camera position readiness was measured against. */
  readonly viewportToken: number;
  readonly status: RequestStatus;
  readonly errorMessage: string | null;
  /** A tile failure that arrived after a settled switch. It never unsets the layer. */
  readonly warningMessage: string | null;
}

export interface EditionBrowserOptions {
  manifest: PublicManifest;
  map: MapLike;
  /** Padding handed to the one permitted fitBounds call. */
  resetPadding?: number;
}

/**
 * Edition order, endpoint limits, direct selection, the separate reset, and the
 * requested/displayed split with its generation and viewport gating. The browser is told
 * about tile outcomes; `tileWatcher.ts` translates MapLibre events into those calls.
 */
export class EditionBrowser {
  readonly manifest: PublicManifest;

  private readonly map: MapLike;
  private readonly resetPadding: number;
  private readonly listeners = new Set<(state: BrowserState) => void>();
  private current: BrowserState;
  private resetCount = 0;
  private coverageCount = 0;
  /** Reload counter per edition; a retry needs a URL the browser cache has not failed on. */
  private readonly reloads = new Map<string, number>();

  constructor(options: EditionBrowserOptions) {
    const { manifest, map } = options;
    if (manifest.edition_order.length === 0) {
      throw new Error("manifest has no editions");
    }
    this.manifest = manifest;
    this.map = map;
    this.resetPadding = options.resetPadding ?? 16;
    // Nothing is displayed until tiles have actually loaded, so the initial edition starts
    // loading with no card. The style ships its layer visible at zero opacity: the
    // constructor must not call the map, whose style may not be ready yet (issue #43).
    if (!manifest.edition_order.includes(manifest.initial_edition)) {
      throw new Error(`initial edition ${manifest.initial_edition} is not in the order`);
    }
    this.current = {
      requestedId: manifest.initial_edition,
      displayedId: null,
      generation: 0,
      viewportToken: 0,
      status: "loading",
      errorMessage: null,
      warningMessage: null,
    };
  }

  get state(): BrowserState {
    return this.current;
  }

  get order(): readonly string[] {
    return this.manifest.edition_order;
  }

  /** Reset actions performed, so a test can show edition switching never fits bounds. */
  get resetViewCalls(): number {
    return this.resetCount;
  }

  edition(id: string): PublicEdition {
    const found = this.manifest.editions.find((candidate) => candidate.id === id);
    if (!found) {
      throw new Error(`unknown edition ${id}`);
    }
    return found;
  }

  /** The card and layer always belong to the edition actually on screen, if any. */
  get displayedEdition(): PublicEdition | null {
    return this.current.displayedId === null ? null : this.edition(this.current.displayedId);
  }

  get requestedEdition(): PublicEdition {
    return this.edition(this.current.requestedId);
  }

  indexOf(id: string): number {
    return this.manifest.edition_order.indexOf(id);
  }

  get canGoPrevious(): boolean {
    return this.indexOf(this.current.requestedId) > 0;
  }

  get canGoNext(): boolean {
    return this.indexOf(this.current.requestedId) < this.manifest.edition_order.length - 1;
  }

  subscribe(listener: (state: BrowserState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Direct selection. Returns the generation that owns this request. */
  select(id: string): number {
    this.edition(id);
    if (id === this.current.requestedId && this.current.status === "displayed") {
      return this.current.generation;
    }
    this.abandon(this.current.requestedId, id);
    if (id !== this.current.displayedId) {
      this.beginLoading(id);
    }
    const generation = this.current.generation + 1;
    this.commit({
      ...this.current,
      requestedId: id,
      generation,
      status: id === this.current.displayedId ? "displayed" : "loading",
      errorMessage: null,
    });
    return generation;
  }

  /** Stops at the first edition instead of wrapping. */
  previous(): number {
    if (!this.canGoPrevious) {
      return this.current.generation;
    }
    return this.select(this.manifest.edition_order[this.indexOf(this.current.requestedId) - 1]);
  }

  /** Stops at the last edition instead of wrapping. */
  next(): number {
    if (!this.canGoNext) {
      return this.current.generation;
    }
    return this.select(this.manifest.edition_order[this.indexOf(this.current.requestedId) + 1]);
  }

  /**
   * Re-request the edition that failed, under a fresh generation. The tile URLs get a new
   * reload counter: without it the browser replays its cached failure and the retry never
   * settles, which is the gap PR #50's review left open. A warned edition that is already
   * on screen is refetched the same way, because MapLibre keeps its errored tiles cached
   * and never asks for them again on its own (PR #51 review).
   */
  retry(): number {
    const id = this.current.requestedId;
    const displayed = id === this.current.displayedId;
    if (!displayed || this.current.warningMessage !== null) {
      const reload = (this.reloads.get(id) ?? 0) + 1;
      this.reloads.set(id, reload);
      this.map.setSourceTiles(sourceIdFor(id), [tileUrlFor(this.edition(id), reload)]);
      if (!displayed) {
        this.beginLoading(id);
      }
    }
    const generation = this.current.generation + 1;
    this.commit({
      ...this.current,
      generation,
      status: displayed ? "displayed" : "loading",
      errorMessage: null,
      // The refetch is in flight; a tile that fails again raises the warning afresh.
      warningMessage: displayed ? null : this.current.warningMessage,
    });
    return generation;
  }

  /**
   * One of the two explicit actions allowed to move the camera (issue #42); the other is
   * `showCoverage`. It never changes the selected edition.
   */
  resetView(): void {
    this.resetCount += 1;
    this.map.fitBounds(this.manifest.view_bounds_wgs84, {
      padding: this.resetPadding,
      animate: false,
      bearing: 0,
      pitch: 0,
    });
  }

  /**
   * The second, explicit camera action: frame the requested edition's own coverage. It
   * never changes the selection, and no switch calls it.
   */
  showCoverage(): void {
    this.coverageCount += 1;
    this.map.fitBounds(this.requestedEdition.coverage_bounds_wgs84, {
      padding: this.resetPadding,
      animate: false,
      bearing: 0,
      pitch: 0,
    });
  }

  /** "Show this map's area" actions performed; switching never adds to it. */
  get showCoverageCalls(): number {
    return this.coverageCount;
  }

  /**
   * Swap layer opacity and card together once the request's visible-viewport tiles are in.
   * `viewportToken` is the camera the readiness was measured against: a signal from before
   * a pan says nothing about what is on screen now.
   */
  confirmDisplayed(id: string, generation: number, viewportToken?: number): boolean {
    // A failed request keeps its generation, so readiness only counts while still loading:
    // otherwise a later idle event would reveal the edition that never loaded (PR #50).
    if (!this.owns(id, generation) || this.current.status !== "loading") {
      return false;
    }
    if (viewportToken !== undefined && viewportToken !== this.current.viewportToken) {
      return false;
    }
    if (this.current.displayedId !== id) {
      // Reveal first, then hide: no third edition is ever uncovered in between.
      this.map.setPaintProperty(layerIdFor(id), "raster-opacity", 1);
      if (this.current.displayedId !== null) {
        this.map.setLayoutProperty(layerIdFor(this.current.displayedId), "visibility", "none");
      }
    }
    this.commit({
      ...this.current,
      displayedId: id,
      status: "displayed",
      errorMessage: null,
      // The warning belonged to the edition leaving the screen.
      warningMessage: null,
    });
    return true;
  }

  /** A failure leaves the last valid layer and its card on screen, and the camera alone. */
  failRequest(id: string, generation: number, message: string): boolean {
    if (!this.owns(id, generation)) {
      return false;
    }
    this.commit({ ...this.current, status: "error", errorMessage: message });
    return true;
  }

  /**
   * A tile failure that arrives once a switch has settled: the pixels on screen are still
   * the edition the card names, so this warns instead of unsetting the layer. It survives
   * later pans, zooms and idles, because the gap it reports is still on screen: only a
   * switch or a retry retires it.
   */
  noteTileWarning(message: string): void {
    if (this.current.warningMessage === message) {
      return;
    }
    this.commit({ ...this.current, warningMessage: message });
  }

  /**
   * The camera moved, so any readiness measured against the old viewport is void and the
   * request waits for tiles covering the new one. The selection and its generation stand.
   */
  noteCameraMove(): number {
    const viewportToken = this.current.viewportToken + 1;
    this.commit({ ...this.current, viewportToken });
    return viewportToken;
  }

  /**
   * MapLibre requests no tiles for a layer whose visibility is `none`, so a requested
   * edition is made visible at zero opacity. It loads without ever being seen.
   */
  private beginLoading(id: string): void {
    this.map.setLayoutProperty(layerIdFor(id), "visibility", "visible");
    this.map.setPaintProperty(layerIdFor(id), "raster-opacity", 0);
  }

  /** Stop loading an edition the user has moved on from, unless it is on screen. */
  private abandon(id: string, replacement: string): void {
    if (id === replacement || id === this.current.displayedId) {
      return;
    }
    this.map.setLayoutProperty(layerIdFor(id), "visibility", "none");
  }

  /** The tile template currently in use, reload counter included. */
  tileUrl(id: string): string {
    return tileUrlFor(this.edition(id), this.reloads.get(id) ?? 0);
  }

  private owns(id: string, generation: number): boolean {
    return generation === this.current.generation && id === this.current.requestedId;
  }

  private commit(next: BrowserState): void {
    this.current = next;
    for (const listener of this.listeners) {
      listener(next);
    }
  }
}
