# E32-D06 — Hand-off (`16` §11.4): the CMP-158 checklist

Component: CMP-158 SafetyInvariantNotice. The pack is [E32-D06.md](E32-D06.md) (every "A-n" below is its §C row, applied to `15` by PR 2; every "L-n" its §2 ledger row; "S-n" its §4 sentence; "M-n" its §8 motion row; "P-n" / "V-n" its §11 pairs). This ticket **changes one component contract** (CMP-158: two hosts as variants, the companions, the placement rule, the Motion / Usage lines) and attaches its checklist (`16` §11.4, §13.3 item 8). CMP-119, CMP-120 and CMP-228 already carry their checklists in E32-D03's hand-off, E32-D04 §6 and E32-D05's hand-off; this pack applies their parents' rows by id (A-9 … A-29) and adds no second checklist for them.

Rule: every line is `[x]` with its evidence, or `[ ]` with its reason (a PR still to land, or `N/A — <reason>`). No blank line at Done (`16` §11.4, §13.3).

## The A-row ledger by component

The pack's §2 holds the ledger: 28<!--=COUNT:ledger--> rows, 12<!--=COUNT:ledger.applied--> applied, 7<!--=COUNT:ledger.amended--> applied-as-amended, 6<!--=COUNT:ledger.routed--> routed, 0<!--=COUNT:ledger.held--> held, 3<!--=COUNT:ledger.appliedby--> applied by a merged PR. Per target, the rows its A-rows carry (the tool derives this table from §2 and §C and fails on a difference):

| Component | Ledger rows                              | A-rows      |
| --------- | ---------------------------------------- | ----------- |
| CMP-158   | L-1, L-3                                 | A-1 … A-8   |
| CMP-119   | L-4, L-5, L-6, L-7, L-8, L-9, L-10, L-12 | A-9 … A-17  |
| CMP-120   | L-18, L-23                               | A-18 … A-25 |
| CMP-228   | L-14                                     | A-26 … A-29 |
| SCR-064   | L-19                                     | A-30, A-31  |
| SCR-065   | L-16                                     | A-32        |

## Handoff checklist — CMP-158 SafetyInvariantNotice (E32-D06, #926)

- [ ] **Final Penpot link** — PR 3: file `E32-D06 boards`, page `E32-D06 Native-SL pattern`, boards 01, 02, 03, 08 and 09 (the reference frames of `16` §10 item 4), referenced by page name + page id only; PNGs under `docs/design/E32/img/E32-D06-NN-*.png`
- [x] **Variants × States matrix** — table 1; one state (`15`:1882), five hosts as variants after A-2; the stories of A-6 7<!--=COUNT:stories.158-->); the companions are CMP-027 / CMP-028 rows, cited, never variants
- [x] **Keyboard table** — table 2: the note is never a Tab stop; the stop field's keys are CMP-100's as E32-D03's hand-off Table 2 cites them (D03H:11); a T2 control changes nothing and re-shows its reason
- [x] **Accessible name / role table** — table 3: the pack's §10 (CMP-158 `note`, the revert line `status`, the refusal line `alert`, the stop field `spinbutton`)
- [x] **Live data** — table 5: nothing live on the note; the companions announce once; the `{n}` of the ticket variant is a profile read, never a tick
- [x] **Motion pair** — table 4: none on the note (a cut on mount and unmount in both modes, A-8); the surfaces' four rows are the pack's §8 (M-1 … M-4), cited
- [x] **Density notes** — the density table: 24 px one line compact / two lines comfortable (`E30D04`:496); full column width; no hit target (not interactive)
- [x] **Essential-exceptions log** — none (no target: the note is not interactive)
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-5 adds no name): `color.status.info.subtle`, `color.text.primary`, `color.status.info.strong`, `radius.card`, `space.inset.sm`, `type.ui.caption` / `type.ui.body`; the Penpot sets equal `packages/ui/tokens` at a0132de011<!--=SHA:TOK-->; zero proposals
- [x] **Data contract confirmed** — `profileTicks` from the account's profile (`GET /exchange-accounts/{id}/profiles`, the ticket variant only, `15`:1886); the other hosts render static keys; the invariant's control is E32-T01's choke point, not a prop (pack §12); the gap G-1 recorded
- [x] **Contrast and CVD** — computed by the tool: the pack's §11 (P-1 … P-7 in three themes, 4<!--=COUNT:pairs.gated--> gated, 3<!--=COUNT:pairs.reported--> reported, 0<!--=COUNT:pairs.failing--> failing; V-1 … V-4); the one PROPOSED `PAIRS` row is §7's, copy-ready for the first consumer's PR; the renders land with PR 3
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards; E32-D07 (#927) runs the a11y review
- [ ] **Sign-off** — the orchestrator's design approval on PR 1, PR 2 and PR 3 (the delegation; the owner's walkthrough post-Done)

