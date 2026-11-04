# E09-C2 Charter: RBAC boundary probing

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.
- Cross-post: Security co-review of this debrief is requested (E09-X02 / #298 owns abuse cases; not duplicated here).

## Charter
As a viewer and a grantless manager, try every admin/owner affordance by deep link, replay, role downgrade and cross-account WS subscription.

## Oracles
- O1 Any screen or route reachable that the role's permission set does not include.
- O2 Any denial that differs between "exists but forbidden" and "does not exist" for other accounts (enumeration).
- O3 Any denial with no audit row.
- O4 Any live socket keeping a topic after its grant is withdrawn.

## Areas covered (in-process evidence)
| Probe | Evidence | Result |
|---|---|---|
| Every route x five actors | `tests/contract/rbac/test_route_matrix.py` (9 tests, matrix-driven) | matrix matches app |
| Capability but non-granted account | `test_scope_and_ws.py::test_valid_capability_but_non_granted_account_is_403_nothing_mutated_and_audited` | 403, audited (O3 ok) |
| Grantless manager cannot create | `test_manager_without_any_grant_cannot_create_even_with_the_capability` | refused |
| Admin mutations owner-only and step-up gated | `test_administrative_mutations_are_owner_only`, `..._require_step_up_even_for_the_owner` | ok |
| Self-service with a target user id (IDOR) | `test_self_service_routes_reject_a_target_user_id_in_the_body` | rejected |
| WS topic x actor, non-entitled gets error not silent empty | `test_every_topic_family_x_actor_matches_the_matrix`, `test_non_entitled_role_gets_forbidden_not_a_silent_empty_subscription` | ok |
| In-flight subscription after grant withdrawn / downgrade | `test_in_flight_subscription_gets_revoked_when_the_grant_is_withdrawn`; `tests/unit/test_ws_permissions.py::test_downgrade_pushes_frame_revokes_and_refuses_orders` | revoked (O4 ok) |
| Role change over WS e2e | `tests/unit/ws/test_gateway_e2e.py::test_ws_e2e_permissions_sub_check_and_live_role_change` | ok |
| Browser deep link as viewer | `apps/web/e2e/auth/denied.spec.ts` (E09-TC-E06/E07, network-stubbed) | uniform denied page |

Run result: 404 tests passed (contract/rbac, authz abuse, ws permissions, gateway e2e, deny-by-default).

## Not probed
- Browser back/forward after a role downgrade (needs a real browser against a backend; stub-level only).
- Replaying a captured request against a live server (E2E backend lane needs the E03 ephemeral stack; see `qa/plans/e09-q02-automation-status.md`).
- Rules-manager grant isolation (SR-050 layer 2): #2094. Owner check shape in rules_actor: #2096.
- CSRF token negative test: blocked by #2090.

## Anomalies
None observed in-process. Known open items above are already tracked.

## Since run 1 (status 2026-11-04)
- #2090 (CSRF token negative test): closed by #2238 (`tests/security/auth/test_csrf_double_submit.py`).
- #2096 (owner check shape in rules_actor): closed (#2164). #2593 (owner effect re-check) closed by #5256.
- #2094 (rules-manager grant isolation): still open.

## Run 2 plan (staging, #2491) · Status: not yet run · planned 2026-11-04
- Format: session-based, 90 min (60-120 time box), human tester on staging with a browser; test accounts only; no live or demo exchange key present. Cites 03 §11.2 and §12.
- Mission: As a viewer and a grantless manager, reach an admin or owner affordance by deep link, replay, downgrade, view-as or an audit-break halt, from the browser and from raw requests.
- Areas:
  - deny-by-default matrix, replay of a captured request after a downgrade, CSRF and Origin checks
  - view-as (SCR-124) is read-only: any state change while impersonating is P0
  - the owner effect re-check (#5256) and the audit-chain-break halt with its Owner acknowledgement (#5323); #1238 open: record what is observed, do not call it a pass
  - US-ONB-005, -010; US-ADMIN-001/-002 via E09-S05; threat rows U3, U4, U14, U15, U20, U25, U30 (#1237 open), U31, U32, U35
  - does not repeat E49-C7 (`E49-charter-7-admin-rbac-probing.md`) or E10-C1 (`E10-charter-1-routing-rbac.md`); Security co-reviews, and the Security engineer and the owner `@basiltt` are notified the same day (SECURITY.md escalation chain) of any security-oracle anomaly
- Oracles (the run-1 oracles O1-O4 stay in force):
  - O2.5 a request replayed after a role downgrade still passes
  - O2.6 a view-as session changes any state (P0)
  - O2.7 an audit-chain break that leaves order entry open, or an acknowledgement a non-Owner can give
  - O2.8 an action with no audit row or no metric movement (U7, U19); observe for more than 1 s
- Keyboard-only segment (03 §12): admin invite (SCR-123) and a denied page by Tab and Enter only; the denied page offers a keyboard way back.
- Automated neighbours: `tests/contract/rbac/test_route_matrix.py`; `tests/contract/rbac/test_scope_and_ws.py`; `tests/security/auth/test_view_as_http.py`; `tests/security/auth/test_csrf_double_submit.py`; `tests/unit/audit/test_break_halt.py`; `apps/web/e2e/auth/denied.spec.ts`.
- Private routing: anomalies matching a security oracle (bypass, escalation, audit gap) go the same day through SECURITY.md's private channel (GitHub Private Vulnerability Reporting, or a direct message to the owner `@basiltt`), never a public issue; the debrief records only the private report id and a pattern-level label. Other anomalies: issue links.
- Debrief slots: tester, date, build sha, minutes spent; anomalies (the private report id for a security-oracle anomaly, an issue link otherwise); not probed; follow-ups. Filled at the #2491 run.
