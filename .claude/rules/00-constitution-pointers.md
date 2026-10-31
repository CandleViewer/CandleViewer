---
description: Authority order and where each rule lives; read before any work in this repo.
---
# Constitution pointers

**Authority order:** `CONSTITUTION.md` > `AGENTS.md` > `docs/plan/*` > these `.claude/rules/*` > anything else.
These rule files are *summaries and pointers*. If one ever disagrees with the Constitution, the
Constitution wins and this file is a bug — fix it in the same PR (C-16.5: never duplicate an owned list;
link to it instead).

## Read order for a new agent session
1. `CONSTITUTION.md` (Appendix A = rule index for agents)
2. `AGENTS.md` §0–§3 (repo map, how to pick up a ticket), §4 (the ONLY command list), §8 (never-do list)
3. `docs/plan/02-definition-of-ready-done.md` (DoR/DoD — C-11.1 / C-11.2)
4. The ticket itself (GitHub issue, mirrored in `docs/plan/backlog/E*.json`)
5. Topic docs named in the ticket's *References* section

## Where things live (single source of truth)
| Topic | Owner file |
|---|---|
| Rules, CI gates (§9), budgets (§14) | `CONSTITUTION.md` |
| Commands | `AGENTS.md` §4 |
| Branching / SDLC | `docs/plan/01-sdlc-and-branching.md` |
| DoR / DoD | `docs/plan/02-definition-of-ready-done.md` |
| Testing | `docs/plan/03-testing-strategy.md` |
| Security | `docs/plan/04-security-program.md`, `SECURITY.md` |
| Architecture / modules | `docs/plan/20-architecture.md`, CONSTITUTION §3 |
| DB schema | `docs/plan/21-database-schema.md` |
| REST contract | `docs/plan/22-api-openapi.yaml` |
| WS protocol | `docs/plan/23-ws-protocol.md` |
| Chart engine | `docs/plan/26-chart-engine-design.md` |
| ADRs | `docs/plan/27-adrs/` |
| Statecharts | `docs/plan/28-statechart-catalogue.md`, `29-statechart-adoption-plan.md`, ADR-0016 |
| Backlog | `docs/plan/backlog/` (`all-tickets.json`, validator `_tools/validate.py`) |

## Citing rules
- Cite rules by stable ID (`C-4.7`). Verify the ID exists verbatim in `CONSTITUTION.md` first — the
  `pr-metadata` CI check fails on dangling references (C-16.4).
- Tickets labelled `retired` are not work items. Never pick them up; follow the replacement named in the body.

## Non-negotiables (summary; details in the Constitution)
- One issue ⇄ one branch ⇄ one PR by default; bundles only under an owner delivery-speed directive, each ticket with its own acceptance table and QA record; `Closes #N` in the PR (C-4.6, C-4.7).
- No flag may gate a safety invariant; native SL is always placed (C-2.6, C-4.14).
- Never edit an applied migration (C-5.4). One migration per PR (C-5.3).
- Secrets are only touched in `services/api/secrets/` (C-3.2).
- No withdrawal endpoint, ever. No live-exchange network calls in tests.
- If a ticket is ambiguous, stop and report (see `70-multi-agent.md`); do not guess scope.
