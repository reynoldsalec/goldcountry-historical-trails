# Auburn Map Browser — local acceptance record (D4b)

**Status: automated evidence only.** Everything below was produced by a coding agent
running the committed targets on a local machine. No human has reviewed the sources or
the viewer, and nothing here is a signoff. Human acceptance is
[issue #38](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/38) and
stays open after this record lands. Nothing is deployed; there is no public URL.

This file is the filled worksheet from [mvp-runbook.md](mvp-runbook.md) §8 for the
technical checks, plus the list of checks a human still has to do.

---

## 1. Code revision and environment

| Item | Value |
| --- | --- |
| Commit the evidence was produced at | `fc395a4` (`feat: add demo-accept and wire the demo targets into make and CI`), clean worktree |
| Branch | `issue-46-demo-d4b-wire-demo-acceptance-and-ci-pre` |
| Date (UTC) | 2026-09-29 |
| OS | Linux 6.6.114 (WSL2), x86_64 |
| Python | 3.11 via `uv`, project `.venv` |
| Node | v22.22.3; npm dependencies from `site/package-lock.json` |
| GDAL / PROJ | GDAL 3.10.3 and PROJ 9.7.1 from the rasterio 1.4.4 wheel; pyproj 3.7.2 with PROJ 9.5.1. No `gdalwarp`/`gdalinfo` binary is used. |
| Raw scans | read-only from the main checkout through `DEMO_RAW_ROOT=<repo>/data/raw`; this worktree holds none |

Later commits on this branch are documentation only. Re-running the commands at the
branch head reproduces the same output; the digests below are the check.

## 2. Selected sources and byte preservation

Verified by `make demo-check` and again by every `make demo-build` run. Each run resolves
the source through `data/sources/retrievals.jsonl` by source ID and compares SHA-256 and
byte count before reading a pixel.

| Edition | Source ID | SHA-256 | Bytes | Source CRS → WGS 84 pipeline |
| --- | --- | --- | --- | --- |
| auburn-1953 | CA_Auburn_288101_1953_24000 | `bec9555f90f4928d219212219ed06c15c6eb94a5dd749a0aa90edb1bb416e7c5` | 12,532,400 | NAD27 / American Polyconic → NAD27 to WGS 84 (6) |
| auburn-1973 | CA_Auburn_288103_1953_24000 | `2a4427b0969a566fd9b2ff558e2cf114ce5099f63dfc515fd8fd2a38abd25967` | 11,709,311 | NAD27 / American Polyconic → NAD27 to WGS 84 (6) |
| auburn-1975 | CA_Auburn_288104_1975_24000 | `4d35331f4a1ff1306decd823e68de0fee02753e921d9deb7c7450a568128fde6` | 14,103,396 | NAD27 / Lambert Conic Conformal (2SP) → NAD27 to WGS 84 (6) |
| auburn-1981 | CA_Auburn_288105_1953_24000 | `d5621357235c6d65ae2cdbe2265235e70b10972fcb5e2574fb7f5ff7b2313196` | 12,427,061 | NAD27 / American Polyconic → NAD27 to WGS 84 (6) |

No file under `data/raw/` and no line of `data/sources/retrievals.jsonl` was written,
renamed or re-timestamped. The pipeline opens the scans read-only.

## 3. Commands and exit codes

Run from the repository root with `DEMO_RAW_ROOT` pointing at the scans.

| Command | Exit | Result |
| --- | --- | --- |
| `make lint` | 0 | ruff format check and ruff check clean |
| `make test-validation` | 0 | 84 passed |
| `make test-topo` | 0 | 52 passed, 1 skipped |
| `make test-coverage` | 0 | 200 passed |
| `make demo-check` | 0 | 4 editions verified; common footprint −121.126028, 38.874881, −121.001023, 38.99988; zoom 10–16 |
| `make demo-accept` | 0 | 7 min 10 s total; see the breakdown below |
| `make` (bare, second run) | 0 | 8.1 s; rebuilt and republished `build/public`, then validated it |
| `make validate` | 0 | all six checks passed; leak scan read 4,025 files under `build/public` |
| `make verify-backup` | 2 | **Archive parent is unavailable; mount the backup drive first.** Honest absence, see §8 |

`make demo-accept` breakdown:

- `make demo-test` — prettier and `tsc --noEmit` clean; vitest 63 tests in 3 files passed;
  Playwright dev suite 17 passed (38.4 s); Playwright built-bundle suite 2 passed (1.3 s);
  pytest `test_demo.py test_demo_rasters.py test_demo_build.py test_demo_make.py`
  173 passed in 101 s (171 passed, 2 skipped when the real scans are not reachable).
- `make demo-build` — 268 s; published 4,025 files to `build/public/`.
- `make validate` — leak scan over the tree that run had just published, then the archive
  and coverage checks.

Full console log: `build/acceptance/accept.log` (not committed; `build/` is gitignored).

## 4. Output, size and local URL

| Item | Value |
| --- | --- |
| Output directory | `build/public/` (absolute path in the log above) |
| Files / bytes | 4,025 files, 451,488,565 bytes (430 MiB) |
| Tiles | 4,020 PNG tiles, 1,005 per edition, zoom 10–16, XYZ row order |
| Metadata | `editions.json`, 4,585 bytes, display fields only |
| App assets | `index.html` 2,662 B; `assets/index-Cc_xTDnO.js` 1,035,345 B; `assets/maplibre-gl-worker-CRiIRpYb.js` 509,702 B; `assets/index-BaHM3vpW.css` 85,199 B |
| Inventory | `build/publish/demo-publish.json` |
| Internal processing record | `build/rasters/demo-processing.json` |
| Local URL used for the browser checks | `http://127.0.0.1:8317/` — `python3 -m http.server 8317 --bind 127.0.0.1` run inside `build/public/` |
| Dev-server alternative | `make demo-dev` → `http://127.0.0.1:5173/`; that serves the source app, not the published tree |

The served tree is the published one. `file://` was not used. The server started for this
record was stopped afterwards.

## 5. Browser evidence on the real build

Chromium 153.0.8010.12 (the browser Playwright 1.63.0 bundles), headless, viewports
1280×800 and 390×780. The script that drove it is not committed: the production bundle
carries no test probe, so the camera is judged from the tile coordinates the page requests
and from the screenshots. Screenshots are in `build/acceptance/` (gitignored).

| Check | Observed |
| --- | --- |
| First load | Card and notice read "1953 topographic map"; `#notice[data-status]="displayed"`; one canvas |
| Zoom to a landmark (American River canyon, wheel input) | Contours and labels legible; scale bar 500 ft |
| Next → 1973 → 1975 → 1981 | Card, notice and imagery change together; the three switches requested the **same 20 tile coordinates** each time, so the camera did not move |
| Previous back to 1953 | Same sequence in reverse, same framing |
| Endpoints | Next disabled on 1981, Previous disabled on 1953; no wraparound |
| Direct selection | The `<select>` lists all four editions and is keyboard reachable |
| Reset view | Separate control; only it refits the shared extent |
| Source card | Product, source ID, base/revision and field-check lines, citation, "Original source record" link, USGS attribution, and the "a line on a map is not a statement about who may use it today" caveat |
| Blocked edition (tile requests for 1975 aborted) | Notice: "Could not load 1975 orthophotoquad: tiles/auburn-1975/13/1341/3132.png: Failed to fetch. Still showing 1973 photorevision." Card stayed on the still-displayed edition. No silent relabel. |
| Storage | `localStorage.length` 0, `sessionStorage.length` 0, no controlling service worker |
| Network | Every response came from `http://127.0.0.1:8317`; no 4xx/5xx, no failed request, no console error |
| 390 px width | 0 px horizontal overflow; controls and source panel usable |

Screenshots: `01-initial-1953.png`, `02-zoomed-1953.png`, `03-next-1973.png`,
`04-next-1975.png`, `05-next-1981.png`, `06-prev-1975.png`, `07-prev-1973.png`,
`08-prev-1953.png`, `09-reset-view.png`, `10-narrow-390.png`, `11-blocked-1975.png`.

Only Chromium was exercised. Firefox, WebKit, real mobile hardware, screen readers,
throttled networks and touch input were not.

## 6. Registration limitations

From `build/rasters/demo-processing.json` → `registration_notes`. These offsets are
carried, not corrected; no control point was moved.

| Edition | Drawn neatline off the labelled graticule | Datum transformation accuracy |
| --- | --- | --- |
| auburn-1953 | 2.743 m | 7 m |
| auburn-1973 | 2.174 m | 7 m |
| auburn-1975 | 5.304 m | 7 m |
| auburn-1981 | 3.637 m | 7 m |

No independent ground control exists in this repository: no surveyed landmark and no
modern reference layer is committed, so **the runbook's three-landmark inter-edition
offset check was not run**. The PROJ grid `us_noaa_cnhpgn.tif` is not installed, so the
NAD27→WGS 84 transformation falls back to the 7 m-accuracy operation; the warning appears
in the logs. A human comparing features between editions must treat differences under
roughly 10 m as possible registration error, not as change on the ground.

## 7. CI

`.github/workflows/validate.yml` keeps `make lint`, `make validate`, `make test-topo`,
`make test-validation` and `make test-coverage`, and adds Node 22, `make site-deps`,
Playwright's system libraries, `make site-browsers` and `make demo-test`. It never runs
`demo-check`, `demo-rasters`, `demo-build` or `demo-accept`, and never sets
`DEMO_RAW_ROOT`: the runner has no scans and no receipts to verify them against, so CI
proves the code paths on synthetic fixtures and proves nothing about the real editions.

**The invalid-fixture failure was proven, not assumed.** Locally, with the exact CI
command, the fake bundle in `scripts/test_demo_build.py` (`write_dist`) was changed to
embed the restricted value `FIXTURE DECLARANT` that the committed fixture records carry.
`make demo-test` then exited 2 with 11 failures, the first being

```
click.exceptions.ClickException: Restricted values reached the staged public build;
nothing was published: ... restricted value 'FIXTURE DECLARANT' appears in
build/.public-incoming/assets/index.js (AGENTS.md §2.5)
```

Log: `build/acceptance/invalid-fixture.log`. The change was reverted immediately; the
committed fixture is the clean one, and the suite passes at the branch head. An earlier
attempt with a value absent from the fixture records passed, which is correct behaviour
and is why the proof uses a value that is actually restricted.

## 8. Source recovery and archive status

Recovery uses the existing tools; no new pipeline was added.

1. Write a selection file, `{"version": 1, "topo_ids": ["CA_Auburn_288101_1953_24000",
   "CA_Auburn_288103_1953_24000", "CA_Auburn_288104_1975_24000",
   "CA_Auburn_288105_1953_24000"]}`.
2. `make topo-plan SELECTION=<file>` — dry run. Verified for this record: it planned
   exactly those four editions from the committed index and reported each expected byte
   count from the receipts.
3. `make fetch-topo-selected SELECTION=<file>` — downloads only those four from USGS
   topoView and refuses any byte string whose hash does not match the receipt.
4. `make verify-sources` / `make validate` — re-verify local copies against
   `data/sources/retrievals.jsonl`.

The separate raw-source archive under `TRAIL_ARCHIVE_ROOT` is **not mounted on this
machine**: `make verify-backup` exits 2 with "Archive parent is unavailable; mount the
backup drive first." `make backup-sources`, `make restore-sources` and `make verify-backup`
are therefore untested here. Nothing in this record should be read as evidence that a
second copy of the scans exists. During `make validate`, `source_archive.py verify
--available` reported "0 sources match SHA-256; 91 local copies absent" because this
worktree has no `data/raw`; the selected four were verified through `DEMO_RAW_ROOT`.

## 9. Still to do — human acceptance (issue #38)

None of these can be produced by a coding agent, and none is claimed above.

- [ ] A named human opens the served build and pages through all four editions.
- [ ] A human reads each source card against the scanned sheet margins and confirms the
      base, revision, photography and field-check wording (§3 of the runbook).
- [ ] A human judges whether the imagery is fit for visual comparison given the
      registration limits in §6, or asks for ground control first.
- [ ] Manual throttled-network, blocked-tile and rapid-switching passes in a real browser
      (§5 of the runbook), and a non-Chromium browser.
- [ ] Screen-reader announcement quality; real touch device at 390 px.
- [ ] Legal-framing review of the viewer copy by whoever counsel designates.
- [ ] Decision recorded on #38 as PASS or BLOCK, with reviewer name and UTC time.
- [ ] Hosting, quota and a public URL: a separate decision. Not requested, not prepared.

## 10. Worksheet

```text
Code revision:                       fc395a4 (branch issue-46-demo-d4b-...)
Selected source IDs / receipt hashes: §2, all four verified by hash and byte count
Processing manifest / tool versions:  build/rasters/demo-processing.json; GDAL 3.10.3,
                                      PROJ 9.7.1/9.5.1, rasterio 1.4.4, pyproj 3.7.2
Output size:                         4,025 files, 451,488,565 bytes, 4,020 tiles
Build and test commands / exits:     §3, all 0 except make verify-backup (2, archive absent)
Browser versions / viewports / URL:  Chromium 153.0.8010.12; 1280x800 and 390x780;
                                     http://127.0.0.1:8317/
Stable landmarks / offsets:          NOT RUN — no independent ground control in the repo;
                                     neatline/datum limits recorded in §6
Edition paging and camera tests:     §5; identical tile coordinate sets across switches
Slow-load / error / retry tests:     automated suites pass; manual throttling still pending
Accessibility / network / output:    §5; screen-reader and touch checks still pending
Screenshots / logs:                  build/acceptance/ (gitignored, regenerable)
Known limitations / failed checks:   §6, §8, §9
Actual reviewer / UTC review time:   none — not performed
Decision:                            NOT DECIDED; issue #38 remains open
```
