# E42 deferred Musts: the verification record

<!-- Written by scripts/verify_deferred_must.py --write-record; rerun it, never edit. -->

E42 defers two Must stories by design (E42-Q06): US-ADMIN-010 to E43 and US-ADMIN-012 to E44. This
record is dated evidence that their owners still hold them, read offline from the backlog. It says
when the claim was last true; the run at epic close is the one of record, and its reviewer is the
E42 QA sign-off's.

- **Date:** 2026-11-04
- **Reviewer:** E42-Q06 pre-close run
- **Result:** PASS
- **Inputs (sha256):**
  - `E42.json`: `7c5127c5325c81cfd980228bd9ece0617f4a25b729ac39a3feb93de6617e4cf1`
  - `E43.json`: `3e52f501423725a4fd1ca56553381dce189e76d0272bbc07cd3636025c96cd42`
  - `E44.json`: `79f666b859c46e762efdcdb93afef8d99e134dac5eb2a3c71cbd71ebeae1f1c1`
  - `verify_deferred_must.py`: `51b5d3f3c72936b57d50f6e0e96e3a3653b235a4bc6bd8f536de3d14bf93f0e8`

| Story        | Owner epic | Ticket  | Issue | Kind  | Sprint | Milestone          | Names the story | Notes                                           |
| ------------ | ---------- | ------- | ----- | ----- | ------ | ------------------ | --------------- | ----------------------------------------------- |
| US-ADMIN-010 | E43        | E43-D01 | #1138 | Task  | S18    | R4 Live enablement | yes             | design, 2 sprints before E43-S02; names SCR-137 |
| US-ADMIN-010 | E43        | E43-S02 | #1229 | Story | S20    | R4 Live enablement | yes             | names SCR-137                                   |
| US-ADMIN-012 | E44        | E44-T04 | #1247 | Task  | S20    | R4 Live enablement | yes             | none                                            |
| US-ADMIN-012 | E44        | E44-S01 | #1266 | Story | S21    | R4 Live enablement | yes             | none                                            |
| US-ADMIN-012 | E44        | E43-S01 | #1258 | Story | S21    | R4 Live enablement | yes             | names SCR-137                                   |

## What the run checked

- Each owner ticket is in its epic's backlog file, carries no `retired` label, names its story, has
  the milestone `R4 Live enablement` and a sprint from Sprint 20 to Sprint 22; a design ticket lands
  at least 2 sprints before the story it serves.
- E43-D01, E43-S01, E43-S02 name SCR-137.
- E42-S01, E42-S05 state the deferral and name the owners; E43 and E44 are blocked by E42.
- `docs/plan/18-traceability-matrix.md` traces each story to screens, components and flows, not to
  an epic, so the story-to-epic link is read from the backlog.

The static checks cover code that spells the key or the setting; beyond that, C7's second key is the
guarantee.

## The one stated exception

The contract's `setFeatureFlag` (`docs/plan/22-api-openapi.yaml`) sets `trading.live_enabled` to
`true` only with `flags:write`, a `reason`, an `https` `evidence_url` and a fresh, single-use
`live_enablement` step-up; E44-T04 owns the evidence binding. That gated path (CG-28) is an accepted
residual until E44-T04 lands, as ruled on 2026-11-03. While it stands, a live order also needs the
process setting `CV_TRADING_LIVE_ENABLED`, which is off by default, so the flag alone admits none.
No E42 test completes a real `live_enablement` step-up; unit tests use an in-memory fake.

## Hand-off

E42-Q04 attaches this record to the E42 QA sign-off.
