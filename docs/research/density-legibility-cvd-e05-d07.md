# Research: density, numeric legibility & CVD palette validation (E05-D07)

Status: **heuristic evaluation** (no live participants — see Method note below). Feeds `docs/plan/16-design-system-brief.md` §2.1/§3 and `docs/plan/05-accessibility-standard.md` §4.

Ticket: E05-D07 · Epic: E05 (Design System) · Blocks: E05-D01 (Figma/Penpot Foundations)

## 0. Method note (agent-delivery adaptation, binding)

Per `docs/plan/backlog/all-tickets.json` E05-D07 "Agent-delivery adaptations" and `CLAUDE.md` §10:
delivery here is a solo AI-agent + single-owner org, so:

- **Moderated usability sessions → heuristic evaluation.** This report applies Nielsen's 10 heuristics
  plus the trading-specific heuristics implied by `05-accessibility-standard.md`, against a **static
  description of the stimulus** (no build exists yet — none is required pre-E05-D01). No participants,
  timings, or quotes are fabricated; every finding below is labelled **(heuristic)**.
- **CVD / contrast validation → computed programmatically.** Done for real (not simulated-as-a-finding):
  `docs/research/_tools/cvd_simulate.py` runs the actual Brettel-1997 dichromacy simulation (protanopia, deuteranopia; Machado 2009 for tritanopia) against the
  real token hex values in `packages/ui/tokens/primitives.tokens.json` /
  `packages/ui/tokens/semantic-dark.tokens.json`, and the real WCAG contrast formula. Its output is
  `docs/research/artifacts/E05-D07/cvd_simulation.md` (committed evidence, not a screenshot).
- A **written session protocol** (§5) is included, ready for the owner to run later with real
  participants; findings from that run should be appended to this file as a dated addendum rather than
  overwriting §§1-4.
- An **owner walkthrough checklist** is posted on issue #114 per the adaptation.

## 1. Density: compact/comfortable row & field heights

**Proposal under test** (`16-design-system-brief.md` §3): compact 24px row / 28px field; comfortable
36px row / 40px field.

**Token cross-check** — `packages/ui/tokens/primitives.tokens.json` already defines:

| Token                      | Value |
| -------------------------- | ----- |
| `size.row.compact`         | 24px  |
| `size.row.comfortable`     | 32px  |
| `size.control.compact`     | 24px  |
| `size.control.comfortable` | 32px  |
| `size.target.min`          | 24px  |

**Finding (heuristic) — comfortable row height should be 32px, not 36px.** The brief's prose proposes
36/40px, but the primitive tokens actually authored (E05-D01, already merged) use 32px for both
`size.row.comfortable` and `size.control.comfortable`. Re-reading the brief against WCAG 2.2 §2.5.8
(24×24px minimum) and the density principle (§1.3 "density is a mode, not a compromise"): 32px clears
the accessible minimum with headroom (+8px, i.e. +33%) while still being meaningfully denser than the
originally-proposed 36-40px for reading-heavy admin/settings surfaces. There is no participant data
contradicting 32px, and the shipped tokens are the closer-to-implementation artefact — **this report
confirms the brief's _intent_ (two-mode system, compact default for trading surfaces) but revises the
comfortable numeric value down to 32/32px to match what E05-D01 already shipped**, rather than forcing
a later token-breaking change. This is recorded as a brief amendment (§6 below), not a silent doc drift.

Compact 24px row / 24px field height (unifying `size.control.compact` = `size.row.compact` = 24px) is
**confirmed as final** — it is exactly WCAG's minimum floor, matching the essential-exception framing in
brief §3 rule 2: any control inside a 24px row that cannot itself be ≥24×24px needs the essential-exception
treatment (§3 below), it does not mean the row shrinks further.

**Heuristic evaluation — positions grid & DOM ladder scanning (heuristic, no live timing data):**

- Positions grid at 24px compact rows: walking through the described data (symbol, side, size, entry,
  mark, PnL, SL) at `font.size.xs`/`sm` (11/12px) monospace, the number of columns realistically legible
  without wrapping is 7-9 before truncation risk — consistent with `15-component-catalogue.md` CMP-107
  needing responsive column priority, not a token change.
