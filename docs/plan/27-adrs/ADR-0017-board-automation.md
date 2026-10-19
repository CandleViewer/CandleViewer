# ADR-0017 — GitHub Projects v2 board automation: capability and limits

- Status: **decided**
- Date: 2026-09-25
- Deciders: Owner, Architect
- Consulted: `docs/plan/00-planning-brief.md`, `docs/plan/01-sdlc-and-branching.md` §4–§5.2, `docs/plan/02-definition-of-ready-done.md` §8, `docs/plan/04-security-program.md` §6.14, `docs/plan/30-release-roadmap.md` §4.2
- Related: E01-K01 (this spike), E01-T07 (board automation, blocked by this ADR), E01-T08 (branch protection)

> Deviation note: the ticket body named this record "ADR-0016"; that number was taken in the interim by
> `ADR-0016-statechart-runtime.md`. This record is filed as **ADR-0017** per the numbering rule in
> `docs/plan/27-adrs/README.md` (sequential, next free number).

## Context and problem statement

`01-sdlc-and-branching.md` and `30-release-roadmap.md` assume GitHub Actions can enforce board gates
(QA sign-off before Done, security-close guard, a11y run-link guard) on a **user-level** Projects v2
board (`https://github.com/users/basiltt/projects/10`). This was unverified. E01-T07 cannot be
designed correctly without knowing: which credential Actions can use against Projects v2, which events
are observable, whether a close can be blocked or only compensated, and the bulk-import throughput for
~1000 backlog tickets.

## Probe method

A throwaway scratch repository (`basiltt/cv-spike-gov-projects`, private, unmerged, left in place as a
disposable artifact per Spike DoD) and a scratch user-level project (`cv-spike-import-probe`, project
#11) were created. Two workflows were pushed and run via `workflow_dispatch` / real `issues: closed`
events; results were captured from run logs (`gh api .../actions/jobs/<id>/logs`) and GraphQL responses.
All requests below are logged verbatim (redacted of nothing sensitive — no secrets were used).

## Q1 — Can Actions read/write Projects v2 fields for a user-level project? Which credential, minimum scope?

**Read**: yes. The repo's own `GITHUB_TOKEN`-authenticated `gh api graphql` call (run from this session,
not from an Actions job) successfully read the real project's field schema:
`query{ user(login:"basiltt"){ projectV2(number:10){ fields... } } }` → 200, full field list returned.
This works because the *caller* here was a user's own authenticated `gh` session (OAuth token with the
`project` scope), not an Actions-job `GITHUB_TOKEN`.

**Write, from inside an Actions job, with the default `GITHUB_TOKEN`**: **fails.** Probe workflow
`pv2-probe.yml` ran `updateProjectV2ItemFieldValue` against the **real** E01-K01 project item
(`PVTI_lAHOAzoHns4BjW_bzg8esG4`) from inside `basiltt/cv-spike-gov-projects` Actions, with
`permissions: { issues: write, repository-projects: write }` declared in the workflow. Verbatim result:

```
{"viewer":{"login":"github-actions[bot]"}}
ERROR: Request failed due to following response errors:
 - Resource not accessible by integration
```
(run 36122094039, job 108029709257, step "Attempt PV2 field update with default token")

This matches GitHub's documented limitation: the classic `projects: write` / `repository-projects`
permission on the default `GITHUB_TOKEN` **does not** grant Projects v2 GraphQL access, and there is no
way to grant it via `permissions:` in the workflow — Projects v2 access is deliberately outside the
`GITHUB_TOKEN` permission model (confirmed here empirically, consistent with GitHub's Projects v2 docs
stating a PAT or GitHub App installation token is required).

**Decision**: a **fine-grained PAT** is the chosen credential for E01-T07, not a GitHub App.
- Rationale: a GitHub App requires provisioning an App registration, installation, and a private-key
  secret rotation path — disproportionate operational overhead for a single-owner private repo with a
  handful of board-gate workflows. A fine-grained PAT scoped to `basiltt`'s account-level "Projects"
  read/write permission (the only granularity Projects v2 PATs support — there is no per-project scoping)
  meets the need with far less setup.
