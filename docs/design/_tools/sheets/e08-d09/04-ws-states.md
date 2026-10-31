# E08-D09 / 04 ws-states

File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-04-ws-states.png`; sheet `04-ws-states.json` (validated); theme dark.

Board 04 of ten (§0 L86: S-06 disconnected, S-07 reconnecting with the attempt count, S-08 resubscribe storm ("Connection unstable"), S-20 dropping updates). Grid (18000, 0); 4640 x 2506 px; footer W-01; "page E08-D09 SCR-147 Connectivity · board 04 · r1".

## Frames

- `SCR-147 · S-06 WS disconnected · dark` (S-06)
- `SCR-147 · S-07 reconnecting · dark` (S-07)
- `SCR-147 · S-08 resubscribe storm · dark` (S-08)
- `SCR-147 · S-20 our queue dropping updates · dark` (S-20)
- `SCR-147 · Force reconnect dialog · dark` (no S-id)

## Validator and size

- `04-ws-states.json: 0 errors, 2 warnings, 45 sections, 144648 bytes` (exit 0)
- 45 sections, 144648 bytes

## Live checks (11)

- modal: re-centre 'CMP-044 dialog · Force reconnect' after relayout (estimated 560 x 380 px)
- S-06 frame: read back socket 1's word 'Disconnected — last data 00:12 ago' and its old values in color.data-confidence.disconnected.text
- Force reconnect dialog: read back the focus ring on Cancel and the W-55 marker as the last line before the buttons
- root 'E08-D09 / 04 ws-states' at (18000, 0): read back the name exactly after the first section call; size 4640 x 2506
- after touchTexts + relayout: the annotation column (estimated 2596 px) ends inside the root (h 2506); raise the root's h to its end + 80 if not
- frame 'SCR-147 · S-06 WS disconnected · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-147 · S-07 reconnecting · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-147 · S-08 resubscribe storm · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'SCR-147 · S-20 our queue dropping updates · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-147 · Force reconnect dialog · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E08/img/E08-D09-04-ws-states.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (6)

- D09-G1 (§21.2 L699): a read of per-account, per-class usage, limit, window and headroom at 1 Hz, with the IP ho
- D09-G3 (§21.2 L701): a read of the inspector: per-topic age, gap count, the per-request and per-socket figures
- D09-G7 (§21.2 L705): a force-reconnect route; the audit code connectivity.reconnect_forced registered
- D09-G4 (§21.2 L702): resubscribe and snapshot re-seed counters; dropped-update and queue figures in a read
- D09-G12 (§21.2 L710): a step-up class for the two connectivity actions
- D09-G17 (§21.2 L715): the server permission each of the two writes needs (force reconnect, budget change)

## Spec gaps (1)

- connection rows: §5.2 gives no 'connected' word; healthy socket rows use S-01 "Within budget" (W-13), SR-9's "Market data connected." is an announcement only

## Deviations (4)

- G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string
- dialog width 560 px: a kit choice (no source gives CMP-044's width)
- board 04: frames draw the summary strip, the inspector (open on the state frames) and Actions only; the clock section between them is off the frame (§2.2 order kept)
- W-36 / W-57 T2 forms of Reconnect market data are named in the annotation only on board 04 (board 03 draws W-36; board 06 draws the view-as form)

## Copy keys (25)

- W-18 (§15 L433; S-06 (D04 + D02 verbatim))
- W-11 (§15 L426; origin label)
- W-45 (§15 L461; socket label)
- W-52 (§15 L467; blast radius)
- W-12 (§15 L427; origin action line)
- W-05 (§15 L419; not wired (S-19))
- W-29 (§15 L444; clock ok)
- W-13 (§15 L428; S-01)
- W-44 (§15 L460; inspector disclosure)
- W-50 (§15 L465; force reconnect trigger, title, confirm)
- W-02 (§15 L416; page `h1`; route name)
- W-03 (§15 L417; header meta)
- W-19 (§15 L434; S-07)
- W-20 (§15 L435; S-08 (verbatim))
- W-28 (§15 L443; S-20)
- W-51 (§15 L466; consequences)
- W-56 (§15 L471; churn line)
- W-54 (§15 L469; step-up slot)
- W-55 (§15 L470; audit marker (the marker's form))
- W-53 (§15 L468; private stream placeholder)
- W-59 (§15 L474; per-connection result)
- W-58 (§15 L473; completion)
- W-36 (§15 L451; T2 reason, hold)
- W-57 (§15 L472; T2 reason, connection budget)
- W-01 (§15 L415; board footer (verbatim))

## Copy gaps (14)

- "REST budget": tile heading, from the spec prose at L176 (not in §15)
- "Public market data": tile heading, from the spec prose at L176 (not in §15)
- "Private streams": tile heading, from the spec prose at L176 (not in §15)
- "Clock": tile heading, from the spec prose at L176 (not in §15)
- "IP hold": tile heading, from the spec prose at L176 (not in §15)
- "State": connection header column (§9's field list), from the spec prose at L335 (not in §15)
- "Topics held": connection header column (§9's field list), from the spec prose at L335 (not in §15)
- "Connected since": connection header column (§9's field list), from the spec prose at L335 (not in §15)
- "Reconnects in the last hour": connection header column (§9's field list), from the spec prose at L335 (not in §15)
- "Last ping": connection header column (§9's field list), from the spec prose at L335 (not in §15)
- "Subscription inspector": section h2, §2.2 anatomy, from the spec prose at L179 (not in §15)
- "Actions": section h2, §2.2 anatomy, from the spec prose at L181 (not in §15)
- "Admin area": the band region name, from §2.1 L171 (CMP-087 own string; not in §15)
- "Cancel": dialog button, from the spec prose at L369 (not in §15)

## Fallbacks (5)

- fallback: CMP-178's octagon glyph drawn with the local icon 'danger'
- fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)
- fallback: CMP-178's triangle glyph drawn with the local icon 'warning'
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim

## Sources (1)

- spec E08-D09.md md5 9146d4d4 (§0 L86, §2, §3, §5.2, §15, §16, §17); hand-off E08-D09-handoff.md md5 3dc8240e

## Tokens (49)

- type.ui.caption
- color.text.secondary
- color.data-confidence.disconnected.indicator
- size.icon
- type.ui.body-strong
- color.text.primary
- space.inset.xs
- type.ui.body
- space.inset.sm
- type.num.base
- color.data-confidence.disconnected.text
- color.surface.canvas
- type.ui.heading-sm
- color.text.link
- color.text.tertiary
- color.surface.raised
- radius.card
- space.inset.lg
- space.stack.sm
- color.neutral.default
- border.thick
- color.status.success.strong
- space.stack.md
- radius.control
- color.border.default
- space.stack.xs
- space.button.paddingX
- color.action.secondary.default
- type.ui.heading-md
- space.stack.lg
- color.surface.app
- color.surface.hover
- color.surface.selected
- color.border.subtle
- space.inset.md
- color.data-confidence.reconnecting.indicator
- color.data-confidence.reconnecting.text
- color.status.warning.strong
- color.focus.ring
- border.focus
- color.text.on-action
- color.action.primary.default
- color.surface.overlay
- radius.dialog
- space.dialog.padding
- border.hairline
- opacity.scrim
- color.surface.sunken
- type.ui.label
