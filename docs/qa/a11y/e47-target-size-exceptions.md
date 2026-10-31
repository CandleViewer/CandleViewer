# Target size exception register (E47-S05)

WCAG 2.2 SC 2.5.8 (Target Size, Minimum, AA), `docs/plan/05-accessibility-standard.md` §3.4 item 7 and §7.5. Every
interactive control is at least 24 x 24 CSS px (the token `--size-target-min`) or has 24 px of clear space around it, at
compact density, the tighter of the two. The rule is `apps/web/e2e/a11y/targetSize.ts`; the check is
`apps/web/e2e/a11y/target-size.spec.ts` (report: `reports/a11y/target-size.json`). It is a report plus an assert, not
a `tools/a11y/gates.py` code (BQ-3).

Exempt by the standard and tagged by the collector, so not listed here: a link inside a run of text (inline), a
native checkbox or radio (user-agent drawn; its label is measured instead) and a disabled control.

A row is the only way to keep a smaller target. `Match` is the CSS selector the element matches; `Screen` is a screen id
or `*`. `Alternative` names the way to reach the same action without the small target and may not be empty
(the spec fails on an empty cell). T05 (E47-T05) accepts or rejects each row.

| Id  | Screen | Match | Size | Why | Alternative | Owner |
| --- | ------ | ----- | ---- | --- | ----------- | ----- |

No exception is registered: every control the check measures is at least 24 x 24 CSS px or exempt by the standard.

## Result (E47-S05, compact density, 1280 x 800)

Screens: R-001, R-901, R-902, R-903 and the signed-in R-201, R-202, R-203 (shell chrome included).

| Finding                                  | Where                                                                                     | Before                                           | Fix                                                          |
| ---------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------ |
| Bare controls ignored the density token  | `button`, text `input` on login (SCR-001), hotkeys (SCR-013)                              | 21 px tall, passing only through the spacing arm | `theme.css` floor, `:where(...)` at `--size-target-min`      |
| Native checkbox and radio drawn at 13 px | hotkey modifiers, accessibility toggles                                                   | 13 x 13 and 17 px labels, spacing arm only       | same floor: min inline and block size on the control         |
| Standalone links in a text line          | R-203 accessibility settings, last line (`Accessibility statement`, `Keyboard shortcuts`) | 17 px tall                                       | exempt as inline (a link in a run of text, 2.5.8); no change |

The report `reports/a11y/target-size.json` lists `underMinimum` per screen: empty on every screen after the fix
apart from the two inline links.
