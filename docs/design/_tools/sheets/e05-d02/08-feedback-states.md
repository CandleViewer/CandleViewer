# E05-D02 / 08 feedback-states

File `E05-D02 boards`, page `E05-D02 slice 4 feedback and overlays` (render with `--page`); export `docs/design/E05/img/E05-D02-08-feedback-states.png`; sheet `08-feedback-states.json` (validated); theme dark.

Board 08: slice 4's feedback states, eleven blocks, the spec's named cells.

## Blocks

- `CMP-015 · Skeleton` — slice 4 L1000-1056; spec export `img/CMP-015-skeleton.png`
- `CMP-023 · ProgressBar` — slice 4 L1184-1240; spec export `img/CMP-023-progress-bar.png`
- `CMP-026 · EmptyState` — slice 4 L1241-1297; spec export `img/CMP-026-emptystate.png`
- `CMP-027 · ErrorState` — slice 4 L1298-1364; spec export `img/CMP-027-errorstate-inlineerror.png`
- `CMP-028 · Callout` — slice 4 L1365-1435; spec export `img/CMP-028-callout-banner.png`
- `CMP-029 · Skeleton-Chart placeholder` — slice 4 L1436-1473; spec export `img/CMP-029-skeleton-chart.png`
- `CMP-038 · InlineSpinnerText` — slice 4 L1474-1517; spec export `img/CMP-038-inlinespinnertext.png`
- `CMP-045 · Toast` — slice 4 L1779-1860; spec export `img/CMP-045-toast-notification.png`
- `CMP-089 · ForbiddenState` — slice 4 L1931-1988; spec export `img/CMP-089-forbiddenstate.png`
- `CMP-090 · NotFoundState` — slice 4 L1989-2030; spec export `img/CMP-090-notfoundstate.png`
- `CMP-091 · GlobalErrorBoundaryFallback` — slice 4 L2031-2086; spec export `img/CMP-091-globalerrorboundaryfallback.png`

## Content checks

- every block draws the spec's named cells (Variants x States table or paragraph)
- every specimen string k.say()'d from the frozen slice 4 spec (slice 1 / 3 where nested)
- tone = glyph + word in every status cell (never colour alone)
- CMP-045 T2 action: lock leads each full label, tertiary label, one reason line (2a notice)
- no inst node; only the local icons locked and close

## Live checks for the drawer

- CMP-028 hatched edge: the 1 px ticks read at 1x on danger.subtle
- every toast / callout start edge reads at 1x (2 px abs rect at x 0)
- render on page 'E05-D02 slice 4 feedback and overlays' (mkcall4.py … --page 'E05-D02 slice 4 feedback and overlays'; its default would be 'E05-D02')
- root 'E05-D02 / 08 feedback-states': hugs its content (about 4101 x 3406 px estimated)

## Not drawn — the text is binding

