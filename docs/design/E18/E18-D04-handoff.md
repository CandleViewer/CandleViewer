# E18-D04 — hand-off: copy-ready A-rows and the motion-pair lines

**Ticket:** E18-D04 (#498) · **PR:** 1b, the second of two (`Refs #498`, `Partial: E18-D03 #497 is open` while it is; §14 of the spec) · **Status:** every row PROPOSED until its owner stamps it; nothing here is applied by this ticket. The spec is `docs/design/E18/E18-D04.md` (§10.3 lists these rows with their owners). The owner walks them from the checklist on #498 (comment 6626707818; spec §12). This hand-off holds only §C and the motion-pair lines; §A, §B and §D–§G belong to E18-D05 #499, the hand-off pack ticket.

## Motion-pair lines for the `16` §11.4 checklists

The checklist line each consuming component's hand-off pastes (`16`:751 item 8; D03's "motion pair N/A → E18-D04" closes here):

- [ ] CMP-109 FootprintCell — motion pair: E18-D04 §2 M-01 … M-04, M-11 (safe) / every reduce cell `instant` (reduce); the holds of §3 and §4.
- [ ] CMP-182 FootprintSeries — motion pair: E18-D04 §2 M-05 … M-12, M-15, M-16 (safe) / every reduce cell `instant` (reduce); §5's LOD rule.
- [ ] CMP-228 PreviewTile, `kind: "footprint"` — motion pair: E18-D04 §2 M-14 (safe) / `instant` (reduce and canvas calm).

## §C Copy-ready A-rows

**Rules.** Old is the whole current line at the base `c56a10bc3`, verbatim; New is the exact text the owner writes; an "insert after" row adds its New after the named line. 8 rows.

### A-1 · CMP-109 · `15`:1292 · insert after

Purpose: Link the motion spec and accessibility review from CMP-109 (T DoD 5). It lands after E18-D03's A-6, which also inserts after this line.

Old:

```text
- **As built (E47-S02, #1358), the non-colour channel and the target-size exception**: `footprintCellSentence` ("64,010.5, bid 12, ask 20, delta +8, ask imbalance"; an unflagged cell says nothing about imbalance; ", estimated" for order-estimated input) and `FootprintCellContent`: the delta as `+`/`−` plus ▲/▼, an imbalance as a dashed border (`border.thick`, `color.footprint.imbalance`, `CanvasText` in forced colours), a corner glyph and the words "Bid imbalance"/"Ask imbalance" (PROPOSED, E18-D04 #498 / E47-D06 #1305). The footprint keys on the shared grid: ↑/↓ price, ←/→ bar, `PageUp`/`PageDown` by bar, `Home`/`End` the bar's first and last cell (`homeEnd: "col"`, PROPOSED: it departs from the APG grid's row ends, for E18-D04 #498 to confirm or return to row ends). Target size (SC 2.5.8, `05` §3.4.7): cells below 24 CSS px at maximum zoom-out are the recorded essential exception `E47-S02-TSE-01` (`targetSize.ts`), SCR-045 the compensating alternative; the spacing and equivalent exceptions do not apply (cells abut; SCR-045 is another screen), and the default-zoom cell size is a carried pixel measure. The cells and their mount are E18-S01 / E18-S11 #741.
```

New:

```text
- **Motion and accessibility review** (E18-D04): `docs/design/E18/E18-D04.md` — the motion table with a reduce variant for every moment (§2), the flicker policy (§3, §4), the LOD text crossfade (§5) and the announcement policy table (§7.3).
```

### A-2 · CMP-182 · `15`:2396 · insert after

Purpose: Link the motion spec from CMP-182 (T DoD 5).

Old:

```text
- **Tests**: unit, visual, axe (mirror), performance (dense grid — the flagged largest-risk perf target, explicit spike-derived budget from `24-owner-decisions.md` §2.1).
```

New:

```text
- **Motion and accessibility review** (E18-D04): `docs/design/E18/E18-D04.md` — §2 (the moments), §5 (the LOD text crossfade on the dead band, fills one frame) and §7 (focus order, keys, announcements).
```

### A-3 · CMP-109 · `15`:1292 · replace

Purpose: C-1358-HOMEEND (BQ-8): confirm `homeEnd: "col"` for the expanded level window only; only the Home / End sentence changes. It lands after E18-D03's A-6, which also inserts after this line.

Old:

