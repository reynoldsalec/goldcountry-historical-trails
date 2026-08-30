# Open questions

Gaps and ambiguities that need a human decision. Append with a date, the question, what
was tried, and what would resolve it (AGENTS.md §5.4). Do not resolve one by guessing.

---

## 2026-08-30 — AOI: both files now built from online sources

**Resolved.** `data/sources/aoi_tier1.geojson` now exists, derived from OpenStreetMap via
a date-pinned Overpass attic query (`make fetch-aoi`). Nothing was hand-drawn. OSM carries
the corridor in detail: `Bear River Canal` (14 ways, merging to one 20.77 mi line), a
named `Bear River Canal Trail` (8 ways, 5.03 mi, `highway=path`, `surface=dirt`), and
`Bowman Feeder Canal`. The canal was cut between its Crother Road and Placer Hills Road
crossings — 5.03 mi — unioned with the trail and the feeder, and buffered 250 m, giving
1.43 sq mi. It sits fully inside the acquisition AOI, which was checked.

The corridor identity question is settled: of the four canals in the area, `Bear River
Canal` is the only one touching all three named roads (Crother, Meadow Gate, Placer
Hills, all at 0 m). `Boardman Canal` is 64 m from Placer Hills Road and is a different
corridor. The README naming is correct.

**Still open: the 250 m buffer is a default, not a decision.** It was chosen to be
generous — a tight buffer around the modern trace would assume historical alignments
followed it, the inference AGENTS.md §2.1 forbids — but nobody has confirmed it is right.
For scale: 100 m gives 0.68 sq mi, 250 m gives 1.43, 400 m gives 2.18, 800 m gives 4.33.
Change with `uv run python scripts/fetch_aoi.py tier1 --buffer N`. Someone who knows how
far the 19c and mid-century alignments wander from the present ditch should set it.

**Still open: "Meadow Vista connectors".** README §2 includes them in Tier 1 but does not
name them, so they are not in the AOI. OSM has a `Sugar Pine Mountain Trail` touching the
corridor, which matches the `sugar-pine` value in the `corridor` enum, and `Simpson
Spillway` and `Combie Ophir Canal` are nearby, matching `simpson` and `combie`. That the
enum maps onto real named OSM features is a good sign, but which of them count as Tier 1
connectors is a scoping decision, not something to infer.

**Caveat carried into the data.** The AOI records `rights: odbl` and the required
attribution. OSM is not an authoritative record of historical trail extent, so no OSM way
may become an alignment in `data/authoritative/` (AGENTS.md §2.1). The file states this in
its own `role` property.

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

---

## 2026-08-29 — Acquisition AOI is ~2,365 sq mi, which resizes M1

**Question.** Not a blocker, but M1 was scoped against a 4-mile corridor and is now scoped
against two counties. The combined AOI bbox is roughly 128 km x 90 km, about 84 cells on a
7.5-minute grid and realistically 55-65 quads once clipped to the county shapes. topoView
carries several editions per quad across 1884-2006, so `make fetch-topo` plausibly means
several hundred GeoTIFFs and multiple GB.

**What was tried.** Nothing yet — no quads have been fetched. Flagged before M1 starts
rather than at download time.

**To resolve.** Decide whether `fetch-topo` pulls every edition of every quad, or filters
by date first (the 1967-1972 hinge in README §1 argues for prioritising mid-century
editions). Also worth deciding whether it fetches lazily per-quad on demand. `data/raw/`
is gitignored and fetched by script per AGENTS.md §4.4, so nothing here threatens the
repo; it is a time and disk question.
