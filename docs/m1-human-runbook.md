# M1 human research and acceptance runbook

**Status: instructions, not evidence of completed review.** Start with the
[assessment](m1-research-assessment.md) and saved
[issue contracts](m1-research-evidence/issue-contracts.json). This document closes
no issue. No template below is a source observation, review event or acceptance.
Only the person who actually performs a review supplies their identity, time,
findings and decision. Do not copy placeholders into the inventory.

## 1. Order, ownership and preparation

Read `AGENTS.md`, `README.md`, `schema/coverage.schema.json`, `docs/data-model.md`,
`docs/sources.md` and `docs/open-questions.md`. Use the existing contracts rather
than inventing fields. M0 acceptance is a prerequisite for every task.

| Issue | Human owner | Accepted dependencies | Deliverable |
| --- | --- | --- | --- |
| #15 | Nevada researcher | #13 | Later-period Nevada searches/candidates and explicit gaps |
| #16 | Placer researcher | #13 | Later-period Placer searches/candidates and explicit gaps |
| #17 | Aerial researcher | #13 | One matched, dated, obtainable frame with bounded footprint |
| #18 | GIS reviewer | #15, #14 | Nevada pre-2000 ready batch and reviewed historical topo |
| #19 | GIS reviewer | #15, #14 | Nevada 2000-onward ready batch |
| #20 | GIS reviewer | #16, #14 | Placer pre-2000 ready batch and reviewed historical topo |
| #21 | GIS reviewer | #16, #14 | Placer 2000-onward ready batch |
| #22 | Source operator | #18, #19, #20, #21 | Exact reviewed topo selection acquired and archived |
| #23 | Engineering reviewer/owner | #13, #17, #22 | Manual M1 audit and explicit M2 handoff |

Serialize edits to `data/sources/coverage.json`, `sources.yml`, selection and
shared docs; use focused child PRs. Preserve other reviewers' selections. Data-only
changes belong in separate `data:` commits with source attribution. Neither this
PR nor a successful schema check accepts these children automatically.

Run from the repository root:

```sh
make validate
make validate-coverage
```

Stop on validation failure. The assessment has already performed metadata discovery,
county-box/cell intersection, public access probing and offline checks. Reuse its
staging records; do not pretend that repeating those steps is human map examination.
Do not change raw bytes, existing receipts or authoritative synthetic fixtures here.
Do not run bare `make`: it includes the unimplemented public build. Raster work,
GCP placement, digitizing and viewer work belong to later accepted milestones.

## 2. #15 and #16 — turn discovery into accountable searches

Owned files: `coverage.json` candidates/searches/cell links, `sources.yml`,
`docs/sources.md`, `docs/open-questions.md`.

1. Work one county at a time: Nevada `06057`, Placer `06061`. Open
   `modern-review-queue.json` and `modern-map-triage.json` in the evidence directory.
   Reconcile every county reference cell for 2000–2009, 2010–2019 and 2020 through
   the actual search date. Boundary cells may belong to both counties.
2. Read actual source metadata and map/title/legend pages. Check exact publisher ID,
   citation, edition/lineage dates, footprint and item rights. API rectangles are
   discovery bounds, not human-verified neatlines. Publication is not feature dating.
3. Inspect the exact county-plan links in the assessment: Nevada final-plan chapters;
   Placer Volume 2 and Appendix D. Record specific pages/figures, whether existing or
   proposed routes, covered region and date basis. A county landing page does not
   establish countywide map coverage. Do not import proposals as existing trails.
4. Perform targeted county and land-management/agency searches for remaining gaps,
   especially the 2000s and eastern county areas. The saved TNM queries have no
   2000s publication leads; this is not evidence that sources or trails are absent.
5. Log actual query, collection, URL, UTC search time, geographic/decade extent,
   result and limitations. Use `access_blocked` for an access failure, not `no_match`.
   Unsearched areas stay explicitly unsearched. Attribute the saved automated search
   to its actual recorded time; never relabel it as a human review performed today.
6. Only promote metadata that has been checked. Keep unknown values null/unknown;
   do not generate review events or trail-history narrative. Resolve item-specific
   rights with the owner where county website terms conflict with blanket assumptions.
   Unknown redistribution rights mean no public imagery publication.

After each county's serialized edits:

```sh
make validate-coverage
make coverage-report
make validate
```

Acceptance requires a human citation/footprint check, actual searches or explicit
remaining gaps for every later-period cell, and traceable verified candidates.
A report rendering successfully is not that acceptance.

## 3. #17 — verify one aerial, not just a flight listing