- CMP-015: interactive states (it is hidden and inert); loading is itself; empty and error are the host's. — not drawn, the text is binding (slice 4 L1000-1056)
- CMP-015: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1000-1056)
- CMP-015: comfortable density — not drawn, the text is binding (slice 4 L1000-1056)
- CMP-023: interactive states (not interactive); indeterminate (never, §6 H12); error (the host's CMP-027). — not drawn, the text is binding (slice 4 L1184-1240)
- CMP-023: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1184-1240)
- CMP-023: comfortable density — not drawn, the text is binding (slice 4 L1184-1240)
- CMP-026: interactive states (static; the CTA and link are CMP-001's, CMP-021's); loading (CMP-015 or backfill). — not drawn, the text is binding (slice 4 L1241-1297)
- CMP-026: the recording cell's owner CTA to the recorder (wording under review, E16-D01 §4) — not drawn, the text is binding (slice 4 L1241-1297)
- CMP-026: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1241-1297)
- CMP-026: comfortable density — not drawn, the text is binding (slice 4 L1241-1297)
- CMP-027: interactive states (its buttons are CMP-001's); loading and empty (other components). — not drawn, the text is binding (slice 4 L1298-1364)
- CMP-027: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1298-1364)
- CMP-027: comfortable density — not drawn, the text is binding (slice 4 L1298-1364)
- CMP-028: interactive states (its buttons are CMP-001's, CMP-002's); empty and error (CMP-026, CMP-027). — not drawn, the text is binding (slice 4 L1365-1435)
- CMP-028: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1365-1435)
- CMP-028: comfortable density — not drawn, the text is binding (slice 4 L1365-1435)
- CMP-029: every interactive state (it is hidden and inert); empty and error (CMP-026, CMP-027 in the pane). — not drawn, the text is binding (slice 4 L1436-1473)
- CMP-029: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1436-1473)
- CMP-029: comfortable density — not drawn, the text is binding (slice 4 L1436-1473)
- CMP-038: hover, focus-visible, active and disabled (not interactive; Cancel is CMP-001's); empty and error (the host's outcome replaces it). — not drawn, the text is binding (slice 4 L1474-1517)
- CMP-038: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1474-1517)
- CMP-038: comfortable density — not drawn, the text is binding (slice 4 L1474-1517)
- CMP-045: hover (behaviour); disabled (never gated whole); the stack, count and storm summary (CMP-212, CMP-165). — not drawn, the text is binding (slice 4 L1779-1860)
- CMP-045: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1779-1860)
- CMP-045: comfortable density — not drawn, the text is binding (slice 4 L1779-1860)
- CMP-089: hover, focus and disabled of the page (its link and button are CMP-021's and CMP-001's); loading (the landing renders from the 403 or the session, with no fetch beyond D09 §5.1's one re-read). — not drawn, the text is binding (slice 4 L1931-1988)
- CMP-089: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1931-1988)
- CMP-089: comfortable density — not drawn, the text is binding (slice 4 L1931-1988)
- CMP-090: interactive states (its links are CMP-021's); loading (it resolves client-side with no network call, 14:2918). — not drawn, the text is binding (slice 4 L1989-2030)
- CMP-090: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1989-2030)
- CMP-090: comfortable density — not drawn, the text is binding (slice 4 L1989-2030)
- CMP-091: interactive states of the surface (its buttons are CMP-001's); loading and empty (other components). It is an outcome, never T2 (conventions 37). — not drawn, the text is binding (slice 4 L2031-2086)
- CMP-091: the route / app h1, the error id line and the protection and repeated-crash sentences (E10-D03's strings) — not drawn, the text is binding (slice 4 L2031-2086)
- CMP-091: every combination beyond the named cells — not drawn, the text is binding (slice 4 L2031-2086)
- CMP-091: comfortable density — not drawn, the text is binding (slice 4 L2031-2086)

## Strings used

- 'page 3 of ~9' — CMP-023 slice 4 L1184-1240
- 'Loading history' — CMP-023 slice 4 L1184-1240
- '0 %' — CMP-023 slice 4 L1184-1240
- '100 %' — CMP-023 slice 4 L1184-1240
- '31 %' — CMP-023 slice 4 L1184-1240
- '85 %' — CMP-023 slice 4 L1184-1240
- '97 %' — CMP-023 slice 4 L1184-1240
- 'History starts {ts} — recording began then' — CMP-026 slice 4 L1241-1297
- 'No rules yet — start from a template' — CMP-026 slice 4 L1241-1297
- 'Browse templates' — CMP-026 slice 4 L1241-1297
- 'Show coverage' — CMP-026 slice 4 L1241-1297
- 'Loading history — page 3 of ~9' — CMP-026 slice 4 L1241-1297
- 'No rows match: Bid-stacked, Delta negative' — CMP-026 slice 4 L1241-1297
- 'Clear filters' — CMP-026 slice 4 L1241-1297
- "Couldn't load users — store unavailable." — CMP-026 slice 4 L1241-1297
- 'Retry' — CMP-026 slice 4 L1241-1297
- 'No rules yet.' — CMP-026 slice 4 L1241-1297
- "Your role can't change rules." — CMP-026 slice 4 L1241-1297
- 'Only the owner can start recording.' — CMP-026 slice 4 L1241-1297
- "Couldn't load users — store unavailable." — CMP-027 slice 4 L1298-1364
- 'Retry' — CMP-027 slice 4 L1298-1364
- 'Technical details' — CMP-027 slice 4 L1298-1364
- 'Sensitivity high may produce many false positives' — slice 4 (outside the CMP section)
- 'Not sent — your access changed.' — CMP-027 slice 4 L1298-1364
- "Owner only: your role can't use this action." — CMP-001 slice 1 L621-694
- 'Not sent — the price is off-tick' — CMP-027 slice 4 L1298-1364
- 'code' — CMP-027 slice 4 L1298-1364
- 'correlation id' — CMP-027 slice 4 L1298-1364
- "Can't submit — 2 problems" — CMP-027 slice 4 L1298-1364
- 'Username' — slice 3 (outside the CMP section)
- 'Account' — slice 3 (outside the CMP section)
- 'Reconnected — backfilling history' — CMP-028 slice 4 L1365-1435
- 'Recorded coverage catching up: 00:41 remaining.' — CMP-028 slice 4 L1365-1435
- 'Degraded — some data feeds are stale' — CMP-028 slice 4 L1365-1435
- 'Book and tape are live; 1 of 4 topics stale 6s. Recent trades may lag.' — CMP-028 slice 4 L1365-1435
- 'Trading locked: daily loss limit −2 % reached at 13:41 UTC.' — CMP-028 slice 4 L1365-1435
- 'Accepted — stop 63,900.0 held by the exchange · exchange id ends …5f60' — CMP-028 slice 4 L1365-1435
- 'Connection unstable — last data Ns ago' — CMP-028 slice 4 L1365-1435
- 'Retry now' — CMP-028 slice 4 L1365-1435
- 'Details' — CMP-028 slice 4 L1365-1435
- 'Disconnected — reconnecting (attempt 3, next in 4 s)' — CMP-028 slice 4 L1365-1435
- 'Last data 00:12 ago. Trading is disabled while offline.' — CMP-028 slice 4 L1365-1435
- 'Your exchange-side stop-losses are unaffected.' — CMP-028 slice 4 L1365-1435
- 'Your access changed just now.' — CMP-028 slice 4 L1365-1435
- 'Reconnected' — CMP-028 slice 4 L1365-1435
- 'While you were offline: 1 order filled, 1 stop moved by a rule.' — CMP-028 slice 4 L1365-1435
- 'Flatten now' — CMP-028 slice 4 L1365-1435
- 'Set stop by hand' — CMP-028 slice 4 L1365-1435
- 'Order live · protective stop pending — attaching the exchange stop (attempt 1 of 3)' — CMP-028 slice 4 L1365-1435
- 'Loading 5,000 bars…' — CMP-029 slice 4 L1436-1473
- 'Loading positions' — CMP-038 slice 4 L1474-1517
- 'Still loading… the server is slow to answer' — CMP-038 slice 4 L1474-1517
- 'Still loading positions…' — CMP-038 slice 4 L1474-1517
- 'Cancel' — CMP-038 slice 4 L1474-1517
- 'Undo' — CMP-045 slice 4 L1779-1860
- 'EMA 21 removed.' — CMP-045 slice 4 L1779-1860
- 'Session extended.' — CMP-045 slice 4 L1779-1860
- 'Idle timer reset. Next warning in 14:00.' — CMP-045 slice 4 L1779-1860
- 'Accepted — stop 63,900.0 held by the exchange' — CMP-045 slice 4 L1779-1860
- 'Open chart' — CMP-045 slice 4 L1779-1860
- 'Snooze ▾' — CMP-045 slice 4 L1779-1860
- 'Disable' — CMP-045 slice 4 L1779-1860
- 'Details' — CMP-045 slice 4 L1779-1860
- 'Warning · Alert' — CMP-045 slice 4 L1779-1860
- 'BTC above 65k' — CMP-045 slice 4 L1779-1860
- 'Last price 65,012.5 crossed above 65,000' — CMP-045 slice 4 L1779-1860
- 'BTCUSDT · 5m' — CMP-045 slice 4 L1779-1860
- 'Not sent — the price is off-tick' — slice 4 (outside the CMP section)
- 'Template removed.' — slice 4 (outside the CMP section)
- 'Snooze' — CMP-045 slice 4 L1779-1860
- "Your role can't change alerts." — CMP-045 slice 4 L1779-1860
- 'Ref {instance}' — CMP-089 slice 4 L1931-1988
- "You don't have access to this" — CMP-089 slice 4 L1931-1988
- "Your role can't see the journal. Ask the owner if you need it." — CMP-089 slice 4 L1931-1988
- 'Back to your workspace' — CMP-089 slice 4 L1931-1988
- 'Copy details' — CMP-089 slice 4 L1931-1988
- 'Your access changed' — CMP-089 slice 4 L1931-1988
- "Your role can't see the journal any more — this changed just now. Anything you already sent was decided by the server: check Orders. Ask the owner if this is unexpected." — CMP-089 slice 4 L1931-1988
- "This account isn't assigned to you." — CMP-089 slice 4 L1931-1988
- 'sub_001' — slice 4 (outside the CMP section)
- "There's nothing at" — CMP-090 slice 4 L1989-2030
- '/nowhere.' — CMP-090 slice 4 L1989-2030
- 'Try:' — CMP-090 slice 4 L1989-2030
- 'Workspace' — CMP-090 slice 4 L1989-2030
- 'Journal' — CMP-090 slice 4 L1989-2030
- 'Settings' — CMP-090 slice 4 L1989-2030
- 'Page not found' — CMP-090 slice 4 L1989-2030
- '/admin/users' — CMP-090 slice 4 L1989-2030
- 'this workspace was deleted' — CMP-090 slice 4 L1989-2030
- 'This panel stopped working' — CMP-091 slice 4 L2031-2086
- 'Reload panel' — CMP-091 slice 4 L2031-2086
- 'Remove panel' — CMP-091 slice 4 L2031-2086
- 'Copy diagnostics' — CMP-091 slice 4 L2031-2086
- 'Reload page' — CMP-091 slice 4 L2031-2086
- 'Reload app' — CMP-091 slice 4 L2031-2086
- 'Start in safe mode' — CMP-091 slice 4 L2031-2086
- 'Technical detail' — CMP-091 slice 4 L2031-2086

## Stamps

- PROPOSED · slice 4 H3 (slice 4 L543)
- PROPOSED · slice 4 H9 (slice 4 L604)
- PROPOSED · slice 4 H4 (slice 4 L552)
- PROPOSED · slice 4 H12 (slice 4 L637)
- PROPOSED · slice 4 H13 (slice 4 L644)
- PROPOSED · slice 4 H14 (slice 4 L648)
- PROPOSED · slice 4 H5 (slice 4 L562)
- PROPOSED · slice 4 H15 (slice 4 L656)
- PROPOSED · slice 4 H29 (slice 4 L822)
- PROPOSED · slice 4 H6 (slice 4 L577)
- PROPOSED · slice 4 H26 (slice 4 L786)
- PROPOSED · slice 4 H27 (slice 4 L803)
- PROPOSED · slice 4 H18 (slice 4 L680)
- PROPOSED · slice 4 H19 (slice 4 L685)
- PROPOSED · slice 4 H20 (slice 4 L689)

## Kit choices and deviations

- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- author choice (board 08): CMP-089 / 090 / 091 drawn at 480 px wide full-panel stand-ins (build-notes §4 board 08)
- author choice (board 08): CMP-026 / 027 cells at 360 px (within §5.1's 480 px maximum) and CMP-028 inline cells at 420 px, the band cell at 560 px
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- fallback: CMP-028's hatched edge (45°, 1 px color.status.danger.strong lines at 6 px pitch on color.status.danger.subtle) is drawn as 1 px ticks at 6 px pitch on a 4 px subtle column: cvsheet has no rotation
- fallback: CMP-014's arc has no dashed / partial stroke in cvsheet: drawn as a full ring in color.border.default with a short arc rect in the indicator colour (a static frame of the spin)
- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- token: size.icon.sm (12) / size.icon.lg (20) are Tier-1 primitives (slice 1 §1, validator WARN)

## Copy gaps

- CMP-023 meter / success / warning / danger cells: the spec gives no label string (CMP-177's and the export's names are the hosts'); drawn unlabelled, named by the host (Label=hidden's form)
- CMP-026 recording: the owner's CTA to the recorder has no string (`14:83`, wording under review in E16-D01 §4): not drawn; the link `Show coverage` is
- CMP-027 details: the code and correlation id values are host data; drawn as their names ('code', 'correlation id') in type.num.sm
- CMP-027 summary: the field names are the host form's; slice 3's 'Username' and 'Account' stand in
- CMP-027 inline: the spec's '{reason}' is drawn with slice 1's D09 key 'Owner only: your role can't use this action.'
- CMP-045 danger: the spec names 'an order rejection' without a title; CMP-027's banner line 'Not sent — the price is off-tick' (slice 4) stands in
- CMP-045 focused: the cell names no toast; E14-D04's 'Template removed. Undo' (slice 4 §6) is drawn
- CMP-089 account: the echoed id is host data; slice 4's account 'sub_001' (CMP-044) stands in
- CMP-091: the route / app h1, the error id, the host's protection sentence and the repeated-crash sentence are E10-D03's strings, not in slice 4: not drawn (the id and the stack lines are drawn as num-line stand-ins only in the details box)

## Sources

- spec docs/design/E05/E05-D02-feedback-overlays.md at 966f9edcd md5 fb6e8b12d79fc6c057f0b695d495867d (frozen copy E05-D02-feedback-overlays@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 4 feedback and overlays'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "08-feedback-states.json", "shapes": 957, "texts": 381, "by_type": {"board": 403, "ellipse": 4, "icon": 16, "rect": 153, "text": 381}, "sections": 20, "bytes": 168580, "largest_section": 11903, "largest_compacted": 8845}
