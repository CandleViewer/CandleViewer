# E05-S01 (#264) QA handoff: the ten control atoms

For the QA pass of E05-Q01 on CMP-001 to CMP-010. The tests carry no Gherkin scenario text, so this note is the scenario-name to test index (DoD: "scenarios covered by automated tests"). Paths are under `packages/ui/`; `T` is `test/`, `S` is `src/components/`. Tests of CMP-003, CMP-005 and CMP-008 live on their open PRs (#4757, #4738, #4761) and appear in this tree once those merge. Divergences from `15` are the A-rows in `docs/design/E05/E05-S01-catalogue-a-rows.md`; keyboard tables are in `src/docs/Atoms.mdx` (Storybook: Atoms/Overview).

## Scenario to test

| Scenario (ticket)                                | Covered by                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full matrix is rendered and snapshot-stable      | One `*.stories.tsx` per atom in `S` (`AllStates`, `AllVariants`, `GatedContrast{Light,HighContrast}` and per-state stories); `pnpm storybook:test` plays every story with axe; themes and densities come from the toolbar globals (`.storybook/preview`), not six copies. Stories for CMP-003, -005, -008 are on #4757, #4738, #4761. |
| Keyboard contract (SegmentedControl, ArrowRight) | CMP-003: `T/SegmentedControl.test.tsx` "arrows move focus and check, wrapping, in both directions" and "Tab leaves the group in both directions and re-enters on the checked segment" (#4757). Same pattern for CMP-006: `T/RadioGroup.test.tsx` lines 84 and 132.                                                                    |
| Disabled states explain themselves (Button)      | `T/Button.test.tsx` "disabled with a reason: focusable, aria-disabled, reason described at mount, no activation"; the same case per atom in `T/IconButton`, `T/Toggle`, `T/RadioGroup`, `T/TextInput`, `T/Select`, `T/Slider`. The reason is the description now; the visible echo waits for CMP-016 (A-12).                          |
| Numeric input is tabular (CMP-008)               | `S/NumericStepperInput.stories.tsx` `Tabular` play function (computed `font-variant-numeric` and mono family) on #4761; pure formatting in `T/numeric.test.ts`.                                                                                                                                                                       |
| Invalid numeric entry (CMP-008, min 0, type -5)  | `T/NumericStepperInput.test.tsx` "an out-of-range entry is invalid, never clamped: error shown, value unchanged (AC)" and the `OutOfRangeEntry` story (#4761); the bound check itself in `T/numeric.test.ts`.                                                                                                                         |
| Loading button cannot double-submit              | `T/Button.test.tsx` "loading keeps the name, sets aria-busy, stays focusable and suppresses activation" and the buy/sell loading cases beside it; story `Loading`.                                                                                                                                                                    |
| No hardcoded values                              | `pnpm lint`: the `candleviewer/no-raw-design-values` rule is `error` for these files (`eslint.config.mjs`, with its rule in `eslint-rules/`); per-component `T/*-css.test.ts` pin the token-only cascade.                                                                                                                             |

## Close-out checks added with this note

- `T/index.test.ts`: the seven atoms present on this stack and their props types are exported from the package entry.
- `T/data-cmp.test.tsx`: each of those roots carries exactly one `data-cmp="CMP-0NN"`.

## Known gaps tracked against later components

| Gap                                                                                         | Target                                                  | Until then                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A-12: no atom shows its disabled reason visibly (no inline text, no hover or focus tooltip) | CMP-016 (tooltip) and CMP-040 (the visible reason line) | The reason is an always-present, visually hidden `aria-describedby` description, so the AC "reason is shown on hover or focus" holds for assistive technology only. Accepted by the coordinator, 27 Oct 2026 19:08Z; the A-row is in `docs/design/E05/E05-S01-catalogue-a-rows.md`. |

## Manual passes still owed (DoD)

- Keyboard-only walk of each component (Atoms/Overview tables are the script).
- Design QA against the boards (E05-D05) and the QA sign-off of E05-Q01; neither is claimed here.
