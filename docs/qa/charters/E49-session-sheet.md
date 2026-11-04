# E49 exploratory session sheet

Copy this file's tables into the session's notes (one sheet per session, one charter each) and fill every
cell; write `none` rather than leaving one empty. The run record
(`docs/qa/e49-run-<n>-findings.md`) is a roll-up of the sheets. Format follows the E28 debrief table
(`qa/plans/e28-exploratory-charters.md`) plus the debrief elements of the E49-Q02 ticket. Public wording
only: paths and statuses, no host, no secret, no real identifier (`E49-README.md`, disposition rules).

## 1. Header

| Field                                         | Entry |
| --------------------------------------------- | ----- |
| Charter (`E49-C<n>`) and run number           |       |
| Tester, role (QA alone / paired engineer)     |       |
| Date, start and end (UTC)                     |       |
| Build sha under test (full sha)               |       |
| Stack tier (A browser on stubs, B seeded)     |       |
| Seed and fixture set; test accounts used      |       |
| Explorable table version (pin sha of charter) |       |
| Recording kept (tier A only) and where        |       |

## 2. Debrief

| Field                                                  | Entry |
| ------------------------------------------------------ | ----- |
| Mission, in one line                                   |       |
| Time on charter / on opportunity (%)                   |       |
| Areas actually probed                                  |       |
| Criteria used (`O<n>.<m>`, `O-ALL.1`)                  |       |
| Areas not reached, and why (parked row, timebox)       |       |
| Screens driven with the keyboard alone (03 §12)        |       |
| Dead ends and traps found by the keyboard-only segment |       |
| Questions and spec gaps                                |       |
| Cases to promote to automated tests                    |       |

## 3. Candidates

One row per observation, id `E49-R<run>-<nn>`. The disposition is one of `bug P0..P3`, `not-a-defect`
(with a one-line reason), `security-private` (public row says only that it exists) or `pending filing`
(`E49-README.md`). A `bug` row gets its issue number in `Status` once filed.

| ID  | Charter | Criterion | Area | Steps (numbered, reproducible) | Expected | Actual | Severity | Status | Evidence |
| --- | ------- | --------- | ---- | ------------------------------ | -------- | ------ | -------- | ------ | -------- |
|     |         |           |      |                                |          |        |          |        |          |

## 4. Routing

| Candidate id | Routed to (E46 perf, E49-Q03 screen reader, E49-S02, E49-S03) | Accepted by |
| ------------ | ------------------------------------------------------------- | ----------- |
|              |                                                               |             |
