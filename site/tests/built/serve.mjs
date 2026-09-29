// Static file server for the built-output browser suite (PR #53 review). It serves the staged
// tree under a non-root prefix only, and never falls back to index.html: a missing file must
// stay a 404 so the suite can fail on one.

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { join, normalize, resolve } from "node:path";

const ROOT = resolve(process.env.DEMO_BUILT_ROOT ?? "");
const PREFIX = process.env.DEMO_BUILT_PREFIX ?? "/sub/";
const PORT = Number(process.env.DEMO_BUILT_PORT ?? 5275);

const CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};

/** Resolve a request path inside ROOT, rejecting traversal rather than normalising it. */
function resolveFile(urlPath) {
  if (!urlPath.startsWith(PREFIX)) {
    return null;
  }
  let requested = decodeURIComponent(urlPath.slice(PREFIX.length));
  if (requested === "" || requested.endsWith("/")) {
    requested += "index.html";
  }
  const relative = normalize(requested).replace(/^[/\\]+/, "");
  if (relative.split(/[/\\]/).includes("..")) {
    return null;
  }
  const absolute = join(ROOT, relative);
  return absolute.startsWith(ROOT + "/") ? absolute : null;
}

createServer((request, response) => {
  const path = resolveFile((request.url ?? "").split("?")[0]);
  if (path === null) {
    response.statusCode = 404;
    response.end("not found");
    return;
  }
  if (!existsSync(path) || !statSync(path).isFile()) {
    response.statusCode = 404;
    response.end("not found");
    return;
  }
  const suffix = path.slice(path.lastIndexOf("."));
  response.setHeader("Content-Type", CONTENT_TYPES[suffix] ?? "application/octet-stream");
  response.setHeader("Cache-Control", "no-store");
  createReadStream(path).pipe(response);
}).listen(PORT, "127.0.0.1", () => {
  process.stdout.write(`built-site: serving ${ROOT} at http://127.0.0.1:${PORT}${PREFIX}\n`);
});
