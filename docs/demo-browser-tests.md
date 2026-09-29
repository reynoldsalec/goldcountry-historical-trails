# The browser test suite (D3c, `make demo-browser-test`)

Playwright checks for the Auburn edition browser: paging, camera invariants, tile failures,
narrow layout and keyboard use. Written for issue #44. Everything below is automated
inspection. The human acceptance of the real sheets is issue #38 and nothing here stands in
for it.

## 1. Prerequisite: one headless browser

```sh
make site-browsers      # npm ci, then playwright install chromium
```

Idempotent. It downloads into the shared Playwright cache
(`~/.cache/ms-playwright` on Linux, `~/Library/Caches/ms-playwright` on macOS), so a second
run does nothing. `make demo-browser-test` depends on it, so a fresh clone needs no extra
step. CI does not run this suite yet; wiring it (Node and Playwright in CI) is #46.

**Tested browser: bundled Chromium only** (`@playwright/test` 1.63.0, which pins Chromium
revision 1243, browser version 153.0.8010.12). Firefox and WebKit are not installed and not
run under this target, and no project is defined for them. The suite therefore says
nothing about them, and no compatibility claim beyond Chromium may be made from it.

## 2. The suite is offline, and it never reads a source

`site/vite.config.ts` takes three environment overrides: `DEMO_MANIFEST`, `DEMO_TILE_ROOT`
and `DEMO_PORT`. `site/playwright.config.ts` sets all three, so the dev server serves a
generated fixture manifest and generated fixture tiles instead of
`data/sources/demo-editions.json` and `build/tiles/demo`. A test run reads no raw scan, no
receipt and no real pyramid, and writes nothing under `data/`.

The fixtures are built by `site/tests/fixtures/manifest.ts` into
`site/.playwright-fixtures/` (gitignored) when the Playwright config loads:

- four editions with invented ids (`fixture-first` … `fixture-fourth`), invented source ids
  (`FIXTURE_SOURCE_1_NOT_A_REAL_SCAN` …), invented citations and years 1899–1920;
- bounds `[0, 0, 0.5, 0.5]` — half a degree in the Gulf of Guinea, nowhere near Auburn;
- zooms 10–12, 26 tiles per edition, each a flat colour PNG written by the hand-rolled
  encoder in `site/tests/fixtures/png.ts`, so no binary fixture is committed and the bytes
  are identical every run.

Nothing in the fixture set can be mistaken for evidence, and nothing in it is committed as
data. `source_url` points at `https://fixture-source-record.invalid`, which cannot resolve:
a background request to it would be an obvious failure rather than a silent one.

The server runs on port 5274 (`DEMO_TEST_PORT`), not the 5173 that `make demo-dev` uses.
`strictPort` is on, so a clash is an error rather than a quiet move to another port.
Playwright starts and stops that one process; `reuseExistingServer` is false, so a run never
adopts or kills a server it did not start.

## 3. What is asserted

`site/tests/editions.spec.ts`, 17 tests:

