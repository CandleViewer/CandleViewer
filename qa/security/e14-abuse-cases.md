# E14 abuse cases — drawings: stored XSS, IDOR and payload exhaustion (E14-X02)

- Ticket: E14-X02 (#474). Threat model: `docs/security/threat-models/E14-drawings.md` (E14-X01,
  SR-E14-01..11, RR1..RR7). Contract: `docs/plan/22-api-openapi.yaml`, `/drawings*`.
- Base: `main` at `5c767dd9c600d8dd5d99eff651485fa47717cd1c` (2026-10-26). Code paths are relative
  to `services/api/candleviewer/`, test paths to `services/api/`.
- Scope of this record: the backend half. The client half (rendering-side XSS at every DOM, ARIA,
  SDF and analytics sink, the Playwright pack and the position-tool integrity test) moved to #4602
  by the orchestrator's split ruling; #4602 is blocked by #545, #546, #547 and #358.
- Location: the ticket's path; the first file in `qa/security/` (reviews live in
  `docs/security/reviews/`, and no document puts abuse-case findings there).
- Disclosure (`SECURITY.md` §1, C-12.13): an open, exploitable weakness would carry only id,
  severity, area, status and tracker here. This pass found none; every open row below is a defence
  gap already stated publicly in the threat model, or an observability or contract gap.

