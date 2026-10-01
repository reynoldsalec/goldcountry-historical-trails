// Browser tests for the Auburn edition browser (issues #44, #58). Everything here runs against
// generated fixtures on a local vite server, in bundled Chromium only. These checks say the
// paging, camera, failure and accessibility behaviour holds for the fixture world; they are
// not a review of the real sheets, and they are not the human acceptance of issue #38.

import { expect, test, type Page } from "@playwright/test";

import {
  FIXTURE_EDITIONS,
  FIXTURE_SOURCE_URL_HOST,
  FIXTURE_ZOOM,
  INITIAL_INDEX,
  type FixtureEdition,
} from "./fixtures/manifest.ts";
import {
  camera,
  dragMap,
  escapeRe,
  expectShowing,
  installTileFaults,
  mapCentreColour,
  openViewer,
  requestedZooms,
  resetViewCalls,
  sameCamera,
  sameColour,
  storageTouches,
  waitForCameraIdle,
  type Camera,
} from "./harness.ts";

// FIRST is the initial edition, third in the order: the viewer opens mid-sequence.
const [REGIONAL_EARLY, MIDSCALE, FIRST, SECOND, THIRD, FOURTH, REGIONAL_LATE, MODERN_ONE] =
  FIXTURE_EDITIONS;
const LAST = FIXTURE_EDITIONS[FIXTURE_EDITIONS.length - 1];
const LABELS = FIXTURE_EDITIONS.map((edition) => edition.label);

function fixtureNumber(edition: FixtureEdition): number {
  return FIXTURE_EDITIONS.indexOf(edition) + 1;
}

function notice(page: Page) {
  return page.locator("#notice");
}

/**
 * Zoom to the fixture maximum so the bounds are wider than the viewport and a drag moves the
 * camera. One click at a time: a click during the previous animation zooms from wherever the
 * animation had got to, which lands short of the maximum.
 */
async function zoomToMax(page: Page): Promise<void> {
  for (let click = 0; click < 5; click += 1) {
    if ((await waitForCameraIdle(page)).zoom === FIXTURE_ZOOM.max) {
      return;
    }
    await page.locator(".maplibregl-ctrl-zoom-in").click();
  }
  throw new Error(`zoom never reached ${FIXTURE_ZOOM.max}`);
}

