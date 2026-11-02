# Screen-reader scripts and pass records (E47-T04, #1359)

Pre-stage on E47-S01 #1316, E47-S02 #1358 and E47-S03 #1317. Protocol: `docs/plan/05-accessibility-standard.md`
§8.1 (matrix) and §8.2 (manual protocol); process: `docs/plan/03-testing-strategy.md` §11.

## What is here

| File                                                               | Purpose                                                                          |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `scripts/00-cross-cutting.md`                                      | XC: environment badge, login, landmarks, symbol switch, reduced motion, fills    |
| `scripts/10-chart-data-cursor.md`                                  | CDC: bar sentence, SCR-045 table                                                 |
| `scripts/20-footprint-inspection.md`                               | FPI: footprint cells, table parity                                               |
| `scripts/30-dom-ladder.md`                                         | DOM: ladder, demo order place and cancel, read-back                              |
| `scripts/40-rule-form-editor.md`, `scripts/50-rule-node-editor.md` | RFE, RNE: SCR-081, SCR-082                                                       |
| `regression-checklist.md`                                          | Dated pin changelog, living checklist, deferred checks, carried rows, scrub list |
| `records/_template.md`                                             | One pass record; copy to `qa/evidence/e47/sr/<at>-<date>/record.md`              |

## Matrix (05 §8.1)

1. NVDA + Electron, Windows 11: P0. 2. JAWS + Electron: P1. 3. NVDA + Chromium: P0 spot-check each sprint.
2. VoiceOver + Electron, macOS: P1. Versions are in the changelog in `regression-checklist.md`; the screen-reader cells are the owner's to fill.

## How to run a pass

1. Take the versions from the changelog in `regression-checklist.md`; if a cell says OWNER FILL, stop and fill it first.
2. Copy `records/_template.md`. Fill the header (screen reader, version, shell, OS build, date, tester, build sha, fixture).
3. Work a script top to bottom, keyboard only, Demo only. Mark each step P or F from what you hear, and note lag.
4. A step you cannot reach is `SURFACE PENDING`, never P. A second person dry-runs a script before its first use.
5. Route every failure with the finding block in the template: a register finding (S01 to S03 or E49), or an expiring
   exception in the shape of `docs/qa/a11y/e47-motion-exception-register.md`. Do not absorb it.

## Capture procedure (from `docs/plan/spikes/E47-K01.md`, not yet validated)

NVDA Speech Viewer plus the NVDA log at Debug, saved as text. Keep **text transcripts only**; no audio, and
screenshots only after review. If the text cannot be exported, use the template's notes-only mode (RSK-040 fallback).
Scrub before commit: account ids, key or token material, window titles, usernames. Never run against Live.

## Evidence honesty

- An agent has no screen reader. Any agent-run record is marked **(heuristic)** and is never a pass and never counted
  toward the full passes of matrix rows 1, 2 and 4. Do not write a `pass:<id>@<sha>` reference without a human record.
- `approved:` in a record stays `pending` until the Accessibility role signs it.
- Results and transcripts live under `qa/evidence/e47/sr/` (the root E47-Q02 #1355 names); this directory keeps only
  templates, scripts and the checklist. The 2026-11-02 heuristic record is `qa/evidence/e47/sr/records/`.
- Parent pins: each script header lists the parent heads it was written against, "if merges as is" for open PRs
  (#5467, #5480 mirror; #5419). `last_verified_sha` is a `main` sha. Unbuilt parents stay `SURFACE PENDING`.
- Every step row has an `Oracle` (spec row, or the `Source` formatter `file:line`) and `heuristic: true`.
- Carried rows, the "Remediation has landed is false today" note, Deviations (C-4.9) and the public-repo scrub list are
  in `regression-checklist.md`. No real captures are committed.