> **Status: Security-engineer sign-off pending** (input to E14-Q08). Open: F-01 (Medium, #2727),
> F-02 and F-03 (Low, #2727), F-04 (Low, to be filed), the residuals in §6. Zero open P0/P1
> security findings against E14's backend.

Severity: the `04-security-program.md` ladder. Status: **open** · **fixed** (on `main`, PR named)
· **contract note** (no defect; the ticket text is stale).

## 1. Findings

| Id   | Severity | Area                   | Finding                                                                                                                                                       | Status        | Tracker                                           |
| ---- | -------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------- |
| F-01 | Medium   | Availability (DR32/33) | No per-user or per-symbol drawing quota and no route rate limit: bounded per call, unbounded in aggregate (RR4, SR-E14-05)                                    | open          | #2727                                             |
| F-02 | Low      | Observability (DR17)   | A scope denial (404 to a foreign id, 409 `target_unavailable` to a foreign batch target) moves no denied counter; only its `rbac.denied` record shows it      | open          | #2727 (SR-E14-11)                                 |
| F-03 | Low      | Observability (DR29)   | A 413 (body over 64 KiB or 1 MiB, batch over 200 operations) leaves no drawings counter, audit record or log line; only the route's 4xx duration series moves | open          | #2727 (SR-E14-11)                                 |
| F-04 | Low      | Contract (DR25)        | `errors[].field` echoes an unknown JSON key: sanitised and cut to 64 code points, not HTML-encoded; 22 states no bound on it                                  | open          | to be filed; client: #4602                        |
| F-05 | Info     | Hardening (E14-X03)    | No `X-Content-Type-Options: nosniff` on `/drawings*` answers (noted on #474, 2026-10-15)                                                                      | fixed         | #4001; #4394 pins it (`test_drawings_nosniff.py`) |
| F-06 | Info     | Ticket text (AC2)      | AC2 expects 404 for a mixed batch; 22 specifies `409 conflict`, rule `target_unavailable`, identical for foreign, deleted and missing targets                 | contract note | #474 (this record)                                |
| F-07 | Info     | Ticket text            | The ticket's "501-op batch" assumes a 500 cap; the shipped cap is 200 (`MAX_BATCH_OPS`), so the probe is the 201-op boundary                                  | contract note | #474 (this record)                                |

### F-01 — no quota (Medium, open, #2727)

- Reproduction: as already disclosed in the threat model (DR32, DR33, RR4); nothing beyond it is
  restated here.
- Evidence: threat model DR32, DR33, RR4; no quota code in `api/drawings.py`. The only pressure
  test is the idempotency cache's (`tests/drawings/test_drawings_abuse_exhaustion.py`
  `test_idempotency_pressure_evicts_the_oldest_key_of_the_flooding_user_only`). Owner: #2727; the
  value is an Owner decision, and RR4 holds E14 epic sign-off until it is made.

### F-02 — scope denials are not counted (Low, open, #2727)

- Reproduction: user B sends `PUT /drawings/{id}` or `DELETE` for user A's live drawing: 404, one
  `rbac.denied` record (`not_owner:workspaces:write:self`), `authz_denied_total` unchanged. A
  foreign batch target is 409 and moves `cv_drawings_conflicts_total{rule="target_unavailable"}`,
  a label it shares with the caller's own soft-deleted target.
- Contrast: a permission denial (a Viewer writing) is counted: `authz_denied_total{permission}`
  +1 per request (`auth/scopes.py:299`) and one `rbac.denied` record.
- Evidence: `tests/drawings/test_drawings_abuse_backend.py:155`
  (`test_a_viewer_write_moves_the_denied_counter_once_and_leaves_one_record`), `:166`
  (`test_a_foreign_id_probe_is_audited_but_counted_nowhere_tripwire_2727`), `:179`
  (`test_a_foreign_batch_target_moves_the_conflict_counter_and_leaves_one_record`); code
  `api/drawings.py:418` (`audit_not_owner`), `:427` (`not_found`), `:567` (`conflict(rule)`).

### F-03 — 413 refusals leave no drawings signal (Low, open, #2727)

- Reproduction: `POST /drawings` with a 64 KiB + 1 byte body, or `POST /drawings/batch` with 201
  operations: 413 `payload_too_large`, no audit record, no log line, no `cv_drawings_*` series;
  `cv_http_request_duration_seconds_count{route="/drawings",status_class="4xx"}` +1 is the only
  trace, and it does not tell a 413 from any other 4xx.
- Evidence: `test_drawings_abuse_backend.py:203`
  (`test_an_oversize_or_over_cap_refusal_leaves_no_drawings_signal_tripwire_2727`), `:240`
  (`test_the_only_trace_of_an_oversize_refusal_is_the_routes_4xx_duration_series`); code
  `api/drawings.py:231` (`_read_capped`), `:264` (`_count_ops`).

### F-04 — hostile keys in `errors[].field` (Low, open, to be filed)

- Reproduction: `POST /drawings` with an extra key `<script>alert(1)</script>`: 422
  `extra_forbidden`, `errors[0].field` is that key verbatim. A key over 64 code points is cut with
  an ellipsis; C0/C1, U+2028/9 and bidi controls are stripped; at most 20 errors are returned.
- Server side this is inert: `application/problem+json`, `nosniff`, no HTML encoding by design (the
  server stores and echoes text; safety lives at the sink, SR-E14-01). The bound comes from the
  #357 decision record and `api/drawings_models.py:530` (`_MAX_SEGMENT`), `:535` (`_clip`), `:541`
  (`format_errors`); 22's `Problem.errors[].field` states none, so a client cannot rely on it.
- Evidence: `test_drawings_abuse_backend.py:443`
  (`test_a_hostile_json_key_is_echoed_sanitised_and_clipped_as_data`, create, PUT and batch),
  `:460` (`test_fifty_hostile_keys_yield_at_most_twenty_bounded_errors`).
- Fix proposed: state the bound in 22 (`Problem.errors[].field`), and add error-field rendering to
  #4602's sink list (a client that puts `field` into markup reflects the key).

### F-06, F-07 — contract notes

AC2's intent holds with 22's status, 409: `test_drawings_abuse_xss_idor.py`
`test_a_batch_with_one_unavailable_target_rolls_back_the_attackers_own_ops` and
`test_batch_bodies_are_identical_for_foreign_deleted_and_missing_targets`. The 201-operation
boundary: `test_drawings_batch.py` `test_batch_limits_are_checked_before_any_operation` and §3.

## 2. Abuse table and AC mapping

`ABUSE_TABLE` (`test_drawings_abuse_backend.py:46`) gives each 22 `/drawings*` operation its IDOR
cases, plus injection and exhaustion cases where it has a body; `:113` and `:126` fail when 22 gains
an operation or a listed test is renamed.

| AC / QA item (2026-10-20 record)                 | Proved by                                                                                         | Verdict                          |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------- | -------------------------------- |
| AC1 no corpus entry executes at any sink         | stored half: `test_drawings_abuse_xss_idor.py` corpus tests; sinks: #4602                         | backend half PASS; rest #4602    |
| AC2 mixed batch changes nothing                  | `test_drawings_abuse_xss_idor.py` batch rollback and identical-body tests (409 per 22, F-06)      | PASS                             |
| AC3 existence is not disclosed                   | `test_drawings_abuse_xss_idor.py` 404/412 probes; `test_drawings_abuse_backend.py:346`            | PASS                             |
| AC4 oversized payload rejected without harm      | `test_drawings_abuse_exhaustion.py`; memory/CPU sampling is a residual (§6)                       | PARTIAL (residual R-3)           |
| OpenAPI meta-test                                | `test_drawings_abuse_backend.py:113`, `:126`                                                      | PASS                             |
| Per-abuse server signals                         | `test_drawings_abuse_backend.py:155`, `:166`, `:179`, `:203`, `:240`                              | PASS for what exists; F-02, F-03 |
| Mass assignment (`owner_user_id` and others)     | `test_drawings_abuse_backend.py:261` (6 fields × create, PUT, batch create, batch update: 422)    | PASS                             |
| IDOR: expired, revoked, deleted-user, downgraded | `test_drawings_abuse_backend.py:346` (real `create_app`; 401, or 403 + audit; no store write)     | PASS                             |
| Batch numeric literal 422 vs 413                 | `test_drawings_abuse_backend.py:381`, `:407`                                                      | PASS                             |
| Hostile keys in `errors[].field`                 | `test_drawings_abuse_backend.py:443`, `:460`                                                      | PASS; F-04                       |
| SR-E14-06 log grep                               | `test_drawings_abuse_backend.py:483` (38 corpus entries, write and refusal paths, logs and audit) | log half PASS; rest #4602        |
| Foreign `alert_id`                               | not exposed: refused in every body (part C `:261`); read allow-list test (DR40)                   | PASS today; E40 later            |
| Nightly security job                             | `.github/workflows/dast-drawings-nightly.yml` job `abuse-packs`                                   | PASS                             |

## 3. What the new cases pin

Batch literals (`1e999`, `NaN`, `Infinity`, a 400-digit decimal): a field 422 inside the cap, 413
one operation past it, no echo. A body the stdlib count cannot parse (4301-digit integer, BOM, raw
control character, trailing data) is `json_invalid` to the model too
(`test_drawings_abuse_backend.py:407`): no input turns a 413 into a per-operation walk.

## 4. Negative controls

- #2571 (XSS store, IDOR): the reviewers' final mutation run, 68 source-level mutants, 0 survivors
  (review record, 2026-10-15T20:33Z). #2602's reviewers' probes are in that PR's review records.
- Author probes (comment on #474, 2026-10-15T20:12Z): 412 instead of 404 for a missing id under
  `If-Match` (3 enumeration tests fail); JSON depth check lowered by one (the depth test fails);
  leading `^` dropped from the colour pattern (8 prefix-anchor failures); idempotency cache keyed
  without the user (the isolation test fails).
- This pass: 19 mutants on the guards behind the new cases, each run against its own tests in a
  scratch copy; 19 killed, 0 survived (author-run, not committed).

| Mutant                                                                     | Killed by                                       |
| -------------------------------------------------------------------------- | ----------------------------------------------- |
| `enforce()` stops counting denials                                         | viewer-write counter (4 of 4)                   |
| batch conflict not counted; foreign target or PUT/DELETE probe not audited | foreign batch target; foreign-id tripwire       |
| a 413 starts logging; a scope denial starts counting (#2727)               | the two tripwires                               |
| `DrawingIn` ignores unknown keys                                           | mass assignment (24 of 24)                      |
| router grants every permission; resolver authenticates with `peek`         | downgraded; expired and revoked sessions        |
| op cap counted after validation; unparsable batch treated as over the cap  | literal differential (5 of 5); parser agreement |
| key segment cap 64 → 200; segment not sanitised; error cap 20 → 50         | hostile keys; fifty hostile keys                |
| `drawing_created` logs the label; batch audit carries the op               | SR-E14-06 grep (37 and 38 of 38)                |
| 22 gains a `/drawings` operation; a listed test is renamed                 | the two abuse-table tests                       |
| duration series loses the route on a 413                                   | 4xx duration series                             |

## 5. SR-E14-01..11 coverage

| SR        | Requirement (short)                             | Assertion here                                                              | Uncovered part → gate                 |
| --------- | ----------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------- |
| SR-E14-01 | DOM sink renders text only                      | stored half: corpus stored stripped, never decoded, served as JSON (part A) | **sinks → #4602** (#547, #358)        |
| SR-E14-02 | accessible name never built from markup         | none server-side                                                            | **all → #4602** (#547; E14-Q07)       |
| SR-E14-03 | SDF text is data, glyphs clamped                | control/bidi stripping, code-point caps (part A)                            | **layer → #4602** (#358)              |
| SR-E14-04 | no CSS strings from `style`                     | colours accept only `^#[0-9a-fA-F]{6}$` (part A)                            | client → #4602; E14-X03 lint arms     |
| SR-E14-05 | per-user quota                                  | none (F-01)                                                                 | **all → #2727**                       |
| SR-E14-06 | events and journal carry ids, never text        | log and audit grep over the corpus (part C)                                 | **analytics, journal → #4602** (#545) |
| SR-E14-07 | position-tool sizing re-validated server-side   | none                                                                        | **all → #4602** (#546)                |
| SR-E14-08 | `alert_id` same-owner check when exposed        | not exposed; refused in every body (part C)                                 | E40, when it exposes the field        |
| SR-E14-09 | layouts FK and same-owner rule                  | foreign layout 422/404 (`test_drawings_layouts.py`)                         | FK test is E15's (#3055)              |
| SR-E14-10 | no test handle in the production bundle         | none here                                                                   | E14-X03 bundle guard (#4394)          |
| SR-E14-11 | denied, 413/422, batch-cap counters; user gauge | existing signals pinned, missing ones tripwired (part C)                    | **counters, gauge → #2727**           |

Parts: A `test_drawings_abuse_xss_idor.py`, B `test_drawings_abuse_exhaustion.py`, C
`test_drawings_abuse_backend.py`, all in `services/api/tests/drawings/`.

## 6. Residuals

| Id  | Residual                                                                                            | Owner                                                                               |
| --- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| R-1 | AC1 rendering sinks (object tree, accessible names, popover, tooltips, SDF layer, analytics)        | #4602 (#545, #546, #547, #358)                                                      |
| R-2 | Playwright pack; position-tool integrity (US-DRAW-007)                                              | #4602 (#546)                                                                        |
| R-3 | Staging memory and CPU sampling, p95 rejection latency, 200 × 1 MiB run (AC4 "returns to baseline") | E14-Q05 budgets; not run here: needs a staging stack                                |
| R-4 | Quota and rate limit (SR-E14-05), counters (SR-E14-11)                                              | #2727                                                                               |
| R-5 | Hostile corpus through real JSONB (router packs use the in-memory repository)                       | E14-Q04's Postgres contract pack (`tests/contract/drawings`) is the place; not done |
| R-6 | Every finding reproduced by a second person (ticket test plan)                                      | Security engineer, at sign-off                                                      |

## 7. Hostile-corpus location

The corpus is `services/api/tests/fixtures/drawings_abuse/corpus.v1.json` (38 payloads, versioned,
marked attack data, loaded only by the abuse packs); the ticket names
`qa/security/corpus/drawings-text.json`. Recommendation: do not move it now. Its only consumers are
Python tests under `services/api`, test fixtures there never ship, and `qa/` holds plans and records,
not fixtures. When #4602 or E14-Q01/Q07 need it from TypeScript, move it to `packages/fixtures`
(the shared TS and Python fixture package in the repo map) in that ticket, with its README line.

## 8. Nightly

`dast-drawings-nightly.yml` (03:57 UTC, or by hand) runs a second job, `abuse-packs`, over
`tests/drawings/test_drawings_abuse_*.py` (a glob, so a new pack joins; pinned in
`scripts/tests/test_zap_nightly.py`). Permissions stay `contents: read`, no secret, SHA-pinned
actions; the packs are deterministic, use in-memory fakes and versioned fixtures, no network.

## 9. Sign-off

- Security engineer: _pending_ (input to E14-Q08).
