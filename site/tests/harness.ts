// Page helpers for the browser suite (issue #44). Kept out of the spec so the assertions
// there read as behaviour, and so the storage and request instrumentation is installed the
// same way for every test.

import { expect, type Page, type Request } from "@playwright/test";

export const TILE_GLOB = "**/tiles/**";

export interface Camera {
  lng: number;
  lat: number;
  zoom: number;
  bearing: number;
  pitch: number;
}

interface TestProbe {
  camera(): Camera;
  resetViewCalls(): number;
}

/** Records every browser-storage touch instead of blocking it, so a touch fails a test. */
const STORAGE_PROBE = `
  window.__storageTouches = [];
  const record = (name) => {
    window.__storageTouches.push(name);
  };
  const fakeStorage = {
    length: 0,
    getItem: () => null,
    setItem: () => undefined,
    removeItem: () => undefined,
    clear: () => undefined,
    key: () => null,
  };
  for (const name of ["localStorage", "sessionStorage"]) {
    Object.defineProperty(window, name, {
      configurable: true,
      get() {
        record(name);
        return fakeStorage;
      },
    });
  }
  Object.defineProperty(window, "indexedDB", {
    configurable: true,
    get() {
      record("indexedDB");
      return { open: () => ({}), deleteDatabase: () => ({}) };
    },
  });
  Object.defineProperty(window, "caches", {
    configurable: true,
    get() {
      record("caches");
      return { open: () => Promise.resolve({}) };
    },
  });
  if (navigator.serviceWorker) {
    const register = navigator.serviceWorker.register.bind(navigator.serviceWorker);
    navigator.serviceWorker.register = (...args) => {
      record("serviceWorker.register");
      return register(...args);
    };
  }
`;

export interface Session {
  /** Every request the page made, in order. */
  readonly requests: Request[];
  urls(): string[];
}

/**
 * Install the probes, load the viewer and wait until the first edition is really on screen.
 * Storage instrumentation goes in before any page script runs.
 */
export async function openViewer(page: Page, path = "/"): Promise<Session> {
  const requests: Request[] = [];
  page.on("request", (request) => requests.push(request));
  await page.addInitScript(STORAGE_PROBE);
  await page.goto(path);
  await expect(page.locator("#notice")).toHaveAttribute("data-status", "displayed");
  return { requests, urls: () => requests.map((request) => request.url()) };
}

export async function storageTouches(page: Page): Promise<string[]> {
  return page.evaluate(
    () => (window as unknown as { __storageTouches: string[] }).__storageTouches,
  );
}

export async function camera(page: Page): Promise<Camera> {
  return page.evaluate(() =>
    (window as unknown as { __demoTestProbe: TestProbe }).__demoTestProbe.camera(),
  );
}

export async function resetViewCalls(page: Page): Promise<number> {
  return page.evaluate(() =>
    (window as unknown as { __demoTestProbe: TestProbe }).__demoTestProbe.resetViewCalls(),
  );
}

/** Whole-pixel comparison: a repaint may leave the float a hair off, a reset never does. */
export function sameCamera(before: Camera, after: Camera): boolean {
  return (
    Math.abs(before.lng - after.lng) < 1e-9 &&
    Math.abs(before.lat - after.lat) < 1e-9 &&
    Math.abs(before.zoom - after.zoom) < 1e-9 &&
    before.bearing === after.bearing &&
    before.pitch === after.pitch
  );
}

/** The notice and the card must name the same edition; a stale label fails here. */
export async function expectShowing(page: Page, label: string): Promise<void> {
  await expect(page.locator("#notice")).toHaveAttribute("data-status", "displayed");
  await expect(page.locator("#notice")).toHaveText(
    new RegExp(`^Showing ${escapeRe(label)}\\.`),
  );
  await expect(page.locator(".card-label")).toHaveText(label);
}

