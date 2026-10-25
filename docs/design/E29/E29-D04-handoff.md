# E29-D04 — Per-component hand-off (`16` §11.4; the blotter design-system contributions)

Four entries written whole — CMP-114 PositionsGrid, CMP-115 OrderRow, CMP-116 PnLBadge and CMP-129 PositionModeToggle — and the field deltas to CMP-123 FlattenAllButton, the CMP-049 base table and the CMP-105 reuse contract, plus the `16` motion block. The spec is [E29-D04.md](E29-D04.md); every "§" below without a prefix is the spec's. Nothing here edits `15` or `16`: §C is copy-ready, applied verbatim by E29-T09 (the plan-reconciliation ticket) after the owner's approval (RULED BQ-2, comment 6399392172; departs from the ticket text; owner approval pending (#2701)). Every figure carries its `audit` marker from the tool's `--json`; E29-T09 keeps the value and drops the marker when it pastes a block. Base `6fc8aacc6`; D01 is cited at its merge `9da45ae35`, D02 at `c4270ba93` (text) and `75a33c164` (boards), D03 at `a59ba382b` (text; its boards #4472 PENDING).

## §A Placement

> **To write (assembler):** A | Component | Form | Placement in `15`, one row per copy-ready row of §C and the `16` block.

## §B Density and theme matrix

> **To write (assembler):** Entry | dark compact | dark comfortable | light compact | light comfortable | high contrast, every cell a board, "on request" or the spec section.

## §C Copy-ready `15` entries and the `16` block (PROPOSED; E29-T09 applies them after the owner's approval)

> **To write (components and motion writers):** one line on the form: whole entries in `15` §0.1 bullet order, the A11y bullet carrying Keyboard, Accessible name and Live region; Table A for field deltas, Old verbatim at its `15` line.

### C.1 A-1 — CMP-114 PositionsGrid

> **To write (components writer):** the whole entry, fenced, in `15` §0.1 order.

### C.2 A-2 — CMP-115 OrderRow

> **To write (components writer):** the whole entry, fenced, in `15` §0.1 order.

### C.3 A-3 — CMP-116 PnLBadge

> **To write (components writer):** the whole entry, fenced, in `15` §0.1 order.

### C.4 A-4 — CMP-129 PositionModeToggle

> **To write (components writer):** the whole entry, fenced, in `15` §0.1 order.

### C.5 Table A — Old (verbatim at `6fc8aacc6`) → New, field by field

> **To write (components writer):** A | Component | Field (`15`:line) | Old (verbatim) | New, for CMP-123 (composing E33-D04 A-6, PENDING), CMP-049 and CMP-105.

### C.6 The `16` block (copy-ready; recipe owner E05-D03 (#3174); applied by E29-T09)

> **To write (motion writer):** the fenced block in `16` §7.1's shape: a Spec line, the tokens used by name, a Surface | Enter | Hold / clear | Source table with `prefers-reduced-motion` in every Enter cell, and the rules.

## §D Storybook stories per entry

> **To write (assembler):** Entry | Stories, every story in dark and light × compact and comfortable (`15`:41).

## §E Test hooks

> **To write (assembler):** Entry | Tests: axe, keyboard, the live-region cadence, the reduced-motion twin, the T2 and exits tests.

## §F Open items

> **To write (assembler):** the open questions and hand-offs, each with its owner.
