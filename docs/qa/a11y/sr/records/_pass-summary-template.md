# Pass summary: TEMPLATE (screen x AT x verdict x blocking defects)

The one table E47-T06 (the conformance report) and E47-Q09 (sign-off) read, and that E47-D13 cites as
`pass:<record id>@<sha>` (`docs/design/E47/E47-D13-handoff.md` §C.2, shared with E47-T04 #1359). Copy to
`qa/evidence/e47/sr/summary-<date>.md`. Posted to the release-candidate checklist in `docs/plan/07-release-and-prr.md`
as a PRR input.

**A `pass:` reference is never written without a human record.** `pass_ref` stays `pending` until a human-run record
for that row exists under `qa/evidence/e47/sr/<at>-<date>/record.md`, its `approved:` is signed by the Accessibility
role, and its `build_sha` is the `<sha>`. A heuristic record, an agent run or a `SURFACE PENDING` row never gets a
`pass_ref`, and counts toward none of the matrix rows of 05 §8.1.

```yaml
summary_id: "summary-<date>"
build_sha: ""
pin: "" # the pin row of regression-checklist.md, for example P-2026-11-02
record_tags: "epic:E47" # per row: at:<nvda|jaws|voiceover>, screen:<SCR-id>
approved: pending # the Accessibility role only
```

## Verdicts

| Verdict           | Meaning                                                                                |
| ----------------- | -------------------------------------------------------------------------------------- |
| `pass`            | Every step of every script covering the screen was heard and passed, on a human record |
| `fail`            | At least one step failed; the blocking defects column lists them                       |
| `not-run`         | No human pass has been run for this screen and AT yet                                  |
| `surface-pending` | The surface is not mounted; the owning ticket is named                                 |

## Summary

| Screen  | AT (pinned version) | Matrix row | Verdict | Blocking defects (finding ids) | Record id | pass_ref |
| ------- | ------------------- | ---------- | ------- | ------------------------------ | --------- | -------- |
| SCR-001 |                     | 1          | not-run |                                |           | pending  |

Add one row per screen and AT. Rows by AT: `nvda` (matrix rows 1 and 3), `jaws` (row 2), `voiceover` (row 4).
A P0 defect (a task that cannot be completed keyboard and screen reader only, or a silent focus move) is listed in
`Blocking defects`, and E47-T06 records that screen as non-conformant until it is closed (05 §8.2 item 5).

## Totals (filled by the human pass only)

| AT        | Screens pass | Screens fail | Screens not-run | Screens surface-pending |
| --------- | ------------ | ------------ | --------------- | ----------------------- |
| nvda      |              |              |                 |                         |
| jaws      |              |              |                 |                         |
| voiceover |              |              |                 |                         |

## Sign-off

Date: ____ Accessibility role: ____ (approved: pending) QA co-sign: ____
