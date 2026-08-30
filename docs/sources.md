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

## OpenStreetMap (Overpass API) — Bear River Canal corridor

- **Used for:** `data/sources/aoi_tier1.geojson`, the Tier 1 digitizing bound.
- **Endpoint:** `https://overpass-api.de/api/interpreter`.
- **Snapshot:** pinned via an Overpass attic query, `[date:"2026-08-30T00:00:00Z"]`. OSM is
  a live database; without the pin the AOI would drift as people edit. Bump the date
  deliberately, never incidentally.
- **Ways used:** `Bear River Canal` (waterway=canal, 14 ways, merges to one 20.77 mi
  line), `Bear River Canal Trail` (highway=path, 8 ways, 5.03 mi, surface=dirt),
  `Bowman Feeder Canal` (waterway=canal, 3 ways, 1.04 mi). Endpoints are the canal's
  crossings with `Crother Road` and `Placer Hills Road`.
- **Rights:** ODbL. Attribution required: "© OpenStreetMap contributors, ODbL". This
  string must appear in the viewer's attribution control if any OSM-derived layer is
  shown (AGENTS.md §2.7).
- **Rebuild:** `make fetch-aoi`. Buffer is `--buffer` on `fetch_aoi.py tier1`, default
  250 m.
- **Not evidence.** OSM is not an authoritative record of historical trail extent. This
  boundary decides where we look; it never establishes what was there. No OSM way may
  become an alignment in `data/authoritative/` (AGENTS.md §2.1).

### Corridor facts established from the snapshot

Chainage is measured along the merged `Bear River Canal` line.

| Feature | Canal chainage |
| --- | --- |
| Crother Road crossing | 14.75 mi |
| Meadow Gate Road crossing | 17.50 mi |
| Placer Hills Road crossing | 19.77 mi |
| Named trail extent | 14.65 – 19.78 mi |

The corridor cut is 14.75 → 19.77 mi, 5.03 mi long. This ordering — Crother, then Meadow
Gate, then Placer Hills — matches the corridor description in README §2 and independent
public trail listings. `Placer Hills Road` crosses the canal three times (13.00, 19.77,
19.86 mi), so the builder picks the crossing pair that best brackets the named trail
rather than the first one it finds.

Half the `Bear River Canal Trail` ways carry `access=private`, and gravel/unpaved
`highway=service` ways run alongside the canal — consistent with the berm/bank
distinction in AGENTS.md §6. Recorded as orientation. It is not evidence of anything.