test("the initial edition loads with its own card, north up", async ({ page }) => {
  const session = await openViewer(page);
  await expectShowing(page, FIRST.label);
  expect(await page.getByLabel("Choose an edition").inputValue()).toBe(FIRST.id);
  // It sits mid-order, so both directions are open, and no other edition was fetched.
  await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Next" })).toBeEnabled();
  const editionsFetched = new Set(
    session
      .urls()
      .flatMap((url) => /\/tiles\/([^/]+)\//.exec(url)?.slice(1) ?? [])
      .filter(Boolean),
  );
  expect([...editionsFetched]).toEqual([FIRST.id]);

  const view = await camera(page);
  expect(view.bearing).toBe(0);
  expect(view.pitch).toBe(0);
  expect(view.zoom).toBeGreaterThanOrEqual(FIXTURE_ZOOM.min);
  expect(view.zoom).toBeLessThanOrEqual(FIXTURE_ZOOM.max);
  // One map, not one per edition.
  await expect(page.locator("#map canvas")).toHaveCount(1);
  // Every published layer carries its attribution in the control (AGENTS.md §2.7).
  await expect(page.locator(".maplibregl-ctrl-attrib-inner")).toContainText(
    `Fixture attribution ${fixtureNumber(FIRST)} (test data)`,
  );
});

test("Previous and Next walk all nine editions and stop at the ends", async ({ page }) => {
  await openViewer(page);
  const previous = page.getByRole("button", { name: "Previous" });
  const next = page.getByRole("button", { name: "Next" });

  for (const label of LABELS.slice(0, INITIAL_INDEX).reverse()) {
    await previous.click();
    await expectShowing(page, label);
  }
  await expect(previous).toBeDisabled();

  for (const label of LABELS.slice(1)) {
    await next.click();
    await expectShowing(page, label);
  }
  await expect(next).toBeDisabled();

  for (const label of [...LABELS].reverse().slice(1)) {
    await previous.click();
    await expectShowing(page, label);
  }
  await expect(previous).toBeDisabled();
});

test("the selector jumps straight to any edition", async ({ page }) => {
  await openViewer(page);
  const select = page.getByLabel("Choose an edition");

  await select.selectOption(FOURTH.id);
  await expectShowing(page, FOURTH.label);
  await select.selectOption(SECOND.id);
  await expectShowing(page, SECOND.label);
  await select.selectOption(FIRST.id);
  await expectShowing(page, FIRST.label);
});

test("paging never moves the camera, and Reset view is the only thing that does", async ({
  page,
}) => {
  await openViewer(page);
  const fitted = await camera(page);

  await zoomToMax(page);
  await dragMap(page, 120, 90);
  const moved = await camera(page);
  expect(sameCamera(fitted, moved)).toBe(false);

  // Every switch across all nine, forward and back, from a camera the user chose. At the
  // top zoom this crosses into and out of sheets cut two levels lower.
  const steps: { button: string; label: string }[] = [
    ...LABELS.slice(0, INITIAL_INDEX)
      .reverse()
      .map((label) => ({ button: "Previous", label })),
    ...LABELS.slice(1).map((label) => ({ button: "Next", label })),
    ...[...LABELS]
      .reverse()
      .slice(1, LABELS.length - INITIAL_INDEX)
      .map((label) => ({ button: "Previous", label })),
  ];
  for (const step of steps) {
    const before = await camera(page);
    await page.getByRole("button", { name: step.button }).click();
    await expectShowing(page, step.label);
    expect(sameCamera(before, await camera(page))).toBe(true);
  }
  expect(await resetViewCalls(page)).toBe(0);

  const selected = await page.getByLabel("Choose an edition").inputValue();
  await page.getByRole("button", { name: "Reset view" }).click();
  await expect.poll(async () => sameCamera(fitted, await camera(page))).toBe(true);
  expect(await resetViewCalls(page)).toBe(1);
  // The reset is a camera action only: it does not change the edition.
  expect(await page.getByLabel("Choose an edition").inputValue()).toBe(selected);
});

test("clicks faster than the loads settle on the last edition asked for", async ({ page }) => {
  await openViewer(page);
  const next = page.getByRole("button", { name: "Next" });
  const before = await camera(page);

  await next.click();
  await next.click();
  await next.click();

  await expectShowing(page, FOURTH.label);
  expect(await page.getByLabel("Choose an edition").inputValue()).toBe(FOURTH.id);
  expect(sameCamera(before, await camera(page))).toBe(true);
  await expect(page.locator("#map canvas")).toHaveCount(1);
});

test("rapid paging through all nine settles on the last edition asked for", async ({
  page,
}) => {
  await openViewer(page);
  await zoomToMax(page);
  const before = await camera(page);
  const select = page.getByLabel("Choose an edition");
  await select.selectOption(REGIONAL_EARLY.id);
  await expectShowing(page, REGIONAL_EARLY.label);

  const next = page.getByRole("button", { name: "Next" });
  for (let click = 1; click < FIXTURE_EDITIONS.length; click += 1) {
    await next.click();
  }
  await expectShowing(page, LAST.label);
  expect(await select.inputValue()).toBe(LAST.id);
  expect(sameCamera(before, await camera(page))).toBe(true);

  const previous = page.getByRole("button", { name: "Previous" });
  for (let click = 1; click < FIXTURE_EDITIONS.length; click += 1) {
    await previous.click();
  }
  await expectShowing(page, REGIONAL_EARLY.label);
  expect(sameCamera(before, await camera(page))).toBe(true);
  expect(await resetViewCalls(page)).toBe(0);
  await expect(page.locator("#map canvas")).toHaveCount(1);
});

test("a sheet cut below the camera zoom is enlarged in place, never refetched or reset", async ({
  page,
}) => {
  const session = await openViewer(page);
  await zoomToMax(page);
  await dragMap(page, 60, 40);
  const before = await camera(page);
  expect(before.zoom).toBe(FIXTURE_ZOOM.max);
  const card = page.locator("#card");
  await expect(card.locator(".card-detail-limit")).toHaveCount(0);

  for (const edition of [REGIONAL_EARLY, MIDSCALE, REGIONAL_LATE]) {
    expect(edition.nativeMaxZoom).toBeLessThan(FIXTURE_ZOOM.max);
    await page.getByLabel("Choose an edition").selectOption(edition.id);
    await expectShowing(page, edition.label);
    // Same centre, zoom and bearing: the camera was not snapped to the sheet's limit.
    expect(sameCamera(before, await camera(page))).toBe(true);
    // MapLibre asked only for the levels that exist; a request above them would 404.
    const zooms = requestedZooms(session.urls(), edition.id);
    expect(zooms.length).toBeGreaterThan(0);
    expect(Math.max(...zooms)).toBe(edition.nativeMaxZoom);
    // Not blank: the enlarged tile is what is painted at the centre of the map.
    await expect
      .poll(async () => sameColour(await mapCentreColour(page), edition.colour))
      .toBe(true);
    await expect(card.locator(".card-detail-limit")).toContainText(
      `zoom ${edition.nativeMaxZoom}`,
    );
    await expect(card).toContainText(`Detail limitzoom ${edition.nativeMaxZoom}`);
  }

  await page.getByLabel("Choose an edition").selectOption(FIRST.id);
  await expectShowing(page, FIRST.label);
  await expect(card.locator(".card-detail-limit")).toHaveCount(0);
  expect(sameCamera(before, await camera(page))).toBe(true);
  expect(await resetViewCalls(page)).toBe(0);
});

test("the detail-limit line follows the camera on a coarse sheet", async ({ page }) => {
  await openViewer(page);
  await page.getByLabel("Choose an edition").selectOption(REGIONAL_EARLY.id);
  await expectShowing(page, REGIONAL_EARLY.label);
  const line = page.locator("#card .card-detail-limit");
  if ((await camera(page)).zoom <= REGIONAL_EARLY.nativeMaxZoom) {
    await expect(line).toHaveCount(0);
  }
  await zoomToMax(page);
  await expect(line).toContainText(REGIONAL_EARLY.label);
  await expect(line).toContainText("no more detail");
});

test("a slow edition keeps the old sheet and old card under a loading notice", async ({
  page,
}) => {
  await openViewer(page);
  const faults = await installTileFaults(page);
  faults.set(SECOND.id, { delayMs: 2_000 });

  await page.getByRole("button", { name: "Next" }).click();

  await expect(notice(page)).toHaveAttribute("data-status", "loading");
  await expect(notice(page)).toHaveText(
    `Loading ${SECOND.label}; still showing ${FIRST.label}.`,
  );
  // The card still names the pixels that are actually on screen.
  await expect(page.locator(".card-label")).toHaveText(FIRST.label);

  faults.reset();
  await expectShowing(page, SECOND.label);
});

test("an HTTP 404 tile fails the switch, keeps the old sheet and retries clean", async ({
  page,
}) => {
  await openViewer(page);
  const faults = await installTileFaults(page);
  const before = await camera(page);
  faults.set(SECOND.id, "http-404");

  await page.getByRole("button", { name: "Next" }).click();

  await expect(notice(page)).toHaveAttribute("data-status", "error");
  await expect(notice(page)).toHaveText(
    new RegExp(
      `^Could not load ${escapeRe(SECOND.label)}: .*HTTP 404.*Still showing ${escapeRe(FIRST.label)}\\.$`,
    ),
  );
  await expect(page.locator(".card-label")).toHaveText(FIRST.label);
  const retry = page.getByRole("button", { name: "Retry this edition" });
  await expect(retry).toBeVisible();
  expect(sameCamera(before, await camera(page))).toBe(true);

  faults.reset();
  await retry.click();
  await expectShowing(page, SECOND.label);
  await expect(retry).toBeHidden();
  expect(sameCamera(before, await camera(page))).toBe(true);
});

test("an aborted tile request is a failure, not a blank success", async ({ page }) => {
  await openViewer(page);
  const faults = await installTileFaults(page);
  faults.set(THIRD.id, "abort");

  await page.getByLabel("Choose an edition").selectOption(THIRD.id);

  await expect(notice(page)).toHaveAttribute("data-status", "error");
  await expect(notice(page)).toContainText(`Could not load ${THIRD.label}`);
  await expect(notice(page)).toContainText(`Still showing ${FIRST.label}.`);
  await expect(page.locator(".card-label")).toHaveText(FIRST.label);

  faults.reset();
  await page.getByRole("button", { name: "Retry this edition" }).click();
  await expectShowing(page, THIRD.label);
});

test("a tile failure after a settled switch warns, and the warning outlives later idles", async ({
  page,
}) => {
  await openViewer(page);
  const faults = await installTileFaults(page);
  await page.getByRole("button", { name: "Next" }).click();
  await expectShowing(page, SECOND.label);

  // The switch has settled; now the tiles the next zoom needs are missing.
  faults.set(SECOND.id, "http-404");
  await zoomToMax(page);

  await expect(notice(page)).toHaveAttribute("data-warning", "true");
  await expect(notice(page)).toContainText("Some tiles did not load");
  await expect(notice(page)).toContainText(
    "A blank area here may be a missing tile rather than a blank sheet.",
  );
  // The sheet on screen is still the one the card names: a warning, not an unset layer.
  await expect(notice(page)).toHaveAttribute("data-status", "displayed");
  await expect(page.locator(".card-label")).toHaveText(SECOND.label);

  // Later pans and the idles they bring must not quietly retire the gap.
  await dragMap(page, 80, 60);
  await dragMap(page, -80, -60);
  await expect(notice(page)).toHaveAttribute("data-warning", "true");

  faults.reset();
  await page.getByRole("button", { name: "Retry this edition" }).click();
  await expect(notice(page)).toHaveAttribute("data-warning", "false");
  await expectShowing(page, SECOND.label);
});

test("moving the viewport mid-load still settles on the requested edition", async ({
  page,
}) => {
  await openViewer(page);
  const faults = await installTileFaults(page);
  await zoomToMax(page);
  faults.set(SECOND.id, { delayMs: 1_200 });

  await page.getByRole("button", { name: "Next" }).click();
  await expect(notice(page)).toHaveAttribute("data-status", "loading");
  await dragMap(page, 150, 0);
  await expect(page.locator(".card-label")).toHaveText(FIRST.label);

  faults.reset();
  await expectShowing(page, SECOND.label);
});

test("no background external origin, and no browser storage of any kind", async ({ page }) => {
  const session = await openViewer(page);
  for (const label of LABELS.slice(INITIAL_INDEX + 1)) {
    await page.getByRole("button", { name: "Next" }).click();
    await expectShowing(page, label);
  }
  await page.getByRole("button", { name: "Reset view" }).click();

  const origin = new URL(page.url()).origin;
  const offSite = session
    .urls()
    .filter((url) => !url.startsWith(`${origin}/`) && !/^(data|blob):/.test(url));
  expect(offSite).toEqual([]);
  // The fixture source_url host is never contacted unless the link is clicked.
  expect(session.urls().filter((url) => url.startsWith(FIXTURE_SOURCE_URL_HOST))).toEqual([]);

  expect(await storageTouches(page)).toEqual([]);
  expect(page.context().serviceWorkers()).toEqual([]);
  const state = await page.context().storageState();
  expect(state.cookies).toEqual([]);
  expect(state.origins).toEqual([]);
  expect(await page.evaluate(() => document.cookie)).toBe("");
});

test("the original-source link is fetched only when a person clicks it", async ({ page }) => {
  const session = await openViewer(page);
  const link = page.getByRole("link", { name: "Original source record" });
  await expect(link).toHaveAttribute("href", `${FIXTURE_SOURCE_URL_HOST}/${FIRST.id}`);
  expect(session.urls().filter((url) => url.startsWith(FIXTURE_SOURCE_URL_HOST))).toEqual([]);

  // Fulfilled locally so the suite stays offline; the point is that the click, and only the
  // click, produces the request.
  await page.route(`${FIXTURE_SOURCE_URL_HOST}/**`, (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<title>stub</title>" }),
  );
  await link.click();
  await expect
    .poll(() => session.urls().filter((url) => url.startsWith(FIXTURE_SOURCE_URL_HOST)).length)
    .toBe(1);
});

test("at 390 by 844 nothing overflows and every control is reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openViewer(page);

  const overflow = await page.evaluate(() => ({
    documentScroll: document.documentElement.scrollWidth,
    documentClient: document.documentElement.clientWidth,
    bodyScroll: document.body.scrollWidth,
  }));
  expect(overflow.documentScroll).toBeLessThanOrEqual(overflow.documentClient);
  expect(overflow.bodyScroll).toBeLessThanOrEqual(overflow.documentClient);

  for (const name of ["Previous", "Next", "Reset view", "Hide source details"]) {
    const control = page.getByRole("button", { name });
    await control.scrollIntoViewIfNeeded();
    await expect(control).toBeInViewport();
  }
  const select = page.getByLabel("Choose an edition");
  await select.scrollIntoViewIfNeeded();
  await expect(select).toBeInViewport();

  // Paging still works at this width, and the card stays in the page.
  await page.getByRole("button", { name: "Next" }).click();
  await expectShowing(page, SECOND.label);

  // The details toggle stays reachable when the details are collapsed.
  await page.getByRole("button", { name: "Hide source details" }).click();
  await expect(page.locator("#details")).toBeHidden();
  const show = page.getByRole("button", { name: "Show source details" });
  await expect(show).toBeInViewport();
  await show.click();
  await expect(page.locator("#details")).toBeVisible();
});

test("every control has an accessible name and takes focus from the keyboard", async ({
  page,
}) => {
  await openViewer(page);
  // From a middle edition both Previous and Next are enabled; a disabled button is correctly
  // skipped by Tab, which would otherwise hide it from this check.
  await page.getByLabel("Choose an edition").selectOption(SECOND.id);
  await expectShowing(page, SECOND.label);
  await page.locator("body").click({ position: { x: 1, y: 1 } });

  const order: string[] = [];
  for (let step = 0; step < 14; step += 1) {
    await page.keyboard.press("Tab");
    order.push(
      await page.evaluate(() => {
        const active = document.activeElement as HTMLElement | null;
        if (active === null || active === document.body) {
          return "";
        }
        return active.id || active.getAttribute("aria-label") || active.tagName.toLowerCase();
      }),
    );
  }
  for (const id of ["detail-toggle", "edition-select", "previous", "next", "reset-view"]) {
    expect(order).toContain(id);
  }
  expect(order.indexOf("previous")).toBeLessThan(order.indexOf("next"));
  expect(order.indexOf("next")).toBeLessThan(order.indexOf("reset-view"));

  // Accessible names, not just ids.
  await expect(page.getByRole("button", { name: "Previous" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reset view" })).toBeVisible();
  await expect(page.getByLabel("Choose an edition")).toBeVisible();
  await expect(page.locator("#map")).toHaveAttribute("aria-label", "Auburn quadrangle map");

  // The keyboard alone can page an edition.
  await page.getByRole("button", { name: "Next" }).focus();
  await expect(page.getByRole("button", { name: "Next" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expectShowing(page, THIRD.label);

  // And the keyboard alone can move the camera.
  const before = await camera(page);
  await page.locator("#map canvas").focus();
  await page.keyboard.press("Equal");
  await expect.poll(async () => (await camera(page)).zoom).toBeGreaterThan(before.zoom);
});

test("loading and error states are announced in a live region", async ({ page }) => {
  await openViewer(page);
  await expect(notice(page)).toHaveAttribute("role", "status");
  await expect(notice(page)).toHaveAttribute("aria-live", "polite");

  const faults = await installTileFaults(page);
  faults.set(SECOND.id, { delayMs: 1_500 });
  await page.getByRole("button", { name: "Next" }).click();
  await expect(notice(page)).toContainText(`Loading ${SECOND.label}`);
  faults.reset();
  await expectShowing(page, SECOND.label);

  faults.set(THIRD.id, "http-404");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(notice(page)).toContainText(`Could not load ${THIRD.label}`);
  await expect(notice(page)).toHaveAttribute("data-status", "error");
  // The retry control is announced by name, not by colour alone.
  await expect(page.getByRole("button", { name: "Retry this edition" })).toBeVisible();
});

test("the card names the source and asserts no present-day access", async ({ page }) => {
  await openViewer(page);
  const card = page.locator("#card");
  const sourceOf = (edition: FixtureEdition) =>
    `FIXTURE_SOURCE_${fixtureNumber(edition)}_NOT_A_REAL_SCAN`;

  await expect(card).toContainText(sourceOf(FIRST));
  await expect(card).toContainText(`Fixture date note ${fixtureNumber(FIRST)}.`);
  await expect(card).toContainText(
    "A line on a map is not a statement about who may use it today.",
  );

  await page.getByLabel("Choose an edition").selectOption(SECOND.id);
  await expectShowing(page, SECOND.label);
  // The card is rebuilt for the edition on screen: no field survives from the last one.
  await expect(card).toContainText(sourceOf(SECOND));
  await expect(card).not.toContainText(sourceOf(FIRST));
  await expect(card).toContainText("revision not field checked");

  await page.getByLabel("Choose an edition").selectOption(THIRD.id);
  await expectShowing(page, THIRD.label);
  await expect(card).toContainText("Orthophotoquad");
  await expect(card).toContainText("1911-07-04");
});

test("regional and modern cards name their sheet, scale, dates and printed credits", async ({
  page,
}) => {
  await openViewer(page);
  const card = page.locator("#card");
  const select = page.getByLabel("Choose an edition");

  await select.selectOption(REGIONAL_EARLY.id);
  await expectShowing(page, REGIONAL_EARLY.label);
  await expect(card).toContainText("SheetFixture Regional 1:125,000");
  await expect(card).toContainText("Surveyed1877");
  // Null fields are left out, not shown as placeholders.
  await expect(card).not.toContainText("Published");
  await expect(card).not.toContainText("Revision");
  await expect(card.locator(".card-credits")).toHaveCount(0);

  await select.selectOption(REGIONAL_LATE.id);
  await expectShowing(page, REGIONAL_LATE.label);
  await expect(card).toContainText("SheetFixture Regional 1:100,000");

  await select.selectOption(MODERN_ONE.id);
  await expectShowing(page, MODERN_ONE.label);
  await expect(card).toContainText("ProductUS Topo map");
  await expect(card).toContainText("Published1940-02-03");
  await expect(card).not.toContainText("Base sheet");
  await expect(card.locator(".card-credits")).toHaveText(
    `Printed credits: ${MODERN_ONE.creditNote}`,
  );
});

/** A camera reading is only useful if the probe itself is honest about its own shape. */
test("the camera probe reports the four values the invariant needs", async ({ page }) => {
  await openViewer(page);
  const view: Camera = await camera(page);
  expect(Object.keys(view).sort()).toEqual(["bearing", "lat", "lng", "pitch", "zoom"]);
});
