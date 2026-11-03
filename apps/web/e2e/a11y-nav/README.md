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

Journeys (`*.journey.ts`): `sweep` (trap, names, h1/main per mounted screen), `focus-ring`, `burst` (AC4) and
`unmounted` (one expected failure per unmounted surface, from `probes.ts`).

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

## Coverage of the plan's 36 Q03 cases (BQ-10 (a))

Source: `cases.json`; `journey` = a journey in this project, `existing` = an e2e spec elsewhere already drives it, `expected-fail` = the surface is not mounted (`unmounted.journey.ts`), `pending` = a later slice. Cases 110, 115, 118 and 306 are manual. The plan's automation column stays a proposal; disagreements are the notes below (103: Ctrl+K opens nothing until #5280; 105: Ctrl+\ with no F6 row, Ctrl+Tab never driven).

| Case       | Surface                                         | Status        | Where                         | Note                                                                                                              |
| ---------- | ----------------------------------------------- | ------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| E47-TC-101 | SCR-010                                         | expected-fail | E47-S05                       | skip links: the shell has only the placeholder's `Skip to focus target`                                           |
| E47-TC-102 | SCR-011                                         | existing      | e2e/shell-chrome.spec.ts      | rail links and Alt+1..7; the `current page` state is partial                                                      |
| E47-TC-103 | SCR-012                                         | expected-fail | #5280                         | Ctrl+K opens nothing until the palette lands (hotkeys.spec.ts @plan-HK-1)                                         |
| E47-TC-104 | SCR-013                                         | existing      | e2e/hotkeys.spec.ts           | Ctrl+/ and Esc focus return; text-input case partial                                                              |
| E47-TC-105 | SCR-020 SCR-021                                 | expected-fail | E15 story                     | Ctrl+\ (alias F6) moves focus per E15-D02 AD-7; the keymap has no F6 row, and Ctrl+Tab is never driven (reserved) |
| E47-TC-106 | SCR-030                                         | expected-fail | E47-S01                       | chart not mounted on any route                                                                                    |
| E47-TC-107 | SCR-037                                         | expected-fail | E47-S05                       | drawing tools and their chord are pending                                                                         |
| E47-TC-108 | SCR-050                                         | expected-fail | E47-S02                       | ladder not mounted                                                                                                |
| E47-TC-109 | SCR-060 SCR-076                                 | expected-fail | E10-S05                       | order ticket not mounted                                                                                          |
| E47-TC-111 | SCR-081 SCR-085 SCR-086 SCR-126                 | expected-fail | E47-S03                       | rule editor form not mounted                                                                                      |
| E47-TC-112 | SCR-082                                         | expected-fail | E47-S03                       | node graph and its non-drag connect are pending                                                                   |
| E47-TC-113 | SCR-121 SCR-122 SCR-123 SCR-127                 | expected-fail | E47-S08                       | admin users grid and invite form not mounted                                                                      |
| E47-TC-114 | SCR-113                                         | existing      | e2e/hotkeys.spec.ts           | conflict classes, reserved keys, bare-key refusal                                                                 |
| E47-TC-116 | SCR-064 SCR-072 SCR-073 SCR-074 SCR-076 SCR-129 | expected-fail | E47-S08                       | freeze confirmation (Ctrl+Shift+K) not mounted                                                                    |
| E47-TC-117 | SCR-010 SCR-030 SCR-050 SCR-063                 | journey       | focus-ring.journey.ts         | ring contrast on mounted shell surfaces; SCR-030/050/063 and target sizes wait for S01/S02 and Q04                |
| E47-TC-119 | SCR-001..006 SCR-016 SCR-017 SCR-149            | existing      | e2e/e09-auth-a11y.spec.ts     | keyboard sign-in; TOTP paste and step-up partial                                                                  |
| E47-TC-121 | Every SCR                                       | journey       | sweep.journey.ts              | trap, names and focus ring per mounted screen                                                                     |
| E47-TC-202 | SCR-030                                         | expected-fail | E47-S01                       | chart image label; shares the chart probe with 106                                                                |
| E47-TC-213 | many                                            | journey       | sweep.journey.ts              | one h1 and one main per mounted screen; landmark names via the tree snapshots                                     |
| E47-TC-301 | SCR-045 SCR-030                                 | expected-fail | E47-S01                       | table alternative (Alt+T) not mounted                                                                             |
| E47-TC-302 | SCR-045 SCR-030                                 | expected-fail | E47-S01                       | table alternative (Alt+T) not mounted                                                                             |
| E47-TC-303 | SCR-045 SCR-030                                 | expected-fail | E47-S01                       | table alternative (Alt+T) not mounted                                                                             |
| E47-TC-304 | SCR-045 SCR-030                                 | expected-fail | E47-S01                       | table alternative (Alt+T) not mounted                                                                             |
| E47-TC-305 | SCR-045 SCR-030                                 | expected-fail | E47-S01                       | table alternative (Alt+T) not mounted                                                                             |
| E47-TC-307 | SCR-038 SCR-049 SCR-050 SCR-030                 | expected-fail | E47-S02                       | table alternative not mounted                                                                                     |
| E47-TC-308 | SCR-038 SCR-049 SCR-050 SCR-030                 | expected-fail | E47-S02                       | table alternative not mounted                                                                                     |
| E47-TC-309 | SCR-038 SCR-049 SCR-050 SCR-030                 | expected-fail | E47-S01                       | table alternative not mounted                                                                                     |
| E47-TC-501 | SCR-030 SCR-050 SCR-053 SCR-015                 | existing      | e2e/motion-reduce.spec.ts     | shell surfaces only; chart effects wait for E47-S04                                                               |
| E47-TC-502 | SCR-010                                         | existing      | e2e/motion-toggle.spec.ts     | Ctrl+Shift+M flips, says so once, persists                                                                        |
| E47-TC-507 | SCR-097 SCR-030                                 | expected-fail | E47-S04                       | replay autoplay pause not mounted                                                                                 |
| E47-TC-510 | SCR-117                                         | existing      | e2e/settings-keyboard.spec.ts | preference toggles; the GET /me/preferences read-back is partial                                                  |
| E47-TC-601 | SCR-116                                         | existing      | e2e/settings-keyboard.spec.ts | persistence read-back is partial                                                                                  |
| E47-TC-602 | SCR-117                                         | existing      | e2e/settings-keyboard.spec.ts | labels and states by keyboard                                                                                     |
| E47-TC-603 | SCR-117                                         | existing      | e2e/motion-reduce.spec.ts     | system default; explicit on/off override                                                                          |
| E47-TC-604 | SCR-113 SCR-013                                 | existing      | e2e/hotkeys.spec.ts           | a rebind persists across reload                                                                                   |
| E47-TC-609 | SCR-010 SCR-119                                 | pending       | later slice                   | TopBar has no Help entry yet; the same-location check needs it                                                    |

The AC4 burst test is `burst.journey.ts`. Its quantity-field journey is marked an expected failure (E10-S05) only
after arrival, session and a positive control (a polite region exists and the watcher counts an injected
mutation) pass; once the field exists it runs as AC4. The mounted variant is a watcher self-check and focus hold,
not AC4 coverage: no route consumes a ticker topic yet. Unmounted probes assert absence, so they go red the day the
surface lands.
