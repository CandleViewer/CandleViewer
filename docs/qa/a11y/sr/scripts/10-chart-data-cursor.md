# Chart data cursor and SCR-045 table

```yaml
script_id: CDC
title: "Chart data cursor and SCR-045 table"
screens: [SCR-030, SCR-045]
status: "SURFACE PENDING E47-S01 #1316 (keyboard cursor and mirror sit with E11-S13 #520)"
env: demo
fixture: "Recorded BTCUSDT 1m series from packages/fixtures, at least 60 bars, a footprint on the bar under test."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "#5278 merged (main sha 086784fcc496de152c0f1ba9c9f8eeae36486c42)"
  - "#5467 e85bc42066f7aed9e352dc28f0bfc955f4dca1a5 (open, if merges as is)"
  - "#5480 ac723c054eeae35373056f1bc8c0f1fea0b84e7d (open, if merges as is)"
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

| Step   | Keys                                         | Expected announcement                                                                                                              | Source                                | Oracle        | Heuristic       | Lag | P/F           |
| ------ | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ------------- | --------------- | --- | ------------- |
| CDC-01 | Tab to the chart                             | The chart view is named and the table toggle hint reads `Table view — Alt+T`                                                       | apps/web/src/chart/a11y/copy.ts:11    | Source column | heuristic: true |     | [ ] P / [ ] F |
| CDC-02 | Arrow to a bar                               | `{hh:mm}, open {O}, high {H}, low {L}, close {C}, volume {V}, delta {+/−D}`; prices grouped with `,`, a negative delta with U+2212 | apps/web/src/chart/a11y/format.ts:142 | Source column | heuristic: true |     | [ ] P / [ ] F |
| CDC-03 | Arrow to a bar with no footprint             | The sentence ends at `volume {V}`; no delta is said                                                                                | apps/web/src/chart/a11y/format.ts:142 | Source column | heuristic: true |     | [ ] P / [ ] F |
| CDC-04 | `Alt+T`                                      | `Table view — Alt+T` is the control's hint; record that the table receives focus and its caption reads `{n} bars loaded`           | apps/web/src/chart/a11y/copy.ts:42    | Source column | heuristic: true |     | [ ] P / [ ] F |
| CDC-05 | Arrow down in the table                      | `Data table, row {r} of {n}`                                                                                                       | apps/web/src/chart/a11y/copy.ts:49    | Source column | heuristic: true |     | [ ] P / [ ] F |
| CDC-06 | Expand a bar's levels                        | `Expanded, {k} levels`; each level reads `Level {i} of {k}, bar {hh:mm}`                                                           | apps/web/src/chart/a11y/copy.ts:51    | Source column | heuristic: true |     | [ ] P / [ ] F |
| CDC-07 | Compare CDC-02 and the table row for one bar | Same values and wording from both (one builder feeds both)                                                                         | apps/web/src/chart/a11y/format.ts:142 | Source column | heuristic: true |     | [ ] P / [ ] F |
| CDC-08 | `Alt+T` again                                | `Chart view`, focus back on the chart                                                                                              | apps/web/src/chart/a11y/copy.ts:48    | Source column | heuristic: true |     | [ ] P / [ ] F |
