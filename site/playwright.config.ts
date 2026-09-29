// Browser tests for the edition browser (issue #44). The suite is offline: the vite dev
// server is pointed at generated fixtures instead of `data/sources/demo-editions.json` and
// `build/tiles/demo`, so it neither reads nor needs the real scans.
//
// Prerequisite: `npx playwright install chromium` (wrapped as `make site-browsers`).
// Tested browser: bundled Chromium only. Firefox and WebKit are not run here, so this
// suite says nothing about them.

import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

import { writeFixtures } from "./tests/fixtures/manifest.ts";

const SITE_DIR = fileURLToPath(new URL(".", import.meta.url));
// A dedicated port, not the 5173 a human's `make demo-dev` uses, and `strictPort` in
// vite.config.ts makes a clash an error rather than a silent move to another port.
const PORT = Number(process.env.DEMO_TEST_PORT ?? 5274);
const BASE_URL = `http://127.0.0.1:${PORT}`;

const fixtureRoot = join(SITE_DIR, ".playwright-fixtures");
const { manifestPath, tileRoot } = writeFixtures(fixtureRoot);

export default defineConfig({
  testDir: "./tests",
  // tests/built runs against the built bundle on its own server; see
  // playwright.built.config.ts.
  testIgnore: "built/**",
  // One worker: every test drives a WebGL map and a routed tile server, and a shared dev
  // server. Determinism matters more here than wall clock.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["github"]] : [["list"]],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1280, height: 800 },
    // Deliberately not "block": a registration must be observable so the suite can fail on
    // it, rather than be silently prevented.
    serviceWorkers: "allow",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: BASE_URL,
    cwd: SITE_DIR,
    // Never adopt a server this run did not start, and never leave one behind.
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
    env: {
      DEMO_PORT: String(PORT),
      DEMO_MANIFEST: manifestPath,
      DEMO_TILE_ROOT: tileRoot,
    },
  },
});
