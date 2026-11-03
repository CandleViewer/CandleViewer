# a11y-nav: the keyboard-only suite (E47-Q03)

Automated enforcement of `docs/plan/05-accessibility-standard.md` s9 items 4 and 6. It asserts **structure and
reachability** (names, roles, landmarks, focus order, no traps, a visible focus ring). It never asserts that
anything "sounds right": a green run is not conformance. Screen-reader and experiential checks are the manual
passes of E47-Q02.

It is the `a11y-nav` project of `e2e/playwright.a11y.config.ts`, inside the required `a11y` job (BQ-03 (a)).

## What is here (PR-1: infrastructure)

| File                 | Purpose                                                                                                                                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mouseGuard.ts`      | `guardPage(page)`: a Proxy that throws `A11Y-K001` on `click`, `hover`, `tap`, `dragTo`, `check`, `page.mouse.*`, `page.touchscreen.*` and pointer-typed `dispatchEvent`, on the page and every locator it returns.          |
| `fixtures.ts`        | `test` whose `page` is guarded, plus an in-page pointer-event counter that fails the test with `A11Y-K002` (the second line of defence). Import `test` and `expect` from here, never from `@playwright/test`.                |
| `trap.ts`            | `checkNoTrap(page, N)`: Tab through the screen, then `judgeFocusSequence`. Fails on no stops (`K010`), a stall (`K011`), an unnamed stop (`K012`), no focus indicator (`K013`), or no return to the start within N (`K014`). |
| `focusVisibility.ts` | `assertFocusIndicator(page)`: indicator contrast against the adjacent background must be at least 3:1, via `tools/contrast/color-math.mjs`, the same `contrastRatio` as the token linter. Never copy the formula.            |
| `normalise.ts`       | `normaliseTree` masks prices, balances, timestamps, ids, emails and account names in an ARIA snapshot; `diffTrees` gives a reviewer-readable diff and flags a lost accessible name.                                          |

Unit tests for all of these are in `apps/web/test/e2e-a11y-nav.test.ts` and `e2e-a11y-normalise.test.ts`.

The focus-ring check judges the indicator against the adjacent background only (3:1). It does not compare the
focused against the unfocused state (WCAG 2.2 SC 2.4.13, Focus Appearance); that comparison is not asserted
here. The 20-run flake-check workflow is not in PR-1; it ships in PR-3.

## The trap limit N

`checkNoTrap(page, N)` takes N from the caller. The per-screen derivation (`ceil(1.5 x focusable nodes) + 10`,
counted from the committed tree baseline, PROPOSED under BQ-07) moves to PR-2 with the journeys that use it;
the G004 collector keeps its fixed `MAX_TABS = 80`.

## Adding a journey when a new screen ships

1. Add the screen to the a11y screen set (`e2e/a11y/screens.ts`) and capture its baseline tree, as for any screen.
2. Create `<screen>.journey.ts` here, importing `test`, `expect` from `./fixtures`.
3. Open the screen, call `checkNoTrap(page, N)`, and assert `verdict.ok` with
   `verdict.failures` as the message.
4. After each focus-moving step in the screen's s8.2 task, call `assertFocusIndicator(page)` and assert `ok`.
5. Drive only the keyboard: `page.keyboard.press(...)`, `locator.press(...)`, `locator.fill(...)`.
   Never `click`; the guard will fail the test and name the call.
6. A surface that is not mounted yet is an expected failure (`test.fail`) naming the remediation ticket,
   never a silent skip.

Reserved chords (`reserved-keys.json`) are never driven: Ctrl+Tab belongs to the browser.

## Updating tree snapshots

Snapshots are normalised with `normaliseTree` before they are compared or committed. Updating one needs the
explicit flag and a reviewer note in the PR saying what semantic change the new tree records.