```text
- **As built (E47-S02, #1358), the non-colour channel and the target-size exception**: `footprintCellSentence` ("64,010.5, bid 12, ask 20, delta +8, ask imbalance"; an unflagged cell says nothing about imbalance; ", estimated" for order-estimated input) and `FootprintCellContent`: the delta as `+`/`−` plus ▲/▼, an imbalance as a dashed border (`border.thick`, `color.footprint.imbalance`, `CanvasText` in forced colours), a corner glyph and the words "Bid imbalance"/"Ask imbalance" (PROPOSED, E18-D04 #498 / E47-D06 #1305). The footprint keys on the shared grid: ↑/↓ price, ←/→ bar, `PageUp`/`PageDown` by bar, `Home`/`End` the bar's first and last cell (`homeEnd: "col"`, PROPOSED: it departs from the APG grid's row ends, for E18-D04 #498 to confirm or return to row ends). Target size (SC 2.5.8, `05` §3.4.7): cells below 24 CSS px at maximum zoom-out are the recorded essential exception `E47-S02-TSE-01` (`targetSize.ts`), SCR-045 the compensating alternative; the spacing and equivalent exceptions do not apply (cells abut; SCR-045 is another screen), and the default-zoom cell size is a carried pixel measure. The cells and their mount are E18-S01 / E18-S11 #741.
```

New:

```text
- **As built (E47-S02, #1358), the non-colour channel and the target-size exception**: `footprintCellSentence` ("64,010.5, bid 12, ask 20, delta +8, ask imbalance"; an unflagged cell says nothing about imbalance; ", estimated" for order-estimated input) and `FootprintCellContent`: the delta as `+`/`−` plus ▲/▼, an imbalance as a dashed border (`border.thick`, `color.footprint.imbalance`, `CanvasText` in forced colours), a corner glyph and the words "Bid imbalance"/"Ask imbalance" (PROPOSED, E18-D04 #498 / E47-D06 #1305). The footprint keys on the shared grid: ↑/↓ price, ←/→ bar, `PageUp`/`PageDown` ten bars (the alias of `Shift+←` / `→`), `Home`/`End` the oldest loaded / latest bar at the bar level and, inside the expanded level window, the bar's first and last level (`homeEnd: "col"`, confirmed for that window only by E18-D04 §7.2; the APG row ends are not used). Target size (SC 2.5.8, `05` §3.4.7): cells below 24 CSS px at maximum zoom-out are the recorded essential exception `E47-S02-TSE-01` (`targetSize.ts`), SCR-045 the compensating alternative; the spacing and equivalent exceptions do not apply (cells abut; SCR-045 is another screen), and the default-zoom cell size is a carried pixel measure. The cells and their mount are E18-S01 / E18-S11 #741.
```

### A-4 · E11-D06 D14 · E11D06:232 · replace

Purpose: Narrow D14 to fills, outlines and the L2 / L3 collapse (BQ-3, RULED; C-3); only the quoted clause changes; applied after merge with the other A-rows.

Old:

```text
A candle LOD step (L0 → L1 at 10.2 px, L1 → L0 at 12 px; L1 → L2 at 8.5 px, L2 → L1 at 10 px — E06-D01 §2's asymmetric band; footprint L0–L3 likewise) is **one frame, in both modes**. No crossfade, by decision and not by omission `(heuristic, with the cost measured in §10)`: a crossfade needs the outgoing and the incoming rendering of the whole series in one frame — a second instanced draw of every candle or cell, in a blended pass — and the blend of a green L0 body over a red L2 column produces a colour that is neither, for several frames, on the one layer whose colour means something (`26` §5 rule 3). What makes the step tolerable is the dead band (E11-S12 gate B2: ≤ 6 LOD changes over the 0.1 → 50 px/bar sweep) and the fact that a wheel zoom already changes the picture every frame — the step is one more frame of a moving picture. During a D7 transition that crosses a threshold the step happens mid-flight on the frame the spacing crosses it, exactly as it would under the wheel. The **aggregation chip** (`Zoomed out · 1 column = 12 bars`, E11-D01 D6) and the **reduced-detail corner badge** appear and disappear at 0 ms in both modes (E11-D02 §10 already says "instantly"; D15 makes it the rule for every chip); the ratio text updates in place ≤ 1 per frame with no animation; the chip's entry and exit announcements are E11-D02 §10's (polite once each), unaffected by motion mode. The load-driven step-down — E11-S12's ladder settings `lod.stepDownFrames` 3 and `lod.recoveryMs` 2 000, under the `06` §4.4 degradation order (whose rung 2 is the footprint text density) — is the same one-frame step with a different trigger.
```

New:

