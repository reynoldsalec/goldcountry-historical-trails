# Open questions

Gaps and ambiguities that need a human decision. Append with a date, the question, what
was tried, and what would resolve it (AGENTS.md §5.4). Do not resolve one by guessing.

---

## 2026-08-29 — AOI: acquisition envelope RESOLVED, digitizing bound still open

**Resolved.** Direction on 2026-08-29: use only GIS data sourceable online at this stage,
and scope acquisition to all of Placer and Nevada County. `data/sources/aoi_counties.geojson`
is now built by `make fetch-aoi` from Census TIGERweb (Census 2020 vintage, public domain,
pinned so it cannot drift). Nothing was hand-drawn. AGENTS.md §5.1 permits the widening
because the task said so explicitly; the exception is recorded there and in README §2, and
is limited to acquisition — digitizing scope is unchanged.

**Still open: `data/sources/aoi_tier1.geojson`.** The digitizing bound does not exist yet.
It cannot be hand-drawn at this stage per the same direction, so it has to be derived from
an online source. Candidates, none yet verified as fit:

- OSM (`README.md` §8, ODbL, attribution required) — the canal is plausibly mapped as
  `waterway=canal` and the trail as `highway=path`. Cheapest to test.
- USGS NHD canal/ditch flowlines via The National Map — public domain, same infrastructure
  as the M1 topo fetch. Worth checking whether the Bear River Canal is carried and
  correctly named; a GNIS name search returned an ambiguous distance-to-Meadow-Vista
  result that was not chased down.
- Placer County Open Data (`README.md` §8) — may publish a trails or canal layer.

**What is known about the corridor,** from public trail listings corroborated 2026-08-29:
it runs from Crother Rd (below the Waldorf school) via Meadow Gate Rd to Placer Hills Rd
(by the Winchester entrance), roughly 4 miles one way. Sources describe a PG&E maintenance
gravel road on one bank and singletrack on the other, which matches the berm/bank
distinction in AGENTS.md §6. This is orientation only — it is not a citation and must not
be used as one.

**To resolve.** Confirm which online source to derive the Tier 1 bound from, and the
buffer distance. The buffer has to be generous enough to contain historical reroutes and
19c alignments, because a tight buffer around the modern trace silently assumes the
historical trail followed it — the inference AGENTS.md §2.1 forbids.

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
