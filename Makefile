# Everything runs through this file (AGENTS.md §4.3). Targets are idempotent and safe
# to re-run. Targets whose milestone has not landed yet exit with a clear message
# rather than silently doing nothing.

UV := uv
RUN := $(UV) run
TRAIL_ARCHIVE_ROOT ?= /Volumes/T7 Shield/historical-trails-backup
export TRAIL_ARCHIVE_ROOT

.DEFAULT_GOAL := all
.PHONY: all setup fetch-aoi fetch-topo rasters validate tiles build-public build-restricted \
        dev fmt lint clean test-topo test-validation test-coverage topo-docs topo-plan \
        fetch-topo-selected coverage-grid coverage-refresh validate-coverage \
        coverage-ready coverage-report \
        catalog-sources verify-sources \
        backup-sources restore-sources verify-backup \
        demo-check demo-inspect demo-test demo-cogs demo-rasters demo-build \
        demo-dev site-deps demo-frontend-test site-browsers demo-browser-test \
        demo-accept

## build the public output, then validate the data and that output (AGENTS.md §4.3)
# Sequential $(MAKE) lines, not prerequisites: the leak scan must read a tree that this
# run built, which parallel make would not guarantee.
all:
	$(MAKE) build-public
	$(MAKE) validate

## uv sync, and check for the external tools the pipeline needs
# GDAL comes from the rasterio wheel and tippecanoe is deferred with the vector program,
# so node is the only binary the Auburn demo needs beyond uv.
setup:
	$(UV) sync
	@missing=""; \
	for tool in node; do \
	  command -v $$tool >/dev/null 2>&1 || missing="$$missing $$tool"; \
	done; \
	if [ -n "$$missing" ]; then \
	  echo "setup: missing external tool(s):$$missing"; \
	  echo "setup: install node 20+ (nodejs.org, nvm, or 'brew install node')."; \
	  echo "setup: 'make validate' does not need it; the site and demo targets do."; \
	else \
	  echo "setup: node present; GDAL is bundled with rasterio."; \
	fi
	@echo "setup: tippecanoe and a gdal CLI are not required; both are deferred with the"
	@echo "setup: countywide vector program (README.md §7, M4/M5)."

## schemas, referential integrity, temporal coherence, geometry, leak test
validate:
	$(RUN) python scripts/validate.py
	$(RUN) python scripts/source_archive.py verify --available
	$(MAKE) validate-coverage

## rebuild both AOIs from online sources (Census TIGERweb + OpenStreetMap)
fetch-aoi:
	$(RUN) python scripts/fetch_aoi.py counties
	$(RUN) python scripts/fetch_aoi.py tier1

## index + pull historical topo sheets covering the acquisition AOI into data/raw/topo/
# TOPO := --tier1 narrows the download to the legacy work area (91 sheets, 1.0 GB)
# instead of the whole acquisition AOI (615 sheets, 6.3 GB). The index is always built
# county-wide so the two scopes cannot drift apart.
TOPO ?=
fetch-topo:
	$(RUN) python scripts/fetch_topoview.py index
	$(RUN) python scripts/fetch_topoview.py download $(TOPO)
	$(RUN) python scripts/fetch_topoview.py docs

topo-docs:
	$(RUN) python scripts/fetch_topoview.py docs

# SELECTION names a JSON file {"version":1,"topo_ids":[...]} of exact editions to pull
# from the committed index; the index itself is never refreshed by these targets.
SELECTION ?=
topo-plan:
	$(RUN) python scripts/fetch_topoview.py download --dry-run $(TOPO) \
	  $(if $(SELECTION),--selection "$(SELECTION)")

fetch-topo-selected:
	@test -n "$(SELECTION)" || { \
	  echo 'fetch-topo-selected: set SELECTION=path/to/selection.json'; exit 1; }
	$(RUN) python scripts/fetch_topoview.py download --selection "$(SELECTION)"

test-topo:
	$(RUN) pytest -q scripts/test_fetch_topoview.py scripts/test_source_archive.py