export function escapeRe(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export type TileMode = "ok" | "http-404" | "abort" | { delayMs: number };

export interface TileFaults {
  /** Apply a mode to one edition's pyramid. Later requests obey it; earlier ones stand. */
  set(editionId: string, mode: TileMode): void;
  reset(): void;
  urls(): string[];
}

/**
 * Fault injection at the network edge, so the page's own fetch path, protocol handler and
 * state machine all run unchanged. `http-404` and `abort` are the two failures the bounded
 * pyramid can really produce: a tile the host does not have, and a dropped connection.
 */
export async function installTileFaults(page: Page): Promise<TileFaults> {
  const modes = new Map<string, TileMode>();
  const seen: string[] = [];
  await page.route(TILE_GLOB, async (route) => {
    const url = route.request().url();
    seen.push(url);
    const id = [...modes.keys()].find((key) => url.includes(`/tiles/${key}/`));
    const mode = id === undefined ? "ok" : modes.get(id)!;
    if (mode === "http-404") {
      await route.fulfill({ status: 404, contentType: "text/plain", body: "no such tile" });
      return;
    }
    if (mode === "abort") {
      await route.abort();
      return;
    }
    if (typeof mode === "object") {
      await new Promise((resolve) => setTimeout(resolve, mode.delayMs));
    }
    await route.continue();
  });
  return {
    set: (editionId, mode) => modes.set(editionId, mode),
    reset: () => modes.clear(),
    urls: () => [...seen],
  };
}

/**
 * Two identical readings in a row. A drag has inertia and a zoom is animated, so a camera
 * read straight after the gesture is still mid-flight and would make an invariant flaky.
 */
export async function waitForCameraIdle(page: Page): Promise<Camera> {
  let previous = await camera(page);
  for (let attempt = 0; attempt < 80; attempt += 1) {
    await page.waitForTimeout(100);
    const next = await camera(page);
    if (sameCamera(previous, next)) {
      return next;
    }
    previous = next;
  }
  throw new Error("camera never settled");
}

export interface Colour {
  r: number;
  g: number;
  b: number;
}

/**
 * The colour actually painted at the centre of the map, read from a 1-pixel screenshot.
 * WebGL keeps no readable drawing buffer, so the composited page is what is sampled; the
 * PNG is decoded in the page itself, as a data: URL, to avoid a decoder dependency.
 */
export async function mapCentreColour(page: Page): Promise<Colour> {
  const box = await page.locator("#map canvas").boundingBox();
  if (box === null) {
    throw new Error("map canvas has no box");
  }
  const png = await page.screenshot({
    clip: {
      x: Math.round(box.x + box.width / 2),
      y: Math.round(box.y + box.height / 2),
      width: 1,
      height: 1,
    },
  });
  return page.evaluate(async (base64) => {
    const image = new Image();
    image.src = `data:image/png;base64,${base64}`;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, 0);
    const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
    return { r, g, b };
  }, png.toString("base64"));
}

export function sameColour(actual: Colour, expected: Colour, tolerance = 3): boolean {
  return (
    Math.abs(actual.r - expected.r) <= tolerance &&
    Math.abs(actual.g - expected.g) <= tolerance &&
    Math.abs(actual.b - expected.b) <= tolerance
  );
}

/** The z of every tile URL requested for one edition, from a list of request URLs. */
export function requestedZooms(urls: string[], editionId: string): number[] {
  const pattern = new RegExp(`/tiles/${escapeRe(editionId)}/(\\d+)/\\d+/\\d+\\.png`);
  return urls.flatMap((url) => {
    const match = pattern.exec(url);
    return match === null ? [] : [Number(match[1])];
  });
}

/** Drag the map canvas by a pixel offset, and wait for the move to finish. */
export async function dragMap(page: Page, dx: number, dy: number): Promise<void> {
  const box = await page.locator("#map canvas").boundingBox();
  if (box === null) {
    throw new Error("map canvas has no box");
  }
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - dx, y - dy, { steps: 8 });
  await page.mouse.up();
  await waitForCameraIdle(page);
}