```text
A candle LOD step (L0 → L1 at 10.2 px, L1 → L0 at 12 px; L1 → L2 at 8.5 px, L2 → L1 at 10 px — E06-D01 §2's asymmetric band; footprint L0–L3 likewise) is **one frame, in both modes** for every fill, every outline and the L2 / L3 collapse; only footprint cell text fades, one alpha uniform on the single glyph draw over `motion.duration.fast` with `motion.easing.decelerate`, a hard cut under reduce (E18-D04 §5). No crossfade of fills, by decision and not by omission `(heuristic, with the cost measured in §10)`: a crossfade needs the outgoing and the incoming rendering of the whole series in one frame — a second instanced draw of every candle or cell, in a blended pass — and the blend of a green L0 body over a red L2 column produces a colour that is neither, for several frames, on the one layer whose colour means something (`26` §5 rule 3). What makes the step tolerable is the dead band (E11-S12 gate B2: ≤ 6 LOD changes over the 0.1 → 50 px/bar sweep) and the fact that a wheel zoom already changes the picture every frame — the step is one more frame of a moving picture. During a D7 transition that crosses a threshold the step happens mid-flight on the frame the spacing crosses it, exactly as it would under the wheel. The **aggregation chip** (`Zoomed out · 1 column = 12 bars`, E11-D01 D6) and the **reduced-detail corner badge** appear and disappear at 0 ms in both modes (E11-D02 §10 already says "instantly"; D15 makes it the rule for every chip); the ratio text updates in place ≤ 1 per frame with no animation; the chip's entry and exit announcements are E11-D02 §10's (polite once each), unaffected by motion mode. The load-driven step-down — E11-S12's ladder settings `lod.stepDownFrames` 3 and `lod.recoveryMs` 2 000, under the `06` §4.4 degradation order (whose rung 2 is the footprint text density) — is the same one-frame step with a different trigger.
```

### A-5 · `16` §7 · `16`:291 · insert after

Purpose: The `16` §7.x subsection (BQ-2), numbered at merge: open motion PRs also add §7.x subsections.

Old:

```text
it unchanged, and only forced colours drops it.
```

New:

```text

### 7.N Footprint motion (E18-D04; PROPOSED until the owner's approval)

Spec: `docs/design/E18/E18-D04.md` §2–§6 (the moments, the flicker policy, the forming fill, the LOD text crossfade, reduced
motion and canvas calm). Tokens used by name, none added: `motion.duration.{fast,normal}` and
`motion.easing.{standard,decelerate,accelerate}`; the 200 ms marker hold is PROPOSED into E08-D11's `motion.hold.*` group.
Rules: every chart row runs in the engine's frame loop, the curve evaluated from the token's four numbers; a marker's
state change is held ≥ 200 ms, the latest winning; a forming fill takes E47-D08 FR-6; only cell text fades on the LOD
band, fills step in one frame; every reduce variant is instant.
```

### A-6 · E47-D08 §4.2 · E47D08:206 · insert after

Purpose: A footprint forming-column row in the per-surface budget (F-5).

Old:

```text
| I-21 heatmap live column | the cell intensity                                          | FR-6; FR-3                                                                                      | the hold of §7                                                   | the same                           | QA-1                          |
```

New:

```text
| E18 footprint forming column | the cell fill; the markers (outline, POC, VA, bracket, ledge, cap) | FR-6 for fills; FR-3; the 200 ms marker hold (E18-D04 §3) | the engine's holds, latest wins | the same | QA-1 |
```

### A-7 · `05` §6.3 · `05`:203 · insert after

Purpose: SCR-045 parity (F-2): the two level facts the mirror speaks that the level sub-row lacks, a level POC marker and a stack run length; PROPOSED, or a recorded reason they stay derivable. `forming` and the bar's POC are the bar row's already (E11D04:183, :185), so no row is added for them.

Old:

```text
| Estimated badge | "(estimated)" footnote marker + reason (`iceberg`, `stop-run`, `order-count proxy`) or blank  | Filter-only (see below)   | Satisfies WCAG 1.3.1 for the heuristic-data caveat |
```

New:

```text
| Level POC marker | "Point of control" on the level that is the bar's POC, else blank                               | Filter-only               | The mirror's "point of control" at the level (E18-D04 F-2) |
| Stack run length | "×3 bid" / "×3 ask" on each level of a stacked run, else blank                                  | Yes (groups stacked rows) | The mirror's "part of a 3-level … stack" (E18-D04 F-2)     |
```

### A-8 · E11-D06 row 22 · E11D06:324 · replace

Purpose: Row 22 follows A-4 (BQ-3, RULED); its Duration cell and its Reduced-motion variant change (reduce: one frame, the cell-text fade included); applied after merge with the other A-rows.

Old:

```text
| 22  | **LOD step-down / step-up** (candle L0–L2, footprint L0–L3)                                                                                                                                                             | spacing crosses the asymmetric band (12 → 10.2 px, 10 → 8.5 px, and back at 12 / 10) or the load ladder                                                                                                                                                                 | the rendering level                                                                                                                                                              | 1 frame, no crossfade                                                                                                    | none                                                                  | same                                                                                                                                     | the step itself no; the level is disclosed by rows 23–24 (text)                                                                   |
```

New:

```text
| 22  | **LOD step-down / step-up** (candle L0–L2, footprint L0–L3)                                                                                                                                                             | spacing crosses the asymmetric band (12 → 10.2 px, 10 → 8.5 px, and back at 12 / 10) or the load ladder                                                                                                                                                                 | the rendering level                                                                                                                                                              | 1 frame, no crossfade of fills, outlines or the L2 / L3 collapse; footprint cell text fades over `fast` (E18-D04 §5)                                                                  | none                                                                  | 1 frame, the cell-text fade included                                                                                                                                     | the step itself no; the level is disclosed by rows 23–24 (text)                                                                   |
```
