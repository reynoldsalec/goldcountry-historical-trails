# Sources

Mostly not yet written. Populated in M1 alongside `data/sources/sources.yml`: every Tier 1
USGS quad edition with date, scale, rights and URL, plus candidate aerial flights and the
19c county maps.

Anything not already in the README §8 inventory needs an entry here before use
(README §8). Entries so far:

## US Census Bureau TIGERweb — county boundaries

- **Used for:** `data/sources/aoi_counties.geojson`, the Placer + Nevada County
  acquisition envelope that bounds `make fetch-topo` and `make rasters`.
- **Service:** `https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer`,
  layer 55 (`Counties` under the `Census 2020` group).
- **Vintage:** Census 2020, pinned deliberately. TIGERweb's layer 1 is a rolling "current"
  vintage; querying it would make the AOI silently drift. Both layers returned identical
  vertex counts for these two counties when checked on 2026-08-29.
- **Rights:** public domain (US federal government work).
- **Attribution:** "County boundaries: US Census Bureau TIGER/Line".
- **Rebuild:** `make fetch-aoi`. Idempotent — it leaves the file untouched when the
  fetched geometry matches what is committed, so the retrieval date does not churn.
- **Not evidence.** This is a reference boundary for scoping downloads. It is not a trail
  observation and never becomes one.
