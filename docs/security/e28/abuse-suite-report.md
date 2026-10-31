# E28-X03 — Abuse-case suite and RBAC matrix: per-account profiles and trade groups

- Ticket: E28-X03 (#976). Threat source: `docs/security/threat-models/E28-profiles-trade-groups.md`
  (the model): section 7 (AC-01 to AC-33), section 9 (SR-E28-01 to SR-E28-33) and section 10 (the
  control-to-ticket map). Programme threats and controls: `docs/plan/04-security-program.md`
  (O3, F2, F4, F6; SR-025, SR-052, SR-053, SR-054, SR-056, SR-064, SR-070 to SR-074).
- Method: white-box and in-process, through the real `create_app()` of the RBAC pack, with every
  E28 route over an in-memory store, no network and no sleeps (C-13.5, C-13.7). The refused cells
  run a second time on a migrated Postgres 16 loaded with the E28 seed, each proven by a per-table
  row-hash checksum to change no table a route can reach. A guard aborts the run on a live target.
- This report holds classes of attack and the controls that hold against them, not request recipes
  (the repository is public).

## 1. Where the suite lives

| Path                                                                    | What it holds                                                                  |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `services/api/tests/security/e28/test_rbac_matrix.py`                   | Every E28 route x every role x every scope situation; absent vs ungranted 404s |
| `services/api/tests/security/e28/test_ws_scope.py`                      | The `trade_groups` topic per role, through the app's own gateway and topic     |
| `services/api/tests/security/e28/test_abuse_cases.py`                   | AC-01 to AC-10, the preview halves of AC-11 and AC-15, SR-E28-21 (AC-29)       |
| `services/api/tests/security/e28/test_suite_meta.py`                    | Coverage of the route table, unmounted routes, the WS row and the live guard   |
| `services/api/tests/security/e28/_cells.py`, `_world.py`, `conftest.py` | The generated cells, the world and the live-target guard                       |
| `services/api/tests/integration/accounts/test_e28_rbac_snapshot_pg.py`  | The refused cells on Postgres, a row-hash checksum over every reachable table  |

The in-memory suite runs in the existing `contract-security-2` lane of the required `ci-required`
check; the Postgres module in the `integration` lane. No new required check name (C-9.1).

## 2. The RBAC matrix

The cells are generated from `tests/contract/rbac/matrix.yaml` (Security-owned, never edited here):
every executed operation on an E28 path, for the five matrix actors, in each situation its route
can name: an object granted to the Manager, one granted to no one, and one with a member on each.
170 cells today, 124 of them refused, plus the topic's five. Each refused cell asserts all three
properties:

1. the status and problem code: `403 forbidden` for a role the row refuses, `403
account_scope_denied` for the preview outside the grants, the uniform `404 not_found` for a read
   outside the grants, `401 unauthenticated` for a read with no session, and `403
csrf_token_invalid` for an unsafe call with no session, which the CSRF guard refuses before any
   route (SR-041);
2. no state change: a walk of every store of the world (profiles, bindings, notices, caches,
   idempotency replays, definitions, groups, preview reads, users, grants, rules), compared before
   and after; on Postgres a checksum over every table of the reachable families, `audit_log`
   excepted, with a meta check that fails on a new table of those families that the list misses;
3. the audit, looked up by the request's own id: one `rbac.denied` naming the caller for a 403, the
   preview's `trade_group.previewed` after it, `auth.csrf_refused` for the CSRF refusal, and no
   record at all for the 404 (a record would be the existence oracle) or a 401 (no principal).

An allowed cell is not refused and answers below 500. No answer names an account the caller does
not hold. One test per read route asserts the ungranted and the absent 404 are byte-identical in
status and body, and identical in `content-type`, `content-length`, `etag` and `cache-control`;
their timing is not asserted (the residual 24 records under SR-E29-13). Every mounted write has a forbidden-role cell and a cross-account cell.

The WS topic: for each actor, a `sub` naming a granted, a foreign and an absent account. The Owner's
is every group; the granted Manager's is narrowed silently (an `ok` result, the narrowing audited,
never answered); the others are refused as the topic row says. No frame names a denied id, and a
group with one leg outside the grants is never sent, not even in part.

## 3. The abuse cases

