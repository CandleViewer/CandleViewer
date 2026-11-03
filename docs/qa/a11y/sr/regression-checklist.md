# Screen-reader regression checklist (living)

Required by `docs/plan/05-accessibility-standard.md` §8.2 item 4 and referenced from `docs/plan/03-testing-strategy.md`
§11. Re-run every release. Add a row for every defect a pass finds, so it stays fixed.

## Pinned screen-reader matrix: dated changelog

Matrix and priorities: `docs/plan/05-accessibility-standard.md` §8.1 (the dated pin changelog lives in this checklist,
per §8.1). The Accessibility role re-pins quarterly, or on a forcing major release, by adding a row here. Screen-reader
and OS cells are **OWNER FILL**: no agent has these products, and a version is never guessed.

Matrix rows: 1 NVDA + Electron on Windows 11 (P0), 2 JAWS + Electron on Windows 11 (P1), 3 NVDA + Chromium (P0,
sprint spot-check), 4 VoiceOver + Electron on macOS (P1).

| Pin          | NVDA       | JAWS       | VoiceOver / macOS | Windows build | Electron                                                                                                                                    | Date       | By                                                      |
| ------------ | ---------- | ---------- | ----------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------- |
| P-2026-11-02 | OWNER FILL | OWNER FILL | OWNER FILL        | OWNER FILL    | 45.0.0 (exact, from the `pnpm-lock.yaml` `electron@45.0.0` entry; `apps/desktop` declares `^45.0.0`; E10-Q03 observed 45.0.0 on 2026-11-01) | 2026-11-02 | pre-stage (E47-T04); screen-reader cells awaiting owner |

- **Next re-pin due (PROPOSED):** 2027-01-04. 05 §8.1 fixes only "quarterly (or on a forcing major)"; the first-Monday day rule is a proposal for the Accessibility role to confirm.
- The "2024.x (latest stable at freeze)" wording in 05 §8.1 is not changed here; the Accessibility role decides.
- **Pin wording question for the Accessibility role (E47-Q02 BQ-05):** 05 §8.1 says "NVDA 2024.x" and "JAWS 2024.x", but the
  pass is run in 2026-11. The role rules whether the standard's wording is amended, or the pins-table row above simply
  records the installed version and the drift is a dated changelog entry (the default). No agent pins a version.

### Re-pin Chore text (drafted; no issue is filed, so this is a carried row)

**Title:** chore(design-system): re-pin the screen-reader matrix (quarterly)

**Cadence:** quarterly (05 §8.1); the day rule "first Monday of January, April, July and October (next: 2027-01-04)" is PROPOSED, not fixed by 05. Also on a forcing NVDA, JAWS or
VoiceOver major release (05 §8.1).

**Task:** the Accessibility role adds a dated row to the changelog above (NVDA, JAWS, VoiceOver and macOS, Windows
build, Electron), re-runs the XC script as a smoke pass on the new pins, and records it under `qa/evidence/e47/sr/`.

**Done:** a new pin row with date and name; a smoke record; this checklist reviewed.

## Re-run every release

- [ ] XC script (`scripts/00-cross-cutting.md`) on rows 1 and 3 of the matrix; JAWS and VoiceOver smoke per 05 §8.1.
- [ ] The environment badge reads first and is never Live in a trading script.
- [ ] Fills are announced assertively once per batch; no per-tick announcement.
- [ ] Read-back names side, price, quantity and account before any order commit.
- [ ] No account name, id or key material in any captured transcript.

## Deferred screen-reader spot-checks to close (E47-T04 DoD item 6)

| Origin        | Deferred check                                                       | Closed by           | State                 |
| ------------- | -------------------------------------------------------------------- | ------------------- | --------------------- |
| E10-Q03 OR-1  | NVDA on the Electron shell (`docs/qa/a11y/e10-q03-shell-v0.md` §6.2) | XC pass, row 1      | open                  |
| E10-Q03 OR-2  | NVDA on Chromium                                                     | XC pass, row 3      | open                  |
| E10-Q03 OR-3  | VoiceOver on the Electron shell                                      | XC pass, row 4      | open                  |
| E10-Q03 OR-4  | JAWS on the Electron shell                                           | XC pass, row 2      | open                  |
| E47-S01 #1316 | SCR-045 and the chart cursor                                         | CDC script          | open, surface pending |
| E47-S02 #1358 | Footprint, ladder, read-back, fills                                  | FPI and DOM scripts | open, surface pending |
| E47-S03 #1317 | Graph editor traversal and connect                                   | RNE script          | open, surface pending |

The S01 to S03 rows are listed from their ticket scope; the owner or the orchestrator confirms them against the carried-row comments.

## Defects found (add rows)

| Date | Pin | Step | Finding id or exception | Fixed in |
| ---- | --- | ---- | ----------------------- | -------- |

## Carried rows (open; not closed by this pre-stage)

- NVDA, JAWS and VoiceOver executions on the pinned matrix (rows 1, 2, 3 and 4), by the owner and E47-Q02 #1355.
- The Accessibility-role sign-off of every record (`approved:` stays `pending`).
- The second-person dry run of each script (`dry_run: pending`).
- The recurring re-pin Chore (text above; no issue filed).
- E47-Q02 #1355 human rows: the three full passes (rows 1, 2 and 4), the NVDA Chromium spot-check (row 3), the pass by a
  daily screen-reader user, the two-tester calibration on task 3 (`records/_calibration-template.md`), the OWNER FILL pin
  cells, the NVDA "2024.x" wording ruling, and the Accessibility-role sign-off of the summary. The task scripts ORD, FLT,
  LIV and ADA stay `SURFACE PENDING` until their tickets mount.
- E47-Q02 #1355 closing rows, after the human passes: committing the transcripts under `qa/evidence/e47/sr/<at>-<date>/`;
  writing the calibration's clarified expected results back into E47-Q01; handing the pass summary to E47-T06 and
  E47-Q09; and posting it to the release-candidate checklist in `docs/plan/07-release-and-prr.md`.
- The ticket's "Remediation has landed" is **false today**: E47-S01, S02 and S03 are only partly merged, and E18-S11,
  E21-S01, E21-S02, E36-S02, E37-S01 and E37-S05 are unbuilt, so those scripts stay `SURFACE PENDING`.

## Deviations (C-4.9)

The ticket's Repo paths name `apps/web`, but its DoD deliverables are docs, scripts and `scripts/tests/`. No `apps/web`
file is changed; the path fill is recorded here. There is no Playwright spec (no automated screen-reader emulation).

A second path fill: `.github/CODEOWNERS` gains one `/qa/evidence/` line (owners as `/qa/plans/`), because the results
under `qa/evidence/e47/sr/` otherwise fall to the catch-all rule (GOV-001). The C-4.15 overlap check on that file found no
other open PR touching it.

## Public-repo scrub checklist (this repo is public; commit no real captures)

Before any record or transcript is committed under `qa/evidence/e47/`, remove: account ids, API key or token material,
hostnames and URLs of private hosts, exchange UIDs, usernames, and window titles. Text transcripts only; no audio.
