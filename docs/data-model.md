# Data model

The normative definition is README §3 (field tables) and the four JSON Schemas in
`schema/`, which carry the `x-sensitivity` annotations that drive the leak test.

The model must support historical foot trails anywhere in Nevada and Placer Counties
from 1950 to the present. The trail schema therefore has no `tier` field, and `corridor`
is a required nonempty free-text grouping label with no locality enum: use `other` when
no grouping is established. A corridor label groups trails; it does not constrain
geography, priority, or digitizing. The four-field temporal model and required source
support apply equally throughout both counties.

The support/role vocabulary and the worked dataset examples arrive with the real data in
M3. The decade rendering rules below are decided now and match README §3 exactly.

## Observation dating

An observation dates the evidence, not the trail's whole life.

- `date_end` null means a dated event: one sheet, one frame, one declaration. It is not
  an ongoing interval and does not extend forward.
- A bare `YYYY` means uncertain within that year. `as_bound()` in `scripts/validate.py`
  widens it to 1 January on the lower side and 31 December on the upper.
- `date_end` records the end of the evidence date range. By itself it never authorizes
  presence across the intervening decades. A source that explicitly supports individual
  further decades is entered as separately justified observations after human review;
  the pipeline never manufactures them.
- A range wholly inside one decade supports that decade. A range crossing a decade
  boundary is unresolved for every decade it touches until a reviewer supplies more
  precise evidence: it neither documents nor brackets a decade.
- Revised sheet dates and `content_year` do not date every feature on a sheet.
  Unresolved feature dating stays in the research inventory. Never fabricate a
  required `observation.date_start` to fill the gap.

## Evidence roles

| Role | Effect on decade state |
| --- | --- |
| `attests_existence` | positive evidence |
| `attests_public_use` | positive evidence |
| `attests_closure` | closure evidence |
| `attests_alignment` | none; supports geometry only |

`attests_public_use` records what a document shows about use. It is not an assertion
that the public holds a right of access (AGENTS.md §2.6).

## Decade decision table

For decade `D` (1970 = 1970-01-01 … 1979-12-31). "Resolves to `D`" means the
observation's whole date range falls inside `D`.

| State | Condition for decade `D` | Reason |
| --- | --- | --- |
| `documented_closed` | closure evidence resolves to `D` and no positive evidence resolves to `D` | `documented_evidence` |
| `documented_open` | positive evidence resolves to `D` and no closure evidence resolves to `D` | `documented_evidence` |
| `unobserved` | both positive and closure evidence resolve to `D`; both citations are retained | `conflicting_evidence` |
| `inferred_open` | no evidence resolves to `D`, the same alignment has positive evidence before `D` and after `D`, and no closure or unresolved range lies between those bracketing observations | `inferred_between_observations` |
| `unobserved` | bracketing positives exist but a closure lies between them | `closure_in_bracket` |
| `unobserved` | the only candidate evidence is a date range crossing a decade boundary | `date_range_unresolved` |
| `unobserved` | anything else, including no observations at all | `no_resolving_evidence` |

### Rule precedence

1. Evidence resolving to `D` outranks any inference across `D`.
2. Within `D`, conflict outranks both documented states.
3. Inference runs only when nothing resolves to `D`, and only with positive evidence on
   both sides. A closure or an unresolved range inside the bracket defeats it.
4. Nothing projects indefinitely. A past opening observation does not keep a trail open
   in later decades, and a past closure is not carried forward either.
5. The four temporal fields on an alignment are bounds. They are never sufficient on
   their own to manufacture a decade observation.

A reopened or rerouted geometry stays a separate reviewed alignment where evidence
supports it. It is not a state transition on the old one.

## Worked examples

`scripts/fixtures/temporal_cases.json` holds the same cases in machine-readable form.
The IDs and dates there are fixture-only and synthetic; the file lives under `scripts/`
and never enters `data/authoritative/`.

