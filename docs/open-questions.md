# Open questions

Gaps and ambiguities that need a human decision. Append with a date, the question, what
was tried, and what would resolve it (AGENTS.md §5.4). Do not resolve one by guessing.

---

## 2026-08-29 — `data/sources/aoi_tier1.geojson` cannot be authored by an agent

**Question.** README §2 and AGENTS.md §6 both say the Tier 1 AOI is *defined by*
`data/sources/aoi_tier1.geojson`, and M0 asks for the README §5 layout. But drawing that
polygon means inventing geometry, which AGENTS.md §2.1 forbids.

**What was tried.** Left the file absent rather than committing a placeholder box. The
directory exists; the file does not. Nothing in M0 reads it.

**To resolve.** A human draws the Bear River Canal corridor AOI (Crother Rd to Placer
Hills Rd, plus the Bowman feeder and Meadow Vista connectors) in QGIS and commits it, or
names an authoritative source polygon to derive it from. Needed before M1, since
`fetch-topo` selects quads by AOI intersection.

---

## 2026-08-29 — Temporal coherence: which comparisons are in scope?

**Question.** AGENTS.md §5.3.4 says "temporal coherence (`earliest_known_open <=
latest_known_open`, etc.)". The "etc." is ambiguous. Within-pair comparisons are obvious.
Cross-pair ones are not: should `latest_known_open <= earliest_known_closed` hold?

**What was tried.** `scripts/validate.py` enforces only the two within-pair comparisons
(open pair, closed pair) plus `date_start <= date_end` on observations. It deliberately
does **not** enforce any open-vs-closed ordering, because a corridor that is documented
closed in 1988 and documented open again in 2001 is a real and important pattern, and a
cross-pair rule would reject it.

**To resolve.** Confirm that reopening is in scope for the model. If it is, the current
behaviour is right and this note can be closed. If a trail is never expected to reopen
within the dataset, add the cross-pair check.

---

## 2026-08-29 — A bare `YYYY` on the "latest" side is widened to 31 December

**Question.** Dates may be `YYYY` or `YYYY-MM-DD`. Comparing `earliest_known_open =
"1954-06-01"` against `latest_known_open = "1954"` is undefined: is the bare year the
start of 1954 or the whole of it?

**What was tried.** `as_bound()` widens a bare year to `(Y, 12, 31)` on the upper side and
`(Y, 1, 1)` on the lower, so a bare year means the whole year. This avoids failing records
that are actually coherent.

**To resolve.** Confirm the interpretation. It matters again in M4, where the decade
stepper has to bucket the same dates (README §3, decade rendering logic).

---

## 2026-08-29 — `support.csv` has no sensitivity column

**Question.** README §3 gives alignments and observations a Sensitivity column but gives
`support.csv` none. Its `note` field is free text authored by a human summarising what a
document shows, and for a restricted declaration that note could easily name the
declarant.

**What was tried.** All five `support.csv` fields are marked `x-sensitivity: public` in
`schema/support.schema.json`, matching the README table as written.

**To resolve.** Decide whether `note` should be `restricted`, or whether the rule is that
notes on support rows pointing at a restricted observation are stripped from the public
build. The second is probably right but it is a modelling decision, not a coding one.

---

## 2026-08-29 — `.github/` is a top-level directory not in README §5

**Question.** M0 requires `.github/workflows/validate.yml`, but README §5 does not list
`.github/`, and AGENTS.md §4.1 forbids new top-level directories without updating both
files.

**What was tried.** Added `.github/workflows/validate.yml` to the README §5 layout block
so the two agree. AGENTS.md §4.1 needed no change — it defers to README for the layout.

**To resolve.** Nothing outstanding; recorded so the README edit is traceable.

---

## 2026-08-29 — Bare `make` fails during M0

**Question.** AGENTS.md §4.3 and README §6 both define `make` with no argument as
`validate build-public`. `build-public` is not implementable until M5, and per the M0
brief it exits with a "not implemented" message.

**What was tried.** `.DEFAULT_GOAL` is `all: validate build-public`, exactly as specified.
Bare `make` therefore validates successfully and then exits non-zero on `build-public`.
`make validate` is the working M0 entry point, and CI runs that target, not bare `make`.

**To resolve.** Nothing to decide — it resolves itself at M5. Flagged so nobody reads the
bare-`make` failure as a broken scaffold.

---

## 2026-08-29 — Fixture records are in `data/authoritative/`

**Question.** M0 asks for fixtures so validation has something to chew on, and README §7
puts them in `data/authoritative/`. That directory is otherwise defined as the source of
truth, and synthetic records living there is a standing hazard.

**What was tried.** Every fixture uses `fixture-` prefixed IDs, `FIXTURE`-prefixed names,
`FIXTURE DECLARANT` as the declarant, `FIXTURE-APN-000-000-00N` as APNs, and a `notes`
field saying the record is synthetic and not evidence.

**To resolve.** Delete all `fixture-*` records in M3 when the real OTCA data lands. If
that slips, consider moving fixtures to `tests/` and pointing `validate.py --data-dir` at
them, at the cost of `make validate` no longer exercising the real directory by default.
