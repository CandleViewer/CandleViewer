# E04-C3 Charter: leak hunt (output surfaces)

- Ticket: E04-Q02 (#257) · Format: session-based test management · Date: 2026-10-31
- Plan: `docs/qa/test-plans/e04-observability-charters.md` (base, rulings, regression pack, blind-spot report, sign-off draft).
- Tester: AI agent. The "Security engineer" seat is the security-reviewer lens on these notes (BQ-03, pending ruling). **Deviation (honest scope):** an agent ran the static and in-process work. It is not a human session, and the lens has not run yet. No stack ran, so no real log stream, alert payload, bundle or dashboard was read.
- Canary values only (`CANARY-SECRET-` prefix, as E04-Q01). No real credential was used, read or printed. No network (C-13.5).
- **If a real secret is found on any surface, it is reported privately under `SECURITY.md` (C-12.13), never as a public issue.** The exposure-window assessment goes in that private report (BQ-03, pending ruling). None was found.

## Charter

Explore every output surface (logs, metric labels, health details, alert payloads, support bundle, dashboard panels) for secret or PII exposure.

Time box: 3 h (the ticket's). Actual: see "Session metrics" (BQ-15, pending ruling).

## Oracles (defined before probing)

- O1 A canary reaches the surface's output.
- O2 A surface carries a free-text field that a producer could fill with a secret, with no filter in between.
- O3 A label or field carries an identifier (account, key, user, order) where the contract forbids it.

## Surfaces

| Surface          | Attempted                   | Result                                                                                                                                                                                                                                                                                                                                                                                                           | Evidence                                                                                                                                                                                                                                                   |
| ---------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Logs             | in-process                  | **Cleared statically.** Canaries pushed through four logging paths, validation errors, exception text and request bodies, headers and queries never reach output.                                                                                                                                                                                                                                                | `services/api/tests/qa/test_e04_q01_blackbox.py`:169 `g01`; `services/api/tests/unit/observability/test_secret_escape_paths.py`:54–99 (8 tests); `test_exception_text_redaction.py` (461 cases); `services/api/tests/security/test_e04_abuse_cases.py`:177 |
| Metric labels    | in-process                  | **Cleared statically.** The `/metrics` body holds no secret or id material. Disallowed label names are refused. Series are capped. WS series carry closed labels only.                                                                                                                                                                                                                                           | `test_e04_abuse_cases.py`:128, :238, :250; `services/api/tests/unit/observability/test_ws_label_cardinality.py`:65; `test_metrics_facade.py`:98, :114, :128; `test_e04_q01_blackbox.py`:144 `t04`                                                          |
| Health details   | in-process plus a code read | **Cleared statically, one residual.** The unauthenticated probes leak nothing (`h04`, `h06`). A probe exception becomes `probe error: <type name>`, never its text (`services/api/candleviewer/observability/health_probes.py`:225–226). Every detail string in `services/api/candleviewer/health_wiring.py` is a fixed phrase, a count or a reason token. Residual: `detail` is free text with no length bound. | `test_e04_q01_blackbox.py`:77, :83; `docs/design/E04/E04-D02.md`:1912 (§11.4, CMP-178 row)                                                                                                                                                                 |
| Alert payloads   | static; the CI render check | **Cleared statically.** The template pipes every label and annotation through redaction patterns (`infra/alertmanager/templates/cv.tmpl`:1–13). Rule annotations interpolate only closed labels (`symbol`, `stream`, `reason`, `class`, `topic`, `scope`, `endpoint_class`, `env`). CI renders a grouped page and checks its fields.                                                                             | `infra/alertmanager/alertmanager.yml`:1–8; `.github/workflows/_job-py.yml`:125–130                                                                                                                                                                         |
| Support bundle   | in-process                  | **Cleared statically.** A secret in any bundle channel fails the generation. The scan survives escaped line breaks.                                                                                                                                                                                                                                                                                              | `test_e04_abuse_cases.py`:227; `test_support_bundle.py` (28 tests); `test_bundle_scan_escaped_break.py` (122 cases)                                                                                                                                        |
| Dashboard panels | static                      | **Cleared statically.** Panel legends use only closed labels, the build labels `commit` and `version`, and `rule_id`, an internal rule id. No legend names a key, account, user or address. Snapshot export strips the models. A live Grafana render is blocked.                                                                                                                                                 | `infra/grafana/dashboards/*.json` (a read of every `legendFormat`); `infra/grafana/tests/test_dashboards.py`:74                                                                                                                                            |

## Session metrics

- Time: about 12 minutes of agent tool time, 05:28–05:40 UTC, shared with charters 1 and 2. Times are from the agent's tool log. Not a 3 h joint session.
- Suites re-run at 05:34, in the one run shared by the three charters: 738 passed, 5 deselected.
- Static reads: the alert template, every alert annotation's `$labels` use, every dashboard `legendFormat`, the detail strings in `health_wiring.py`.

## Findings

None. Six of six surfaces are cleared statically. Absence of a finding is not evidence of absence: the live surfaces were not read.

## Residuals (no issue; rows in the plan)

- `HealthReport.components[].detail` is unbounded free text. E04-D02 §11.4 already records the contract the CMP-178 build must meet: plain text, no key id, no node name, bounded length.
- A live read of each surface on a running stack: a real log stream, a real `/metrics` scrape, a delivered alert, a generated bundle, a rendered dashboard. Blocked on the PRR staging re-run (BQ-01).

## Handover to E04-X02

E04-X02 (#258) closed on 2026-10-04. Its follow-up #1720 (remove nine `nosemgrep` suppressions) is open. The proposed handover is one comment on #258 with the per-surface table above, cross-linked on #1720 (BQ-03, pending ruling). It is drafted in the plan's sign-off section and **not posted**.
