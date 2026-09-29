# Staging evidence for the M1 assessment

These are discovery records, not schema-valid coverage inventory records, human
reviews, acquired source rasters or acceptance. No record here authorizes a ready
batch, a trail observation or publication of imagery.

- `issue-contracts.json`: issue #2 and #15–#23 bodies/comments at the recorded UTC
  retrieval time; historical snapshots, not claims about future issue state.
- `citation-ledger.json`: the original stable numbered source ledger. Uncited entries
  are discovery leads, not asserted evidence. Ledger access dates use the prior
  process's local calendar; browser records carry precise UTC observations.
- `tnm-*.json`: observed API request URLs and response text. The full county responses
  retain public federal metadata needed to reproduce counts. Matching `.txt` files
  are extraction inputs used for citation quotes, not additional independent sources.
- `modern-map-triage.json`: publisher fields and computed county/cell intersections;
  rights are unknown and reviewed is false. Publication decades are not feature dates.
- `modern-review-queue.json`: later-publication-decade cell leads and explicit no-lead
  lists, not completed source searches across every possible collection.
- County plan/access/rights JSON and matching text: selected verbatim excerpts with
  observed URLs and discovered links retained. Navigation and unrelated full-page
  prose were removed to avoid unnecessary republication. Original captures remain
  outside Git; no raster or receipt was altered by this cleanup.
- UCSB county/flight/index/directory records: factual catalog listings and source
  locators. Catalog presence is not human confirmation of an individual frame.
- `aerial-access-probe.json`: a bounded 16-byte response, not full TIFF acquisition.
  `aerial-index-extract.json` is text extraction, not visual index/frame review.
- `discovery-*.json`: search results only, not proof that linked documents were read.
- `baseline.json`: local inventory counts and receipt hash, not archive acceptance.
- `initial-checks.json`: prior command capture; topo-test output was truncated.
  `completion-checks.json` provides fresh complete regression/validation outputs and
  expected release/archive blockers. `additional-checks.json` covers deterministic
  grid, refresh, report and dry-run probes. `numeric-verification.json` records an
  offline recount from saved responses and committed geometry.
- `document-checks.json`: completion-time local checks, including the citation tool.

Local checkout/cache prefixes were redacted. No credentials are required by the
public discovery records. Do not commit credentials, unpublished documents, private
archive paths or restricted source material when extending this directory.

See [assessment](../m1-research-assessment.md) for interpretation and
[runbook](../m1-human-runbook.md) for the remaining human work.
