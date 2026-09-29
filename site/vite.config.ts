// Dev-server wiring for the edition browser shell (issue #42). The public build that
// writes editions.json and copies the tile trees is D4; until then the dev server serves
// both straight out of the repo so the shell can be inspected against the real rasters.

import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vitest/config";

import { publicManifestFrom } from "./src/editions.ts";

const SITE_DIR = fileURLToPath(new URL(".", import.meta.url));
const REPO_ROOT = resolve(SITE_DIR, "..");
// The Playwright suite points these at generated fixtures so it never serves, and never
// depends on, the real scans or their receipts (issue #44).
const MANIFEST_PATH = resolve(
  process.env.DEMO_MANIFEST ?? join(REPO_ROOT, "data/sources/demo-editions.json"),
);
const TILE_ROOT = resolve(process.env.DEMO_TILE_ROOT ?? join(REPO_ROOT, "build/tiles/demo"));
const PORT = Number(process.env.DEMO_PORT ?? 5173);

/** Reject `..` before it is joined, so a request cannot escape the tile tree. */
function safeTilePath(urlPath: string): string | null {
  const relative = normalize(decodeURIComponent(urlPath)).replace(/^[/\\]+/, "");
  if (relative.split(/[/\\]/).includes("..")) {
    return null;
  }
  const absolute = join(TILE_ROOT, relative);
  return absolute.startsWith(TILE_ROOT + "/") ? absolute : null;
}

function demoDevServer(): Plugin {
  return {
    name: "demo-dev-server",
    configureServer(server) {
      server.middlewares.use("/editions.json", (_request, response) => {
        // Read per request so an edit to the manifest shows up without a restart.
        const source = JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
        const body = JSON.stringify(publicManifestFrom(source));
        response.setHeader("Content-Type", "application/json; charset=utf-8");
        response.setHeader("Cache-Control", "no-store");
        response.end(body);
      });

      server.middlewares.use("/tiles", (request, response, next) => {
        const path = safeTilePath((request.url ?? "").split("?")[0]);
        if (!path) {
          response.statusCode = 400;
          response.end("bad tile path");
          return;
        }
        if (!existsSync(path) || !statSync(path).isFile()) {
          // A missing tile is a real 404, never a blank success (issue #42).
          response.statusCode = 404;
          response.setHeader("Cache-Control", "no-store");
          response.end("no such tile");
          return;
        }
        response.setHeader("Content-Type", "image/png");
        createReadStream(path).pipe(response).on("error", next);
      });

      const missing = !existsSync(TILE_ROOT);
      server.config.logger.info(
        missing
          ? `demo-dev: no tiles at ${TILE_ROOT}; run "make demo-rasters" first`
          : `demo-dev: serving /tiles from ${TILE_ROOT}`,
      );
    },
  };
}

export default defineConfig({
  root: SITE_DIR,
  plugins: [demoDevServer()],
  server: { port: PORT, strictPort: true, host: "127.0.0.1", open: false },
  // Pre-bundling rewrites MapLibre's worker URL and the worker then fails to start in dev.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  build: { outDir: "dist", emptyOutDir: true, assetsDir: "assets" },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
