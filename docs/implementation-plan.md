# M0 and M1 implementation handoff

This plan decomposes the first two MVP milestones into bounded tasks. It defines
future implementation contracts; it does not claim those contracts are implemented.
M2–M5 are outside this issue-creation batch. Parent issues retain their milestone
acceptance criteria and close only after the children and final acceptance pass.

## Dispatch rules

- Assign only `coder` tasks to a Sol coding worker. Research, GIS review, source
  operations, and milestone acceptance require the role named in each issue.
- Start a task only after its listed prerequisites are accepted. All M1 tasks also
  require parent M0 acceptance. Existing acquisition work remains intact.
- Implement one child issue per focused PR. A child PR must not close its parent.
- Serialize tasks sharing a file, particularly Makefile, README, coverage.py, and
  coverage.json. In isolated branches, rebase and review overlapping changes before
  integration. Workers must preserve each other's edits.
- Each issue contains file ownership, the implementation contract, failure cases,
  acceptance criteria, verification commands, exclusions, and rollback guidance.
- Missing evidence is a blocker for evidence-dependent acceptance, never permission
  to invent a date, geometry, review event, source identifier, or citation.

## Architecture decisions

### Data contracts and temporal rules

Remove the obsolete trail `tier` field. Preserve IDs and existing corridor values;
`corridor` remains a required nonempty grouping string without a locality enum.
The four alignment temporal fields remain unchanged.

Decade classification must depend on linked observations and support roles. A lone
past opening or closure does not establish every later decade. A null observation
end date is not an ongoing interval. The current schema cannot distinguish uncertain
range dating from continuous-use testimony, so a range alone cannot establish
continuous presence across decades. M0.2 specifies the conservative decision table,
conflict reasons, schema-description correction, and twelve isolated examples.
Feature dates on revised maps still require source inspection. This task set does
not implement the viewer's classifier or decide dates for real sources.

Build validator regressions around temporary datasets and temporary output. Test
calendar validity, provenance, geometry, and planted restricted values separately.
An absent public build does not establish publication safety. Keep existing CI
checks and add a single `make test-validation` entry point.

### Coverage inventory

Use a deterministic 0.125-degree reference grid generated from the county AOI,
not from available map sheets. This prevents missing sources from removing areas
from the inventory. Cell IDs are `q7p5-{i}-{j}` relative to the global origin
(-180, -90); they are reference IDs, not official quadrangle names. Keep cells
with positive-area county intersections and record both county GEOIDs when shared.

Planned artifacts:

| Path | Responsibility |
| --- | --- |
| `data/sources/coverage_grid.geojson` | Reproducible grid with county intersections |
| `data/sources/coverage.json` | Area/decade cells, source candidates, searches, reviews, and batches |
| `schema/coverage_grid.schema.json` | Grid structure |
| `schema/coverage.schema.json` | Inventory structure and field contracts |
| `scripts/coverage.py` | Grid generation, refresh, validation, and reporting |
| `scripts/test_coverage_*.py` | Offline regression cases |
| `data/sources/mvp-topo-selection.json` | Exact topo IDs selected for acquisition |
| `docs/coverage.md` | Generated research coverage report |

The inventory contains every reference cell and every decade from 1950 through
its explicit `through_decade`. Sources located, sources reviewed, and trails
digitized are separate facts. Metadata import never creates review timestamps or
claims that a trail was observed. Preserve manual reviews and search records on
refresh; fail on orphaning changes rather than silently deleting them.

`topo:<topo_id>` references the existing index; `candidate:<candidate_id>` references
a separately verified source candidate. Candidate records include a source kind,
known or null dates/bounds, rights, sensitivity, access status, and publisher ID.
Reviews identify their source, cell, county, decade, actual reviewer/time, evidence
locator, and dating confidence. Schemas and semantic validators are separate tasks;
M1.3 performs local schema/preservation checks before M1.4 extends full validation.

