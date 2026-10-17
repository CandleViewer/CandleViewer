# E35 abuse-case suite, SAST rules and DAST plan (E35-X02)

Continuous-enforcement half of the E35 security posture (analysis: E35-X01, review: E35-X03).
Threat model: [`../threat-models/e35-rule-engine.md`](../threat-models/e35-rule-engine.md).

## Semgrep rules (`.semgrep/`, fixtures in `.semgrep/tests/`, run by `tools/ci/check_semgrep_rule_tests.py`)

| Rule                                       | Enforces                                                                                                                                    |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `cv-rules-no-dynamic-eval`                 | ADR-0007 R1: no `eval/exec/compile/__import__/pickle.load(s)` in `rules/`                                                                   |
| `cv-rules-no-exchange-import`              | rule engine never imports `candleviewer.exchange*`; actions go via OMS                                                                      |
| `cv-rules-no-sensitive-log`                | no `input_snapshot`/balance/equity args to log calls at INFO or below                                                                       |
| `cv-rules-no-order-payload`                | no exchange order payload dict literals (`orderType`, `orderLinkId`, `stopLoss`, `reduceOnly`) so the OMS native-SL path cannot be bypassed |
| `cv-rules-no-scope-check-outside-resolver` | heuristic: no ad-hoc `in/not in ...granted_accounts` in evaluator/runner/service; use `ScopeResolver`                                       |

Each ships a positive (`# ruleid:`) and negative (`# ok:`) fixture, and is verified to be clean on the current tree.

## Abuse-case suite (`services/api/tests/rules/abuse/`, ordinary pytest, merge-queue suite)

| Case                                                                     | Test          | Status                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------ | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| a ungranted account                                                      | `test_ac_a_*` | enforced (403 + `rule_scope_denied` audit, no state change)                                                                                                                                                                |
| b no simulation on current hash                                          | `test_ac_b_*` | enforced (422 `simulation_required`, `rule.mode_refused` audit)                                                                                                                                                            |
| c open safety warning                                                    | `test_ac_c_*` | enforced (422 `safety_warning_open`)                                                                                                                                                                                       |
| d live without perm / fresh step-up                                      | `test_ac_d_*` | enforced (403 `permission_required` / `step_up_required`)                                                                                                                                                                  |
| e loosen stop without `rules.loosen_stop`                                | `test_ac_e_*` | enforced at save (422)                                                                                                                                                                                                     |
| f `all_accounts` without widest grant                                    | `test_ac_f_*` | enforced (403 for non-Owner on create/update/activate; Owner 201)                                                                                                                                                          |
| g act after post-arming revocation                                       | `test_ac_g_*` | enforced (action denied, `rule_action_scope_denied`/`grant_revoked`)                                                                                                                                                       |
| h kill-switch / frozen author                                            | `test_ac_h_*` | enforced (denied + audit `manager_frozen`)                                                                                                                                                                                 |
| i disable/edit/delete `sys.native_sl_watchdog` / `sys.clock_drift_block` | `test_ac_i_*` | enforced (403 `system_rule_protected` via API and manager, `rule.system_rule_refused` audit; `sys.` namespace reserved; direct-DB tamper detected by `verify_system_rules` -> `rule.system_rule_tampered`)                 |
| j export leaks no account id / armed state                               | `test_ac_j_*` | enforced at manager level (`export_rule` strips ids, forces disabled/demo)                                                                                                                                                 |
| k import lands disabled, no remap                                        | `test_ac_k_*` | enforced at manager level (`import_rule`)                                                                                                                                                                                  |
| l schema bounds + expensive IR                                           | `test_ac_l_*` | enforced (bounds 422; timeout aborts; auto-disable)                                                                                                                                                                        |
| m signal loop                                                            | `test_ac_m_*` | enforced at save (`feedback_loop`); runtime chain-depth limit not built                                                                                                                                                    |
| n read another user's rules                                              | `test_ac_n_*` | enforced (404, no existence leak, no mutation)                                                                                                                                                                             |
| o raise a rule's action budget above its default (04 §7.2.2 row 26)      | `test_ac_o_*` | enforced at save and activation (403 `forbidden` + `rule.scope_refused` audit for a non-Owner, no state change; 422 `rule_ir_invalid` above the hard cap for every role); the arming re-check is the second slice of #3232 |

`test_rbac_matrix.py` asserts every `/rules*` write/read operation x role (anonymous, no perms, reader, writer).

## Findings (triage)

| ID                                                                                  | Severity | Disposition                                                                                                                                                                 |
| ----------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| X02-F1 `targets: all_accounts` had no widest-grant check                            | High     | **fixed in this PR** (`_require_grants`), test f                                                                                                                            |
| X02-F2 `sys.native_sl_watchdog` / `sys.clock_drift_block` absent                    | High     | **fixed in this PR**: protected-name guard + tamper detector (`manager.py`); the always-on provisioning of the rules themselves stays with the system-rule ticket (E35-S08) |
| X02-F3 export/import HTTP endpoints not built                                       | Medium   | manager-level hygiene implemented and tested; routes deferred to E35-S06                                                                                                    |
| X02-F4 runtime emit_signal chain-depth limit absent (only save-time loop rejection) | Medium   | deferred (dated follow-up: E35-S08)                                                                                                                                         |
| X02-F5 submit-to-ack p95 <= 300 ms under a pathological rule                        | Medium   | **not run locally (no docker)**; unit-level bound proven by test l (timeout + auto-disable). Needs owner-approved exception or E35-Q04 harness; requested on #1051          |

## DAST

`.zap/rules-low-priv.yaml`: OpenAPI-driven active scan of `/rules*` with a low-privilege (`rules:read`) bearer
token taken from `ZAP_LOWPRIV_TOKEN`. Any response returning data outside the session's grants is a High finding.
Not run locally (no ZAP/docker). Wired as `.github/workflows/dast-rules-nightly.yml` (nightly + manual; needs the `ZAP_LOWPRIV_TOKEN` secret). First nightly result is the evidence.
