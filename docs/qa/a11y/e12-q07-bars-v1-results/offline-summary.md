# E12-Q07 v1 results: the offline legs (PR 1)

Pin `aa0a02b8c54c877c39718f101abf69467cb4a2d6` plus this PR's test file; run 2026-11-04 on Linux (WSL2), Node with vitest 4.1.12 and jsdom 25.0.1; the Storybook leg in Chromium 156.0.8078.4 headless. Agent-run; every verdict is (heuristic).

## apps/web (vitest, jsdom)

17 files, 312 tests, 312 pass, 0 fail (§3.1's 16 files and 307 tests, plus this PR's 5).

| File                                                               | Tests | Pass |
| ------------------------------------------------------------------ | ----- | ---- |
| `apps/web/test/chart/a11y/ChartDataTable.test.tsx`                 | 27    | 27   |
| `apps/web/test/chart/a11y/ChartTablePanel.test.tsx`                | 9     | 9    |
| `apps/web/test/chart/a11y/compositeGrid.test.ts`                   | 18    | 18   |
| `apps/web/test/chart/a11y/compositeGridHost.test.tsx`              | 13    | 13   |
| `apps/web/test/chart/a11y/e12Q07Audit.test.tsx`                    | 5     | 5    |
| `apps/web/test/chart/a11y/footprintGrid.test.tsx`                  | 3     | 3    |
| `apps/web/test/chart/a11y/format.test.ts`                          | 14    | 14   |
| `apps/web/test/chart/a11y/marks.test.tsx`                          | 14    | 14   |
| `apps/web/test/chart/a11y/orderflowFormat.test.ts`                 | 10    | 10   |
| `apps/web/test/chart/a11y/politeWriter.test.tsx`                   | 13    | 13   |
| `apps/web/test/chart/a11y/readback.test.ts`                        | 15    | 15   |
| `apps/web/test/chart/a11y/series.test.ts`                          | 9     | 9    |
| `apps/web/test/features/chart-errors/ChartErrorSurface.test.tsx`   | 26    | 26   |
| `apps/web/test/features/chart-errors/copy.test.ts`                 | 40    | 40   |
| `apps/web/test/features/chart-errors/state.test.ts`                | 19    | 19   |
| `apps/web/test/features/chart-price-scale/PriceScaleMenu.test.tsx` | 28    | 28   |
| `apps/web/test/features/symbol-search/QuickSwitcher.test.tsx`      | 49    | 49   |

## packages/ui (Storybook project, Chromium)

| File                                                                              | Stories | Pass |
| --------------------------------------------------------------------------------- | ------- | ---- |
| `packages/ui/src/components/Skeleton.stories.tsx` and `SkeletonChart.stories.tsx` | 15      | 15   |

## Contrast gate

`contrast:gate`: 516 pair checks, 33 heatmap-stop checks, 81 CVD checks, 0 findings; data-ink 582 checks, 0 failing per theme; no-hue-alone ok.