Owned files: aerial candidate/search records in `coverage.json`, `sources.yml`,
`docs/sources.md`, `docs/open-questions.md`.

The saved CAS-4042 lead supplies a catalog date and a scan URL, but only a 16-byte
HTTP range response was read. No full image, printed frame ID, footprint or usable
image quality has been verified. The assessment links the flight report, index PDF
and `cas-4042_1.tif`. PAI-Tahoe-50 is a fallback flight lead, not a chosen frame.

1. Open the catalog and index, then obtain the actual full scan through the observed
   public method if permitted. Inspect its margins and image, matching printed frame
   identity to catalog/index. Record discrepancies; CAS-4042 has a catalog warning
   about its stamped scale. Do not resolve this by trusting the stamp.
2. Establish the frame footprint from defensible index/metadata evidence and confirm
   intersection with the county AOI. A locality label or centerpoint is not bounds.
   Resolve a 1950-or-later capture date/precision without guessing.
3. Record exact `source_identifier`, collection, URL/access method (no credentials),
   date, bounds, rights, sensitivity and attribution. Confirm the full scan can be
   obtained, not just a thumbnail or partial response. Keep unknown rights explicit;
   internal georeferencing eligibility is separate from public redistribution.
4. Have the researcher confirm scan/catalog identity and availability. Leave the
   issue blocked for unresolved identity, date, footprint or scan access. Do not
   replace it with a topo. Get authorization for login, purchase, contact or visits.
5. Hand M2 the verified frame ID, source locator, raw storage/access information,
   restrictions and the need for manual `.points` GCPs. Do not invent GCPs now.

The existing receipt/archive tooling covers public USGS TIFFs, not arbitrary aerials.
Do not fabricate a USGS receipt for this scan or assume `backup-sources` archives it.
Document the aerial preservation handoff separately for owner approval.

```sh
make validate-coverage
make coverage-report
make validate
```

Human frame metadata/access review remains mandatory after these commands.

## 4. #18–#21 — inspect dated foot-trail evidence and choose batches

Owned files: `coverage.json` reviews/batches/cell links,
`data/sources/mvp-topo-selection.json`, `docs/open-questions.md`.

For each issue choose one bounded locality/reference-cell group and one decade in
its county/era. Pre-2000 means 1950–1999. Neither a favored locality nor downloaded
map availability is a priority rule. Select for evidence and countywide gap benefit.

1. Open the actual source at readable scale in an appropriate map/PDF/GIS viewer.
   Record exact sheet/page/figure/feature locator, source reference, reviewed area,
   county GEOID, actual reviewer and UTC time, and partial vs whole-source footprint.
2. Inspect legend and feature identity: is it demonstrably a foot trail rather than
   road, canal, maintenance route, bicycle-only route or planned project? Ambiguous
   identity stays unresolved. A map omission does not establish closure or absence.
3. Resolve that feature's observation date using base/revision/field-check evidence
   under `docs/data-model.md`. A latest lineage or printing date cannot be assigned
   to every feature. Cross-decade uncertain ranges do not qualify a ready batch.
   Do not carry a modern route backward or a single observation forward indefinitely.
4. Record a ready batch only with an inspected positive, date-resolved foot-trail
   review supporting this county and decade. Supply area IDs, source IDs, review IDs,
   bounded digitizing tasks and remaining gaps. Do not supply alignment IDs or mark
   anything digitized in M1. All four temporal fields remain part of the later model.
5. #18 and #20 each require a reviewed historical topo supporting their county's
   pre-2000 batch. Include each exact `topo_id` in the selection. The combined selection
   is the sorted, deduplicated union needed by all batches; preserve existing entries.
   Check every ID against `data/sources/topo_index.csv`. Modern PDF IDs are not
   historical topo IDs and cannot be fed to this TIFF selection downloader.

If inspection needs a missing topo, a reviewer may create a bounded *inspection*
selection containing real indexed IDs and use the existing selected-download path.
That does not accept #22 or authorize a countywide acquisition. Review the dry-run
first; preserve raw bytes and record actual retrievals. The final approved release
selection exists only after the four batch reviews, not from this template.

```sh
# Only after a real, reviewed selection file exists:
make topo-plan SELECTION=data/sources/mvp-topo-selection.json
# If authorized source bytes are needed for inspection:
make fetch-topo-selected SELECTION=data/sources/mvp-topo-selection.json
make validate-coverage
make coverage-report
make validate
```

Do not combine selection with `TOPO=--tier1` or scale filters. No source availability
can substitute for trail identity/date review. Each child needs manual acceptance.

## 5. #22 — reviewed acquisition and the real archive mount

