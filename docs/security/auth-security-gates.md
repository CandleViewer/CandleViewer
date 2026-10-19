# Auth security gates (E09-X03)

Owner: Security. Threat model: `docs/security/threat-models/e09-auth-rbac.md` (E09-X01).

## What runs

| Gate                                                  | Where                                                                  | Blocks on                                                                                                                   |
| ----------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Auth Semgrep pack (`security/semgrep/auth/`, 9 rules) | CI step `security-auth` (job `read-only-scans` in `_job-security.yml`) | any finding on the auth surface                                                                                             |
| Rule fixtures (`security/semgrep/auth/fixtures/`)     | `tools/ci/check_auth_semgrep.py`                                       | a rule with no positive or no negative fixture; a rule not firing/over-firing on its fixtures                               |
| Suppression policy                                    | same script                                                            | `nosem`/`nosec`/`noqa: S…` in auth/accounts/secrets/api without `reason= owner= review=YYYY-MM-DD`, or past its review date |
| gitleaks token shapes                                 | `.gitleaks.toml` (`cv-*` rules), `.husky/pre-commit`, CI `gitleaks`    | session/refresh/invite token, recovery code, TOTP secret                                                                    |
| ZAP authenticated scan                                | `.github/workflows/dast-auth-zap.yml`, `security/zap/`                 | high alerts; any loss of the logged-in indicator                                                                            |
| SCA                                                   | `dependabot.yml` (pip/npm), CI `pip-audit` / `npm-audit` + alert gate  | high/critical advisories (argon2-cffi, TOTP, starlette cookie/session)                                                      |
| Bandit                                                | CI `bandit` (`[tool.bandit]`, no rule skipped)                         | medium+ — B105/B106/B311 stay active for token/recovery-code generation (CSPRNG only, SR-012/SR-022)                        |

## Rule → SR map

`no-raw-account-id` SR-051 · `no-adhoc-authz` SR-017 · `no-target-user-on-self-service` SR-026 ·
`stepup-required` SR-025 · `no-secret-logging` SR-122 · `no-jwt-in-browser-storage` SR-012 ·
`cookie-flags` (+`-domain`) SR-012 · `argon2-params` SR-011 · `audit-write-required` SR-112.
Each finding message names its SR id.

## Allowlists

`no-adhoc-authz` and `no-secret-logging` carry path excludes inside the rule files (the `has_permission`
wildcard implementations; replay/recording `session_id`). Both files are Security-owned: widening an
exclude needs Security review (CODEOWNERS).
`audit-write-required` allow-lists whole files whose audit is emitted below the handler (`api/rules.py`,
`api/rules_crud.py`, `api/step_up.py`) or that are not audited actions (`api/telemetry.py`), plus an exact-route
`pattern-not` list for the drawings and workspaces writes (not C-2.9 by #357 item 11 and #402 D20; foreign-id denials
audited as `rbac.denied` where recorded). A new route in those routers is still flagged. The rule cannot see new
behaviour inside an approved handler: revisit when E40 exposes `drawings.alert_id` and the 3.8.5 hotkey routes land.

## Suppressions

Format: `# nosem: <rule> reason=<why> owner=@team review=2026-12-31`. Undated/unowned = job failure.

## Triage of an accepted risk

1. Prefer fixing in the owning ticket. 2. A true false positive: fix the rule or add an in-file
   suppression in the format above. 3. Otherwise a dated entry in `security/accepted-risks.yaml`
   (never for gitleaks). High/critical never merge without one.

## ZAP

Credentials are CI secrets `ZAP_FIXTURE_USER`, `ZAP_FIXTURE_PASSWORD`, `ZAP_FIXTURE_TOTP_SECRET`
(test-only, never committed). `login-totp.js` does password + TOTP and ZAP re-runs it when the
logged-in indicator (`/v1/auth/me` returns `"principal"`) disappears after session rotation (SR-013).
The plan asserts `/v1/auth/me` is 200 before and after the active scan; otherwise the scan fails.
Baseline on each PR; full active scan weekly (Mon 03:17 UTC) and via `workflow_dispatch` at release gates.
Reports are private artefacts (14-day retention); never attach them to issues.

## Status notes

Git-history gitleaks scan and ZAP end-to-end run need docker/gitleaks and CI secrets and were not run locally.
The rules were measured against the repo: 0 findings after the documented allowlist and two
dated suppressions (`api/auth.py` 501 stubs with no mutation, review 2026-12-31).
