# Order ticket: limit order through the confirm

```yaml
script_id: ORD
title: "Order ticket: limit order through the confirm"
screens: [SCR-060, SCR-076, SCR-063]
status: "SURFACE PENDING E30-S01, E30-S04 and E30-S06 (SCR-060 ticket, SCR-076 confirm, risk preview)"
env: demo
fixture: "Replay fixture from E47-Q01 (F-RPL-2K, tape streaming) and a demo account F-ACC-DEMO-1 with no open orders; a second, inaccessible account that must never be named."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "E30-S01 (SCR-060 order ticket): SURFACE PENDING (unbuilt)"
  - "E30-S04 (arm, badge, SCR-076 confirm): SURFACE PENDING (unbuilt)"
  - "E30-S06 (risk preview, account selector): SURFACE PENDING (unbuilt)"
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

> **NEVER AGAINST LIVE.** Run on Demo only. If ORD-01 does not read Demo, stop: the pass is void and nothing was
> done. Demo orders go via REST only (C-2.11). Case ids link to `qa/plans/e47-accessibility-test-plan.md`: ORD-10 is the manual leg of E47-TC-204, ORD-06 and ORD-07 of E47-TC-205.

## Steps

| Step   | Keys                                                                                                                               | Expected announcement                                                                                                                                                                                                                                             | Source                                                | Oracle         | Heuristic       | Lag | P/F           |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| ORD-01 | [SCR-075 · SC 1.4.1 4.1.2] Tab to the top bar                                                                                      | `Trading environment: Demo` (read first). **Stop and fail the script if it says Live**; nothing was placed                                                                                                                                                        | apps/web/src/features/app-shell/TopBarEnvBadge.tsx:47 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| ORD-02 | [SCR-060 · SC 2.4.3 3.2.1] Move to the SCR-060 ticket from the chart (key per E30-S01; record it)                                  | Record the ticket name, landmark and first focused control verbatim; focus lands once and is not stolen (SURFACE PENDING E30-S01)                                                                                                                                 | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-03 | [SCR-060 · SC 1.3.1 4.1.2 1.4.1] Select side Buy, entry type Limit, then enter price and quantity                                  | Record each control's name, role and value verbatim; side and entry type are said as words, not colour (SURFACE PENDING E30-S01)                                                                                                                                  | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-04 | [SCR-060 · SC 3.3.2 4.1.2] Select the demo account and read the risk preview                                                       | Record the account name, risk preview and native stop-loss field verbatim; the mandatory stop-loss field is reachable and named (SURFACE PENDING E30-S03)                                                                                                         | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-05 | [SCR-060 · SC 3.3.1 3.3.3] Submit with a required field empty                                                                      | Record the error verbatim; it names the field and says what is wrong; focus goes to the first invalid control (SURFACE PENDING E30-S01)                                                                                                                           | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-06 | [SCR-060 SCR-053 · SC 3.2.1 4.1.3] With F-RPL-2K playing and the tape panel streaming, Tab away from the price field and wait 10 s | Focus stays on the control you left it on; record the count of utterances in 10 s (more than 6 fails). **Any silent focus move is a P0 defect regardless of cause** (AC4); record it verbatim (SURFACE PENDING E30-S01)                                           | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-07 | [SCR-060 · SC 3.2.1 2.2.2] Same, then burst: let the fixture raise its update rate while you type a quantity                       | Typing is not interrupted; no announcement lands inside the field; focus and caret stay put (twin of E47-TC-205 and the Q03 no-focus-in-WebSocket-handler assertion, `qa/plans/e47-accessibility-test-plan.md` §10); record it verbatim (SURFACE PENDING E30-S01) | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-08 | [SCR-076 · SC 4.1.2 3.3.4] Press the submit key (per E30-S04; record it)                                                           | SCR-076 opens as a dialog and is announced first: record the title and the read-back verbatim. It must name side, price, quantity and account and the environment (Demo) (SURFACE PENDING E30-S04)                                                                | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-09 | [SCR-076 · SC 2.1.2 2.4.3] Tab inside SCR-076, then `Esc`                                                                          | Focus is trapped in the dialog and `Esc` cancels; focus returns to the ticket control that opened it; record what is said on return; record it verbatim (SURFACE PENDING E30-S04)                                                                                 | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-10 | [SCR-076 SCR-063 · SC 4.1.3 3.3.4] Reopen SCR-076 and confirm (Enter on the confirm button)                                        | Record the confirmation verbatim; then the acceptance or rejection arrives once, assertively, naming side, size, symbol, price (SURFACE PENDING E30-S04)                                                                                                          | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-11 | [SCR-063 · SC 1.4.1 4.1.2] Open the SCR-063 working-orders tab and find the order                                                  | Record the row verbatim: status word (working, filled, rejected, cancelled) in text, not colour (SURFACE PENDING E29-S02)                                                                                                                                         | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ORD-12 | [SCR-076 · SC 3.3.4 1.3.1] Select a two-account target, then an inaccessible account                                               | Record the per-account lines; no inaccessible account name or id is said (SURFACE PENDING E30-S06)                                                                                                                                                                | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |

## Notes

- ORD-06 and ORD-07 are the AC4 focus-steal check (E47-Q02 #1355, BQ-07). The automated twin is the E47-Q03 keyboard suite; link them by case id when Q03 lands (`E47-TC-205`, `E47-TC-204`, `E47-TC-121`).
- Order amounts are demo sizes only (for example a 0.001 contract). No Live key or credential is used or named.
- ORD-08 to ORD-10 also cover the confirm-dialog operability of 05 §8.2 item 3.
