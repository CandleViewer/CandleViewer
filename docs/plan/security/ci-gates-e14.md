# CI security gates for the drawings persistence surface (E14-X03)

> Owner: `@CandleViewer/security`. Ticket: E14-X03 (#549), slice PR-1 of 3. Threat model:
> `docs/security/threat-models/E14-drawings.md` (DR1, DR10, DR12, DR20, DR21, DR23, DR29, DR30,
> section 4). Programme rules: `docs/plan/04-security-program.md` section 12.2 (Semgrep composition,
> CI-SEC-006 suppressions) and 16.2 (exceptions). This page explains each gate; the rule YAML is the
> source of truth for what is matched.

## Running locally

- Validate: `semgrep --metrics=off --validate --config .semgrep`.
- Prove the fixtures: `python tools/ci/check_semgrep_rule_tests.py`. Every rule needs at least one
  `# ruleid: <id>` line and, since E14-X03, one `# ok: <id>` line: a line a naive rule would flag.
- Fixtures are trees, `.semgrep/tests/<rule-id>/<repo path>/...`, staged at those paths, with a PEP 695
  file where the real file has generics (`api/drawings*.py`): Semgrep parses it another way (#3549).

## How these gates run

`_job-security.yml` passes every `.semgrep/cv-*.yml` to `semgrep scan` and runs the fixture checker in
the same job: no workflow change, no new required-check name (C-9.1); `ERROR` blocks
(`security_gate.py`). `scripts/tests/test_e14_security_gates.py` pins each rule's metadata and doc
section, and that the rules are quiet on `services/api/candleviewer` but for the four exceptions
below. This is the persistence half of E14-X03; the render-sink rules, the lint ban, the bundle
guard and the nightly ZAP profile are the next slices.

## Reviewed exceptions

Four statements are unscoped by design. Each has a comment-only `nosemgrep:
cv-drawings-query-missing-owner-filter reason=<token> owner=@basiltt review=2027-03-25` on the line
above it, with its rationale (CI-SEC-006: review within 180 days, policed by governance):
`_EXISTS_OTHER` (asks whether an id is another owner's; a bool; DR20), `_PURGE` (retention, no caller;
DR35) and `_COUNT_LIVE` (the all-owner rows gauge; DR25) in `drawings_sqlalchemy.py`, and
`_PURGE_LAYOUTS` in `workspaces_sqlalchemy.py` (its correlated `SELECT ... FROM drawings` looks for
live drawings of any owner under a layout it would purge; D21, SR-E14-09).

## cv-drawings-query-missing-owner-filter

- **Protects:** DR1, DR12, DR20, DR21; SR-051, C-12.4. `scope: self` is a data-layer promise.
- **Matches:** a `SELECT`, `UPDATE` or `DELETE` on `drawings` with no `owner_user_id = :owner`
  predicate, as text SQL (`text(`, `execute(`, `fetch(` ... or an assignment whose first literal opens
  with the verb) or as a Core `select`/`update`/`delete` with no `.where(...)` naming
  `owner_user_id`. Scope: `services/api/candleviewer/**`, not migrations. Fix: add
  `AND owner_user_id = CAST(:owner AS uuid)`, or annotate with a reason.
- **Does not match:** `INSERT`, a statement that does not name `drawings`, `drawing_templates`, text
  built before the call (`cv-no-raw-sql-interpolation` owns construction). The predicate is looked
  for, not parsed: one under an `OR` passes; the repository's unit test covers its constants.
- **Deliberate-regression fixture:** the `ruleid` lines of
  `.semgrep/tests/cv-drawings-query-missing-owner-filter/`, with the annotated multi-line statement
  that proves the marker placement the four exceptions use.

## cv-drawings-owner-from-body

- **Protects:** DR1; SR-051, SR-040. The owner is `principal.user_id`; request models are closed.
- **Matches:** the owner taken from request data (`request.query_params`, `path_params`, `headers`,
  `json()`; an attribute of `body`/`op`/`payload`; a `model_validate` result) as the store's first
  argument, an `owner`/`owner_user_id` keyword or dict key, or an owner-named variable; and an
  `owner`, `owner_id`, `owner_user_id`, `user_id`, `actor_user_id` or `created_by` field on a request
  model. Scope: `api/drawings*.py`. Fix: `str(principal.user_id)`; no owner field on a model.
- **Does not match:** `request` alone (`caller(request, ...)` stays clean), request data at a
  non-owner argument, response models (`..Out`, `..Response`, `..Row`). Search mode, not taint mode:
  one rule cannot hold the structural schema arm, and only owner-named variables are followed (DR1's 422 test and the repository tests own the rest).
  **Fixture:** `.semgrep/tests/cv-drawings-owner-from-body/`.

## cv-drawings-unbounded-geometry

- **Protects:** DR29, DR30 (DR10); SR-040; section 4. The bounds are `DrawingIn._tool_rules`,
  `POINT_COUNTS` and the caps in `drawings_models.py`; storage validates no geometry or style.
- **Matches:** `DrawingFields(` outside `_fields`; `model_construct(...)`; `model_copy(update=...)`;
  `extra="allow"` or `"ignore"`; a dict display given to the store's `create`, `update` or
  `apply_batch`. Scope: `api/drawings*.py`. Fix: `_parse(DrawingIn, text)`, then `_fields(body)`.
- **Does not match:** `_ListQuery` (`extra="ignore"`: unknown query parameters are ignored, as FastAPI
  does), `model_copy()` without `update`. A tripwire on the roads round the validator, not a proof.
  **Fixture:** `.semgrep/tests/cv-drawings-unbounded-geometry/`.

## cv-drawings-batch-unvalidated-ids

- **Protects:** DR12, DR21, DR23; SR-051. Invariant: the owner-scoped snapshot precedes every UPDATE
  or DELETE of existing rows.
- **Matches:** in `storage/repositories/drawings*.py`, `_UPDATE_MANY` or `_SOFT_DELETE_MANY` run with
  no earlier `_SNAPSHOT` in the same function; in `api/drawings*.py`, a `store().update`,
  `soft_delete` or `create` in a loop or comprehension over `ops`/`operations`. Fix: hand the whole
  batch to `store().apply_batch(owner, ops)`.
- **Does not match:** `_INSERT_MANY` (a create touches no existing row; a key collision is refused
  atomically), and a snapshot taken in a helper is not seen: a structural heuristic.
  **Fixture:** `.semgrep/tests/cv-drawings-batch-unvalidated-ids/`.

## cv-drawings-pixel-geometry

- **Protects:** DR10. A correctness guard: the contract (`22-api-openapi.yaml`, `DrawingPoint`,
  `DrawingGeometry`, `additionalProperties: false`) stores chart space only, a time `t` and a price `p`.
- **Matches:** a field, dict key, subscript key or keyword named `x`, `y` or `px` in
  `api/drawings*.py`. Fix: convert pixels to chart coordinates in the client. The TypeScript arm
  follows in the render slice.
- **Does not match:** a comprehension or lambda variable `x` (as in `_parse_t`), a parameter.
  **Fixture:** `.semgrep/tests/cv-drawings-pixel-geometry/`.

## Budget

The ticket asks for under 30 s added to CI. Measured with Semgrep 1.181.0 on the shared 8-vCPU VPS at a
1-minute load of 8 to 13 (below 8 only at the start of the first run), under `nice -n 10`:

- **Repo-wide scan:** the five rules over `services/api` (793 files, `--jobs 2`): 0 findings, 0 errors.
  Their own matching is 1.5 s (`semgrep --time`: `cv-drawings-query-missing-owner-filter` 1.26 s over 20
  files, slowest `db/models.py` 0.43 s; the other four 0.05 to 0.08 s each).
- **Fixture checker,** one `semgrep scan` per rule: 345.8 s wall (325.8 s CPU) with 52 rules, 412.9 s (373.4 s
  CPU) with 57, at different loads. Alternating in the same windows, five new scans took 30.3 and 31.5 s
  wall (28.7 and 29.7 s CPU) and five existing tree-rule scans 34.4 and 36.1 s (30.3 and 32.2 s CPU); a
  trivial scan takes 5.8 s (5.2 s CPU). A new rule costs one start-up, no more than an existing one, so the
  five add about 30 s here: at the bound, not under it. Not measured on a CI runner.

## Requesting an exception

Fix the code if you can. Otherwise add `# nosemgrep: <rule-id> reason=<token> owner=@<handle>
review=YYYY-MM-DD` (at most 180 days) on the line above the finding's first line, with the rationale
above it, and tag `security-review`; a High finding or an exception that outlives a release also
follows `04-security-program.md` section 16.2.
