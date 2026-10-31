---
description: Multi-agent protocol - ticket claiming, file ownership, interface-first, conflict protocol, and how to report blockers.
---
# Multi-agent protocol

Several AI agents work tickets in parallel. Source: `CONSTITUTION.md` §4 (C-4.6, C-4.9, C-4.15), §7, §8;
`AGENTS.md` §3, §9; `docs/plan/01-sdlc-and-branching.md` §10 (interface-first).

## 1. Claiming a ticket
1. Pick only issues in status **Ready** (DoR met, C-11.1), not labelled `retired`, `blocked` or `in-progress`,
   with no assignee. Use `/pickup <issue#>`.
2. Verify every `blocked_by` issue is closed. If not, do not start; pick another.
3. Claim atomically: assign yourself (`gh issue edit N --add-assignee @me --add-label in-progress`) and post a
   comment `Claimed by <agent-id> on branch <branch>`. If someone else claimed first (check comments after
   posting), release and pick another.
4. One agent = one ticket at a time by default; an agent bundling under C-4.6 claims each ticket of the bundle.

## 2. File ownership
- Your ticket's *Files / Scope* section is your write set. Touch nothing else (C-4.9).
- Before editing, check open PRs for overlapping paths (C-4.15): `gh pr list --state open --json files`.
- Shared hotspots need extra care and must be named in the ticket: `docs/plan/22-api-openapi.yaml`,
  `23-ws-protocol.md`, `packages/protocol`, `packages/ui/src/tokens`, `pnpm-lock.yaml`, `uv.lock`,
  Alembic `versions/`, `machine_hashes.lock`, CONSTITUTION/AGENTS. Shared-package changes follow §7.
- Generated files: regenerate, never hand-edit (C-4.16).

## 3. Interface-first
- If your ticket depends on an interface another ticket implements, land (or consume) the contract first:
  schema/type/protocol stub + a fake, merged in its own small PR. Code against the fake; swap later.
- Never block waiting; never implement another ticket's scope "to unblock yourself".

## 4. Conflict protocol
- Rebase on `main` often (`git pull --rebase origin main`). On conflict in a file you do not own: stop,
  comment on both issues/PRs, and let the owner of the earlier-merged PR's area decide.
- Two migrations racing: the later PR re-parents (C-5.3). Two machine-hash changes: later PR regenerates the lock.
- Never force-push someone else's branch; never close/edit another agent's PR; never approve or merge your own PR.

## 5. Reporting blockers and ambiguity
Post a comment on the issue with this format, add label `blocked` (or `needs-clarification`), unassign if you stop:
```
BLOCKER: <one line>
Type: dependency | ambiguity | contract-gap | env | failing-check-not-mine
Evidence: <file:line, command output, rule id>
Needed: <exact decision or artefact>
Proposed: <your recommended resolution>
```
- Do not guess on ambiguity in acceptance criteria, money/risk logic, security, or contracts — ask.
- Minor gaps (typo, obvious path) can be resolved and noted in the PR under *Deviations*.

## 6. Handoff
- On finishing: PR open with `Closes #N`, checks green, status In Review, claim label removed.
- If you must abandon: push WIP branch, comment what is done / left / next step, unassign.
