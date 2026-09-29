// Browser tests for the built bundle, served from a subpath (PR #53 review). The dev suite
// in playwright.config.ts drives `npm run dev`, so it cannot see a production-only failure
// such as a worker asset vite never emitted.
//
// Prerequisites: `npm run build` (the staged tree is a copy of site/dist) and
// `npx playwright install chromium`. Bundled Chromium only.

import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

import { stageBuiltSite } from "./tests/built/stage.ts";

const SITE_DIR = fileURLToPath(new URL(".", import.meta.url));
const PORT = Number(process.env.DEMO_BUILT_PORT ?? 5275);
// A non-root prefix on purpose: the published tree must work where it is deployed, not only
// at a domain root.
const PREFIX = "/sub/";
const BASE_URL = `http://127.0.0.1:${PORT}${PREFIX}`;

const stageRoot = join(SITE_DIR, ".playwright-built");
stageBuiltSite(join(SITE_DIR, "dist"), stageRoot);

export default defineConfig({
  testDir: "./tests/built",
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
    serviceWorkers: "allow",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "node tests/built/serve.mjs",
    url: `${BASE_URL}index.html`,
    cwd: SITE_DIR,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
    env: {
      DEMO_BUILT_PORT: String(PORT),
      DEMO_BUILT_PREFIX: PREFIX,
      DEMO_BUILT_ROOT: stageRoot,
    },
  },
});
