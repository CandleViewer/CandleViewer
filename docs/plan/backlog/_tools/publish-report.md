# GitHub Project Board Publish — Verification Report

Run date: 2026-09-24
Repo: `CandleViewer/CandleViewer` (node `R_kgDOUZDklw`)
Project: `#10` owner `basiltt` (`PVT_kwHOAzoHns4BjW_b`)

## Summary

The board (issues + Project #10) was verified against
`docs/plan/backlog/all-tickets.json` and `docs/plan/backlog/_tools/published.json`.
Two real discrepancies were found and fixed; everything else already matched.

| Check | Expected | Found | Status |
|---|---|---|---|
| Live tickets (non-`retired`) | 1,379 | 1,379 | OK |
| Total tickets (incl. `retired`) | 1,438 | 1,438 | OK |
| Retired tickets | 59 | 59 | OK |
| Issues in repo | 1,379 | 1,379 (after fix, see below) | FIXED |
| Epics | 50 | 50 | OK |
| Epic -> sub-issue links (GraphQL `subIssues.totalCount`, all 50 epics) | matches JSON `parent` counts exactly | 0 mismatches | OK |
| `blocked_by` edges, retired targets excluded | 3,182 | 3,182 linked (`blockedby_done` complete for every live ticket) | OK |
| Issues labelled `retired` | 0 | 0 | OK |
| Milestones R0-R5 | 6, matching epic/ticket rollup | R0 224, R1 274, R2 274, R3 421, R4 78, R5 108 (all open, sums to 1,379) | OK |
| Placeholder issues (#1-26, pre-planning) | closed, **off** the project | closed OK, but still attached to Project #10 | **FIXED** |
| Random 40-issue sample: title `[KEY]` prefix, labels, milestone, Kind/Phase/Sprint/Priority/Perspective/Risk/Component/Status fields, body = header table + 14 sections + Agent execution brief | all present | 7/40 missing `Sprint` (all in Sprint 19-26) | **FIXED** |
| Sprint distribution sanity (Sprint 01) | mostly `Ready` | 50 Ready / 19 Backlog of 69 | OK |

## Discrepancies found and fixed

### 1. 26 placeholder issues still on the project board
Issues #1-26 (the original pre-planning placeholder epics/tickets from the
initial commit, e.g. "Epic: Chart Engine", "Add MIT LICENSE file") were closed
correctly, but a GraphQL check
(`issue(number:N){ projectItems { nodes { project { number } } } }`)
showed all 26 were still attached to Project #10 as items.

**Fix:** removed all 26 via `deleteProjectV2Item` (GraphQL), one batched
mutation. Verified `gh project item-list 10 --owner basiltt` now returns
exactly 1,379 items (0 extra). Two unrelated stray issues (`#869`, `#1368`,
"TEST DEBUG …") were confirmed **not** on the project — left untouched (they
are outside the ticket set and not part of this backlog).

### 2. Sprint field missing options 19-26 (265 live tickets silently unset)
`docs/plan/backlog/_tools/publish_board.py`'s `SPRINT_OPTS` table, and the
live Project `Sprint` single-select field, only had options `Sprint 01`
through `Sprint 18` (+ `Backlog`, `Future`). The backlog itself schedules
work through **Sprint 26** (265 live tickets in Sprint 19-26: 87/33/29/10/54/
19/24/9 respectively). Because the option didn't exist, `sprint_key in
SPRINT_OPTS` was false for those tickets and the mutation was silently
skipped — so ~265 issues had no `Sprint` field value and weren't wired to
their `Start`/`Due` dates either.

**Fix:**
1. Added 8 new options (`Sprint 19`..`Sprint 26`) to the Project's `Sprint`
   single-select field via `updateProjectV2Field`.
2. That mutation **replaces** the options array and regenerates every
   option's id (a GitHub Projects v2 API quirk) — this orphaned the
   already-set Sprint value on **all 1,379** items, not just the new 265.
   Recovered by re-applying `Sprint` on every live ticket from
   `all-tickets.json` against the new option ids (69 batched GraphQL calls,
   0 failures).
3. Updated `SPRINT_OPTS` in `publish_board.py` (now covers 01-26) with the
   new ids and a comment explaining the id churn, so future re-runs of the
   publish script stay correct.

Post-fix: `gh project item-list` shows 0 items with an empty `Sprint` field;
distribution is Backlog 4, Sprint 01 69 ... Sprint 26 9, summing to 1,379.
Re-ran the 40-item random sample (fixed seed) — 0 discrepancies.

## Body content spot-check

5 of the 40 sampled issues had their raw body fetched via
`gh issue view --json body`: all 5 have the `| Field | Value |` header table
followed by the 14 sections (`Context`, `Scope / Deliverables`, `Out of
scope`, `Acceptance criteria`, `Technical notes / design`, `Test plan`,
`Security notes`, `Accessibility notes`, `Performance notes`, `Observability`,
`Definition of Done`, `Dependencies`, `Branch`, `References`) plus the
`## Agent execution brief` (or `## Agent guidance` for epics) section — 15
`##` headers total, matching the ticket JSON's 14 body sections + brief.

## Not in scope / pre-existing, unrelated to this verification

`python docs/plan/backlog/_tools/validate.py` reports 2 pre-existing sprint
**capacity** errors unrelated to the board publish (`OVER-CAPACITY Sprint 07`:
47 vs 45 eng-pts; `TRAIN-OVER-CAPACITY R1`: 407 vs 405 available) and 184
warnings. These are backlog-content planning concerns (estimate rebalancing),
not board-publish defects, and were left untouched — flagged here for a
follow-up planning pass rather than silently fixed as part of a mechanical
board-sync task.

## Commands used (for repro)

```bash
export PATH="$PATH:/c/Program Files/GitHub CLI"
gh api graphql -f query='...'                     # subIssues / projectItems checks
gh project item-list 10 --owner basiltt --format json --limit 1500
gh api graphql -F query=@remove_placeholders.graphql   # deleteProjectV2Item x26
gh api graphql -F query=@add_sprints.graphql           # updateProjectV2Field (Sprint 19-26)
python docs/plan/backlog/_tools/publish_board.py ...   # (SPRINT_OPTS ids updated)
```
