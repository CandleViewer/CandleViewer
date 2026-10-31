# E08-D07 — Hand-off (`16` §11.4; SCR-100, the watchlist panel, and SCR-101, the manager)

Ticket E08-D07 (#175); spec [E08-D07.md](E08-D07.md); every "§", "D", "Q" and "C" below without a prefix is the spec's. This screen pair changes component contracts (§5), so the hand-off is due (spec Deviation 9; `16` §11.4; `02` §3.1). **Status:** the spec's header reads "In Review — owner approval pending"; this file is a checklist only, derived from the spec's merged text, and adds no decision, string, number or token. Anything the spec leaves open is listed as open with its row id and owner.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | CMP-161 WatchlistRow                                                      | CMP-162 WatchlistGroupTabs                          | CMP-049 Table (grid mode)                           | CMP-056 ColumnPicker         | CMP-067 FileDrop                 | CMP-239 FreshnessMarker                             | CMP-078 StaleDataShade                              |
| ------------------------ | ------------------------------------------------------------------------- | --------------------------------------------------- | --------------------------------------------------- | ---------------------------- | -------------------------------- | --------------------------------------------------- | --------------------------------------------------- |
| Final Penpot link        | [x] page `E08-D07`, §9: SCR-100 boards 01–04, 06–08                       | [x] page `E08-D07`, §9: SCR-100 boards 01–04, 06–08 | [x] page `E08-D07`, §9: SCR-100 boards 01–04, 06–08 | [ ] board 14 not drawn (§9)  | [ ] board 13 not drawn (§9)      | [x] page `E08-D07`, §9: SCR-100 boards 01–04, 06–08 | [x] page `E08-D07`, §9: SCR-100 boards 01–04, 06–08 |
| Variants × states        | [x] §5 stories; §4.2                                                      | [x] §5 stories; §4.2                                | [x] §5 stories; §4.2                                | [x] §5 stories; §4.3 Columns | [x] §5 stories; §4.3, §4.4       | [ ] §5 names no story                               | [ ] §5 names no story                               |
| Keyboard table           | [x] §6.2, §6.4                                                            | [x] §5 (manual activation), §6.3                    | [x] §6.1, §6.2                                      | [x] §6.4 Columns, §6.5       | [x] §6.5, §6.6                   | [ ] not stated in D07 (§5)                          | [ ] not stated in D07 (§5)                          |
| Accessible name and role | [x] §4.2 A11y, §5                                                         | [x] §5 (tab named with its count)                   | [x] §5 (`aria-rowcount`, `colspan`)                 | [x] §5                       | [x] §4.4 (native file input)     | [x] §5 (`aria-describedby`)                         | [x] §5 (the panel status text)                      |
| Live data                | [x] §4.5 (D17: one summary per stale episode)                             | [x] none                                            | [x] §4.5                                            | [x] §4.5 (polite move)       | [x] §4.5 (import result, polite) | [x] §4.5                                            | [x] §4.5                                            |
| Motion pair              | [x] §8 (owner: E08-D11); [ ] C-13 open                                    | [x] none (§8 names none)                            | [x] §8 (sort, reorder)                              | [x] none (§8 names none)     | [x] none (§8 names none)         | [x] §8 (one flip); [ ] C-13 open                    | [x] §8; [ ] C-13 (a) open                           |
| Density notes            | [x] D30 (compact 24 px, comfortable 32 px)                                | [x] D30                                             | [x] D30 (card at 200 %)                             | [x] D30                      | [x] D30                          | [x] D30                                             | [x] D30                                             |
| Essential exceptions     | [ ] the spec has no log: open                                             | [ ] open                                            | [ ] open                                            | [ ] open                     | [ ] open                         | [ ] open                                            | [ ] open                                            |
| Tokens used              | [x] §7.1; [ ] DS-CR-2 open                                                | [x] §7.1                                            | [x] §7.1                                            | [x] §7.1                     | [x] §7.1                         | [x] §7.1                                            | [x] §7.1; [ ] DS-CR-1 open                          |
| Data contract            | [ ] open: C-1 to C-8, C-10 to C-12 (§12); §12 maps no item to a component | [ ] see the CMP-161 cell (§12 maps none)            | [ ] see the CMP-161 cell (§12 maps none)            | [ ] see the CMP-161 cell     | [ ] see the CMP-161 cell         | [ ] see the CMP-161 cell                            | [ ] see the CMP-161 cell                            |
| Contrast                 | [x] §7.2 (computed); [ ] §7.3 items 1–3 open                              | [x] §7.2                                            | [x] §7.2                                            | [x] §7.2                     | [x] §7.2                         | [x] §7.2                                            | [x] §7.2                                            |
| Storybook                | [x] §5 names them; built with the component (Deviation 9)                 | [x] same                                            | [x] same                                            | [x] same                     | [x] same                         | [ ] §5 names none                                   | [ ] §5 names none                                   |
| Sign-off                 | [ ] owner approval pending (§11 AC6)                                      | [ ] pending                                         | [ ] pending                                         | [ ] pending                  | [ ] pending                      | [ ] pending                                         | [ ] pending                                         |

Used as catalogued (§5): CMP-001, CMP-011, CMP-016, CMP-019 (`lock`), CMP-026, CMP-043, CMP-044, CMP-079, CMP-216. D36 adds CMP-017, CMP-041, CMP-160 (T2) and CMP-213 with E08-D05's A-D05-3 and A-D05-6.

## §B `02` §3.1 design-ready lines for E08-S08 (#4702)

| Line                                 | Evidence                                                                                                                                               |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [ ] Linked hi-fi, Status = Done      | page `E08-D07`, id `504164f9-8cb1-8083-8008-d484567a7bed` (§9); ten boards drawn, dark (§9); owner approval pending (§11 AC6)                          |
| [ ] Done for ≥2 sprints, or a waiver | §11 "≥2 sprints ahead": owner approval pending; Q16 and C-5 (no consuming story) are as the spec words them; waiver owner: CDO / Architect (`02` §3.1) |
| [x] Components in `15`               | §C below: every id checked at the base; two §10 rows held for the owner                                                                                |
| [x] States enumerated                | SCR-100: §4.2 (and the REC table); SCR-101: §4.3; import and export: §4.4; density: board 08 (200 symbols), D30                                        |
| [x] §11.4 hand-off linked            | this file, §A                                                                                                                                          |

Consumers named by the spec: E08-S03 (#284), E16-S02 (#566), E08-Q05 (#282), E08-D08 (#176), E08-D11 (#179), E08-D12 (#180), E08-D13 (#181), E08-D14 (#277). `docs/plan/backlog/E08.json` lists SCR-100 and SCR-101 in E08-S08 (#4702, the build; `blocked_by` E08-D07), E08-T07 (#4706, `/watchlists`; SCR-100 and SCR-101), E08-T08 (#4707, the `ticker` producer and bulk snapshot; SCR-100), and E08-Q05 (#282). The spec's C-5 and Q16 (no story builds the UI) are not edited here.

## §C Components and catalogue at the base (checked by content; origin/main)

| Item                                          | In `15` / `14` at the base                                                                        |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| §5 rows CMP-161, 162, 049, 056, 067, 239      | [x] applied (each entry carries its §5 text and stories)                                          |
| §5 row CMP-078                                | [ ] not applied: its Old text is gone (§10; E17-D02 rewrote it); the owner decides, with C-13 (a) |
| §10 CMP-213 "on list" tag                     | [ ] not applied: `15` carries A-D05-3's `tags?` only; held for the owner (§10)                    |
| §10 CMP-160 T2; CMP-035 grid exception        | [x] applied                                                                                       |
| §10 A1–A9, B1–B7 in `14` (SCR-100, SCR-101)   | [x] applied                                                                                       |
| §10 routed: `12` M-022 and R-110; E08-Q05 gap | [ ] `12` R-110 still reads "full-page view" at the base; each goes to its owner (§10)             |
| §10 A10 (E09-D09 §3.2 workspaces row)         | [ ] open, to E09-D09's owner                                                                      |

## §D Tokens (§7.1 names; no value)

Names (§7.1 token map): `color.surface.{raised,canvas,app,hover,selected,overlay}`, `color.border.{subtle,selected,default,input}`, `color.text.{primary,secondary,tertiary,buy,sell,inverse}`, `color.data-confidence.{live,stale,disconnected,delisted}.*`, `color.focus.ring`, `color.status.warning.{subtle,strong}`, `type.ui.{label,caption}`, `type.num.{sm,base}`, `size.row.height`, `space.{panel,dialog}.padding`, `elevation.{popover,dialog}`, `radius.{badge,dialog}`. §7.1 also names `color.text.disabled` and `opacity.disabled` only as never used (T2 row). `color.surface.sunken`, `radius.card`, `opacity.muted`, `motion.duration.fast` are not in §7.1 and are not listed.

- [ ] DS-CR-1 (disconnected and reconnecting pair), DS-CR-2 (`color.text.buy/sell/neutral`), DS-CR-3 (light selected fill): raised to the design-system owner (§7.3, Q7); none of the three is applied in `packages/ui/tokens` at the base; the §7.3 fallbacks apply until each merges.
- [ ] `tools/contrast/pairs.mjs` and `encodings.json` additions (§7.3 item 7, §10): routed, open.

## §E Keyboard, motion and boards

- Keyboard: SCR-100 §6.2 (the Watchlist context; `Ctrl+F` and `Alt+↑/↓` conflicts checked in §6.2); focus order §6.3; reorder §6.4; SCR-101 §6.5; gated controls (T2) §6.6; reason keys §6.7 (PROPOSED keys registered through §10 A3 and B7).
- [ ] The Watchlist context joins `keymap.json` with the build (§6.2; E49-T04 #1343); `**Interactions:**` stays the field marker (§10).
- Motion: §8; E08-D11 (#179, merged as #4066) owns it. [ ] C-13 (a)–(c) and Q18 open: owner on E08-D11.
- Boards: page `E08-D07`; the ten the cap keeps: 01–04, 06–08, 10, 11 and 26, dark (§9); every other board and every light twin binds as text, drawn on request. Board 10 sits in the per-set file (page id by cite, §9). Exports under `docs/design/E08/img/` (§9); CVD renders for boards 01, 03, 04, 07 (§9, §7.4).

## §F Acceptance-criteria trace and open items

AC1–AC5: specified, boards drawn (§11). [ ] AC6 sign-off: owner approval pending. [ ] Test plan: density review (200 rows), screen-reader pass and engineering walkthrough pending, owner (§11 protocol; nothing has been run).

| Open item     | Owner named by the spec                                                            |
| ------------- | ---------------------------------------------------------------------------------- |
| Q1–Q18        | the owner; silence means each default (§3)                                         |
| C-1, C-3      | C-1: E08 contract owner (contract first); C-3: not named                           |
| C-2, C-4, C-8 | not named                                                                          |
| C-5 (Q16)     | the owner or orchestrator                                                          |
| C-6           | the pane-settings owner (E15)                                                      |
| C-7           | the audit-vocabulary owner                                                         |
| C-10          | E17 (`23`)                                                                         |
| C-11          | E08-S01 (#182) and E08-S03 (#284), interface first                                 |
| C-12          | the E16 security review                                                            |
| C-13          | E08-D11 (#179); the owner on (b) and (c)                                           |
| C-9           | closed by E09-D09's ruling A-6 (§12)                                               |
| Risks (§12)   | T1 = 5 s check on recorded fixtures (E08-S03); E16-D02 (#323) on the REC menu verb |
