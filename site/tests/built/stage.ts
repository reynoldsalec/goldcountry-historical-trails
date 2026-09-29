// Stage the real `vite build` output the way `build/public` is laid out, so the built bundle
// can be driven in a browser (PR #53 review). The editions.json and the tiles are the same
// invented fixtures the dev suite uses, so nothing here reads the Auburn scans.

import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { publicManifestFrom } from "../../src/editions.ts";
import { fixtureSourceManifest, writeFixtureTiles } from "../fixtures/manifest.ts";

/**
 * Copy `dist` to `root` and add the two things the publisher adds. Throws when there is no
 * build, rather than serving an empty tree that would fail the tests for the wrong reason.
 */
export function stageBuiltSite(distDir: string, root: string): void {
  if (!existsSync(join(distDir, "index.html"))) {
    throw new Error(`no built site at ${distDir}; run "npm run build" in site/ first`);
  }
  rmSync(root, { recursive: true, force: true });
  mkdirSync(root, { recursive: true });
  cpSync(distDir, root, { recursive: true });
  const manifest = publicManifestFrom(fixtureSourceManifest());
  writeFileSync(join(root, "editions.json"), `${JSON.stringify(manifest, null, 2)}\n`);
  writeFixtureTiles(join(root, "tiles"));
}
