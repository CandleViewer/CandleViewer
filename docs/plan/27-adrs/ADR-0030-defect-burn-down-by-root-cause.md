# ADR-0030: Defect burn-down by root cause

- Status: Accepted (ratified 2026-10-29 by main-orchestrator under the owner's delegation, #2701 ledger 2 (comment 6493096777), row 39; the owner may revoke there)
- Date: 2026-10-05
- Ticket: E49-K01 (#1334); evidence: `docs/plan/backlog/artifacts/e49-root-cause-clusters.md`
- Related: ADR-0017 (board DoD gates), `docs/plan/02-definition-of-ready-done.md` §5.2, §6.2

## Context

E49 plans three burn-down waves and assumed a 22-month accumulated backlog. The 2026-10-05 snapshot (main @ 6596bcd)
shows 76 `type/bug` issues (27 open, 49 closed); excluding 7 planning issues, **21 open and 48 closed defects**, none P0,
oldest about 10 days. 59 merged `fix(...)` commits were used as recurrence evidence. Reproduction of two members per cluster
was not performed; shared causes are hypothesised from issue bodies and fix commits.

## Decision

Eight groups were found (7 clusters plus 1 singleton); 20 of 21 open defects (95%) are clustered.

| Cluster               | Open / closed | Decision                                                                                  |
| --------------------- | ------------- | ----------------------------------------------------------------------------------------- |
| `dod-evidence-gap`    | 5 / 9         | **Root fix** (process: Done-gate script, #1859) plus patch the 5 open items individually  |
| `gate-tooling`        | 4 / 0         | **Patch individually** (four unrelated tools)                                             |
| `flaky-tests`         | 3 / 1         | **Root fix** (shared hypothesis profile, cold-cache job, #1855)                           |
| `storage-writer`      | 3 / 5         | **Root fix** with named backpressure guard test (#1856); safety-adjacent, security review |
| `supply-chain-pins`   | 3 / 0         | **Root fix** in one `security-review` PR (#1857)                                          |
| `statechart-contract` | 2 / 1         | **Patch individually** (below the 3-member threshold)                                     |
| `unwired-component`   | 0 / 13        | **Accept the closed fixes; add the guard test** at `create_app()`/`main.tsx` (#1858)      |
| singleton (#1822)     | 1 / 19        | **Patch individually**; post-GA acceptable                                                |

### Defer, need more data

The ticket's hypothesised families below have no open or closed bug evidence at this snapshot, because the feature areas
have mostly not shipped. Decision: **defer; re-run `tools/triage/cluster_report.py` at S23 start and when E49-S04/S05 land.**
Follow-up: a re-clustering task at S23 planning.

- design-token drift; missing/ad-hoc empty-loading-error states
- number/time/locale formatting
- keymap conflicts and context leakage (one closed fix, E49-S07)
- RBAC copy and disclosure leakage in 403/404 paths
- chart-engine correctness at extreme zoom/density
- WS reconnect and gap-fill edge cases; replay determinism
- Electron-vs-browser shell divergence
- OMS/rule-runtime race conditions (only the writer deadlock #1835 and statechart contract defects seen)

## Consequences

Waves are sized small (about 8 points each). A root fix touching a trading-safety path needs a named guard test and a
Security-engineer pass (feeds E49-X01). Any root fix needs the change to stay within the 400 LOC rule, split if not.
