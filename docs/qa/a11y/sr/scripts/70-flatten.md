# Rule-engine flatten announcement

```yaml
script_id: FLT
title: "Rule-engine flatten announcement"
screens: [SCR-063, SCR-087]
status: "SURFACE PENDING E29-S01 (positions tab), E35-S09 (SCR-087 fire history) and E35-S03 (rule actions through the OMS, flatten refusal)"
env: demo
fixture: "A demo account with one open demo position and an armed simulated rule whose action is flatten; the fixture fires it on cue (E47-Q01 replay)."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
  - "The flatten is simulated on Demo; no real order is emitted."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "E29-S01 (SCR-063 positions tab): SURFACE PENDING (unbuilt)"
  - "E35-S09 (SCR-087 fire history): SURFACE PENDING (unbuilt)"
  - "E35-S03 (rule actions through the OMS under safety limits): SURFACE PENDING (unbuilt)"
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

> **NEVER AGAINST LIVE.** Run on Demo only. If FLT-01 does not read Demo, stop: the pass is void and nothing was
> done. Demo orders go via REST only (C-2.11). This is the 05 §8.2 item 3 flatten task; its automated neighbour is E47-TC-204.

## Steps

| Step   | Keys                                                                                                      | Expected announcement                                                                                                                                                                        | Source                                                | Oracle         | Heuristic       | Lag | P/F           |
| ------ | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| FLT-01 | [SCR-075 · SC 1.4.1 4.1.2] Tab to the top bar                                                             | `Trading environment: Demo` (read first). **Stop and fail the script if it says Live**; nothing was done                                                                                     | apps/web/src/features/app-shell/TopBarEnvBadge.tsx:47 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| FLT-02 | [SCR-063 · SC 1.4.1 4.1.2] Tab to SCR-063 and open the Positions tab; focus the open position row         | Record the row verbatim: symbol, side word, size and a Profit or Loss word with the sign (never colour only) (SURFACE PENDING E29-S01)                                                       | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| FLT-03 | [SCR-063 · SC 4.1.3] Leave focus on that row; trigger the simulated rule fire (fixture cue) and wait      | The position-closed event is announced once, in full and assertively; record it verbatim. It names the symbol and that it was closed by the rule (SURFACE PENDING E29-S01)                   | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| FLT-04 | [SCR-063 · SC 3.2.1 2.4.3] Check where focus is after the announcement                                    | Focus has not moved silently: it is on the row or control you left it on, or in an alertdialog announced first; a silent move is P0; record it verbatim (SURFACE PENDING E29-S01)            | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| FLT-05 | [SCR-063 · SC 4.1.2 2.4.3] Read the position row again                                                    | Record verbatim; the row shows closed or is gone, and the position count the page reports changed; focus lands on a named, sensible control if the row was removed (SURFACE PENDING E29-S01) | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| FLT-06 | [SCR-087 · SC 1.3.1 4.1.2] Open SCR-087 (fire history, key per E35-S09; record it) and find the new entry | Record the entry verbatim: rule name, action word (flatten), result and time as text (SURFACE PENDING E35-S09)                                                                               | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| FLT-07 | [SCR-087 · SC 2.1.1 2.1.2 1.3.1] Tab through the SCR-087 table to its end and back                        | One tab stop for the grid with arrow keys; every column header is read; record any trap or skipped cell; record it verbatim (SURFACE PENDING E35-S09)                                        | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| FLT-08 | [SCR-063 SCR-087 · SC 3.3.1 4.1.3] Trigger a flatten that is refused (fixture cue)                        | Record the refusal verbatim; it is announced once, assertively, and says what to do next (SURFACE PENDING E35-S03)                                                                           | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |

## Notes

- A flatten may close several positions: record whether the announcement is one summary or one per position, and that it is never one per tick.