- DOM ladder at 24px rows: heuristic walk-through of "find-the-largest-loss" / "find-the-price-level"
  tasks (the ticket's named task probes) suggests price-column left-alignment + tabular-figure monospace
  is necessary at compact density to keep digit columns aligned during fast repaint — this is _already_
  implied by `type.num.*` using `font.family.mono` (confirmed, no change needed).
- No participant session occurred, so no measured error/time rates exist; this is flagged as an open
  question in §7, not asserted as validated.

## 2. Numeric legibility: mono face candidates

**Candidates considered:** `JetBrains Mono` (currently `font.family.mono` in the shipped primitives) vs
a UI-family tabular-figure variant of `Inter` (`font.family.ui` with `font-variant-numeric: tabular-nums`).

**Decision: JetBrains Mono is confirmed as `font.family.mono`.** Rationale (heuristic, static-mock
review — no rendered-font A/B was run):

- JetBrains Mono is purpose-built for dense numeric/code columns: consistent glyph width, distinct
  `0`/`O`, `1`/`l`/`I`, `8`/`B` shapes — the exact ambiguity classes that matter for price/qty misreads
  in an execution UI (safety-relevant per `CLAUDE.md` §1 "it moves real money").
- It is already uploaded to the team's Penpot font library (`docs/design/README.md` "Fonts" section,
  2026-09-25) and referenced by every `type.num.*` token in `semantic-dark.tokens.json` — reversing this
  decision now would be a breaking, unforced token change.
- A tabular-nums `Inter` variant was not prototyped/tested; the comparison here is a font-metrics/glyph
  design review, not a timed legibility test. Per the ticket's Gherkin ("Mono face is decided ... or the
  decision is explicitly deferred with the blocking question named"): **decision is not deferred** —
  JetBrains Mono is selected — but the **comparative timed-legibility test itself is deferred** to the
  owner-run session (§5), since no build/stimulus exists yet to run it against. This is recorded as an
  open question in §7, not a blocker (adaptation: heuristic evaluation stands in for the missing session).

`font.size.xs` (11px) / `font.size.sm` (12px) against `surface.app` (`#0B0E11`) / `surface.canvas`:
contrast for the primary text token (`#E8EAED` equivalent used at `color.text.*`) computed via the same
WCAG formula as `cvd_simulate.py` clears AA body-text 4.5:1 comfortably at both surfaces (near-black vs
off-white is a >15:1 pair) — no legibility risk from contrast at these sizes; risk if any is purely
glyph-shape/x-height at 11px, which is why the mono family choice (not size) is the load-bearing decision.

## 3. Essential-exception list (compact-mode sub-24px controls)

Per brief §3 rule 2, walking `15-component-catalogue.md` CMP-100..139 for compact-row-embedded controls
that cannot reach 24×24px without breaking row density:

| CMP-*                                                         | Control                                          | Why it can't be 24×24px in a 24px row                                                                                                                        | Compensating control                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-108 DomLadderRow                                          | inline buy/sell click-to-trade glyph per row     | Row itself is 24px tall; a 24×24 hit target would consume the entire row height leaving no margin between rows, defeating scan density                       | Invisible padding extends the true hit target to the full row height/width band even though the visual glyph is ~16px; 1px visual separator + `:hover` background-tint gives a mis-tap guard; documented in CMP-108's Storybook a11y notes per brief §3 rule 2                                                                                                                     |
| CMP-109 FootprintCell                                         | per-cell bid/ask numeric click target (drill-in) | Cell grid density is the entire point of footprint — cells are frequently <24px square at deep zoom-out                                                      | Whole-cell click area already matches the rendered cell bounds (which vary with zoom); at zoom levels where a cell would render <24px, the DOM-mirror surrogate (05-accessibility-standard.md §6.1) is sized to the _visible_ cell, and keyboard/focus navigation (not pointer precision) is the accessible path — flagged as CMP-109's primary a11y strategy, not a padding trick |
| CMP-113 HeatmapLegend row (per §"Trading-specific" catalogue) | legend swatch + label repeated per ramp stop     | Legend rows are informational, not primary click targets, but a click-to-filter-by-stop interaction (if added) would be undersized at compact legend density | If added: legend rows are given `size.control.comfortable` (32px) height even in an otherwise-compact panel — legends are exempted from row-height inheritance, per no-shrink-below-minimum in brief §3 rule 2                                                                                                                                                                     |

Any other compact-mode control **not** on this list must meet 24×24px unconditionally (brief §3 rule 2)
— this includes CMP-102 SideToggle, CMP-100/101 numeric inputs' step buttons, and CMP-107 OrderTicket's
submit button, none of which are compressed below `size.control.compact` (24px) in any density mode.

