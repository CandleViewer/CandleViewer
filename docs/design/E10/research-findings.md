# E10 shell — research findings (heuristic evaluation)

**Status**: heuristic evaluation only. Per the ticket's binding Agent-delivery adaptations
(owner decision 2026-09-25), moderated usability / participant sessions are substituted with a
documented heuristic evaluation plus a ready-to-run session protocol for the owner to execute later.
**No participants, timings or quotes below are real or fabricated** — every finding is labelled
`(heuristic)` and derives from applying Nielsen's heuristics and the trading-specific heuristics in
`docs/plan/05-accessibility-standard.md` to the SCR-010 shell anatomy and CMP-211 (panic control)
candidate placements.

This document is the (re-created) source the ticket calls "E10-D01 output"
(`docs/design/research/e10-shell-ia.md`); E10-D01 was withdrawn and its research absorbed into
E10-D02 per the ticket body, so this file lives under `docs/design/E10/` as the ticket's own
research artefact rather than a separate E10-D01 deliverable.

## Study 1 (adapted) — environment legibility `(heuristic)`

**Original design**: 5 participants (owner + 2 managers + 2 proxies) view greyscale and colour mock
chrome for DEMO/LIVE at 3 m viewing distance, 1920x1080 and 2560x1440. Gate: 5/5 correct ID in both
conditions.

**Heuristic evaluation applied instead**:

- Nielsen #1 (visibility of system status) + #4 (consistency): the ENV badge must be legible without
  colour (label text "DEMO"/"LIVE" always rendered, not an icon/colour-only chip) and must appear at
  two independent scan positions (TopBar + StatusBar) so a glance at either confirms environment.
- Trading-specific heuristic (irreversible-action legibility, `05-accessibility-standard.md`): any
  region that can trigger a live order must carry the environment signal within the same visual
  fixation as the action, not requiring a separate glance to the top bar.
- **Decision carried into SCR-010**: badge text is never abbreviated to a single letter/icon, uses
  `color.env.demo` / `color.env.live` tokens for the _background_ only (redundant with text), and is
  duplicated in StatusBar. This satisfies the _design intent_ of the gate (colour-independent,
  redundant, always-visible) without claiming the 5/5-participant pass/fail result was measured.
  **Superseded by ruling 2 (#137 re-QA)**: the env colour is only the badge's 2 px border and dot; the
  word stays in `color.text.primary` on `color.surface.raised`. See `E10-D02.md`.

**Not yet done**: the actual 5-participant colour/greyscale pass-rate measurement. A ready-to-run
protocol is below for the owner to execute; until run, this ticket does **not** claim the gate passed.

## Study 2 (adapted) — panic-control reachability `(heuristic)`

**Original design**: accidental-activation count over a 15-minute simulated session across candidate
CMP-211 placements, plus time-to-activate when deliberately sought. Gate: zero accidental activations,
deliberate activation <=2s.

**Heuristic evaluation applied instead**:

- Nielsen #5 (error prevention) + #9 (help users recognize/recover from errors): a control this
  consequential should (a) sit apart from high-frequency-click regions (order entry, panel tabs),
  (b) require a hold or typed confirmation rather than a single click, (c) have a visibly larger hit
  target than adjacent controls, (d) never share a hover state with a non-destructive control.
- Candidate placements considered: RightRail top (isolated above positions/orders), StatusBar
  (rejected — too close to high-frequency health-chip glance/click area), TopBar far-right (rejected —
  adjacent to workspace switcher, higher accidental-click risk from switcher misclicks).
- **Decision carried into SCR-010**: RightRail top, own sub-region, hold-to-confirm (per Security
  notes in the spec) — chosen because it best satisfies error-prevention heuristics among the
  candidates, not because a live 15-minute session measured zero accidental activations.
  **Superseded by ruling 1 (#137 re-QA)**: the Safety cluster (CMP-211) sits at the right of the TopBar
  on every screen and FREEZE… opens one confirmation (E39-D01). See `E10-D02.md`.

**Not yet done**: the actual accidental-activation count and deliberate-activation timing. Protocol
below.

## Ready-to-run session protocol (for the owner)

**Study 1 — environment legibility**

1. Prepare 2 static exports of SCR-010 (DEMO, LIVE) at 1920x1080 and 2560x1440, each in full colour
   and in a desaturated/greyscale filter.
2. Seat each participant (owner + 2 managers + 2 proxies) 3 m from the display.
3. Show each of the 8 combinations (2 env × 2 breakpoints × 2 colour conditions) in randomised order;
   ask "Is this DEMO or LIVE?"; record correct/incorrect.
4. Gate: 5/5 correct per combination. Any failing combination is reworked (badge size/contrast/copy)
   and re-tested before sign-off.

**Study 2 — panic-control reachability**

1. Build an interactive prototype (or the drawn Penpot frame with click-through) of SCR-010 with
   CMP-211 at the RightRail-top placement.
2. Each participant runs a 15-minute simulated trading session performing routine tasks (switch
   workspace, open command palette, adjust an order) — log every click within CMP-211's hit area that
   was not an intentional panic activation.
3. Separately, ask each participant to deliberately activate the panic control as fast as possible;
   record time from cue to completed hold/typed-confirm.
4. Gate: zero accidental activations across all participants; deliberate activation <=2s for each.

Record real results in a new section of this file (or a dated addendum) once run — do not overwrite
the `(heuristic)` sections above; append.

## Deferred studies (not dropped)

The navigation card-sort / first-click study (R-100..R-360 route groups) and the health-chip
vocabulary study are explicitly **deferred to E15**, which owns the workspace switcher and command
surfaces they inform (per the E10-D02 ticket body). They are carried by **#1479** (E15).