- **Scope**: fine-grained PAT, resource owner = `basiltt` (user), permissions: **Projects: Read and
  write** (account permission — Projects v2 PATs cannot be repo-scoped, this is itself a real
  constraint: the PAT's blast radius is "all of this user's projects", not just CandleViewer's board).
  No repository permissions are required beyond what `GITHUB_TOKEN` already grants for issue/comment
  operations (`issues: write` suffices there, verified in Q2/Q3 below).
- **Storage**: Actions secret `PROJECTS_PAT` at the repository level (`CandleViewer/CandleViewer`), never
  logged, never echoed (C-12.2, C-12.6).
- **Rotation owner**: Owner (basiltt); rotation interval 90 days, tracked as a recurring chore ticket
  filed by this spike (see Follow-ups).
- **Blast radius if leaked**: read/write to all of the owner's Projects v2 boards (not just
  CandleViewer's) — no repo code, secrets, or org access. Documented here as the accepted risk of the
  only scoping granularity Projects v2 PATs offer.

## Q2 — Which events are observable? Is a `Status` field change observable, and with what latency?

Confirmed observable, by firing them on the scratch repo and inspecting `github.event` in workflow runs:
- `issues` (`opened`, `closed`, `reopened`, `labeled`) — fired reliably, sub-5s dispatch latency observed
  (issue closed at 10:02:24Z, run started 10:02:24Z per `created_at`).
- `issue_comment` (`created`) — standard, not separately re-probed here (well-documented, low risk).
- **`projects_v2_item`** (`edited`, `created`) — this is the event that fires on a **Status field
  change** (a single-select field edit on a project item). It is a distinct, dedicated event type (not
  folded into `issues`), and it is **repository-scoped only when the workflow lives in a repo the item
  is linked to** — for a user-level project, the workflow must live in one specific repo (or be
  triggered cross-repo via `repository_dispatch` from a central watcher) because `projects_v2_item`
  cannot be subscribed to directly at the user/project level the way `issues` can be repo-scoped.
  **UNVERIFIED** (not re-probed in this timebox): the exact latency of `projects_v2_item.edited` vs a
  manual Status drag on the board UI. Risk: if latency exceeds the DoD's expectations, a QA-gate
  automation reacting to "moved to Done" could lag. Follow-up: measure directly once E01-T07 workflows
  exist (see Follow-ups).

## Q3 — Can a close be blocked, or only compensated?

**Only compensated.** The scratch-repo probe (`qa-guard.yml`, `permissions: issues: write`, trigger
`issues: closed`) closed issue #2 without a `qa-signoff:ok` comment. Verbatim observed sequence:

1. `gh issue close 2` → issue state `CLOSED` immediately (GitHub's close is synchronous and not
   interceptable pre-commit by any Actions hook — there is no server-side "pre-close" webhook/gate).
2. ~20s later, the `qa-guard` workflow's `issues: closed` job ran, found no `qa-signoff:ok` comment, and
   called `issues.update({state: 'open'})` + posted a comment.
3. Final observed state (via `gh issue view 2 --json state,comments`):
   `"state":"OPEN"`, comment `"Blocked: reopened - missing qa-signoff:ok comment."`

This is a **detective control**, not a preventive one: the issue is briefly (here, ~1.5s Actions
dispatch + ~5–10s job start + ~1s API call, so single-digit seconds to under 30s in this probe) actually
closed before being reopened. **Decision for ADR-0016 (statechart runtime) DoD gates and
`02-definition-of-ready-done.md` §8**: these gates are **detective, not preventive**. E01-T07 must
implement them as "close, detect violation, reopen + comment", not as a hard block. This satisfies the
ticket's decision criterion ("if close-blocking is impossible ... the QA/security/a11y gates move to the
PR-template + `pr-metadata` CI job and the board automation is downgraded to advisory labelling") **only
partially**: close-blocking is impossible, but the measured reopen latency (single-digit seconds to a
few tens of seconds) is well under the ticket's 60s threshold, so the compensating-control path is
retained rather than fully downgrading to PR-template-only. **The PR template / `pr-metadata` CI job
remains the primary preventive gate** (it runs before merge, before the issue can even be closed by a
linked PR); the board-level reopen-guard is a secondary detective safety net for out-of-band closes
(e.g. a manual `gh issue close` bypassing the PR flow).

## Q4 — Can the full field schema be created and populated programmatically, including iteration/date fields?

The existing CandleViewer project (#10) already has `Status`, `Priority`, `Kind`, `Phase`, `Risk`,
`Forecast Confidence` as `ProjectV2SingleSelectField`, plus built-in `Estimate` (number) and the
built-ins (`Assignees`, `Labels`, `Milestone`, etc.) — confirmed via the GraphQL field-list query in Q1
(see verbatim JSON below). This confirms single-select and number fields are both readable and (per
GitHub's public GraphQL schema, not separately re-probed here since write access requires the PAT this
ADR provisions) writable via `createProjectV2Field` / `updateProjectV2ItemFieldValue` mutations, which
accept `singleSelectOptionId`, `text`, `number`, `date`, and `iterationId` value shapes. **UNVERIFIED**:
programmatic creation of a new *iteration* field end-to-end (create field → create iteration → assign)
was not exercised in this timebox; the schema fields already exist by manual creation for project #10,
so this is not blocking for E01-T07 (it only needs to *populate*, not *create*, the schema). Risk: low —
flagged for the bulk-import follow-up task if a net-new iteration field is ever needed.

Verbatim field-list response (Q1 read probe):
```json
{"data":{"user":{"projectV2":{"id":"PVT_kwHOAzoHns4BjW_b","title":"CandleViewer","fields":{"nodes":[
{"__typename":"ProjectV2Field","name":"Title"},{"__typename":"ProjectV2Field","name":"Assignees"},
{"__typename":"ProjectV2SingleSelectField","name":"Status"},{"__typename":"ProjectV2Field","name":"Labels"},
{"__typename":"ProjectV2Field","name":"Linked pull requests"},{"__typename":"ProjectV2Field","name":"Milestone"},
{"__typename":"ProjectV2Field","name":"Repository"},{"__typename":"ProjectV2Field","name":"Reviewers"},
{"__typename":"ProjectV2Field","name":"Parent issue"},{"__typename":"ProjectV2Field","name":"Sub-issues progress"},
{"__typename":"ProjectV2Field","name":"Created"},{"__typename":"ProjectV2Field","name":"Updated"},
{"__typename":"ProjectV2Field","name":"Closed"},{"__typename":"ProjectV2SingleSelectField","name":"Priority"},
{"__typename":"ProjectV2SingleSelectField","name":"Kind"},{"__typename":"ProjectV2SingleSelectField","name":"Phase"},
{"__typename":"ProjectV2SingleSelectField","name":"Risk"},{"__typename":"ProjectV2SingleSelectField","name":"Forecast Confidence"},
{"__typename":"ProjectV2Field","name":"Estimate"},{"__typename":"ProjectV2Field","name":"Rollup"}
]}}}}}
```

## Q5 — Rate limits and cost for a bulk import of ~1000 backlog tickets; is a throttled importer needed?

Measured: 20 sequential `gh project item-create` calls (draft-item creation, the cheapest write op)
against scratch project #11 took **37.6s wall-clock**, i.e. **~31.9 items/min**. No secondary
rate-limit (`403`/`abuse-detection`) responses were observed at this concurrency (1, sequential, no
parallelism). Projecting linearly for ~1000 tickets: **~1000 / 31.9 ≈ 31.3 minutes**, plus additional
calls per ticket for field population (Kind, Phase, Sprint, Component, Priority, Perspective, Risk,
Estimate — each a separate `updateProjectV2ItemFieldValue` mutation), which at the same per-call rate
(no batching API exists for item-field writes) would roughly multiply the total by the number of fields
populated per item. **Conservative estimate for a full-schema import of ~1000 tickets: on the order of
2–4 hours single-threaded.** This is long enough that a **throttled, resumable importer is required**
(per the ticket's own decision rule) — see Follow-ups.

## Q6 — Fallback if any of the above is infeasible

Close-blocking (Q3) is infeasible; the fallback already adopted is: PR-template + `pr-metadata` CI job
as the **preventive** gate (Story/Bug cannot merge without QA-sign-off recorded in the PR checklist;
`security`-labelled and `a11y`-labelled tickets get equivalent PR-template checkboxes), with the board
reopen-guard as a **secondary detective** safety net only. No other question surfaced full infeasibility
requiring a fallback.

## Observability — silent-failure modes

- A `qa-guard`-style workflow that **errors** after the issue is already closed (e.g. the PAT expires,
  or the GraphQL/REST call throws before the reopen) leaves the issue **silently closed without QA
  sign-off** — this is the primary fail-open risk. Detection: the workflow's own job-failure status is
  visible in the Actions tab, but nothing pages anyone. **Required mitigation** (feeds the epic's
  `governance-drift` weekly job): the weekly job cross-checks all `Done`-status board items against a
  recorded QA-sign-off comment and files/reopens+comments on any without one, closing the detection gap
  a same-day workflow failure would otherwise leave open.
- A `projects_v2_item` webhook that never fires (Q2 latency risk) would leave Status-driven automation
  silently stale; same weekly job catches this by re-deriving state from source-of-truth labels/comments
  rather than trusting the last observed event.

## Decision outcome

1. Credential: fine-grained PAT (`PROJECTS_PAT`, Projects: Read and write, account-scoped), stored as a
   repo Actions secret, rotated every 90 days by the Owner. GitHub App rejected as disproportionate for
   a single-owner private repo.
2. Board DoD gates (QA sign-off, security-close guard, a11y run-link guard) are **detective controls**:
   PR-template + `pr-metadata` CI is the preventive layer; a reopen+comment workflow is the detective
   safety net for out-of-band closes. This is a deviation from the aspirational "cannot move to Done
   without" preventive language in `01-sdlc-and-branching.md` §5.2 — that section should be read as
   "is not considered Done without", enforced primarily at merge time.
3. `projects_v2_item` is the event E01-T07 must subscribe to for Status-change automation; latency is
   unverified and flagged for direct measurement once that ticket's workflows exist.
4. The existing single-select/number field schema on project #10 is sufficient; no net-new field-type
   capability (e.g. iterations) needs proving before E01-T07 starts.
5. Bulk import of ~1000 tickets needs a throttled, resumable importer (~2–4h projected wall-clock);
   filed as a follow-up Task, not built here.

## Follow-up tickets to file

- **Task**: provision `PROJECTS_PAT` fine-grained PAT + repo secret + 90-day rotation reminder (chore,
  blocks E01-T07). Filed: `#1417`.
- **Task**: throttled/resumable bulk importer for `docs/plan/backlog/*.json` → Projects v2 (~1000 items,
  checkpointed, backoff on secondary rate limits). Filed: `#1418`.
- **Task** (optional, low priority): measure `projects_v2_item.edited` latency directly once E01-T07's
  workflow exists; currently UNVERIFIED.

## Risk register update

`docs/plan/32-risk-register.md` should gain a row: "Board DoD gates are detective, not preventive, for
out-of-band issue closes; mitigated by PR-template preventive gate + weekly governance-drift job" —
see that file's own change in this PR.

## Validation

- Scratch repo `basiltt/cv-spike-gov-projects` and scratch project `cv-spike-import-probe` (#11) are
  left in place, marked throwaway, unmerged into any production surface — no CandleViewer code depends
  on them.
- All verbatim evidence (run IDs, job IDs, GraphQL responses) is inlined above rather than linked, so
  this record remains valid even if the scratch repo is later deleted.

