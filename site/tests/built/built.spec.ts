// What `vite build` produces, served from `/sub/` (PR #53 review). The dev suite passed while
// the built page 404'd on MapLibre's worker and showed no map, so this suite drives the real
// bundle and fails on any 4xx or on a notice that is not the first edition.

import { expect, test, type Request, type Response } from "@playwright/test";

import { INITIAL_EDITION } from "../fixtures/manifest.ts";

const FIRST = INITIAL_EDITION;
const PREFIX = "/sub/";

interface Traffic {
  responses: Response[];
  failures: Request[];
}

function watchTraffic(page: import("@playwright/test").Page): Traffic {
  const traffic: Traffic = { responses: [], failures: [] };
  page.on("response", (response) => traffic.responses.push(response));
  page.on("requestfailed", (request) => traffic.failures.push(request));
  return traffic;
}

test("the built bundle renders the initial edition from a subpath", async ({ page }) => {
  const traffic = watchTraffic(page);
  await page.goto("./");

  // "displayed" is set only once the edition's tiles have actually loaded (issue #43).
  await expect(page.locator("#notice")).toHaveAttribute("data-status", "displayed");
  await expect(page.locator("#notice")).toHaveText(
    new RegExp(`^Showing ${FIRST.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.`),
  );
  await expect(page.locator(".card-label")).toHaveText(FIRST.label);
  await expect(page.locator("#map canvas")).toHaveCount(1);

  const failed = traffic.failures.map((request) => request.url());
  expect(failed).toEqual([]);
  const bad = traffic.responses
    .filter((response) => response.status() >= 400)
    .map((response) => `${response.status()} ${response.url()}`);
  expect(bad).toEqual([]);

  const paths = traffic.responses.map((response) => new URL(response.url()).pathname);
  // Everything the page loaded came from under the deploy prefix, same-origin.
  expect(paths.filter((path) => !path.startsWith(PREFIX))).toEqual([]);
  // The worker is the failure this suite exists for: it must be a published asset.
  expect(paths.filter((path) => /maplibre-gl-worker.*\.js$/.test(path))).not.toEqual([]);
  expect(paths.filter((path) => path.startsWith(`${PREFIX}tiles/${FIRST.id}/`))).not.toEqual(
    [],
  );
});

test("a missing file under the prefix is a 404, so the no-4xx check means something", async ({
  request,
}) => {
  const response = await request.get("assets/there-is-no-such-asset.js");
  expect(response.status()).toBe(404);
});
