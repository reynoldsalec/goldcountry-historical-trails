// Tile fetches go through a MapLibre protocol handler so an HTTP failure is reported.
// MapLibre 6.11.2 fires no `error` event for a tile whose request failed with status 404
// (`TileManager._loadTile`), and the bounded pyramid encodes every in-bounds tile, so a
// 404 here is a failure, not no-data (PR #51 review, issue #43). Kept DOM-free and
// MapLibre-free so a test can drive it with a fake fetch.

export const STRICT_TILE_PROTOCOL = "strict-tile";

const PREFIX = `${STRICT_TILE_PROTOCOL}://`;

/** Route a tile URL or URL template through the handler. Idempotent. */
export function strictTileUrl(url: string): string {
  return url.startsWith(PREFIX) ? url : `${PREFIX}${url}`;
}

/** The URL the handler actually fetches. */
export function targetTileUrl(url: string): string {
  return url.startsWith(PREFIX) ? url.slice(PREFIX.length) : url;
}

export interface TileRequestLike {
  url: string;
}

export interface TileFetchResponse {
  ok: boolean;
  status: number;
  statusText?: string;
  arrayBuffer(): Promise<ArrayBuffer>;
}

export interface StrictTileDeps {
  fetch(
    url: string,
    init: { signal: AbortSignal; cache: RequestCache },
  ): Promise<TileFetchResponse>;
  /** Base for the manifest's relative tile paths; the protocol prefix defeats MapLibre's. */
  baseUrl?: string;
}

/**
 * Fetch one tile. A non-OK response throws an error that carries no `status` property,
 * because MapLibre drops the error event for a rejection whose status is 404.
 */
export async function loadStrictTile(
  request: TileRequestLike,
  abortController: AbortController,
  deps: StrictTileDeps,
): Promise<{ data: ArrayBuffer }> {
  const path = targetTileUrl(request.url);
  const url = deps.baseUrl === undefined ? path : new URL(path, deps.baseUrl).toString();
  let response: TileFetchResponse;
  try {
    response = await deps.fetch(url, {
      signal: abortController.signal,
      // The retry's ?reload=N already defeats the cache; this keeps a failed tile from
      // being replayed from it on an ordinary pan.
      cache: "default",
    });
  } catch (reason: unknown) {
    if (abortController.signal.aborted) {
      // MapLibre cancelled this tile itself; it must stay an abort, not a failure.
      throw reason;
    }
    throw new Error(`${path}: ${reason instanceof Error ? reason.message : String(reason)}`);
  }
  if (!response.ok) {
    const detail = response.statusText === undefined ? "" : ` ${response.statusText}`;
    throw new Error(`${path}: HTTP ${response.status}${detail}`.trimEnd());
  }
  return { data: await response.arrayBuffer() };
}
