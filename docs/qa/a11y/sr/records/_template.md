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
script: "" # XC | CDC | FPI | DOM | RFE | RNE
dry_run_by: "" # a second person
approved: pending # the Accessibility role only
```

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