| # | `case_id` | Observations | Decade | State | Reason |
| --- | --- | --- | --- | --- | --- |
| 1 | `tc-01-positive-in-decade` | 1954 positive | 1950 | `documented_open` | `documented_evidence` |
| 2 | `tc-02-positive-not-projected-forward` | 1954 positive | 1970 | `unobserved` | `no_resolving_evidence` |
| 3 | `tc-03-bracketed-by-positives` | 1954 positive, 1978 positive | 1960 | `inferred_open` | `inferred_between_observations` |
| 4 | `tc-04-closure-inside-decade` | 1954 positive, 1978 positive, 1962 closure | 1960 | `documented_closed` | `documented_evidence` |
| 5 | `tc-05-closure-inside-bracket` | 1954 positive, 1978 positive, 1958 closure | 1960 | `unobserved` | `closure_in_bracket` |
| 6 | `tc-06-closure-not-projected-forward` | 1962 closure | 1970 | `unobserved` | `no_resolving_evidence` |
| 7 | `tc-07-positive-and-closure-same-decade` | 1961 positive, 1962 closure | 1960 | `unobserved` | `conflicting_evidence` |
| 8 | `tc-08-alignment-role-only` | 1963 `attests_alignment` only | 1960 | `unobserved` | `no_resolving_evidence` |
| 9 | `tc-09-range-crosses-decade-boundary` | 1968–1972 positive range | 1960 | `unobserved` | `date_range_unresolved` |
| 10 | `tc-10-range-inside-one-decade` | 1962–1968 positive range | 1960 | `documented_open` | `documented_evidence` |
| 11 | `tc-11-no-observations` | none | 1960 | `unobserved` | `no_resolving_evidence` |
| 12 | `tc-12-pre-1950-positive-only` | 1947 positive | 1950 | `unobserved` | `no_resolving_evidence` |

Case 4 is `documented_closed` because the 1962 closure resolves to the 1960s while both
positives sit outside it. Case 5 keeps the closure at 1958, outside the decade but inside
the bracket, so the inference in case 3 no longer holds and nothing renders.

## Coverage inventory

`data/sources/coverage.json` is research bookkeeping, validated by
`schema/coverage.schema.json`. It records where the project has looked, what it found,
and what it examined. It is not part of the evidence graph: no cell, candidate, search,
review, or batch supports an alignment. Presence in the dataset still requires an
observation and a `support.csv` row (AGENTS.md §2.4). The inventory is internal until
the audience-aware export lands; nothing in it is cleared for publication by being here.

### Four distinct states

Conflating any two of these would let bookkeeping read as evidence.

| State | Recorded by | Means |
| --- | --- | --- |
| source located | a `candidate` record, or a `topo:` ref into `topo_index.csv` | a source covering the area and decade is known to exist |
| source examined | a `review` record | a named person looked at that source for that area and decade |
| trail digitized | a `batch` with `status: digitized` and `alignment_ids` | geometry was drawn from reviewed sources |
| unexamined | a `gap_code`, or the absence of a cell | nobody has looked, or the look was partial or blocked |

An empty `gap_codes` list asserts nothing. It is the absence of a recorded gap, not a
claim of complete historical coverage. A search with `outcome: no_match` says the query
returned nothing; it never says no trail existed. `scope: partial` on a review limits
that review to the part actually examined, so a partial review leaves the rest of the
cell unexamined.

### Records

- **cell** — one `area_id` + `decade` unit, unique on that pair. Carries the refs and
  gap codes for the unit. `area_id` keys `data/sources/coverage_grid.geojson`.
- **candidate** — a located source not yet entered as an observation: metadata only.
  `collection_id` must match a `sources.yml` id; `source_identifier` holds the
  publisher's own identifier, while `candidate_id` is a local slug. `rights: unknown`
  is the absence of a permission, never a permission to publish (AGENTS.md §2.7).
  Bounds are all four numbers or all four null. `date_end` dates the source, not
  continuous trail use, and requires a `date_start`.
- **search** — one attempt to locate sources, with the query as issued so it can be
  repeated. `searched_at` is an observed UTC instant, never a file mtime.
- **review** — one human examination. `reviewed_at` and `reviewer_id` must reflect the
  review that happened. `foot_trail_evidence: yes` requires an `evidence_locator` so a
  second reviewer can find the same mark.
- **batch** — a unit of planned digitizing work for one county, decade, and set of areas.

### Source references

A `source_ref` is `topo:<topo_id>` for a row in `topo_index.csv` or
`candidate:<candidate_id>`. The topoView index and its receipts stay authoritative for
topo metadata and bytes; the inventory points at them rather than copying them.

### Deferred to the validator

Draft 2020-12 checks shape, not fact. The M1.4 validator owns real-calendar date
validity (the schema only matches `YYYY` / `YYYY-MM-DD`, as `DATE_SHAPE` does in
`scripts/validate.py`), `date_start <= date_end`, `-180 <= west < east <= 180` and
`-90 <= south < north <= 90`, `area_id`/`collection_id`/ID cross-references,
uniqueness of `area_id` + `decade`, and six-decimal coordinate truncation on the grid.
The coverage schemas are deliberately not registered in `scripts/validate.py`, which
governs `data/authoritative/` and requires `x-sensitivity` on every property.