### Table 1 — Variants × States

| Variant                              | State   | Penpot frame (PR 3)          | Story name                         | Notes                                                                    |
| ------------------------------------ | ------- | ---------------------------- | ---------------------------------- | ------------------------------------------------------------------------ |
| ticket (SCR-060 / 061 / 066 … / 076) | default | `E32-D06 / 02 variant-table` | Default, Comfortable, HighContrast | S-6 (`E30D02`:394); `{n}` from the profile                               |
| rule editor (CMP-145 / CMP-146)      | default | 02                           | InRuleEditor                       | S-1 + S-4 (`15`:1879); above the action bar                              |
| arming dialog (SCR-085)              | default | 02                           | InArmingDialog                     | S-5 (`E35D02`:328); block 5                                              |
| held position (SCR-064)              | default | 02, 04                       | InHeldPosition (PROPOSED, A-6)     | S-1 + S-3 (D05:127); under the stop row                                  |
| draft builder (SCR-065 / SCR-069)    | default | 02, 04                       | InDraftBuilder (PROPOSED, A-6)     | S-1 + S-2 (D02:342); under the stop row                                  |
| any                                  | default | 01, 08, 09                   | HighContrast                       | compact / comfortable; dark / light / hc; forced-colors strip (board 09) |

### Table 2 — Keyboard

| Key                               | Action                                                                                                 | Focus after   | Global conflict? | Notes                                        |
| --------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------- | ---------------- | -------------------------------------------- |
| `Tab` / `Shift+Tab`               | the note is skipped (not focusable); the stop field and the actions are the stops                      | the next stop | none             | `15`:1883; `E30D04`:495                      |
| the stop field's keys             | CMP-100's (`↑` / `↓` one tick, `Shift` ×10, `PageUp` / `PageDown` ×100; `Enter` commits, never places) | the field     | none (D03H:11)   | a commit on a held stop may revert (pack §5) |
| `Enter` / `Space` on a T2 control | nothing changes; the reason re-shows inline with one polite announcement                               | unchanged     | none             | `RULE` G-T2.3                                |

### Table 3 — Accessible name / role

| Element          | Role                                                     | Accessible name (source)                                                                             | States / properties                                                                                       |
| ---------------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| CMP-158          | `note`                                                   | its text content: S-1 + the host's clause (pack §4)                                                  | not a live region; never announced on change; not focusable; the glyph `aria-hidden` (`15`:1883)          |
| the revert line  | `status` (CMP-027 `inline`, polite)                      | `sl.kept` / `sl.loosen.refused` / `sltp.trail.refused` (D02:207, D02:349)                            | once per commit; mounted with the field; E32-D07 finalises the vocabulary                                 |
| the refusal line | `alert` (CMP-027 `banner` / CMP-028 `danger`, assertive) | `sltp.rejected` (D02:355), the `refusal.*` lines                                                     | once per refusal (`05`:148); the inputs stay; the error summary takes focus on its heading (`E30D02`:141) |
| the stop field   | `spinbutton` (CMP-100)                                   | "Stop-loss (required)" / "Stop-loss · held by Bybit (exchange)" / "Stop-loss · none at the exchange" | described by the source line, the holder and the revert or validity line (D03H:12; D05H:135)              |

### Table 4 — Motion pair

| Property                   | motion-safe                                                     | motion-reduce                    | Duration / easing tokens                                                                                                  |
| -------------------------- | --------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| the note (mount / unmount) | a cut (`E30D04`:497; A-8)                                       | the same cut                     | —                                                                                                                         |
| the surfaces' transitions  | the pack's §8: M-1 the scrim, M-2 a cut, M-3 the bar, M-4 a cut | `none`, the end state at frame 0 | M-1 `motion.duration.normal` · `motion.easing.standard`; M-3 `motion.duration.fast` · `motion.easing.standard` (PROPOSED) |

### Table 5 — Live data

| Field                      | Politeness           | Cadence                | Coalescing        | Notes                                 |
| -------------------------- | -------------------- | ---------------------- | ----------------- | ------------------------------------- |
| the note                   | none (`role="note"`) | static                 | —                 | never announced on change (`15`:1883) |
| the ticket variant's `{n}` | none                 | a profile read on open | —                 | never a tick (`15`:1886)              |
| the revert line            | polite (`status`)    | once per commit        | the latest commit | D02:257                               |
| the refusal line           | assertive (`alert`)  | once per refusal       | never coalesced   | `05`:148; D02:257                     |

### Density

| Mode        | Row / control height                | Padding tokens   | Smallest target     |
| ----------- | ----------------------------------- | ---------------- | ------------------- |
| compact     | 24 px, one line (`type.ui.caption`) | `space.inset.sm` | — (not interactive) |
| comfortable | two lines (`type.ui.body`)          | `space.inset.sm` | — (not interactive) |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |
