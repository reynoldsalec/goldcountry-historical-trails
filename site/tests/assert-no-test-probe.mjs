// The Playwright suite reads the camera through a `window.__demoTestProbe` that main.ts
// guards with `import.meta.env.DEV` (issue #44). This asserts the guard really removes it, so
// the test hook cannot ship. Run against site/dist after `vite build`.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DIST = fileURLToPath(new URL("../dist", import.meta.url));
const FORBIDDEN = "__demoTestProbe";

function files(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

let dist;
try {
  dist = files(DIST);
} catch {
  console.error(`assert-no-test-probe: no build at ${DIST}; run "npm run build" first.`);
  process.exit(1);
}

const scripts = dist.filter((path) => path.endsWith(".js"));
if (scripts.length === 0) {
  console.error("assert-no-test-probe: the build produced no JavaScript to inspect.");
  process.exit(1);
}

const leaked = scripts.filter((path) => readFileSync(path, "utf8").includes(FORBIDDEN));
if (leaked.length > 0) {
  console.error(`assert-no-test-probe: ${FORBIDDEN} reached the production bundle:`);
  for (const path of leaked) {
    console.error(`  ${path}`);
  }
  process.exit(1);
}

console.log(
  `assert-no-test-probe: ${FORBIDDEN} absent from ${scripts.length} bundled script(s).`,
);