**Current blockers:** four batch selections are not accepted, the release selection
file does not exist, and the configured archive parent is unavailable. Existing 91
hash-verified local files do not prove the eventual selection or its archive exists.

After dependencies are accepted, the operator confirms both-county selected IDs and
mounts/chooses the real separate archive. `TRAIL_ARCHIVE_ROOT` may refer to a mounted
path/symlink; do not create a replacement mount directory or use a local copy to
misrepresent independent backup. Keep private paths out of public logs. The example
below requires replacing the placeholder with the operator's actual mounted root:

```sh
make topo-plan SELECTION=data/sources/mvp-topo-selection.json
# Human approves the plan, byte budget, storage and actual archive mount first.
make fetch-topo-selected SELECTION=data/sources/mvp-topo-selection.json
make verify-sources
make backup-sources TRAIL_ARCHIVE_ROOT="/actual/mounted/source-archive"
make verify-backup TRAIL_ARCHIVE_ROOT="/actual/mounted/source-archive"
make test-topo
make validate
# Verify idempotent reuse and no duplicate receipts:
make fetch-topo-selected SELECTION=data/sources/mvp-topo-selection.json
make verify-sources
```

Verification/backup targets cover the **entire receipt set**, not merely selection.
Match every selected ID to a receipt with verified hash and byte count. Record the
receipt ledger digest and actual archive manifest snapshot/hash, command exit codes
and logs; the assessment's local ledger hash is not a new archive verification.
Preserve original paths and retrieval times, use null for unknown historic retrieval
times, and commit receipts, never rasters. Stop on missing mount, missing receipt,
hash mismatch or changed remote bytes. Never overwrite evidence to make a check pass.

## 6. #23 — final human acceptance, then and only then M2

Owned deliverables: parent #2 acceptance/checklist, acceptance record in
`docs/implementation-plan.md`, unresolved blockers in `docs/open-questions.md`.

```sh
make coverage-ready
make validate
make test-coverage
make test-validation
make test-topo
make lint
```

The engineering reviewer personally audits all child deliverables and records:

- Exact accepted revision, child PR/issue links and latest CI results.
- Full county/decade inventory, search scope and explicit unresolved gaps. Gaps never
  mean no trails. Coverage states distinguish located, examined and not digitized.
- Four qualifying county/decade batches: two distinct decades in each county, one
  before 2000 and one from 2000 onward, with inspected positive dated foot-trail
  evidence and precise locators; both pre-2000 historical topo requirements met.
- Exact selected source IDs, receipt digest, and successful independent archive
  verification/snapshot from #22. Any archive failure keeps M1 open.
- One obtainable, identity-matched, dated aerial frame, bounded county intersection,
  access method, rights and human confirmation; no substituted flight-level lead.
- Exact M2 input list (topos and frame), restrictions, remaining questions and manual
  GCP work. No broad instruction to repeat research instead of a concrete handoff.
- Actual reviewer identity, UTC acceptance time and explicit accept/block decision.

A green release gate is necessary, not sufficient: manually check trail identity,
feature dating, rights, footprint and archive evidence. An absent `build/public`
means no publication leak scan occurred; do not claim public release safety. Close
#23 and #2 only when all criteria and children are accepted; otherwise record precise
blockers and keep them open. Do not start M2 or merge this documentation as acceptance.

## 7. Blank human worksheet — NOT EVIDENCE

Copy this into working notes only. Empty fields remain empty until the named human
has actually performed the work; the prose worksheet is not schema-valid JSON.

```text
Issue / county / decade / area IDs:
Actual reviewer / actual UTC review time:
Collection / exact item ID / observed URL:
Search performed / time / spatial and temporal extent / outcome:
Source page, sheet, frame, figure and precise feature locator:
Footprint evidence / county intersection / review extent:
Foot-trail identity evidence (including legend) / ambiguity:
Feature date evidence / base vs revision / precision / unresolved ranges:
Rights statement and source / internal-use limits / publication decision:
Scan identity and full-access confirmation (aerial only):
Batch sources / positive review IDs / bounded tasks / remaining gaps:
Selection additions and reason / other reviewers' entries preserved:
Commands / exact revision / exits / receipt and archive snapshot hashes:
Human accept or block decision / reason / follow-up owner:
```

Never invent a reviewer, date, observation, foot-trail narrative, frame footprint or
license to fill this worksheet. Unresolved evidence, unauthorized access/cost, rights
conflict, validation failure, missing archive, unmet dependencies and missing manual
acceptance are stop conditions for their affected step. Log what was tried and what
would resolve the gap; preserve the rest of the countywide work.
