// The tile protocol handler (issue #43): a missing tile must surface as an error MapLibre
// will report, which means no `status` property on it (PR #51 review).

import { describe, expect, it } from "vitest";

import {
  STRICT_TILE_PROTOCOL,
  loadStrictTile,
  strictTileUrl,
  targetTileUrl,
  type TileFetchResponse,
} from "./tileProtocol";

const BASE = "http://127.0.0.1:5173/";

function response(status: number, statusText: string, bytes = new Uint8Array([1, 2])) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    arrayBuffer: async () => bytes.buffer,
  } satisfies TileFetchResponse;
}

interface Call {
  url: string;
  cache: RequestCache;
}

function recorder(result: TileFetchResponse | Error): {
  calls: Call[];
  fetch: (
    url: string,
    init: { signal: AbortSignal; cache: RequestCache },
  ) => Promise<TileFetchResponse>;
} {
  const calls: Call[] = [];
  return {
    calls,
    fetch: async (url, init) => {
      calls.push({ url, cache: init.cache });
      if (result instanceof Error) {
        throw result;
      }
      return result;
    },
  };
}

describe("strictTileUrl", () => {
  it("prefixes a tile template once", () => {
    const wrapped = strictTileUrl("tiles/auburn-1953/{z}/{x}/{y}.png");
    expect(wrapped).toBe(`${STRICT_TILE_PROTOCOL}://tiles/auburn-1953/{z}/{x}/{y}.png`);
    expect(strictTileUrl(wrapped)).toBe(wrapped);
    expect(targetTileUrl(wrapped)).toBe("tiles/auburn-1953/{z}/{x}/{y}.png");
  });

  it("keeps the retry's reload counter", () => {
    expect(targetTileUrl(strictTileUrl("tiles/auburn-1973/{z}/{x}/{y}.png?reload=2"))).toBe(
      "tiles/auburn-1973/{z}/{x}/{y}.png?reload=2",
    );
  });
});

describe("loadStrictTile", () => {
  it("resolves the manifest's relative path against the page and returns the bytes", async () => {
    const fetcher = recorder(response(200, "OK"));
    const result = await loadStrictTile(
      { url: strictTileUrl("tiles/auburn-1953/13/1341/3132.png") },
      new AbortController(),
      { fetch: fetcher.fetch, baseUrl: BASE },
    );
    expect(new Uint8Array(result.data)).toEqual(new Uint8Array([1, 2]));
    expect(fetcher.calls).toEqual([
      { url: `${BASE}tiles/auburn-1953/13/1341/3132.png`, cache: "default" },
    ]);
  });

  it("throws on a 404 with no status property, so MapLibre reports it", async () => {
    const fetcher = recorder(response(404, "Not Found"));
    const failure = await loadStrictTile(
      { url: strictTileUrl("tiles/auburn-1973/13/1341/3132.png") },
      new AbortController(),
      { fetch: fetcher.fetch, baseUrl: BASE },
    ).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(Error);
    // MapLibre's TileManager._loadTile swallows the error event when `status` is 404.
    expect((failure as Record<string, unknown>).status).toBeUndefined();
    expect((failure as Error).message).toBe(
      "tiles/auburn-1973/13/1341/3132.png: HTTP 404 Not Found",
    );
  });

  it("throws on any other non-OK response", async () => {
    const fetcher = recorder(response(500, "Internal Server Error"));
    await expect(
      loadStrictTile(
        { url: strictTileUrl("tiles/auburn-1975/12/670/1566.png") },
        new AbortController(),
        {
          fetch: fetcher.fetch,
          baseUrl: BASE,
        },
      ),
    ).rejects.toThrow("tiles/auburn-1975/12/670/1566.png: HTTP 500 Internal Server Error");
  });

  it("passes the abort signal through and lets an aborted fetch reject", async () => {
    const aborted = new Error("The user aborted a request.");
    const fetcher = recorder(aborted);
    const controller = new AbortController();
    controller.abort();
    await expect(
      loadStrictTile({ url: strictTileUrl("tiles/auburn-1981/13/1341/3132.png") }, controller, {
        fetch: fetcher.fetch,
        baseUrl: BASE,
      }),
    ).rejects.toBe(aborted);
  });

  it("names the tile when the request fails outright", async () => {
    const fetcher = recorder(new TypeError("Failed to fetch"));
    await expect(
      loadStrictTile(
        { url: strictTileUrl("tiles/auburn-1981/14/2683/6263.png") },
        new AbortController(),
        { fetch: fetcher.fetch, baseUrl: BASE },
      ),
    ).rejects.toThrow("tiles/auburn-1981/14/2683/6263.png: Failed to fetch");
  });
});
