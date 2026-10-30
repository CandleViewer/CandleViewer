# E15 design-system contributions — the usage rules for panel chrome

**Owner:** E15-D13 (#367). **Status:** Draft with PR 1 of 4. **For:** every epic that adds a panel to the workspace (E18 footprint, E21 DOM, E30 order tickets, E39 journal and everything after). **Sources:** the pack [`docs/design/E15/E15-D13.md`](../E15/E15-D13.md) (its §C is the catalogue text `15` and `16` take in PR 2), the merged E15 hi-fi (E15-D02 … E15-D07, E15-D15), `15` and `16`. Where this document and `15` / `16` disagree after PR 2, `15` / `16` win and this document is a defect.

## 1. What this document is

This document binds every later panel epic. It is written as rules with reasons, so that an engineer who adds a panel with no E15 designer present knows what to use, what may change and what must never change, and why. Each rule names the catalogue entry or token it rests on. A panel that needs something these rules do not cover opens a design-system change request against the entry named (`02-definition-of-ready-done.md` §3.1), never a local variant.

**The three lists, in one line each.** **Must use:** CMP-080 DockPanel with CMP-082 PanelHeader, the dock's tokens, the environment badge on an order-capable panel, the region name. **May override:** the header's own action slot, the body's content and its minimum size, the kind's glyph and words. **Must never restyle:** the focus affordance, the environment disclosure, the sync badge.

## 2. Required chrome (must use)

| R   | Rule                                                                                                                                                                                                                                                                                                                                                       | Reason                                                                                                                                                           |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R-1 | Mount every panel inside CMP-080 DockPanel; never draw a frame of your own.                                                                                                                                                                                                                                                                                | The frame reserves the focus affordance's space in both states; a home-made frame either resizes on focus or loses the focus signal.                             |
| R-2 | Give the panel exactly one header row, CMP-082 PanelHeader, at `space.panelheader.height.*`. Your own buttons go into its action slot; your "More" merges into its overflow menu.                                                                                                                                                                          | One row is what E15-D03's chrome budget pays for (`docs/design/E15/E15-D03.md` §3); a second row takes market space from every panel of every layout.            |
| R-3 | Name the panel's region by kind, symbol and spelled interval, plus the environment word for an order-capable kind ("Chart, BTCUSDT 1 minute, Live"). The name never changes with width, focus or collapse.                                                                                                                                                 | A screen-reader user who moves between panels hears where they are and whether a trade there is live; a name that changes with width reads as a different panel. |
| R-4 | An order-capable panel shows CMP-075 EnvBadgeLocal in its header: word, weight, glyph and the `color.env.*` rule. Order-capable is decided by kind, never by role: `chart`, `dom` and `positions` today, and a new kind that can place, change or close an order joins the list. A floating window carries the same word whatever its kind (`15` CMP-215). | The environment must survive a crop to the panel alone (`14-screens-catalogue.md` §0.5.1); a global banner is not on the panel the user is looking at.           |
| R-5 | Bind the panel's layout through CMP-081 DockGrid's tree; never store the panel's position in the panel.                                                                                                                                                                                                                                                    | The tree is the saved layout's contract (`22-api-openapi.yaml`'s `LayoutGridSpec`); a position held elsewhere drifts from the saved layout.                      |
| R-6 | Give every pointer operation on the panel a keyboard path through the panel menu (CMP-216) or move mode (CMP-249).                                                                                                                                                                                                                                         | No drag-only operation ships (`05-accessibility-standard.md` §3.4 item 8, WCAG 2.5.7).                                                                           |
| R-7 | Every control in the header, and the handle, is at least `size.target.min` (24 px) in both densities.                                                                                                                                                                                                                                                      | Compact density sits exactly on WCAG 2.2's 24 px minimum (`16` §3); anything smaller is a failure, not a density.                                                |

## 3. The dock's tokens, with their reasons

| Token                                                                                               | Use it for                                          | Reason                                                                                                                                                                  |
| --------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `space.dockgrid.gutter`                                                                             | the gap between panels                              | the splitter's line sits in it; zero would put two panels' frames on one pixel                                                                                          |
| `space.panelheader.height.compact` / `.comfortable`                                                 | the header row and a tab group's row                | the row height the chrome budget assumes; never a third value                                                                                                           |
| `space.dock.tray.height.compact` / `.comfortable`                                                   | the minimised tray                                  | present only while used, so it costs nothing in the usual layout                                                                                                        |
| `space.workspacetabs.height.*` (a composite: `size.control.*` + 2 × `space.inset.xs`)               | the workspace tab strip and the move-mode bar       | the bar takes the strip's row so entering move mode never moves a panel                                                                                                 |
| `size.dock.splitter.hit`                                                                            | the splitter's hit band                             | a 24 px target over a thin line: easy to grab, invisible at rest                                                                                                        |
| `border.focus.panel` with the header bar (`border.thick` + `border.hairline`) in `color.focus.ring` | the panel's focus affordance                        | drawn inside a constant frame so focus never changes the content box (§4, rule 5)                                                                                       |
| `color.sync.a` / `.b` / `.c`                                                                        | the sync group's tile edge only                     | a group colour is never used without the group letter; the hue only repeats the letter, because a colour-only group can mislead a user about which panes share a symbol |
| `color.border.default`, `elevation.card`, `radius.card`                                             | the panel's frame, lift and corners, focused or not | focus never lifts a panel: a lift changes paint around the box and draws the eye away from the data                                                                     |
| `color.focus.ring` with a `color.surface.canvas` halo                                               | any focus or drop carrier drawn over panel content  | content is arbitrary; one tone alone fails over some content, two tones never do                                                                                        |
| `color.env.demo` / `color.env.live`                                                                 | the environment's rule only                         | never the only carrier (the word is mandatory), ≥ 3:1 for the rule and ≥ 4.5:1 for the word in focused and unfocused chrome, and never redefined by your epic           |

**Retired names: never use them.** `color.border.panel`, `color.accent.subtle`, `color.surface.base`, `motion.fast` and `motion.toast` were named in early catalogue text and never shipped; their replacements are in the pack's §5. **Re-measure when you add a background.** The sync hues and the drop-zone carrier are measured against the darkest and the lightest hosted content of each theme (the panel surfaces and a dense footprint; the pack's §6). If your panel paints a background darker or lighter than those, run `docs/design/_tools/e15_d13_ds_audit.py` with it added to `HOSTED` and record the result on your ticket before your panel ships.

## 4. The two docking rules, with their reasons (`16` §8 rules 1 and 5, as A40 amends them)

- **Rule 1 — the layout is a tree of n-ary row / column splits with tabsets holding leaves, within `LayoutGridSpec`'s limits.** Reason: the saved layout's contract stores exactly this tree (depth, node and leaf limits included); a binary model would need a translation that loses same-direction splits, and any panel the contract cannot store is a panel the user loses on the next load.
- **Rule 5 — panel focus is the 2 px inset frame plus the header bar in `color.focus.ring`: no elevation step and never a change of the content box; it is set by `Ctrl+\`, `F6` / `Shift+F6` and `Ctrl+Alt+←/→`; the splitter's hit band is 24 px.** Reason: the frame is inset specifically so that focusing a panel does not resize a WebGL canvas — a changed content box resizes the canvas and drops a frame on every click between panels. The keys are E15-D02 AD-7's, never `Ctrl+Tab`, which belongs to the browser.

## 5. Must never restyle

| N   | Never                                                                                                                                                                         | Reason                                                                                                                                                                      |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N-1 | Restyle, thicken, offset or animate the panel focus affordance, or show focus by an elevation step, a weight or a size change.                                                | It is inset so focus never resizes a canvas (§4); it is also the only cue that tells a user which panel takes Buy, Sell and Flatten.                                        |
| N-2 | Drop, shorten, recolour or hide the environment word on an order-capable panel or a floating window, or carry the environment by colour alone.                                | A user who misreads LIVE as DEMO places a real order; the word is the safety signal and the colour only repeats it.                                                         |
| N-3 | Show a sync group by colour alone, or move the letter out of the badge. A market panel in no group shows "No sync"; a panel with no symbol (an account panel) shows no badge. | A colour-only group can mislead a user about which panes share a symbol; the letter is the signal in greyscale, under every colour-vision simulation and in forced colours. |
| N-4 | Add a second header row, a second overflow menu or a second tablist.                                                                                                          | Each costs every layout a row or splits one responsibility across two components (`15` §8's rule: no two components with one responsibility).                               |
| N-5 | Bind a hex, px or ms value in panel chrome.                                                                                                                                   | Every value resolves to a token or stands in an exception with its reason (the pack's §9); a raw value drifts from the theme and the density.                               |

## 6. May override

| O   | You may                                                     | Within                                                                                            |
| --- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| O-1 | fill the header's action slot with your panel's own buttons | CMP-002 IconButtons at the control size; they collapse into the overflow menu first (E15-D03 D-3) |
| O-2 | set your panel's minimum width and height                   | the compact view takes over below them (E15-D04 D04-D-5); splitters stop there and say so         |
| O-3 | choose the kind's words and glyph                           | through CMP-019's registry (E05-T06), never a local glyph                                         |
| O-4 | draw anything inside the body                               | the body's own tokens; the chrome around it is not yours                                          |

## 7. Density, performance and analytics

**Density.** Two modes, compact and comfortable; a chart's `dense` changes no chrome height. The dock's values are one table in `16` §3 (the pack's §7): use the tokens, never the numbers. **Performance** (every rule names the budget it protects): the chrome is static — no per-frame repaint — so four order-flow panes hold ≥ 55 fps; a layout change is one mutation and a cut, so a transition stays ≤ 200 ms; a panel mounts ≤ 150 ms (`14-screens-catalogue.md` §0.5.7); a drop zone moves by transform and opacity only, never by layout. **Analytics** (analytics, never audit; properties are small closed sets, never a symbol, a name or an account):

| Event (primary)                                   | Ticket alias    | When                                 | Properties            |
| ------------------------------------------------- | --------------- | ------------------------------------ | --------------------- |
| `layout.panel_added`                              | `panel.added`   | Add panel, Duplicate                 | `type`, `placement`   |
| `layout.panel_removed`                            | `panel.removed` | Close                                | —                     |
| `panel.context_menu_opened`                       | —               | the panel menu opens (E15-D07)       | `panelType`, `method` |
| `layout.panel_moved`                              | —               | a drop, move mode, Move to ▸, a swap | `method`, `zone`      |
| `layout.split_created`                            | —               | a split made                         | `orientation`         |
| `layout.panel_floated`                            | `panel.floated` | Pop out                              | —                     |
| `layout.maximised`                                | —               | Maximise                             | —                     |
| `layout.panel_minimised`, `layout.panel_restored` | —               | the tray (PROPOSED in E15-D02)       | —                     |

E15-D02's `layout.*` names are primary and the ticket's are aliases; a later epic emits the primary name with these properties and invents no per-panel variant.

## 8. Buildability checklist (E15-D03 §17.3's form)

- [ ] The panel mounts in CMP-080 and its header is CMP-082; no other frame or header exists in the panel's code (R-1, R-2).
- [ ] The region name is a pure function of kind, symbol, interval and environment (R-3); a test changes the width and asserts the name unchanged.
- [ ] An order-capable panel renders CMP-075 in its header in every state, the compact view included (R-4).
- [ ] Focusing and unfocusing the panel leaves the content rectangle unchanged, asserted as geometry (N-1).
- [ ] Every header control and the handle measure at least 24 × 24 in both densities (R-7).
- [ ] Every chrome value is a token from §3 or the catalogue entry's Tokens row (N-5).
- [ ] The sync badge shows its letter in every state, the greyscale story included (N-3).
- [ ] The panel emits the §7 events with their primary names.
- [ ] The panel's stories sit in its entry's Storybook tree in dark / light × compact / comfortable, and axe reports no serious or critical finding on them.

## 9. The dry run `(heuristic)`

No session took place and none is claimed. **The run, 2026-10-30:** a separate agent instance, briefed as an E21 frontend engineer who has never worked on E15, was given this document alone and asked to plan the chrome of a hypothetical order-capable panel, "Liquidation map", before writing code. It listed its needs and, for each, the rule that answered it or "not found". 12<!--=COUNT:walk.needs--> needs: 10<!--=COUNT:walk.found--> found, 2<!--=COUNT:walk.nf--> not found; the three rules it read as ambiguous are clarified in place (R-4's scope, the badge on a panel with no symbol, the name at every width), and the stories-and-axe line it missed is added to §8.

| W    | Need                                                           | Answered by       | Not found → where it went                                                           |
| ---- | -------------------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------- |
| W-1  | mount the panel's frame in the dock                            | §2 R-1            | —                                                                                   |
| W-2  | one header row with the panel's own buttons                    | §2 R-2; §6 O-1    | —                                                                                   |
| W-3  | the region name with symbol, interval and environment          | §2 R-3            | —                                                                                   |
| W-4  | the environment badge on an order-capable panel                | §2 R-4; §5 N-2    | —                                                                                   |
| W-5  | the focus affordance; which panel takes Buy and Sell           | §4 rule 5; §5 N-1 | —                                                                                   |
| W-6  | a keyboard path for every pointer operation                    | §2 R-6            | —                                                                                   |
| W-7  | the density tokens and the 24 px targets                       | §2 R-7; §3; §7    | —                                                                                   |
| W-8  | the analytics events on add, move and close                    | §7                | —                                                                                   |
| W-9  | the kind's glyph and words                                     | §6 O-3            | —                                                                                   |
| W-10 | the tests: geometry, name, targets, stories, axe               | §8                | —                                                                                   |
| W-11 | a keyboard path to place an order from a row, with its confirm | not found         | the body's trading contract: the order ticket's (E30) and `05` §3; not panel chrome |
| W-12 | the body's order states (confirm, error, loading)              | not found         | the panel's own epic and CMP-080's `state` prop; not panel chrome                   |

The owner's own walkthrough, if wanted, runs after Done (BQ-19).