catalog-sources:
	$(RUN) python scripts/source_archive.py catalog

verify-sources:
	$(RUN) python scripts/source_archive.py verify

backup-sources:
	$(RUN) python scripts/source_archive.py backup

restore-sources:
	$(RUN) python scripts/source_archive.py restore

verify-backup:
	$(RUN) python scripts/source_archive.py verify-backup

## Auburn map-browser demo (docs/implementation-plan.md, D1)
# DEMO_RAW_ROOT points the preflight at the raw scans when they are not in this checkout
# (data/raw is gitignored, so a worktree usually has none).
DEMO_RAW_ROOT ?= data/raw
export DEMO_RAW_ROOT

## verify the four-edition manifest against its schema, the index, receipts and scans
demo-check:
	$(RUN) python scripts/demo.py check

## print the neatline locators and derived geometry that demo-check compares against
demo-inspect:
	$(RUN) python scripts/demo.py inspect

## warp the four verified sources onto one EPSG:3857 grid -> build/rasters/ (D2a)
# Uses the GDAL inside the rasterio wheel; no gdalwarp binary is needed. Re-running warps
# only what changed. See docs/demo-processing.md.
demo-cogs:
	$(RUN) python scripts/demo.py cogs

## preflight + COGs + bounded XYZ PNG tiles -> build/tiles/demo/<edition>/{z}/{x}/{y}.png (D2b)
# Zooms 10-16, XYZ y orientation, cut with the same bundled GDAL as demo-cogs. Unchanged
# pyramids are reused. See docs/demo-processing.md.
demo-rasters:
	$(RUN) python scripts/demo.py rasters

NPM ?= npm
SITE := site

## install the pinned frontend dependencies; a no-op once the lockfile is satisfied
site-deps: $(SITE)/node_modules/.package-lock.json
$(SITE)/node_modules/.package-lock.json: $(SITE)/package.json $(SITE)/package-lock.json
	cd $(SITE) && $(NPM) ci --no-audit --fund=false
	@touch $@

## vitest unit tests and prettier/tsc checks for the edition browser shell (D3a)
demo-frontend-test: site-deps
	cd $(SITE) && $(NPM) run format:check
	cd $(SITE) && $(NPM) run typecheck
	cd $(SITE) && $(NPM) run test

## vite dev server for the edition browser -> http://127.0.0.1:5173/
# Serves /editions.json from data/sources/demo-editions.json and /tiles from
# build/tiles/demo, so run 'make demo-rasters' first or the map has no imagery.
demo-dev: site-deps
	@test -d build/tiles/demo || { \
	  echo 'demo-dev: no tiles in build/tiles/demo; run "make demo-rasters" first.'; exit 1; }
	cd $(SITE) && $(NPM) run dev

## install the headless browser Playwright drives; idempotent once the cache is populated
site-browsers: site-deps
	cd $(SITE) && $(NPM) run browsers

## Playwright checks for paging, camera, failures, layout and accessibility (D3c)
# Offline: the dev server is pointed at generated fixtures, never at data/sources or
# build/tiles. DEMO_TEST_PORT (default 5274) is this suite's own port, separate from
# 'make demo-dev'. Bundled Chromium only. See docs/demo-browser-tests.md.
# The second suite serves the built bundle from a subpath on DEMO_BUILT_PORT (default 5275),
# so a production-only failure such as a missing worker asset cannot pass unseen (PR #53).
DEMO_TEST_PORT ?= 5274
DEMO_BUILT_PORT ?= 5275
export DEMO_TEST_PORT DEMO_BUILT_PORT
demo-browser-test: site-browsers
	cd $(SITE) && $(NPM) run build
	cd $(SITE) && node tests/assert-no-test-probe.mjs
	cd $(SITE) && $(NPM) run test:browser
	cd $(SITE) && $(NPM) run test:browser:built

