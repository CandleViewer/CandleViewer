# E49-Q02 exploratory run 2: run record (agent baseline, tier A)

- Ticket: E49-Q02 (#1336), slice S-C2 (`Partial:`) · Run: 2026-11-04 · Tier A only (static build, stubbed API,
  socket stub on) · Base: the stacked E49 harness branch
- Charters: `docs/qa/charters/E49-README.md` · Harness: `docs/qa/e49-exploratory-harness.md` (tier A) ·
  Sessions: `apps/web/e2e/exploratory/run-2.explore.ts`, 16 tier A sessions, all completed; egress guard clean.
- **Agent baseline sweep, not a human 90-minute charter session.** It satisfies no DoD box on its own.
- **Tier B (the seeded stack, C7 server half and two tabs) has not run**: it needs the docker host; its rows are
  carried to the next run, owner the E27 lane.

## §1 Run log summary

| Charter | Sessions | Notes | `ok` | `suspect` | `info` | Oracles applied                       |
| ------- | -------- | ----- | ---- | --------- | ------ | ------------------------------------- |
| C7      | 3        | n/a   | n/a  | 0         | n/a    | O7.1, O-ALL.1                         |
| C8      | 6        | n/a   | n/a  | 0         | n/a    | O8.1, O8.2, O-ALL.1                   |
| KB      | 7        | n/a   | n/a  | 8         | n/a    | O-KB.1, O-KB.2, O-ALL.1               |
| All     | 16       | 254   | 214  | 8         | 32     | the session logs are git-ignored (§3) |

The eight `suspect` notes are the rows of §2; each is one note. Session logs and recordings stay in the
git-ignored `apps/web/test-results/explore/` and hold stub values only.

## §2 Findings

| ID        | Charter | Oracle  | Area                 | Steps                                       | Expected                               | Actual                                                                      | Severity | Status                                                                | Evidence                             |
| --------- | ------- | ------- | -------------------- | ------------------------------------------- | -------------------------------------- | --------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------- | ------------------------------------ |
| E49-R2-01 | KB      | O-KB.2  | Settings search      | Tab through `/settings/appearance` as Owner | Every stop shows a visible focus style | Stop 15, the "Search settings" input, shows no ring                         | P3       | pending filing; owner E49-S03 #1363                                   | `keyboard--06cd5` (Tab sweep)        |
| E49-R2-02 | KB      | O-KB.2  | Settings search      | Tab through `/settings/hotkeys` as Owner    | Every stop shows a visible focus style | Stop 15, the "Search settings" input, shows no ring                         | P3       | pending filing; same cause as E49-R2-01                               | `keyboard--839ab` (Tab sweep)        |
| E49-R2-03 | KB      | O-KB.2  | Settings search      | Tab through `/settings/profile` as Owner    | Every stop shows a visible focus style | Stop 15, the "Search settings" input, shows no ring                         | P3       | pending filing; same cause as E49-R2-01                               | `keyboard--cda3f` (Tab sweep)        |
| E49-R2-04 | KB      | O-KB.1  | Hotkeys screen       | Press Tab 80 times on `/settings/hotkeys`   | Focus cycles back to the first stop    | 80 stops, no cycle, no trap: the page has more stops than the sweep's bound | n/a      | not-a-defect: harness bound of 80 presses reached before the cycle    | `keyboard--839ab` (Tab sweep)        |
| E49-R2-05 | KB      | O-ALL.1 | Signed-out bootstrap | Signed out, open `/login`                   | No console error                       | "Failed to load resource": a 401 answer from the preview server             | P3       | pending filing; triage with E49-R1-03 (owner E49-S03 #1363)           | `keyboard--242f1` (Tab sweep, login) |
| E49-R2-06 | KB      | O-ALL.1 | Signed-out bootstrap | Signed out, open `/login`                   | No console error                       | "Failed to load resource": a 404 answer, first of three                     | n/a      | not-a-defect: the bootstrap reads have no signed-out stub (E49-R1-03) | `keyboard--242f1` (Tab sweep, login) |
| E49-R2-07 | KB      | O-ALL.1 | Signed-out bootstrap | Signed out, open `/login`                   | No console error                       | "Failed to load resource": a 404 answer, second of three                    | n/a      | not-a-defect: the bootstrap reads have no signed-out stub (E49-R1-03) | `keyboard--242f1` (Tab sweep, login) |
| E49-R2-08 | KB      | O-ALL.1 | Signed-out bootstrap | Signed out, open `/login`                   | No console error                       | "Failed to load resource": a 404 answer, third of three                     | n/a      | not-a-defect: the bootstrap reads have no signed-out stub (E49-R1-03) | `keyboard--242f1` (Tab sweep, login) |

## §3 Counts and routing

| Severity / disposition | Count                                        |
| ---------------------- | -------------------------------------------- |
| P0, P1, P2             | 0                                            |
| P3                     | 4 (E49-R2-01, -02, -03, -05; pending filing) |
| Not-a-defect           | 4                                            |
| Undecided              | 0                                            |

- Filing is the orchestrator's (filing freeze); the closing PR records the issue numbers and resolves every
  `pending filing` row. Routings: none to E46 (no perf probe) or E49-Q03 (no screen-reader probe).
- Evidence paths are session folders under `apps/web/test-results/explore/run-2.explore.ts-<folder>/`; they are
  not committed.
- Carried to the next run: all of tier B; C1 to C4 and C6 once their screens exist; C5; the two bug bashes.
