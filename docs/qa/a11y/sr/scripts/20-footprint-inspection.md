# Footprint inspection (mirror and table parity)

```yaml
script_id: FPI
title: "Footprint inspection (mirror and table parity)"
screens: [SCR-030]
status: "SURFACE PENDING E18-S11 #741 (footprint grid) and E11-S13 #520 (mirror)"
env: demo
fixture: "Recorded footprint bars from packages/fixtures with one bid-flagged and one ask-flagged imbalance."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "#5371 merged (main sha e5b286ed50d3a320d80b24df5030fb09dd405a4a)"
  - "#5467 e85bc42066f7aed9e352dc28f0bfc955f4dca1a5 (open, if merges as is)"
  - "#5480 ac723c054eeae35373056f1bc8c0f1fea0b84e7d (open, if merges as is)"
  - "E18-S11 #741: SURFACE PENDING (unbuilt)"
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

| Step   | Keys                                          | Expected announcement                                                                                                | Source                                        | Oracle         | Heuristic       | Lag | P/F           |
| ------ | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | -------------- | --------------- | --- | ------------- |
| FPI-01 | Enter the footprint grid                      | Record the grid's name and row count; no shipped string is cited                                                     | n/a                                           | 05 §8.2 item 1 | heuristic: true |     | [ ] P / [ ] F |
| FPI-02 | Arrow to a cell                               | `{price}, bid {b}, ask {a}, delta {+/−d}` with price first                                                           | apps/web/src/chart/a11y/orderflowFormat.ts:63 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| FPI-03 | Arrow to a flagged cell                       | The same, then `bid imbalance` or `ask imbalance`; an unflagged cell says nothing about imbalance                    | apps/web/src/chart/a11y/orderflowCopy.ts:22   | Source column  | heuristic: true |     | [ ] P / [ ] F |
| FPI-04 | Arrow to an order-estimated cell              | Ends with `estimated`                                                                                                | apps/web/src/chart/a11y/orderflowCopy.ts:23   | Source column  | heuristic: true |     | [ ] P / [ ] F |
| FPI-05 | Open the table (`Alt+T`), find the same level | Level columns price, bid, ask, delta, imbalance; imbalance reads `Bid-stacked` or `Ask-stacked`                      | apps/web/src/chart/a11y/copy.ts:27            | Source column  | heuristic: true |     | [ ] P / [ ] F |
| FPI-06 | Compare FPI-02 with the table level           | Same numbers: price, bid, ask, delta (data parity, 05 §8.2 item 3). Wording may differ: the table uses its own words | apps/web/src/chart/a11y/orderflowFormat.ts:63 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| FPI-07 | A bar with no footprint                       | `No footprint for this bar`                                                                                          | apps/web/src/chart/a11y/copy.ts:31            | Source column  | heuristic: true |     | [ ] P / [ ] F |