## 4. CVD validation — buy/sell pairs & heatmap ramps

Full machine-generated evidence: `docs/research/artifacts/E05-D07/cvd_simulation.md` (run via
`python docs/research/_tools/cvd_simulate.py`).

**Summary:**

- Two candidate buy/sell pairs were tested: pair-A (`color.buy.default` #2EBD59 / `color.sell.default`
  #E5484D) and pair-B (`color.buy.hc` #6BD48A / `color.sell.hc` #F08A8A, the high-contrast-theme variant).
- Both pairs pass WCAG AA 3:1 non-text contrast against `surface.app` (#0B0E11) in normal vision: pair-A
  7.87:1 / 4.94:1, pair-B 10.51:1 / 8.02:1.
- Both pairs remain separable (CIE76 `dE` ≥ 5.0, the conservative JND floor used here) between simulated
  buy and simulated sell swatches under all three dichromacies (deuteranopia, protanopia, tritanopia) —
  full per-deficiency `dE` values in the artefact.
- **Both pairs are recommended as the two CVD-safe buy/sell pairs** — pair-A for the default dark theme,
  pair-B for the `.hc`/high-contrast theme toggle (`Ctrl+Shift+H`) — matching the brief's existing §2.1
  design (`color.buy`/`color.sell` + `.hc` variants) exactly. This is confirmation, not a change.
- Both heatmap ramps (`green-bid-red-ask`, `red-bid-green-ask` — same 5 stops per side, sides swapped)
  were simulated; **zero adjacent-stop pairs fall below the JND floor** under any of the 3 deficiencies —
  no ramp stop requires re-tuning.

**Caveat (heuristic vs. computed):** this is a colourimetric simulation, not a human CVD-participant
session. It is the "computed programmatically" adaptation explicitly permitted by the ticket's
Agent-delivery adaptations block, and is intended to seed the automated check E05-T05 builds on, per the
ticket's Technical notes ("the CVD simulation script is handed to E05-T05 as the seed").

## 5. Session protocol (written, ready for the owner to run)

**Positions-grid scanning task** ("find-the-largest-loss"):

1. Present a static/replay positions grid (≥12 rows) at compact density.
2. Time-to-first-correct-click, per participant, per density mode (compact vs comfortable), per mono
   candidate (if a second candidate is prototyped).
3. Record error count (wrong row clicked) and verbal confusion notes.

**DOM-ladder scanning task** ("find-the-price-level"):

1. Present a static DOM ladder (≥20 price rows) with a target price called out verbally.
2. Time-to-first-correct-click; record whether compact row height caused adjacent-row mis-clicks.

**Zoom/text-scale check:** at least one session includes a participant setting OS text scale to 125%
and 200%, confirming the compact-density table reflows to the card/stacked layout
(`05-accessibility-standard.md` §5.7) rather than clipping.

**Structure:** ≥3 sessions total covering both tasks (ticket's Gherkin minimum), notes stored without
identifying details (session notes: first name only, per ticket's Security notes), CVD screenshots
(Able/Stark/Chrome DevTools vision-deficiency emulation) attached alongside the programmatic simulation
above as a cross-check.

## 6. Brief amendment (recorded per Gherkin "Density decision is evidence-backed")

`docs/plan/16-design-system-brief.md` §3 table's **comfortable row/field height is amended from
36px/40px to 32px/32px**, to match the already-shipped `size.row.comfortable` / `size.control.comfortable`
primitive tokens (E05-D01). Compact 24px/24px is confirmed unchanged. Amendment applied directly to the
brief's §3 table (inline note, dated 2026-09-25) and §2.1's CVD-pair confirmation, in this PR.

## 7. Open questions (for owner walkthrough)

1. **Comparative timed mono-face test** (JetBrains Mono vs a tabular-nums Inter variant) was not run —
   no build/stimulus exists yet to test against. Decision stands (JetBrains Mono) but the owner may want
   to commission this test once E05-D01/CMP-build reaches a renderable positions-grid prototype.
2. **No live participant sessions occurred** — every scanning-speed/error-rate claim above is a heuristic
   walkthrough, not measured data. The protocol in §5 is ready to run.
3. **JND floor (dE76 ≥ 5.0)** used for ramp/pair separability is a documented, conservative choice, not a
   WCAG-mandated number (WCAG has no CVD-specific numeric contrast rule) — flagging for Accessibility-role
   review at design sign-off in case a stricter or looser floor is preferred for E05-T05's automated gate.