| Case  | Class                                                 | Controls                  | Threats        | Asserted                                                                                                   |
| ----- | ----------------------------------------------------- | ------------------------- | -------------- | ---------------------------------------------------------------------------------------------------------- |
| AC-01 | Turning the native stop off                           | SR-E28-08, SR-056         | F6, PF-T09     | 422 `native_stop_mandatory` on create, update and a hand-made payload; `profile.save_refused`; no write    |
| AC-02 | A symbol off the account's allow-list                 | SR-E28-06, SR-054         | O3, PF-T07     | The leg is not planned (`symbol_not_allowed`); the preview is recorded; nothing is sent                    |
| AC-03 | An oversized quantity hint                            | SR-052, SR-053, D6        | O3, PF-T06     | 403 `risk_limit_breached`, never clamped; `trade_group.override_refused` ahead of the preview record       |
| AC-04 | An alternate widening each protected cap in turn      | SR-E28-03, SR-052, SR-053 | O3, F2, PF-T03 | Notional, daily loss, leverage: 403 and `override_refused`; symbol lists: the bound list decides           |
| AC-05 | Demo and live in one group, or a member edited across | SR-E28-16, C-2.11         | PF-T16         | Preview 400 `environment_mismatch`, recorded; definition create and replace 400 before any write, recorded |
| AC-06 | A preview or group read reaching an ungranted account | SR-E28-21, SR-E29-13      | F2, PF-I01/I02 | One `account_scope_denied` shape for a foreign and an absent account; `rbac.denied`; reads 404             |
| AC-07 | A profile write without step-up                       | SR-025, SR-E28-02         | PF-S02         | 403 `step_up_required` from the production step-up service, its challenge recorded; no write               |
| AC-08 | A wildcard pattern matching outside the listed perps  | SR-E28-06, SR-054         | PF-T07         | Seeded property test over anchored suffix patterns; bare, short or malformed patterns 422 at save          |
| AC-09 | An idempotency key reused with another body           | SR-E28-17                 | F4, PF-T17     | 409 `idempotency_key_reuse` on profile create, replace and delete; nothing more written                    |
| AC-10 | A client-supplied profile snapshot                    | SR-052                    | PF-T06         | 422 (`additionalProperties: false`), recorded                                                              |
| AC-11 | Another account's profile named as an alternate       | SR-E28-03                 | PF-T03         | Preview half: the 404 of an unknown id, byte for byte                                                      |
| AC-15 | One account repeated in the legs                      | SR-E28-17                 | PF-T17         | Preview half: 422 before any read, recorded                                                                |
| AC-29 | Group reads and frames with a leg outside the grants  | SR-E28-21, SR-074         | F2, PF-I02     | Not listed, a 404 when named, never framed (the matrix's mixed cells and the WS test)                      |

## 4. Where the ticket's wording and the model differ (the model wins)

- C-1 (AC-01, "template apply"): no server route applies a template; templates are a client
  surface (E28-S02) whose saves are the profile writes asserted here.
- C-2 (AC-02, `profile_forbidden`): no such code is registered (22 `x-error-codes`). The preview
  plans no leg for a symbol off the bound profile's list and says why (`symbol_not_allowed`); the
  submit's refusal is owed with `createTradeGroup` (E34-S02 #1110). The threat model's
  `profile_forbidden` wording is a C-row for E28-X01's owner (ruled 2026-10-30).
- C-3 (AC-03): refused with `risk_limit_breached`, never clamped (D6).
- C-4 (AC-04): a wider alternate never raises a cap; a request past the bound profile's value is
  refused and audited. For the symbol lists the bound list decides the leg (a plan refusal, not an
  `override_refused` record). `require_native_sl` is no override member at all (422).
- C-5 (AC-05), fixed by **#5120**: a definition refused for its environments is recorded, one
  `trade_group_definition.save_refused` with reason `environment_mismatch` under the request's id,
  written before the `400` (C-2.9, C-2.11); unwritten, `503 audit_unavailable`.
- C-6 (AC-09): the 409 writes no record, by design (ruled 2026-10-30); the expectation is the
  code alone.
- C-7 (AC-10): a 422, not "ignored" (the model, section 10).
- C-8: a refused read outside the grants is the unaudited 404 (PF-I06), not a 403 with a record.

## 5. Deferred, by owner

- Submit halves, waiting on `createTradeGroup`, its amend and cancel being mounted (the meta check
  fails the day one is served without cells): AC-02, AC-05 and AC-10 to E34-S02 (#1110); AC-09 to
  E34-S02 (#1110) and E34-S03 (#1111); SR-E28-33 (amend and cancel) to E34-S03 (#1111).
- SR-E28-28 (lockout override and kill-switch release refuse Managers): the routes are declared
  and not mounted; the meta check fails when either is served without cells (E39).
- AC-11 (submit half), AC-12, AC-13, AC-14, AC-15 (submit half), AC-16 to AC-28 and AC-30 to AC-33,
  SR-E28-11, SR-E28-12, SR-E28-14 and SR-E28-32, and E13 AC-10, AC-11, AC-23 and AC-24: to the
  owners section 10 of the model names (E28-T03, E28-T04, E28-S05, E28-Q02, E28-Q03, E29-T04,
  E32-S04, E32-T02, E34-S01, E34-S02, E34-S03, E39), each with its row there. AC-30 is the matrix's
  viewer cell on the preview (403 `forbidden`, per P-1).
- The Postgres module leaves the preview's scope cells to the in-memory suite: the preview reads no
  table before its scope check and writes none (`test_trade_group_preview_read_only_pg.py`).

## 6. Mutation demonstrations

Each control removed in a scratch working tree, the suite run, the change reverted (never
committed):

| Control removed                                           | Suite run                                 | Result               |
| --------------------------------------------------------- | ----------------------------------------- | -------------------- |
| The profile writes' RBAC refusal (`accounts:write`)       | `tests/security/e28 -k profile`           | 24 failed, 52 passed |
| The preview's per-leg grant check and its missing-row arm | `tests/security/e28 -k "preview or ac06"` | 6 failed, 11 passed  |
| The WS topic's account narrowing                          | `tests/security/e28/test_ws_scope.py`     | 3 failed, 2 passed   |

Not demonstrated by mutation: the read routes' scoped 404, the definition writes' admission, the
CSRF guard, the native-stop validator, the widening comparator, the idempotency cache, the step-up
gate, the environment checks, the allow-list matcher and the request models' `extra="forbid"`.

## 7. Sign-off

Owed: the Security engineer's review of this report and the suite (the ticket's Definition of Done).
No new risk was found, so `docs/plan/32-risk-register.md` is unchanged.
