# Data model

The normative definition is README §3 (field tables) and the four JSON Schemas in
`schema/`, which carry the `x-sensitivity` annotations that drive the leak test.

The model must support historical foot trails anywhere in Nevada and Placer Counties
from 1950 to the present. Existing `tier` and local `corridor` enums are legacy schema
constraints, not geographic priorities. Their migration is tracked in
`docs/open-questions.md`. The four-field temporal model and required source support
apply equally throughout both counties.

Not yet written. This file gets the worked explanation — the four-field temporal model,
the decade rendering logic, and the support/role vocabulary — once the real dataset lands
in M3.
