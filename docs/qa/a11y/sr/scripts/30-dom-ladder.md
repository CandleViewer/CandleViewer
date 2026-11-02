# DOM ladder, demo order place and cancel

```yaml
script_id: DOM
title: "DOM ladder, demo order place and cancel"
screens: [SCR-050, SCR-060]
status: "SURFACE PENDING E21-S01 #648 (ladder) and the SCR-060 order ticket"
env: demo
fixture: "Recorded BTCUSDT book from packages/fixtures; a demo account with no open orders; a second, inaccessible account that must never be named."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "#5371 merged (main sha e5b286ed50d3a320d80b24df5030fb09dd405a4a)"
  - "E21-S01 #648: SURFACE PENDING (unbuilt)"
  - "E21-S02 #649: SURFACE PENDING (unbuilt)"
  - "#5419 91e9bde449dc29325efd23e3e1f2fd5a34867351 (open, if merges as is)"
dry_run: pending
```

> **Expected text is a contract, not an observation.** It is derived from the shipped sentence builders cited per
> step (`file:line`), written as a pattern with fields. Wording is PROPOSED in those files; a copy change edits the
> builder, not this script. Nothing here was heard on a screen reader. Mark a step P/F only from what you hear.
> A `SURFACE PENDING` script cannot be executed until the named ticket mounts its surface.
> Oracle: the spec row or the `Source` formatter `file:line` each step verifies. `heuristic: true` marks a row
> derived by an agent from source, never heard; a human pass may correct it. Lag column: note any keypress-to-speech delay over about 200 ms as an E46 candidate.

> **NEVER AGAINST LIVE.** Every step below places or cancels an order. Run it on Demo only. If DOM-01 does not read
> Demo, stop: the pass is void and nothing was placed. Demo orders go via REST only (C-2.11).

## Steps

| Step   | Keys                                                                                           | Expected announcement                                                                                                                                                   | Source                                                | Oracle         | Heuristic       | Lag | P/F           |
| ------ | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| DOM-01 | Tab to the top bar                                                                             | `Trading environment: Demo`. **Stop and fail the script if it says Live**                                                                                               | apps/web/src/features/app-shell/TopBarEnvBadge.tsx:47 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-02 | Enter the ladder                                                                               | Grid named `{symbol} order book ladder`                                                                                                                                 | apps/web/src/chart/a11y/orderflowCopy.ts:95           | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-03 | Arrow to a bid row                                                                             | `{price}, bid {b}, ask {a}, bid side`                                                                                                                                   | apps/web/src/chart/a11y/orderflowFormat.ts:99         | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-04 | Arrow to the spread row                                                                        | `{price}, bid {b}, ask {a}, inside the spread`                                                                                                                          | apps/web/src/chart/a11y/orderflowCopy.ts:28           | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-05 | Arrow to an ask row                                                                            | The same ending `ask side`                                                                                                                                              | apps/web/src/chart/a11y/orderflowCopy.ts:28           | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-06 | Start a limit buy on the focused row (key per E21-S01 and the order-ticket binding; record it) | The read-back before commit: `Limit buy {SYMBOL}, DEMO, at {price}. {account}: {qty} {unit}. 1 account, total {qty} {unit}`. It names side, price, quantity and account | apps/web/src/chart/a11y/readback.ts:165               | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-07 | Same, with two target accounts                                                                 | One `{account}: {qty}` per account, then `2 accounts, total {qty}`                                                                                                      | apps/web/src/chart/a11y/orderflowCopy.ts:72           | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-08 | Same, with an inaccessible account selected                                                    | `Order not shown: an account is not available to you`; no account name or id is said                                                                                    | apps/web/src/chart/a11y/orderflowCopy.ts:75           | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-09 | Confirm the DOM-06 order                                                                       | Record the confirm and any rejection verbatim; no scripted text                                                                                                         | n/a                                                   | 05 §8.2 item 1 | heuristic: true |     | [ ] P / [ ] F |
| DOM-10 | Return to the placed row                                                                       | Ends with `your buy order {qty} working`                                                                                                                                | apps/web/src/chart/a11y/orderflowCopy.ts:29           | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-11 | Cancel the order (key per E21-S01; record it) and confirm                                      | Record the cancel confirmation verbatim; the row no longer says `working`                                                                                               | n/a                                                   | 05 §8.2 item 1 | heuristic: true |     | [ ] P / [ ] F |
| DOM-12 | Trigger a demo fill (fixture event)                                                            | `Filled: bought {qty} {symbol} at {price}, {account}`, assertive                                                                                                        | apps/web/src/chart/a11y/orderflowCopy.ts:87           | Source column  | heuristic: true |     | [ ] P / [ ] F |
| DOM-13 | Focus an empty ladder                                                                          | `No price levels in the book`                                                                                                                                           | apps/web/src/chart/a11y/orderflowCopy.ts:38           | Source column  | heuristic: true |     | [ ] P / [ ] F |
