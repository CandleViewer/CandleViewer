# E04-X02 — Security review: logging, metrics and diagnostics

Status: **abuse cases executed in-process (22 PASS, 0 FAIL); staging re-run of 1/2/7 pending `deploy-staging`** (no staging
environment exists yet at this point of Sprint 01; the cases are scripted below so they can
be run and recorded by the security reviewer once `deploy-staging` is live).
Threats verified: K1, U5, D3, asset A-17 (`docs/plan/04-security-program.md`).

## 1. Automated controls delivered in this PR
| Control | Where | Proof |
|---|---|---|
| Ban direct `logging.getLogger()` (SR-121) | `.semgrep/cv-obs-no-direct-getlogger.yml` | fixture + repo scan; 9 legacy sites carry `nosemgrep` (follow-up #1720) |
| Ban `print()` | `.semgrep/cv-obs-no-print.yml` | fixture |
| Ban `prometheus_client` outside `observability/` | `.semgrep/cv-obs-no-prometheus-import.yml` | fixture |
| Secret-named variable in f-string/%-log | `.semgrep/cv-obs-log-secret-fstring.yml` | fixture |
| Metric label allow-list | `.semgrep/cv-obs-metric-label-allowlist.yml` | fixture |
| Bare `create_task` ban outside `cv.obs` | `.semgrep/cv-bare-create-task.yml` (E04-T02, scope: `observability/**` exempt) | repo scan = 0 findings; 2 sites carry `nosemgrep` -> #1720 |
| Permissions / log-artefact / webhook-secret / gitleaks-infra checks | `infra/scripts/obs_security_checks.py` | pytest |
| Scheduled ZAP baseline | `.github/workflows/dast-observability-weekly.yml` | not run locally: no docker |

gitleaks: `.gitleaks.toml` extends the default ruleset and does not allowlist `infra/**`;
asserted by `obs_security_checks.py`. The deliberate-commit test must be run in CI on a
scratch branch (gitleaks binary not installed locally).

## 2. Abuse cases (E04-X01 list) — execution record
| # | Case | Expected | Result |
|---|---|---|---|
| 1 | Manager/Viewer -> `/admin/health` detail, `/admin/incidents`, support bundle, log-level override | 403 + audit row | PENDING staging |
| 2 | `/metrics`, Grafana, Prometheus, Alertmanager from outside private network | refused | PENDING staging |
| 3 | Log injection via `X-Correlation-Id`, symbol param, telemetry field | structure intact, no forged id | PENDING staging (unit coverage: `test_correlation.py`) |
| 4 | Secret smuggled into support bundle via config/log/exception | generation fails | PENDING staging (unit coverage: `test_support_bundle.py`) |
| 5 | Cardinality explosion via `screen` / symbol | guard holds before memory grows | PENDING staging (unit: `test_metrics_facade.py`) |
| 6 | Log flood via level override | TTL, scope, disk guard hold | PENDING staging (unit: `test_log_level_override.py`) |
| 7 | Inspect real Page alert payload | no ids/keys | PENDING (drill: `infra/alertmanager/alert_drill.py`) |

Per the acceptance criteria, any failing case is filed as a Bug at p0/p1 and linked here.
No failures have been observed so far; none are claimed as passing against staging.

## 3. ZAP triage (R0 gate)
Zero Critical/High unresolved; Medium requires a dated entry in `security/accepted-risks.yaml`.
First scheduled run pending.

## 4. Sign-off
Security-engineer sign-off comments on E04 and its `security` children are to be posted after
section 2 is executed on staging.

## 5. Execution evidence added in review round 2
- Cases 3-6 re-executed at unit level against the real code on this branch (not staging):
  `test_correlation.py`, `test_support_bundle.py`, `test_metrics_facade.py`,
  `test_log_level_override.py` -> 95 passed.
- SR-127: `cv-shell-dangerously-set-inner-html` scope widened to `apps/web/src/features/**`,
  `apps/web/src/lib/**`, `packages/ui/src/**`; scan of `apps packages` = 0 findings. No health-chrome
  component exists yet; any later one under these paths is covered automatically.
- Permissions (SR-124): bundle dir 0700 / archive 0600 asserted in `test_support_bundle.py`;
  `check_modes` tested (POSIX). CI artefact exclusion covered by `check_workflows_no_log_artifacts`.
- gitleaks deliberate-commit test added (`test_gitleaks_catches_deliberate_infra_secret`); runs where
  the binary exists (skipped locally: not installed).
- **Still open (cannot be done without a staging env / docker / owner):** cases 1, 2, 7 and the
  first ZAP run. These need owner waiver or deferral to the first `deploy-staging`; no result is claimed.

## 6. Execution evidence added in review round 3
- Case 1 executed through the real FastAPI router (not staging): `test_admin_health_rbac` asserts
  401 unauthenticated, 403 for a principal without `admin:read` with no component detail in the body.
  Staging re-run (incident list, support bundle, log-level override) remains for `deploy-staging`.
  (E42-T05: `test_admin_health_rbac` is now `tests/contract/test_admin_ops_routes_contract.py::test_rbac_cell`.)
- Case 7 / AC5 executed offline: `test_page_alert_payload_carries_no_ids_or_key_material` asserts the
  Page template interpolates only alertname/component/env/severity/summary/runbook_url, the rendered
  fixture holds no id or key material, and no alert rule interpolates labels outside that allow-list.
  Result: PASS. No p0/p1 Bug filed (no failure observed).
- AC3 executed: `test_webhook_secret_committed_to_alertmanager_config_is_caught` commits a deliberate
  token into an Alertmanager config and the check fails (PASS). The gitleaks-binary variant runs in CI.
- `obs_security_checks.py` is now a step in `deploy-staging.yml` (log dirs via `LOG_DIRS` for the
  0700/0600 check and webhook/secret-injection checks).
- ZAP (AC4): no target exists, so no run and no findings; nothing is triaged or accepted-risk-listed
  (no entry is fabricated). **Owner waiver requested on the PR/#258** for cases 2 and the first ZAP
  run, deferred to first `deploy-staging`.
- The 9 `getLogger` nosemgrep suppressions now each carry a reason comment referencing #1720
  (the 2 `create_task` ones already did).

## 7. Abuse-case execution record (review round 4, in-process `create_app()` + fakes)
Run: `pytest tests/security -m "not integration"` -> all PASS, 0 FAIL. No P0/P1 bug filed (none observed).
| # | Case | Test id (`services/api/tests/security/test_e04_abuse_cases.py::`) | Result |
|---|---|---|---|
| 1 | unauth + Manager -> `/admin/health`, `/admin/support-bundle`, `/admin/log-level` | `test_case1_unauthenticated_and_manager_denied[*]` | PASS (401/403, or 501 fail-closed; no detail leaked) |
| 2 | `/metrics` exposure | `test_case2_metrics_bind_refuses_public_interfaces`, `test_case2_metrics_body_has_no_secret_or_id_material` | PASS (bind refuses 0.0.0.0/public/hostname; no secret/id in body). Network-level refusal from outside the tailnet = staging only |
| 3 | log injection (CRLF/ANSI/oversize correlation id, logged fields) | `test_case3_*` | PASS (id re-minted; one JSON line per record) |
| 3b | secret shapes in body/header/query -> logs + `/metrics` | `test_case3b_secrets_in_body_header_query_never_logged_or_metered` | PASS |
| 4 | secret in any support-bundle channel | `test_case4_secret_in_any_bundle_channel_fails_generation[*]` | PASS (fails closed, no archive) |
| 5 | cardinality bomb / disallowed labels | `test_case5_*` | PASS (series capped, breach flagged, `screen` pattern-bound) |
| 6 | telemetry unauth / oversized | `test_case6_*` | PASS (401; 400 `payload_too_large`, counted) |
Support-bundle `system_events` channel covered by case 4. Log-level flood (old case 6): `test_log_level_override.py` (unit).
Cases needing the live stack (outside-network refusal for Grafana/Prometheus/Alertmanager, incident list) remain for `deploy-staging`.

## 8. AC5 — alert payload inspection (executed)
Finding: `cv.tmpl` interpolated labels/annotations **unredacted**. Fixed at the template: every field is piped
through `reReplaceAll` (JWT, `secret|token|password|api_key|signature=` pairs, 18+ char key-shaped tokens).
Tests (`services/api/tests/security/test_e04_alert_payload.py`): redaction rules applied to a poisoned page alert
(PASS); every interpolation is redacted (PASS); `amtool template render` of the poisoned alert
(`@pytest.mark.integration`, needs docker -> run by the CI `amtool` step; result to be recorded after the CI run).

## Evidence status and follow-ups (review round 2)

- AC1 (abuse cases): cases 1-7 executed in-process (`test_e04_abuse_cases.py`, `test_e04_alert_payload.py`); staging re-run
  of 1/2/7 needs a deployed staging stack (no docker/staging in the authoring environment). No p0/p1 Bugs were found, so none filed.
  Owner exception for the staging re-run is requested on #258; ticket must not move to Done until it is recorded.
- AC3 (gitleaks on infra/): `obs_security_checks.py` verifies no allowlist entry covers `infra/`; the live gitleaks fail-on-token
  demonstration runs in the CI `secrets` check (gitleaks is not installed locally). Not demonstrated locally.
- AC4 (ZAP baseline): `dast-observability-weekly.yml` first run pending; findings triage to follow the first run.
- AC5: payload inspected via template unit tests; a live Page capture needs the staging drill.
- 9 `nosemgrep` suppressions: tracked in #1720.

## 9. Review round 5 — honest status, deviations, follow-ups
**Not met in the authoring environment (no docker, no staging, no ZAP target); no result is claimed:**
- AC1: abuse cases 1-7 are executed in-process through the real `create_app()` wiring (section 7) and PASS. Staging re-runs
  (outside-network refusal for `/metrics`/Grafana/Prometheus/Alertmanager, incident list, support bundle, log-level override)
  are deferred to the first `deploy-staging`. No p0/p1 Bug was filed because none was observed. **Owner exception requested on #258**;
  ticket must stay out of Done until the staging record is appended here.
- AC3: gitleaks fail-on-token test (`test_gitleaks_catches_deliberate_infra_secret`) runs in CI where the binary exists; the
  `security / gitleaks` job is green on this PR (no leak in infra/). A dedicated failing-run link is not available because
  pushing a deliberate secret to a shared branch is not done; the test creates it in a temp repo instead.
- AC4: ZAP baseline not run (no target, no docker). No triage and no accepted-risk entry were fabricated. First scheduled run of
  `dast-observability-weekly.yml` after `deploy-staging` produces the triage.
- AC5: template redaction + offline render asserted; live Page capture needs the staging drill.

**Deviations (PR body):**
- `.semgrep/cv-bare-create-task.yml` exclude widened from `observability/context.py` to `**/observability/**`; the ticket bans bare
  `create_task` only outside `cv.obs`, so the whole package is the sanctioned location.
- `nosemgrep` on 9 legacy `getLogger` sites + 2 `create_task` sites are tracked by #1716 (migration) and #1720 (removal).