Normal validation accepts explicit evidence gaps. `make coverage-ready` additionally
requires four qualifying ready batches: an earlier and a later decade in each county,
plus an obtainable verified aerial frame dated 1950 or later. Pre-2000 batches
include qualifying topo editions so acquisition covers both counties. M1 rejects
`digitized` batch status until M3 adds verified source-to-observation linkage.
Aerials with unknown redistribution rights can support internal review but cannot
be published. Coverage files remain internal research inputs until audience-aware
export is implemented later.

### Acquisition and evidence work

Extend the existing downloader with exact-ID selection; do not create another
fetcher. Validate the entire selection before network access, keep dry-run free of
writes, and preserve receipt, hashing, interruption, and immutable-file behavior.
An exact selection must not trigger a countywide index refresh.

Separate research tasks locate later-period sources for each county and verify an
obtainable aerial. Four GIS-review tasks select and justify the actual batches;
no source locations or feature dates are invented in this plan. A source operator
then acquires and verifies the selected topo bytes and their separate archive.
The engineering reviewer verifies the M1 gate and supplies concrete M2 inputs.

## Task index

Dependencies below are child-task dependencies. The parent M0 gate also blocks
all M1 work. Links are the authoritative worker instructions.

| Task | Role | Deliverable | Prerequisites |
| --- | --- | --- | --- |
| [M0.1](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/3) | coder | Remove obsolete geographic constraints from the trail contract | None |
| [M0.2](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/4) | coder | Specify observation dating and decade-state examples | None |
| [M0.3](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/5) | coder | Add isolated schema and provenance regression tests | M0.1 |
| [M0.4](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/6) | coder | Validate calendar dates and temporal bound ordering | M0.1, M0.2 |
| [M0.5](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/7) | coder | Prove restricted-value leak detection with temporary output | M0.1 |
| [M0.6](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/8) | coder | Wire validator regression targets into CI and record M0 acceptance | M0.1, M0.2, M0.3, M0.4, M0.5 |
| [M1.1](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/9) | coder | Define coverage inventory schemas and neutral initial document | M0.6 |
| [M1.2](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/10) | coder | Generate the complete county-intersecting quadrangle grid | M1.1 |
| [M1.3](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/11) | coder | Build area-by-decade cells and attach candidate source references | M1.2 |
| [M1.4](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/12) | coder | Validate inventory references and batch readiness | M1.3 |
| [M1.5](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/13) | coder | Add coverage reporting and CI completeness checks | M1.4 |
| [M1.6](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/14) | coder | Support explicit topo edition selection in the existing downloader | M0.6 |
| [M1.7](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/15) | researcher | Research modern maps and agency records for Nevada County | M1.5 |
| [M1.8](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/16) | researcher | Research modern maps and agency records for Placer County | M1.5 |
| [M1.9](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/17) | researcher | Verify one obtainable aerial frame for the raster pipeline | M1.5 |
| [M1.10](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/18) | GIS reviewer | Review and select one Nevada digitizing batch before 2000 | M1.7, M1.6 |
| [M1.11](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/19) | GIS reviewer | Review and select one Nevada digitizing batch from 2000 onward | M1.7, M1.6 |
| [M1.12](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/20) | GIS reviewer | Review and select one Placer digitizing batch before 2000 | M1.8, M1.6 |
| [M1.13](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/21) | GIS reviewer | Review and select one Placer digitizing batch from 2000 onward | M1.8, M1.6 |
| [M1.14](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/22) | source operator | Acquire and archive the reviewed topo selection | M1.10, M1.11, M1.12, M1.13 |
| [M1.15](https://github.com/reynoldsalec/goldcountry-historical-trails/issues/23) | engineering reviewer | Audit the M1 completion gate and hand off to raster work | M1.5, M1.9, M1.14 |

## Acceptance record

Planning completed on 2026-09-16. No implementation child is complete merely because
its issue was created. M0.6 and M1.15 record command results, CI references, evidence
review, and unresolved blockers in their parent issues before milestone closure.

Implementation estimates are intentionally not calendar promises. Coding tasks are
scoped to one focused PR; the worker should report when a discovered dependency
would require changing another task's contract. Research duration depends on actual
source access and review, which cannot be estimated from code alone.