## preflight + rasters + site bundle -> allowlisted build/public/ (D4a)
# Only the four recorded tile trees, the built app assets and a sanitized editions.json are
# copied. Nothing is published until the staged tree passes its completeness and
# restricted-value checks, so a failure leaves any previous build/public untouched.
# The output inventory is written to build/publish/demo-publish.json.
demo-build: site-deps
	$(RUN) python scripts/demo.py build

demo-test: demo-frontend-test demo-browser-test
	$(RUN) pytest -q scripts/test_demo.py scripts/test_demo_rasters.py \
	  scripts/test_demo_build.py scripts/test_demo_make.py

## the local release gate: offline demo suites, the real build, then baseline validation (D4b)
# Validation runs last and on purpose: scripts/validate.py scans the build/public tree this
# run just published, so an empty or absent build cannot pass as a clean leak scan.
# Needs the selected scans; point DEMO_RAW_ROOT at them. Never run in CI (docs/demo-acceptance.md).
demo-accept:
	$(MAKE) demo-test
	$(MAKE) demo-build
	$(MAKE) validate
	@echo "demo-accept: built and validated build/public; human acceptance is issue #38."

# Files are listed explicitly so a deleted or renamed regression module fails loudly
# instead of silently shrinking the glob.
test-validation:
	$(RUN) pytest -q scripts/test_validate.py scripts/test_validate_dates.py scripts/test_validate_leaks.py

test-coverage:
	$(RUN) pytest -q scripts/test_coverage_schema.py scripts/test_coverage_grid.py \
	  scripts/test_coverage_refresh.py scripts/test_coverage_validate.py \
	  scripts/test_coverage_report.py

## 7.5-minute reference grid over the county AOI -> data/sources/coverage_grid.geojson
coverage-grid:
	$(RUN) python scripts/coverage.py grid

## area/decade cells + candidate source references -> data/sources/coverage.json
# THROUGH_DECADE pins the horizon so a run is reproducible across calendar years.
THROUGH_DECADE ?=
coverage-refresh:
	$(RUN) python scripts/coverage.py refresh \
	  $(if $(THROUGH_DECADE),--through-decade $(THROUGH_DECADE))

## inventory cross-references, cell coverage and batch readiness
validate-coverage:
	$(RUN) python scripts/coverage.py validate

## county/decade coverage counts -> docs/coverage.md
coverage-report:
	$(RUN) python scripts/coverage.py report

## the M1 release gate: four ready county/decade batches and one obtainable aerial frame
coverage-ready:
	$(RUN) python scripts/coverage.py validate --release-ready

## warp + COG aerial frames from committed GCP files (countywide program)
rasters:
	@echo "make rasters: deferred with the countywide raster pipeline (M2)."
	@echo "  Needs committed .points files in data/sources/gcp/ for raw aerial frames."
	@echo "  The four already-georeferenced Auburn editions warp with 'make demo-cogs'."
	@exit 1

## tippecanoe -> build/tiles/alignments.pmtiles
tiles:
	@echo "make tiles: deferred with the countywide vector program (M4)."
	@echo "  Needs digitized alignments and tippecanoe; the demo ships raster PNG tiles"
	@echo "  from 'make demo-rasters' and no vector or PMTiles layer."
	@exit 1

## the public build: currently the Auburn map browser (alias of demo-build)
build-public: demo-build

## assemble build/restricted/
build-restricted:
	@echo "make build-restricted: deferred with the authenticated countywide build (M5)."
	@echo "  The raster-only MVP has a public build only; its restricted-value scan"
	@echo "  already runs in 'make validate'. See README.md §7, M5."
	@exit 1

## dev server for the viewer: currently the Auburn map browser (alias of demo-dev)
dev: demo-dev

## ruff format
fmt:
	$(RUN) ruff format scripts
	$(RUN) ruff check --fix scripts

## ruff check
lint:
	$(RUN) ruff format --check scripts
	$(RUN) ruff check scripts

## remove derived output; never touches data/
clean:
	rm -rf build/public build/restricted build/tiles build/rasters build/publish \
	  build/.public-incoming build/.public-previous
