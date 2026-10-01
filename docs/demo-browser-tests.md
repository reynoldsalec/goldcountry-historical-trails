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
`data/sources/demo-editions.json`, `build/tiles/demo` and `build/expansion/tiles`. A test run reads no raw scan, no
receipt and no real pyramid, and writes nothing under `data/`.

The fixtures are built by `site/tests/fixtures/manifest.ts` into
`site/.playwright-fixtures/` (gitignored) when the Playwright config loads:

- nine editions with invented ids, shaped like the real set (#58): two coarse regional
  sheets, a 1:62,500 sheet, four base sheets (`fixture-first` … `fixture-fourth`, one a
  photo product) and two modern products with invented printed credits; invented source
  ids (`FIXTURE_SOURCE_1_NOT_A_REAL_SCAN` …), citations and years 1880–1950. The third,
  `fixture-first`, is `initial_edition`, so the viewer opens mid-order;
- bounds `[0, 0, 0.5, 0.5]` — half a degree in the Gulf of Guinea, nowhere near Auburn;
- zooms 10–12; each edition's pyramid stops at its own `native_max_zoom` (10, 11 or 12), so
  a viewer that asked for a level above it would get a 404. Each tile is a flat colour PNG
  written by the hand-rolled encoder in `site/tests/fixtures/png.ts`, so no binary fixture
  is committed and the bytes are identical every run.

Nothing in the fixture set can be mistaken for evidence, and nothing in it is committed as
data. `source_url` points at `https://fixture-source-record.invalid`, which cannot resolve:
a background request to it would be an obvious failure rather than a silent one.

The server runs on port 5274 (`DEMO_TEST_PORT`), not the 5173 that `make demo-dev` uses.
`strictPort` is on, so a clash is an error rather than a quiet move to another port.
Playwright starts and stops that one process; `reuseExistingServer` is false, so a run never
adopts or kills a server it did not start.

## 3. What is asserted

`site/tests/editions.spec.ts`, 21 tests:

| Area | Assertion |
| --- | --- |
| First load | the initial (third) edition's card and notice name the same edition; both Previous and Next enabled; no other edition's tiles fetched; bearing 0, pitch 0, zoom inside the manifest range; one canvas; the layer's attribution is in the control |
| Paging | Previous/Next walk all nine forward and back; Previous is disabled at the first edition and Next at the last |
| Direct jump | the selector reaches any edition from any other |
| Camera invariant | after a zoom to 12 and a drag, every switch across all nine, into and out of sheets cut to 10 and 11, leaves centre, zoom, bearing and pitch bit-identical, and `resetViewCalls` stays 0 |
| Reset view | returns to the fitted camera, counts one call, and leaves the selected edition alone |
| Fast clicks | three Next clicks inside one load settle on the requested edition, with one canvas and an unmoved camera |
| Rapid paging | at zoom 12, eight Next clicks then eight Previous clicks with no waits settle on the last and then the first edition; camera unmoved, no reset, one canvas |
| Overzoom | at zoom 12, selecting each sheet cut to 10 or 11 keeps the camera, requests no tile above the sheet's own top zoom, paints the sheet's colour at the map centre (not blank), and shows the card's detail-limit line; returning to a zoom-12 sheet removes the line |
| Detail line | on a coarse sheet the detail-limit line appears once a zoom passes its limit |
| Regional and modern cards | sheet name and scale (`1:125,000`, `1:100,000`), survey year, US Topo product, publication date and printed credits verbatim; null fields omitted |
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

## 6. The second suite: the built bundle, served from a subpath

The suite above drives `npm run dev`, so it cannot see a failure that exists only in the
built output. One did: `vite build` emitted no MapLibre worker asset, the published page
404'd on `assets/maplibre-gl-worker.mjs`, and no edition ever appeared (PR #53 review).

`site/playwright.built.config.ts` closes that gap. It copies `site/dist` into
`site/.playwright-built/` (gitignored), adds the same fixture `editions.json` and fixture
tile pyramids, and serves that tree with `site/tests/built/serve.mjs` under `/sub/` on port
5275 (`DEMO_BUILT_PORT`) - a non-root prefix on purpose, because the published tree has to
work where it is deployed. The server never falls back to `index.html`, so a missing file
stays a 404.

`site/tests/built/built.spec.ts`, 2 tests:

| Area | Assertion |
| --- | --- |
| First load from `/sub/` | `#notice` reaches `data-status="displayed"` and names the first edition, the card names it too, one canvas; no request failed and no response was 4xx or worse; every request was under `/sub/`; the MapLibre worker asset and the first edition's tiles were among them |
| The 404 control | an unknown path under the prefix really returns 404, so the no-4xx assertion is not vacuous |

Verified against a deliberate regression: with `setWorkerUrl` removed from
`site/src/main.ts`, the staged page requested `/sub/assets/maplibre-gl-worker.mjs`, got a
404, and `#notice` read `Could not load Fixture sheet one (test data, 1899): Worker failed
to load. Check that the worker URL is correct.. No edition is on screen yet.` with
`data-status="error"`. The first test failed; with the fix in place both pass.

`make demo-browser-test` runs both suites, dev first.

## 7. Limits

- Chromium only, headless, one worker, on a fixture world of flat-colour tiles. Nothing here
  checks that the real rasters register against each other, that the scans are legible, or
  that the card text is factually right about a USGS sheet.
- The built-bundle suite (§6) loads the real `vite build` output, but against fixture tiles
  and a fixture `editions.json`, not `build/public`. It says the bundle starts, fetches its
  own assets relatively and renders one edition; it says nothing about the real pyramids.
- No screenshot or pixel comparison. "The right edition is on screen" is asserted through the
  state the viewer publishes (the notice status and the card), not through pixels.
