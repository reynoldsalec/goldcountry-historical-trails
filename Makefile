# Everything runs through this file (AGENTS.md §4.3). Targets are idempotent and safe
# to re-run. Targets whose milestone has not landed yet exit with a clear message
# rather than silently doing nothing.

UV := uv
RUN := $(UV) run

.DEFAULT_GOAL := all
.PHONY: all setup fetch-aoi fetch-topo rasters validate tiles build-public build-restricted \
        dev fmt lint clean test-topo test-validation test-coverage topo-docs topo-plan

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

topo-plan:
	$(RUN) python scripts/fetch_topoview.py download --dry-run $(TOPO)

test-topo:
	$(RUN) pytest -q scripts/test_fetch_topoview.py

# Files are listed explicitly so a deleted or renamed regression module fails loudly
# instead of silently shrinking the glob.
test-validation:
	$(RUN) pytest -q scripts/test_validate.py scripts/test_validate_dates.py scripts/test_validate_leaks.py

test-coverage:
	$(RUN) pytest -q scripts/test_coverage_schema.py

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
