# Calibration exercise record: TEMPLATE (task 3, footprint navigation)

Quality gate of E47-Q02 #1355: two testers independently run task 3 (footprint navigation, script `FPI` plus the
SCR-045 table, 05 §8.2 item 3) on the same build. Their verdicts must agree. Any disagreement is resolved by the
Accessibility role and written back into E47-Q01 as a clarified expected result **before** the main passes proceed.
Copy to `qa/evidence/e47/sr/<at>-<date>/calibration.md`. **SURFACE PENDING E18-S11:** the footprint cells are not
mounted yet, so no calibration can be run; this template waits for that surface.

```yaml
record_id: "calibration-<at>-<date>"
mode: full # a calibration is human-only; an agent never fills it
task: "3 (footprint navigation, FPI + SCR-045)"
screen_reader: "" # name and exact version, same for both testers
shell: ""
os_build: ""
date: ""
build_sha: ""
fixture: "" # the E47-Q01 replay fixture, so both testers hear the same data
profile: fresh
voiceover_launch_flags: "" # REQUIRED for VoiceOver; "n/a (not VoiceOver)" otherwise
tester_a: ""
tester_b: ""
tester_a_ran_independently: false # neither saw the other's transcript before verdicts were written
tester_b_ran_independently: false
resolved_by: "" # the Accessibility role
approved: pending # the Accessibility role only
```

## Verdicts

One row per step of the FPI script, then the SCR-045 table parity check. Verdict is P, F or SURFACE PENDING.

| Step | Tester A verdict | Tester B verdict | Agree (yes / no) | Heard A (verbatim) | Heard B (verbatim) |
| ---- | ---------------- | ---------------- | ---------------- | ------------------ | ------------------ |

## Disagreements

Every row with `Agree: no` gets one block. Resolution is written by the Accessibility role, not by either tester.

```yaml
- step_id: ""
  tester_a: ""
  tester_b: ""
  resolution: "" # the clarified expected result
  written_back_to: "E47-Q01" # the expected result is amended there before the main pass
  resolved_by: ""
  date: ""
```

## Gate

- [ ] Every step has two independent verdicts.
- [ ] Every disagreement is resolved and written back into E47-Q01.
- [ ] The main passes start only after the two lines above are ticked.

## Scrub checklist

- [ ] No account ids, key or token material, usernames or window titles in any attached text.

## Sign-off

Date: ____ Accessibility role: ____ (approved: pending)