| Area | Assertion |
| --- | --- |
| First load | the first edition's card and notice name the same edition; bearing 0, pitch 0, zoom inside the manifest range; one canvas; the layer's attribution is in the control |
| Paging | Previous/Next walk all four forward and back; Previous is disabled at the first edition and Next at the last |
| Direct jump | the selector reaches any edition from any other |
| Camera invariant | after a zoom and a drag, every one of the six switches leaves centre, zoom, bearing and pitch bit-identical, and `resetViewCalls` stays 0 |
| Reset view | returns to the fitted camera, counts one call, and leaves the selected edition alone |
| Fast clicks | three Next clicks inside one load settle on the fourth edition, with one canvas and an unmoved camera |
| Slow load | notice reads `Loading X; still showing Y.` and the card still names Y |
| HTTP 404 | the switch fails, the old sheet and card stay, the notice names the failed edition and the one still showing, Retry appears, the camera does not move, and Retry settles clean |
| Aborted request | same outcome as a 404: an error and the previous sheet, never a blank success |
| Warning persistence | a tile failure after a settled switch warns, keeps the card, and survives two later drags and their idles; only Retry clears it |
| Move during load | a drag mid-load does not reveal the requested edition early, and the switch still settles |
| Request allowlist | every request the page makes is to the test server's own origin; the `.invalid` host is never contacted |
| Browser storage | `localStorage`, `sessionStorage`, `indexedDB`, `caches` and `serviceWorker.register` are instrumented and untouched; no service worker, no cookie, empty `storageState` |
| Clicked source link | the link carries the manifest URL, is not fetched until clicked, and the click produces exactly one request |
| 390 × 844 | no document or body horizontal overflow; Previous, Next, Reset view, the selector and the details toggle are all in the viewport; paging works; the toggle stays reachable while the details are collapsed |
| Keyboard | Tab reaches the toggle, selector, Previous, Next and Reset view in order, each with an accessible name; Enter on Next pages the edition; `=` on the canvas zooms |
| Announcement | `#notice` is `role="status" aria-live="polite"`; loading and error text land in it; Retry is named, not colour-coded |

Storage is instrumented rather than blocked, and `serviceWorkers` is `"allow"` rather than
`"block"`: a violation has to be observable for the suite to fail on it.

## 4. The test hook, and why it cannot ship

The camera is read through `window.__demoTestProbe`, set in `site/src/main.ts` behind
`import.meta.env.DEV`. `vite build` inlines that as `false` and drops the branch, so the
production bundle carries neither the probe nor its name.
`make demo-browser-test` runs `npm run build` and then
`site/tests/assert-no-test-probe.mjs`, which greps every bundled script for the identifier
and exits non-zero if it is there. Nothing else in `site/` puts anything on `window`.

## 5. The deliberate regressions, and the recorded failures

Two regressions were introduced on purpose, run, and reverted. Both were caught. Recorded
output, not paraphrase.

**Camera reset on switch.** One line added to `EditionBrowser.select` in
`site/src/editions.ts`:

```
this.map.fitBounds(this.manifest.view_bounds_wgs84, { padding: this.resetPadding });
```

```
  1) [chromium] › tests/editions.spec.ts:97:1 › paging never moves the camera, and Reset view is the only thing that does

    Error: expect(received).toBe(expected) // Object.is equality

    Expected: true
    Received: false

      118 |     await page.getByRole("button", { name: step.button }).click();
      119 |     await expectShowing(page, step.label);
    > 120 |     expect(sameCamera(before, await camera(page))).toBe(true);

  1 failed
  16 passed (57.1s)
```

Line removed again; the suite went back to 17 passed.

**Stale card under a new label.** `confirmDisplayed` changed to keep whatever was displayed
first:

```
displayedId: this.current.displayedId ?? id,
```

```
  1) [chromium] › tests/editions.spec.ts:66:1 › Previous and Next walk every edition and stop at the ends

    Error: expect(locator).toHaveText(expected) failed

    Locator: locator('#notice')
    Expected pattern: /^Showing Fixture sheet two \(test data, 1899\/1905\)\./
    Received string:  "Showing Fixture sheet one (test data, 1899)."
    Timeout: 10000ms
```

Fourteen of the seventeen tests failed on that one change. No assertion was loosened to make
either case pass; the code was put back instead.

## 6. Limits

- Chromium only, headless, one worker, on a fixture world of flat-colour tiles. Nothing here
  checks that the real rasters register against each other, that the scans are legible, or
  that the card text is factually right about a USGS sheet.
- The suite drives the dev server, so it exercises the dev module graph. The production
  bundle is built and inspected for the test hook, but it is not the artifact the browser
  tests load. The public build is D4.
- No screenshot or pixel comparison. "The right edition is on screen" is asserted through the
  state the viewer publishes (the notice status and the card), not through pixels.
