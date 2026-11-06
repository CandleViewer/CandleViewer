# Demo to Live switch (stops at Cancel)

```yaml
script_id: LIV
title: "Demo to Live switch (stops at Cancel)"
screens: [SCR-074, SCR-075]
status: "SURFACE PENDING E38-S02, E38-S04 and E44-S02 (SCR-074 switcher, SCR-075 badge, hardened switch)"
env: demo
fixture: "A demo-flagged build. The script stops at the typed confirmation and cancels; no switch to Live is ever completed. No Live credential exists on the test machine."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
  - "The build is demo-flagged (BQ-08). If you cannot show that, stop: the pass is void."
  - "The script ends at the typed confirmation with Cancel. Never confirm the switch, never against Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "E38-S04 (chrome and switch from the shell): SURFACE PENDING (unbuilt)"
  - "E38-S02 (safe environment switch, step-up): SURFACE PENDING (unbuilt)"
  - "E44-S02 (hardened switch on SCR-074): SURFACE PENDING (unbuilt)"
  - "#5501 merged (T04 scripts, templates and checklist under docs/qa/a11y/sr/)"
  - "#5419 91e9bde449dc29325efd23e3e1f2fd5a34867351 (open, if merges as is)"
dry_run: pending
```

> **Expected text is a contract, not an observation.** No shipped sentence builder exists for these surfaces yet, so
> every expected cell states what must be obtainable and says `Record ... verbatim`: the tester writes down what is
> heard and never scripts copy (05 §8.2 item 3; "information must be obtainable, not identical" across NVDA, JAWS and
> VoiceOver). Wording is PROPOSED by the owning ticket; a copy change edits the builder, not this script. Nothing here
> was heard on a screen reader. Mark a step P/F only from what you hear. A `SURFACE PENDING` step cannot be executed
> until the named ticket mounts its surface, and is never P.
> Oracle: the spec row each step verifies. `heuristic: true` marks a row derived by an agent from the plan, never
> heard; a human pass may correct it. Lag column: note any keypress-to-speech delay over about 200 ms as an E46 candidate.

> **NEVER AGAINST LIVE.** Run on Demo only. If LIV-01 does not read Demo, stop: the pass is void and nothing was
> done. Demo orders go via REST only (C-2.11). XC-01 keeps its rule: the badge is read first and a Live
> reading fails the script. The script stops at the typed confirmation (Cancel); the badge-change announcement after a
> completed switch is a carried human row until the owner names a safe target (orchestrator ruling on BQ-08).

## Steps

| Step   | Keys                                                                                         | Expected announcement                                                                                                                                                           | Source                                                | Oracle         | Heuristic       | Lag | P/F           |
| ------ | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| LIV-01 | [SCR-075 · SC 1.4.1 4.1.2] Tab to the top bar                                                | `Trading environment: Demo` (read first). **Stop and fail the script if it says Live**; nothing was done                                                                        | apps/web/src/features/app-shell/TopBarEnvBadge.tsx:47 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| LIV-02 | [SCR-074 · SC 4.1.2 1.4.1] Open the SCR-074 switcher (key per E38-S04; record it)            | Record the control name, role and current value verbatim; the current environment is said as text (SURFACE PENDING E38-S04)                                                     | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| LIV-03 | [SCR-074 · SC 4.1.2 3.3.4] Choose the Live target and press the switch key                   | A confirm dialog opens and is announced first; record its title and body verbatim. It says the target and the consequence (SURFACE PENDING E38-S02)                             | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| LIV-04 | [SCR-074 · SC 2.1.2 2.4.3] Tab inside the dialog                                             | Focus is trapped in the dialog; record each control name, role and value verbatim (SURFACE PENDING E44-S02)                                                                     | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| LIV-05 | [SCR-074 · SC 3.3.8 4.1.2] Type the typed confirmation with the keyboard only; do not submit | The field has a name, role and value; record each prompt and any error verbatim; no secret is said or shown in the transcript (SURFACE PENDING E44-S02)                         | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| LIV-06 | [SCR-074 · SC 2.1.2 2.4.3 4.1.3] Choose Cancel (button, then repeat once with `Esc`)         | The dialog closes and the cancel is announced once; focus returns to the switcher; the badge still reads `Trading environment: Demo`; record verbatim (SURFACE PENDING E44-S02) | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |

## Notes

- Out of scope until the owner names a safe target: completing the switch and the SCR-075 badge-change announcement. They are a carried row in `regression-checklist.md`.
