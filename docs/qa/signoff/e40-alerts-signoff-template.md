# E40 alerts: QA sign-off comment template

Post one comment on #1203 when every slot below is filled. A slot with no evidence says "not run" and why; nothing is marked passed that was not run. The session sheets are the fields in the E40 charters (docs/qa/charters, PR 5731): attach each filled sheet, do not copy its fields here.

## Summary

| Area                        | State on `<date>`     | Evidence  |
| --------------------------- | --------------------- | --------- |
| Scripted regression (pack)  | `<result>`            | `<link>`  |
| Exploratory charters 1 to 5 | `<result>`            | `<link>`  |
| Chaos scenarios 1 to 6      | `<result>`            | `<link>`  |
| Load and storm baseline     | `<result>`            | `<link>`  |
| Accessibility               | `<result>`            | `<link>`  |
| Open defects                | `<count by severity>` | `<links>` |
| **Proposed verdict**        | `<verdict>`           | Decision  |

## Header

- Ticket: #1203 (E40-Q02). Base `main` at: `<full sha>`. Run by: `<agent or person>`, date `<UTC>`.
- Pack run: `cd services/api && HYPOTHESIS_PROFILE=ci uv run pytest -p no:randomly --no-cov -m e40_regression` (qa/plans/e40-regression-pack.md). Result: `<passed / failed / xfailed / deselected>`.

## Per-story verdicts

| Story       | Verdict (pass / fail / not run) | Evidence link | Notes |
| ----------- | ------------------------------- | ------------- | ----- |
| US-ALRT-001 |                                 |               |       |
| US-ALRT-002 |                                 |               |       |
| US-ALRT-003 |                                 |               |       |
| US-ALRT-004 |                                 |               |       |
| US-ALRT-005 |                                 |               |       |
| US-ALRT-006 |                                 |               |       |

US-ALRT-007 (alert-to-action automation, Could) and US-ALRT-008 (webhook delivery, Could) are out of scope for this sign-off: both are Could stories, and the webhook channel is flagged off and descoped to R5.

## Scripted results

One row per run: who ran it, base `<full sha>`, command, result, wall time. An author run is labelled as one.

## Evidence slots

- Regression pack run (above): `<link>`
- Load and storm baseline (`docs/qa/perf/e40-alerts-baseline.md`): `<link>`
- Chaos scenarios 1 to 6: `<link>`
- 24 h soak report: `<link or not run>`
- Accessibility audit and the owner-run NVDA, VoiceOver and Electron passes: `<links>`
- Exploratory session sheets, charters 1 to 5: `<links>`; run by an AI agent where the DoD allows, deviation stated in each sheet.
- Defects found: `<issue links, severity>`; any open P0 or P1 blocks sign-off.

## Explicit deviations

- Webhook channel: flagged off and descoped to R5; untested by design.
- `<each other deviation: what, why, who approved>`

## Not tested

- `<what was not run, and why>`

## Residual risk

- `<risk, likelihood, impact, owner, ticket>`

## Conditions

| Id  | Condition     | Ticket |
| --- | ------------- | ------ |
| C1  | `<condition>` | `#<n>` |

## Decision

- Recommend: `<sign off / sign off with conditions / do not sign off>`. Conditions: `<list>`.
- Done is set by QA, not by the author (C-10.4).

## Proposed QA comment (for the owner to post or amend)

> QA verdict for E40 (proposed by `<agent or person>`): `<verdict>` as of `<UTC>`. Evidence: `<link to the filled sheet>`. Open conditions: `<ids>`.
>
> QA sign-off: `<pass|fail>`

The marker line `QA sign-off: pass` or `QA sign-off: fail` is what `scripts/gh/guard_qa_signoff.py` matches; leave it as a placeholder until the verdict is decided, and post it only with a real result.
