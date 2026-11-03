# Cross-cutting screen-reader script (05 §8.2)

```yaml
script_id: XC
title: "Cross-cutting screen-reader script (05 §8.2)"
screens: [SCR-001, SCR-075]
status: "READY (reachable steps); SURFACE PENDING E10-S03 for symbol switch"
env: demo
fixture: "Demo build with the E27 account fixture stack and a demo TOTP account; no credentials in this repo."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "#5371 merged (main sha e5b286ed50d3a320d80b24df5030fb09dd405a4a)"
  - "E10-S03: SURFACE PENDING (unbuilt)"
  - "#5419 91e9bde449dc29325efd23e3e1f2fd5a34867351 (open, if merges as is)"
dry_run: pending
```

> **Expected text is a contract, not an observation.** It is derived from the shipped sentence builders cited per
> step (`file:line`), written as a pattern with fields. Wording is PROPOSED in those files; a copy change edits the
> builder, not this script. Nothing here was heard on a screen reader. Mark a step P/F only from what you hear.
> A `SURFACE PENDING` script cannot be executed until the named ticket mounts its surface.
> Oracle: the spec row or the `Source` formatter `file:line` each step verifies. `heuristic: true` marks a row
> derived by an agent from source, never heard; a human pass may correct it. Lag column: note any keypress-to-speech delay over about 200 ms as an E46 candidate.

## Steps

| Step  | Keys                                                                 | Expected announcement                                                                                                                                           | Source                                                | Oracle         | Heuristic       | Lag | P/F           |
| ----- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| XC-01 | Tab to the top bar                                                   | `Trading environment: Demo` (read first; **fail the script if it says Live**)                                                                                   | apps/web/src/features/app-shell/TopBarEnvBadge.tsx:47 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| XC-02 | Open the login page, then submit valid credentials and the TOTP code | Record each prompt, field name and error verbatim; no scripted text (no shipped string is cited)                                                                | n/a                                                   | 05 §8.2 item 1 | heuristic: true |     | [ ] P / [ ] F |
| XC-03 | Landmark list (NVDA `D`, JAWS `R`, VoiceOver rotor)                  | Landmarks match 05 §3.4.1, including a "Primary" navigation                                                                                                     | apps/web/src/features/app-shell/AppShell.tsx:143      | Source column  | heuristic: true |     | [ ] P / [ ] F |
| XC-04 | Switch symbol via watchlist search                                   | The chart update is announced once and not flooded (SURFACE PENDING E10-S03: search is T2)                                                                      | apps/web/src/features/app-shell/TopBarSlot.tsx:19     | Source column  | heuristic: true |     | [ ] P / [ ] F |
| XC-05 | `Ctrl+Shift+M`                                                       | Record what is said; the reduced-motion override flips and focus does not move                                                                                  | apps/web/src/keymap/shellCommands.ts:15               | Source column  | heuristic: true |     | [ ] P / [ ] F |
| XC-06 | Wait for a status change in the status bar                           | Said politely in the one "System status" region, not assertively                                                                                                | apps/web/src/features/app-shell/StatusBar.tsx:204     | Source column  | heuristic: true |     | [ ] P / [ ] F |
| XC-07 | Trigger a demo fill (fixture event)                                  | `{Filled or Partially filled}: {bought or sold} {qty} {symbol} at {price}[, {account}]`, assertive, once per batch; more than 3 fills end with `{n} more fills` | apps/web/src/chart/a11y/orderflowCopy.ts:87           | Source column  | heuristic: true |     | [ ] P / [ ] F |

## Notes

- XC-07 is the one live-region step; the shell hosts it at `apps/web/src/features/app-shell/announcer.tsx:87`.
- Record the §8.2 item 3 tasks that need surfaces not built yet (order ticket, flatten, Demo to Live) as
  `SURFACE PENDING` in the run record, not as passes.
