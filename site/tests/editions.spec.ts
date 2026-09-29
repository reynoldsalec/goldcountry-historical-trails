// Browser tests for the Auburn edition browser (issue #44). Everything here runs against
// generated fixtures on a local vite server, in bundled Chromium only. These checks say the
// paging, camera, failure and accessibility behaviour holds for the fixture world; they are
// not a review of the real sheets, and they are not the human acceptance of issue #38.

import { expect, test, type Page } from "@playwright/test";

import {
  FIXTURE_EDITIONS,
  FIXTURE_SOURCE_URL_HOST,
  FIXTURE_ZOOM,
} from "./fixtures/manifest.ts";
import {
  camera,
  dragMap,
  escapeRe,
  expectShowing,
  installTileFaults,
  openViewer,
  resetViewCalls,
  sameCamera,
  storageTouches,
  waitForCameraIdle,
  type Camera,
} from "./harness.ts";

const [FIRST, SECOND, THIRD, FOURTH] = FIXTURE_EDITIONS;
const LABELS = FIXTURE_EDITIONS.map((edition) => edition.label);

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

test("the first edition loads with its own card, north up", async ({ page }) => {
  await openViewer(page);
  await expectShowing(page, FIRST.label);

  const view = await camera(page);
  expect(view.bearing).toBe(0);
  expect(view.pitch).toBe(0);
  expect(view.zoom).toBeGreaterThanOrEqual(FIXTURE_ZOOM.min);
  expect(view.zoom).toBeLessThanOrEqual(FIXTURE_ZOOM.max);
  // One map, not one per edition.
  await expect(page.locator("#map canvas")).toHaveCount(1);
  // Every published layer carries its attribution in the control (AGENTS.md §2.7).
  await expect(page.locator(".maplibregl-ctrl-attrib-inner")).toContainText(
    "Fixture attribution 1 (test data)",
  );
});

test("Previous and Next walk every edition and stop at the ends", async ({ page }) => {
  await openViewer(page);
  const previous = page.getByRole("button", { name: "Previous" });
  const next = page.getByRole("button", { name: "Next" });

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

  // Every switch, forward and back, from a camera the user chose.
  const steps: { button: string; label: string }[] = [
    ...LABELS.slice(1).map((label) => ({ button: "Next", label })),
    ...[...LABELS]
      .reverse()
      .slice(1)
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
  for (const label of LABELS.slice(1)) {
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

  await expect(card).toContainText("FIXTURE_SOURCE_1_NOT_A_REAL_SCAN");
  await expect(card).toContainText("Fixture date note 1.");
  await expect(card).toContainText(
    "A line on a map is not a statement about who may use it today.",
  );

  await page.getByLabel("Choose an edition").selectOption(SECOND.id);
  await expectShowing(page, SECOND.label);
  // The card is rebuilt for the edition on screen: no field survives from the last one.
  await expect(card).toContainText("FIXTURE_SOURCE_2_NOT_A_REAL_SCAN");
  await expect(card).not.toContainText("FIXTURE_SOURCE_1_NOT_A_REAL_SCAN");
  await expect(card).toContainText("revision not field checked");

  await page.getByLabel("Choose an edition").selectOption(THIRD.id);
  await expectShowing(page, THIRD.label);
  await expect(card).toContainText("Orthophotoquad");
  await expect(card).toContainText("1911-07-04");
});

/** A camera reading is only useful if the probe itself is honest about its own shape. */
test("the camera probe reports the four values the invariant needs", async ({ page }) => {
  await openViewer(page);
  const view: Camera = await camera(page);
  expect(Object.keys(view).sort()).toEqual(["bearing", "lat", "lng", "pitch", "zoom"]);
});
