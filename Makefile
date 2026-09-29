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
        demo-check demo-inspect demo-test demo-cogs demo-rasters \
        demo-dev site-deps demo-frontend-test site-browsers demo-browser-test

## validate build-public (AGENTS.md §4.3)
all: validate build-public

## uv sync, and check for the external tools the pipeline needs
setup:
	$(UV) sync
	@missing=""; \
	for tool in gdalinfo tippecanoe node; do \
	  command -v $$tool >/dev/null 2>&1 || missing="$$missing $$tool"; \
	done; \
	if [ -n "$$missing" ]; then \
	  echo "setup: missing external tool(s):$$missing"; \
	  echo "setup: install with 'brew install gdal tippecanoe node' (macOS)."; \
	  echo "setup: 'make validate' does not need them; the raster and tile targets do."; \
	else \
	  echo "setup: gdal, tippecanoe and node present."; \
	fi

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
DEMO_TEST_PORT ?= 5274
export DEMO_TEST_PORT
demo-browser-test: site-browsers
	cd $(SITE) && $(NPM) run build
	cd $(SITE) && node tests/assert-no-test-probe.mjs
	cd $(SITE) && $(NPM) run test:browser

demo-test: demo-frontend-test demo-browser-test
	$(RUN) pytest -q scripts/test_demo.py scripts/test_demo_rasters.py

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

## warp + COG everything with a GCP file, write to build/rasters/
rasters:
	@echo "make rasters: not implemented until M2 (raster pipeline)."
	@echo "  Needs scripts/warp_raster.py and committed .points files in data/sources/gcp/."
	@echo "  See README.md §7, M2."
	@exit 1

## tippecanoe -> build/tiles/alignments.pmtiles
tiles:
	@echo "make tiles: not implemented until M4 (viewer)."
	@echo "  Needs scripts/build_vector_tiles.py and tippecanoe on PATH."
	@echo "  See README.md §7, M4."
	@exit 1

## assemble build/public/ (restricted fields stripped)
build-public:
	@echo "make build-public: not implemented until M5 (split builds and deploy)."
	@echo "  Needs scripts/build_site.py. Until then 'make validate' is the M0 entry point."
	@echo "  See README.md §7, M5."
	@exit 1

## assemble build/restricted/
build-restricted:
	@echo "make build-restricted: not implemented until M5 (split builds and deploy)."
	@echo "  Needs scripts/build_site.py."
	@echo "  See README.md §7, M5."
	@exit 1

## vite dev server against build/public/
dev:
	@echo "make dev: not implemented until M4 (viewer)."
	@echo "  Needs the MapLibre viewer in site/."
	@echo "  See README.md §7, M4."
	@exit 1

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
	rm -rf build/public build/restricted build/tiles build/rasters
