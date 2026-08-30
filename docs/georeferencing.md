# Georeferencing

Not yet written. Populated in M2: the GCP workflow for scanned aerial frames and map
sheets, `.points` file conventions in `data/sources/gcp/`, warp method per source type,
and the per-GCP-set RMS error log.

Standing rules meanwhile: topoView GeoTIFFs arrive georeferenced and are reprojected and
tiled only, never re-georeferenced. Aerial frames arrive as raw scans and need manual GCPs
committed alongside the frame ID (AGENTS.md §3).
