# Screen-reader pass record: TEMPLATE

```yaml
record_id: "<at>-<date>"
mode: full # full | smoke | notes-only | heuristic
screen_reader: "" # name and exact version
shell: "" # Electron or Chromium, exact version
os_build: ""
date: ""
tester: ""
build_sha: ""
fixture: ""
profile: fresh # a pass on a customised profile is void (E47-Q02 technical notes)
voiceover_launch_flags: "" # REQUIRED for VoiceOver rows: the exact Electron launch flags and NSAccessibility activation used; "n/a (not VoiceOver)" otherwise
script: "" # XC | CDC | FPI | DOM | RFE | RNE | ORD | FLT | LIV | ADA
dry_run_by: "" # a second person
approved: pending # the Accessibility role only
```

## Setup

Required before step 1. A record with an empty field here is invalid.

- [ ] Fresh profile, default hotkey map, default theme, default screen-reader verbosity (05 §8.2 item 1).
- [ ] Versions copied from the pin changelog in `regression-checklist.md`, never guessed; a drift from the pin is a dated changelog entry.
- [ ] **VoiceOver only:** `voiceover_launch_flags` above holds the exact launch command flags and how `NSAccessibility` was activated for Electron (for example whether the app was started with an accessibility flag, or VoiceOver was already running at launch), so the pass is reproducible. macOS-only defects are filed apart from their Windows equivalent.
- [ ] Demo-flagged build; the LIV script stops at Cancel (BQ-08).

## Matrix rows covered

| Row | Combination                 | Priority | Covered | Pin (from the changelog in `regression-checklist.md`) |
| --- | --------------------------- | -------- | ------- | ----------------------------------------------------- |
| 1   | NVDA + Electron, Windows 11 | P0       | no      |                                                       |
| 2   | JAWS + Electron, Windows 11 | P1       | no      |                                                       |
| 3   | NVDA + Chromium             | P0       | no      |                                                       |
| 4   | VoiceOver + Electron, macOS | P1       | no      |                                                       |

## Steps

| Step | Result (P / F / SURFACE PENDING) | Heard (verbatim) | Lag (ms) |
| ---- | -------------------------------- | ---------------- | -------- |

## Findings

Every failed step gets one block. A block with no `expected` is invalid.

```yaml
- at: ""
  at_version: ""
  step_id: ""
  expected: ""
  screen: ""
  wcag_sc: ""
  severity: "" # per 05 §8.2 item 5
  source: manual
  owner: ""
  routing: "" # E47-S01 | E47-S02 | E47-S03 | E49 | exception
```

## Scrub checklist

- [ ] No account ids, key or token material, usernames or window titles in any attached text.
- [ ] Demo environment confirmed at the start (badge read as Demo).

## Sign-off

Date: ____ Screen-reader and shell versions: ____ Build sha: ____
Accessibility role: ____ (approved: pending) QA co-sign: ____
