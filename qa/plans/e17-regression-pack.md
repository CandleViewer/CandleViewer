# E17 regression pack: the web client's transport states, end to end

Ticket: E17-Q04 (#569), part 1 of 2 (`Refs #569`, `Partial:`). Ruling of record: 6556829275 (BQ-01 to BQ-14, all as
recommended, with its precisions). Base: `origin/main` be4294d0e2<!--=SHA:base-->.
Sources: `qa/plans/e17-ws-conformance.md` (E17-Q01, the protocol half), `docs/design/E17/E17-D02.md` (the 24-row
state matrix, section 2) and `docs/design/E17/E17-D01.md` (the six states, section 4). E17-D04 (#408) has not merged:
nothing of it is quoted here. E17-D02's issue (#325) is open while its text is merged; the merged text is the one read.
Paths below are relative to `apps/web/` unless they start with `qa/`, `docs/`, `apps/` or `packages/`.

This pack holds what a trader sees when the transport misbehaves, forced one state at a time against the real web
client and shell, on the fixture gateway. Protocol conformance, chaos and load are other packs (E17-Q01, E17-Q02,
E17-Q03). Section H says where each part ran; a cell never says "passed" for a thing that was not run (BQ-11).
The audit tool `qa/plans/_tools/e17_q04_audit.py` (BQ-05; a new `_tools` folder beside the plans, as the design tools'
folder is beside the designs) checks this page against the specs, E17-D02 and `origin/main`.

## How to run

Command names are owned by `AGENTS.md` section 4; this page names configs and selectors only.

| Lane           | Config and selector                                                                                   | Bundle                                                  | Where it runs                             |
| -------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------- |
| Stub lane      | `e2e/playwright.config.ts`, the `e2e/e17/*.spec.ts` files, title tag `@e17-regression`, `--retries=0` | shipped `dist/`                                         | per PR and nightly (the existing web job) |
| Flagged lane   | `e2e/playwright.fault.config.ts` (`e2e/e17/*.flagged.ts`)                                             | built with `CV_ALLOW_FAULT_INJECTION=1` outside `dist/` | not wired into a job yet (section G, G2)  |
| Real-time lane | `e2e/playwright.e17-nightly.config.ts` (`e2e/e17/*.nightly.ts`), title tag `@e17-realtime`            | shipped `dist/`                                         | not wired into a job yet (section G, G2)  |

- No network and no live exchange: the gateway is `e2e/support/wsHarness.ts` with its recorded ticker fixture
  (C-13.5). The shipped bundle carries neither the harness (`e2e/market-data/ws-harness.spec.ts`) nor the fault
  channel (Q04-S02).
- Every spec is written for `--retries=0`. A test that passes only on a retry is a defect in the test and leaves the
  pack (BQ-10).
- The per-PR check stays web-only. The Electron pair is a parked row (section B2, E-1) (BQ-04).

### Entry rule

A case enters the pack after 10 consecutive green nightly runs with zero retries (BQ-07, BQ-10). Until then its
status is `candidate (n/10)`, `n` the nightly greens so far. No regression pack index exists at `main`; this page
follows the per-epic shape of the E04, E08 and E09 packs and adds none (BQ-07).

## A. Cases

Files: T = `e2e/e17/transport-states.spec.ts`, N = `e2e/e17/named-rows.spec.ts` (bodies in `e2e/e17/namedRows.ts`),
X = `e2e/e17/accessibility.spec.ts`, F = `e2e/e17/fault-channel.flagged.ts`. Helpers: `e2e/e17/support.ts`. A test's
title starts with its case id; a loop's tests share it. Each case cites the C-rule (`23` section 16, a `23` section
where no C-rule names it, or a CONSTITUTION rule), the E17-D02 row and the story scenario or ticket AC it guards,
exactly as its `covers` annotation does. Driver: `harness` = the fixture gateway on the shipped bundle; `fault` = the
dev-only fault channel on the flagged build (BQ-02). Cases: 35<!--=COUNT:cases-->.

### A0. Premises

| Case    | What it shows                                                                                    | File | Why the suite needs it                                                                                           |
| ------- | ------------------------------------------------------------------------------------------------ | ---- | ---------------------------------------------------------------------------------------------------------------- |
| Q04-S01 | The page's clock moves the page, not the shared worker: the worker's `ping` carries its own time | T    | BQ-09: ages and T4 steps move on the page's clock; the worker's retries and the gateway's counter keep real time |
| Q04-S02 | The suite runs on the shipped bundle, which has no fault channel                                 | T    | BQ-02: the production-absence check of the driver the suite does not use                                         |

### A1. Behaviour to test

| Case    | What a person sees                                                                                          | File | C-rule | D02 row                     | Story or AC                                         | Driver  | Pack             |
| ------- | ----------------------------------------------------------------------------------------------------------- | ---- | ------ | --------------------------- | --------------------------------------------------- | ------- | ---------------- |
| Q04-T01 | First connect reads "Connecting…"; no region, no announcement; then Live                                    | T    | C7     | 1                           | US-MKT-005 Reconnect                                | harness | candidate (0/10) |
| Q04-T02 | Live: no region, no announcement, one socket                                                                | T    | C7     | 2                           | US-MKT-005 Subscribed                               | harness | candidate (0/10) |
| Q04-T03 | A lost transport shows Disconnected with the last good time, said once; the age moves, nothing more is said | T    | C7     | 3                           | US-MKT-003 Feed interrupted; AC 2                   | harness | candidate (0/10) |
| Q04-T04 | Reconnect: Live on a new session, a fresh `snap` from `s: 1`, the alert cleared                             | T    | C7     | 16                          | US-MKT-005 Reconnect; AC 3                          | harness | candidate (0/10) |
| Q04-T05 | A 60 s outage on the page's clock, then Live; the new snapshot is newer than anything before it             | T    | C7     | 20                          | US-MKT-005 Reconnect; AC 3                          | harness | candidate (0/10) |
| Q04-T06 | T4: the age line turns at 30 s; the region escalates at 5 min                                               | T    | C7     | 20                          | AC 2                                                | harness | candidate (0/10) |
| Q04-T07 | A fatal close (4400): "Offline — retry stopped", said once; only Retry now brings it back                   | T    | C7     | 6                           | US-MKT-005 Reconnect                                | harness | candidate (0/10) |
| Q04-T08 | Session ended (4403): Sign in, no Retry now, said once                                                      | T    | C7     | 21                          | AC 2                                                | harness | candidate (0/10) |
| Q04-T09 | A sequence gap is a resync on the same socket; the chrome ends Live                                         | T    | C2     | 9                           | US-MKT-006 Gap detection; US-MKT-007 Sequence break | harness | candidate (0/10) |
| Q04-T10 | While `system` resyncs, the kill switch reads unknown: order entry off (R6), said once; then gone           | T    | C12    | 18                          | WS-E06; AC 2                                        | harness | candidate (0/10) |
| Q04-T11 | A `lagging` class: no chip change, no region, no announcement                                               | T    | C4     | 4                           | AC 2                                                | harness | candidate (0/10) |
| Q04-T12 | `err` by class: modal, badge, toast with a console error, capacity toast (four tests)                       | T    | §10.3  | 23                          | AC 2                                                | harness | candidate (0/10) |
| Q04-T13 | A slow-consumer close (4429): Disconnected, said once, then Live on its own                                 | T    | C7     | 3                           | US-MKT-005 Reconnect                                | harness | candidate (0/10) |
| Q04-T14 | The exchange's public feed down: a CMP-092 warning row, said politely; the chip stays Live                  | T    | §15.9  | 13                          | US-MKT-003 Feed interrupted                         | harness | candidate (0/10) |
| Q04-T15 | Maintenance, then the store down: blocking rows, said assertively; no connection region                     | T    | §15.9  | 22                          | AC 2                                                | harness | candidate (0/10) |
| Q04-T16 | The private feed reconnecting: a row for 10 s, then the region's R5                                         | T    | §15.9  | 24, 17                      | AC 2                                                | harness | candidate (0/10) |
| Q04-N01 | C8, restore half: hide then show sends only heartbeats, no new `snap`, same socket, Live                    | N    | C8     | 2                           | AC 1                                                | harness | candidate (0/10) |
| Q04-N02 | C12: a `kill_switch` frame puts the region in R2, said once, with no request that could poll the switch     | N    | C12    | 17                          | WS-E06; AC 1                                        | harness | candidate (0/10) |
| Q04-N03 | C12: a `shutdown_notice` puts the region in R1, said once                                                   | N    | C12    | 8                           | AC 1                                                | harness | candidate (0/10) |
| Q04-N04 | C12 after a reconnect: the switch is what `auth_ok` says, never the old R2                                  | N    | C12    | 16                          | WS-E06; AC 3                                        | harness | candidate (0/10) |
| Q04-X01 | axe, zero violations of any impact, in nine forced states (section D)                                       | X    | C-14.1 | 1, 2, 3, 5, 6, 8, 9, 17, 21 | AC 4                                                | harness | candidate (0/10) |
| Q04-X02 | Retry now by Tab, then Enter or Space (two tests); a state change never moves focus; no dialog              | X    | C-14.1 | 6                           | AC 4                                                | harness | candidate (0/10) |
| Q04-X03 | Reduced motion: the chip changes with no cross-fade                                                         | X    | C-14.1 | 3                           | AC 4                                                | harness | candidate (0/10) |
| Q04-X04 | Full motion, the control: the same change fades                                                             | X    | C-14.1 | 3                           | AC 4                                                | harness | candidate (0/10) |
| Q04-X05 | 200% reflow at 640 px: no horizontal scroll, Retry now in view                                              | X    | C-14.1 | 6                           | AC 4                                                | harness | candidate (0/10) |
| Q04-F01 | Fault `close` 4400: Offline — retry stopped, said once                                                      | F    | C7     | 6                           | AC 2                                                | fault   | candidate (0/10) |
| Q04-F02 | Fault `drop`: the next `system` delta never arrives, so the client resyncs                                  | F    | C2     | 9                           | US-MKT-006 Gap detection                            | fault   | candidate (0/10) |
| Q04-F03 | Fault `delay`: the kill switch reaches the region no sooner than the delay                                  | F    | C12    | 17                          | AC 2                                                | fault   | candidate (0/10) |
| Q04-F04 | Fault `quality`: the class takes a number and the next real delta applies with no gap                       | F    | C4     | 5                           | AC 2                                                | fault   | candidate (0/10) |
| Q04-F05 | Fault `shutdown`: R1, said once                                                                             | F    | C12    | 8                           | AC 1                                                | fault   | candidate (0/10) |
| Q04-F06 | Fault `killSwitch`: R2, said once                                                                           | F    | C12    | 17                          | AC 1                                                | fault   | candidate (0/10) |
| Q04-F07 | Fault `revoke` on `system`: the switch reads unknown (R6), said once                                        | F    | C12    | 15, 18                      | WS-E06                                              | fault   | candidate (0/10) |
| Q04-F08 | Fault `staleSnap` on `system`: a stale snapshot leaves the switch unknown (R6), said once                   | F    | C21    | 12, 18                      | WS-E06                                              | fault   | candidate (0/10) |

Q04-R01 (`e2e/e17/realtime.nightly.ts`, `@e17-realtime`) measures AC 2's 2 s and AC 3's 10 s on real timers and
records the numbers; it is never a PR gate and never a pack row.
Existing specs this pack cites and does not copy: `e2e/market-data/ws-harness.spec.ts` (the wire, and the harness's
own frames) and `e2e/system-states/break-glass-notice.spec.ts` (CMP-092's `notice` row).

### A2. Mutation record

Each line is a change in the client that must turn its case red (BQ-08). The named rows (C8, C12) have one line per
assertion, numbered as the `// M-Nnn-k` mark on the assertion's line in `e2e/e17/namedRows.ts` and
`e2e/e17/named-rows.spec.ts`; the other cases have one line per case. Written, not yet run (section H, H6).

| Mutation | Case    | Change that must fail it                                                              |
| -------- | ------- | ------------------------------------------------------------------------------------- |
| M-T01    | Q04-T01 | the first connect is drawn as a region, or announced                                  |
| M-T02    | Q04-T02 | a live client draws a region, or opens a second socket                                |
| M-T03    | Q04-T03 | the region drops the last-data age; the announcement is written on every tick         |
| M-T04    | Q04-T04 | the client resumes the old session (no new `hello`), or the alert outlives the outage |
| M-T05    | Q04-T05 | the age is read from the worker's clock, or the region stays after the reconnect      |
| M-T06    | Q04-T06 | the age line keeps its ink past 30 s, or the region never escalates at 5 min          |
| M-T07    | Q04-T07 | a 4400 close is retried by the client itself (a third socket), or draws Sign in       |
| M-T08    | Q04-T08 | a 4403 close draws Retry now                                                          |
| M-T09    | Q04-T09 | a gap closes the socket, or leaves the region drawn after the resync                  |
| M-T10    | Q04-T10 | a resyncing `system` keeps the last kill-switch value instead of unknown              |
| M-T11    | Q04-T11 | `lagging` changes the chip or draws the region                                        |
| M-T12    | Q04-T12 | a code maps to another class's surface, or a client-bug code skips the console        |
| M-T13    | Q04-T13 | a 4429 close with `reconnect: true` stops the retry                                   |
| M-T14    | Q04-T14 | the public-feed row is not drawn, or is said assertively                              |
| M-T15    | Q04-T15 | maintenance is routed to the connection region, or not said                           |
| M-T16    | Q04-T16 | the private-feed row never hands over to R5, or both surfaces show at once            |
| M-N01-1  | Q04-N01 | `visible` sends `sub`, `resync` or `ctl`                                              |
| M-N01-2  | Q04-N01 | restoring the tab asks for a new snapshot                                             |
| M-N01-3  | Q04-N01 | hiding the tab closes the socket                                                      |
| M-N01-4  | Q04-N01 | a hidden tab changes the chip                                                         |
| M-N01-5  | Q04-N01 | a hidden tab draws the region                                                         |
| M-N02-1  | Q04-N02 | the client waits for REST before it shows R2                                          |
| M-N02-2  | Q04-N02 | R2 is drawn as a transport state                                                      |
| M-N02-3  | Q04-N02 | R2's title changes                                                                    |
| M-N02-4  | Q04-N02 | R2 is not announced, or announced politely                                            |
| M-N02-5  | Q04-N02 | the kill switch changes the chip                                                      |
| M-N02-6  | Q04-N02 | R2 is announced again on a later frame                                                |
| M-N02-7  | Q04-N02 | the client polls the switch over REST after the frame                                 |
| M-N03-1  | Q04-N03 | a `shutdown_notice` does not put the region in R1                                     |
| M-N03-2  | Q04-N03 | R1 is drawn as a transport state                                                      |
| M-N03-3  | Q04-N03 | R1 is not announced                                                                   |
| M-N03-4  | Q04-N03 | the notice changes the chip before the close                                          |
| M-N03-5  | Q04-N03 | R1 is announced again on a later frame                                                |
| M-N03-6  | Q04-N03 | the client polls REST after the notice                                                |
| M-N04-1  | Q04-N04 | a `kill_switch` frame does not reach the region                                       |
| M-N04-2  | Q04-N04 | the old R2 outranks Disconnected while the link is down                               |
| M-N04-3  | Q04-N04 | the client keeps the pre-outage switch instead of `auth_ok`'s                         |
| M-N04-4  | Q04-N04 | the reconnect leaves the chip off Live                                                |
| M-X01    | Q04-X01 | any axe violation, of any impact, in a forced state                                   |
| M-X02    | Q04-X02 | the region takes focus, traps it, or Retry now ignores Enter or Space                 |
| M-X03    | Q04-X03 | the cross-fade runs under reduced motion                                              |
| M-X04    | Q04-X04 | the cross-fade is removed for everyone (the control fails)                            |
| M-X05    | Q04-X05 | the region forces a horizontal scroll at 640 px                                       |
| M-F01    | Q04-F01 | the channel's `close` does not reach the close policy                                 |
| M-F02    | Q04-F02 | `drop` does not drop, or the client patches over the gap                              |
| M-F03    | Q04-F03 | `delay` passes frames at once                                                         |
| M-F04    | Q04-F04 | an injected frame does not shift the server's numbering                               |
| M-F05    | Q04-F05 | `shutdown` injects nothing                                                            |
| M-F06    | Q04-F06 | `killSwitch` injects nothing                                                          |
| M-F07    | Q04-F07 | a revoked `system` keeps the last kill-switch value                                   |
| M-F08    | Q04-F08 | a stale `system` snapshot is trusted                                                  |

## B. The E17-D02 state matrix: one ledger row per matrix row

The 24 rows of `docs/design/E17/E17-D02.md` section 2 are the coverage ledger; the acceptance names are E17-D01's six
states (BQ-01). The State cell is the matrix row's name as D02 writes it. Status: `covered` (the cases cover the row),
`partial` (the cases cover what the build shows; the rest is parked), `unit` (no E2E driver in this pack; the unit test
named covers it) or `parked` (the surface is not built). A parked half names a probe: a string that is absent from
the path at `main` today. When it appears there, the audit tool fails until the row is updated (BQ-03). A parked row
is never a skipped test.

Counts: 5<!--=COUNT:ledger.covered--> covered, 14<!--=COUNT:ledger.partial--> partial, 1<!--=COUNT:ledger.unit--> unit, 4<!--=COUNT:ledger.parked--> parked, of 24.

| Row | State                                                                         | Status  | Cases                                       | Elsewhere                                                                           | Parked half: probe                                                                 | Owner of the parked half                                                |
| --- | ----------------------------------------------------------------------------- | ------- | ------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 1   | `connecting` before the session's first `auth_ok`                             | covered | Q04-T01, Q04-X01                            |                                                                                     |                                                                                    |                                                                         |
| 2   | `connected`                                                                   | covered | Q04-T02, Q04-N01, Q04-X01                   |                                                                                     |                                                                                    |                                                                         |
| 3   | `reconnecting`                                                                | partial | Q04-T03, Q04-T13, Q04-X01, Q04-X03, Q04-X04 | unit `apps/web/test/lib/ws/connectionRegion.test.ts` "Not connected to the tailnet" | `WatchlistRow` in `apps/web/src`; `OrderTicket` in `apps/web/src`                  | E08-S08 (the watchlist's disconnected cells); E30-S01 (the ticket's T2) |
| 4   | `degraded:lagging`                                                            | covered | Q04-T11                                     |                                                                                     |                                                                                    |                                                                         |
| 5   | `degraded:saturated`                                                          | partial | Q04-F04, Q04-X01                            |                                                                                     | `status: "delayed"` in `apps/web/src/lib/ws/state`                                 | E17-D02 (#325): the shell-level source of Delayed                       |
| 6   | `offline` — retry stopped — in a mounted workspace: `OfflineCause fatal` only | partial | Q04-T07, Q04-F01, Q04-X01, Q04-X02, Q04-X05 |                                                                                     | `controls.includes("details")` in `apps/web/src/features/app-shell`                | E10-S04 (#306): Details and Copy details                                |
| 7   | `offline` — a shell cause on the login screen                                 | unit    |                                             | unit `apps/web/test/features/system-states/OfflineOverlay.test.tsx` "OFFLINE_COPY"  |                                                                                    |                                                                         |
| 8   | `shutdown_pending`                                                            | partial | Q04-N03, Q04-F05, Q04-X01                   |                                                                                     | `Back in ~${` in `apps/web/src`                                                    | E10-S04 (#306): the R1 countdown                                        |
| 9   | `topic_resyncing`                                                             | partial | Q04-T09, Q04-F02, Q04-X01                   |                                                                                     | `Resyncing book…` in `apps/web/src`                                                | E21-S01 (SCR-050)                                                       |
| 10  | `topic_stale`, T1 ≤ age < T2                                                  | parked  |                                             |                                                                                     | `WatchlistRow` in `apps/web/src`; `StaleDataShade` in `apps/web/src`               | E08-S08 (SCR-100); CMP-078: no build ticket found in the backlog        |
| 11  | `topic_stale` ≥ T2                                                            | parked  |                                             |                                                                                     | `WatchlistRow` in `apps/web/src`; `StaleDataShade` in `apps/web/src`               | E08-S08 (SCR-100); CMP-078: no build ticket found in the backlog        |
| 12  | stale (server)                                                                | partial | Q04-F08                                     |                                                                                     | `WatchlistRow` in `apps/web/src`                                                   | E08-S08 (the "Stale (server)" cell)                                     |
| 13  | stale — upstream feed down                                                    | partial | Q04-T14                                     |                                                                                     | `Stale — exchange feed down` in `apps/web/src`                                     | E17-D02 (#325): the chip's stale words                                  |
| 14  | book rebuilt                                                                  | parked  |                                             |                                                                                     | `Book rebuilt` in `apps/web/src`                                                   | E21-S01 (SCR-050)                                                       |
| 15  | `topic_revoked` / permission change                                           | partial | Q04-F07                                     |                                                                                     | `No longer shown — access to` in `apps/web/src`                                    | E29-S01 (the withdrawn-account line)                                    |
| 16  | recovered / reconciling                                                       | partial | Q04-T04, Q04-N04                            |                                                                                     | `Reconciling with the exchange` in `apps/web/src`; `"recovered"` in `apps/web/src` | E29-S07 (reconciling); E10-S04 (#306): the region's `recovered`         |
| 17  | Read-only reason — the region's slot                                          | partial | Q04-T16, Q04-N02, Q04-F03, Q04-F06, Q04-X01 |                                                                                     | `risk lockout until` in `apps/web/src`                                             | E10-S04 (#306): R3, R4 and R7                                           |
| 18  | `system` unknown                                                              | covered | Q04-T10, Q04-F07, Q04-F08                   |                                                                                     |                                                                                    |                                                                         |
| 19  | flapping                                                                      | parked  |                                             |                                                                                     | `Connection unstable` in `apps/web/src`                                            | E10-S04 (#306): the region's `unstable`                                 |
| 20  | long-outage / the T4 steps                                                    | partial | Q04-T05, Q04-T06                            |                                                                                     | `notifyDue` in `apps/web/src/features`                                             | E10-S04 (#306): the 10 s OS notification                                |
| 21  | session ended — no retry                                                      | covered | Q04-T08, Q04-X01                            |                                                                                     |                                                                                    |                                                                         |
| 22  | backend-health conditions                                                     | partial | Q04-T15                                     | e2e `apps/web/e2e/system-states/break-glass-notice.spec.ts` "auth.break_glass_used" | `account_notice` in `apps/web/src`                                                 | E27-S05 (per-account notices)                                           |
| 23  | `err` by `errorMapping` class                                                 | partial | Q04-T12                                     |                                                                                     | `Rebuild budget exhausted` in `apps/web/src`                                       | E21-S01 (the first pane's notice)                                       |
| 24  | upstream private reconnect                                                    | partial | Q04-T16                                     |                                                                                     | `Positions as of` in `apps/web/src`                                                | E29-S07 (SCR-063's banner)                                              |

### B2. Parked halves of the named rows and of the parity claim

| Id    | The parked half                                                                                                                       | Probe                            | Owner                                                 |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | ----------------------------------------------------- |
| C8-a  | C8's throttle half: a `ctl` of 1 000 ms or more while hidden, an `unsub` for a collapsed pane; it needs a mounted consumer of a topic | `WatchlistRow` in `apps/web/src` | E08-S08 (the first topic consumer)                    |
| C12-a | "The order ticket is disabled"; the wire half is Q04-N02                                                                              | `OrderTicket` in `apps/web/src`  | E30-S01                                               |
| E-1   | The Electron pair (BQ-04): N01 to N03 on a hidden `BrowserWindow`, through the dev-server load path                                   | path `packages/fixtures/e2e`     | E10-Q02 (the shared e2e support both apps can import) |

E-1, why parked: `apps/desktop` may not import `apps/web` (`.dependency-cruiser.js`, `desktop-not-to-web`, C-3.5), so
the Electron spec cannot reuse the harness or the session stubs from `apps/web/e2e`. E10-Q02's open PR moves shared e2e
support into `packages/fixtures/e2e`; the pair is written on it once it merges, from `e2e/e17/namedRows.ts`, whose
bodies take the hide and show steps as arguments for that reason.

## C. The six acceptance criteria

| AC                                   | After part 1 | What is covered; what waits                                                                                                                                                                                       |
| ------------------------------------ | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 Named rows on both shells          | partial      | C8's restore half and C12 run on the web shell (Q04-N01 to N04). The Electron pair is E-1; C8's throttle half is C8-a; the ticket half of C12 is C12-a                                                            |
| 2 Never stale as live                | partial      | Disconnected with the last good time (Q04-T03), the read-only reasons, the kill switch never "not killed" (Q04-T10, Q04-F07, Q04-F08). Stale, Resyncing and Delayed panel treatments are parked (rows 5, 9 to 12) |
| 3 Reconnect restores the workspace   | partial      | The 60 s outage on the page's clock (Q04-T05), the switch after a reconnect (Q04-N04), the real-time numbers (Q04-R01). Four panes and private topics are parked (no pane host); section G, G5                    |
| 4 Accessibility is clean             | partial      | axe with zero violations in nine forced states, keyboard, reduced motion, 200% reflow (section D). The screen-reader passes are owner-run rows (section E)                                                        |
| 5 Exploratory findings dispositioned | waits        | Owner-run rows OR-1 to OR-3 (section E)                                                                                                                                                                           |
| 6 Sign-off evidenced                 | waits        | Part 2, after #408 and the owner-run rows (BQ-13, BQ-14)                                                                                                                                                          |

## D. Accessibility split with E17-D04 (#408)

One owner per check (BQ-06). "Six forced states" are E17-D01's six as far as the build forces them: Live,
Disconnected, Resyncing, Delayed and Read-only are forced; Stale cannot be, since no topic consumer is mounted
(rows 10 to 12). Q04-X01 also scans the four variants that draw their own region (first connect, retry stopped,
session ended, the shutdown notice). The scan is `strictAxe` in `e2e/e17/support.ts`: the gate's tagged scan, every
impact, minus the waivers ruled in `qa/plans/_tools/e17_q04_ruled_pins.txt` (none is ruled). `seriousAxe` is unchanged.

| Check                                                                         | Owner         | Where                              |
| ----------------------------------------------------------------------------- | ------------- | ---------------------------------- |
| axe, zero violations of any impact, dark theme, nine forced states            | Q04 automated | Q04-X01                            |
| axe in the light theme and the densities                                      | D04 manual    | not in part 1                      |
| Retry now by Tab, Enter and Space; focus unmoved by a state change; no dialog | Q04 automated | Q04-X02                            |
| Focus order of the whole chrome                                               | D04 manual    | not in part 1                      |
| Reduced motion: the chip's cross-fade, with a full-motion control             | Q04 automated | Q04-X03, Q04-X04                   |
| Reduced motion: the in-app override and the rest of the chrome                | D04 manual    | not in part 1                      |
| 200% reflow at one viewport                                                   | Q04 automated | Q04-X05                            |
| Text spacing and 400%                                                         | D04 manual    | not in part 1                      |
| One announcement per transition, on the page                                  | Q04 automated | Q04-T03, Q04-T10, Q04-N02, Q04-N03 |
| One announcement per transition, as a screen reader says it                   | owner-run     | OR-4, OR-5                         |

## E. Owner-run rows: exploratory charters and screen-reader passes

These are the owner's sessions (BQ-12, BQ-13): the protocol is written here; no session is claimed. Part 2 lists
each row as run or waived by the owner; the ticket stays In Test until then. Format and timebox:
`docs/plan/03-testing-strategy.md` section 11.2 (mission, areas, pass criteria, debrief); severity and the finding
taxonomy: its section 11.3. Any charter 2 finding is at least P1 (ticket, Security notes).

| Row  | Session                                                                  | Run by                             | Status             |
| ---- | ------------------------------------------------------------------------ | ---------------------------------- | ------------------ |
| OR-1 | Charter 1: race pane open and close against reconnects                   | QA engineer, assigned by the owner | owner-run; not run |
| OR-2 | Charter 2: find a state where the UI shows data that is not current      | QA lead, personally                | owner-run; not run |
| OR-3 | Charter 3: throttles and pane visibility that freeze or misdraw a render | QA engineer, assigned by the owner | owner-run; not run |
| OR-4 | NVDA on Windows: every transition the pack forces                        | screen-reader tester               | owner-run; not run |
| OR-5 | VoiceOver on macOS: the same walk                                        | screen-reader tester               | owner-run; not run |

Set-up for every session: the demo stack with a test identity (no live keys), the fixture gateway or the flagged
build's fault channel (Q04-F01 to F08 show it works), and a note of the build and the shell.

- OR-1. Areas: pane open and close, collapsed panes, symbol switch, Retry now, a reconnect in the middle of each. Pass:
  one chrome state after every race; no pane keeps pre-outage data; one `sub` per topic on the wire. Until a pane
  host exists the session covers the chrome only and says so.
- OR-2. Areas: every row of the ledger, every pair of states that can overlap (Disconnected with Read-only, Stale with
  Resyncing, a reconnect during a resync), a hidden window restored, a long outage, clock movement. Pass: no price,
  book, position or age reads as current when it is not; the last good time is shown wherever data is frozen. Start
  with the parked rows.
- OR-3. Areas: Delayed with a hidden window, a collapsed pane restored, off-screen panes, a heatmap resize while
  throttled. Pass: no frozen pane drawn as live; a restored pane is current within one snapshot.
- OR-4 and OR-5. Protocol: `docs/plan/05-accessibility-standard.md` (the manual screen-reader protocol). Walk first
  connect, lost transport, reconnect, fatal close, session ended, kill switch, shutdown notice, the CMP-092 rows. Pass:
  one announcement per transition, E17-D02 section 10's words, nothing per tick, focus unmoved. Transcripts are
  attached to the ticket, not summarised.

## F. Traceability

Generated by the audit tool from the `covers` annotations (BQ-14); never edited by hand. AC 5 and AC 6 have no case:
they are the owner-run rows and part 2 (section C).

<!-- BEGIN GENERATED: q04-matrix -->

| Story scenario or AC        | Cases                                                                                                      |
| --------------------------- | ---------------------------------------------------------------------------------------------------------- |
| US-MKT-003 Feed interrupted | Q04-T03, Q04-T14                                                                                           |
| US-MKT-005 Reconnect        | Q04-T01, Q04-T04, Q04-T05, Q04-T07, Q04-T13                                                                |
| US-MKT-005 Subscribed       | Q04-T02                                                                                                    |
| US-MKT-006 Gap detection    | Q04-F02, Q04-T09                                                                                           |
| US-MKT-007 Sequence break   | Q04-T09                                                                                                    |
| AC 1                        | Q04-F05, Q04-F06, Q04-N01, Q04-N02, Q04-N03                                                                |
| AC 2                        | Q04-F01, Q04-F03, Q04-F04, Q04-R01, Q04-T03, Q04-T06, Q04-T08, Q04-T10, Q04-T11, Q04-T12, Q04-T15, Q04-T16 |
| AC 3                        | Q04-N04, Q04-R01, Q04-T04, Q04-T05                                                                         |
| AC 4                        | Q04-X01, Q04-X02, Q04-X03, Q04-X04, Q04-X05                                                                |
| WS-E06                      | Q04-F07, Q04-F08, Q04-N02, Q04-N04, Q04-T10                                                                |

<!-- END GENERATED: q04-matrix -->

A `test_traceability` block in the ticket JSON is a follow-up, not in this part.

## G. Gaps and carries

Each line is one gap and its owner; none is fixed here.

| Id  | Gap                                                                                                                                                                                                                                                                                    | Owner                                                      |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| G1  | Four ledger rows are parked and fourteen are partial (section B); the parked halves name their probes and owners                                                                                                                                                                       | per row in section B                                       |
| G2  | The flagged lane and the real-time lane have configs but no job step yet, so their nightly greens cannot be counted                                                                                                                                                                    | CI owner                                                   |
| G3  | BQ-10 carry: `docs/plan/03-testing-strategy.md`:373 says no automatic CI retries, while `.github/workflows/_job-e2e.yml`:88 runs the web shards with `--retries=1`; the E17 specs are written for `--retries=0` and no config changes here                                             | CI owner                                                   |
| G4  | E17-D04's "focus trap" wording against E17-D02 section 6's non-modal region; Q04-X02 tests the merged design                                                                                                                                                                           | E17-D04 (#408)                                             |
| G5  | AC 3's "within 10 seconds" against `23` section 9.2's ladder: after a real 60 s outage the next attempt can be up to 40 s away (row 6, 30 s plus or minus 10 s). Q04-T05 runs the outage on the page's clock; Q04-R01 records the real numbers                                         | E17-T04 area: the AC, the ladder or an extra retry trigger |
| G6  | The `err` toasts' words (`WsErrorHost.tsx`) are not E17-D02 section 10 I's PROPOSED strings; Q04-T12 reads the shipped words                                                                                                                                                           | E17-D04 (#408)                                             |
| G7  | A 4429 close shows the Disconnected treatment only: `23` section 8.4 sends `bye` and the close with no `err`, and the client keeps no `bye`, so section 10 E's sentence waits for E17-D02's G12                                                                                        | E17-D02 (#325)                                             |
| G8  | The ticket's Repo paths name `services/api/<module>/`; this ticket writes no `services/api` code                                                                                                                                                                                       | ticket template                                            |
| G9  | The ticket says "the chaos proxy"; E17-Q02 shipped an in-process virtual-clock harness (`docs/qa/perf/e17-ws-chaos-report.md`); the fixture gateway stands in for it here                                                                                                              | this ticket                                                |
| G10 | The harness gained `hold`, `release`, `sendSystem`, `sendErr`, `closeWith` and a second entry point, `startWsHarness`; its `system` resync snapshot now carries the kill switch, as the first one does (`23` section 12.1). `e2e/market-data/ws-harness.spec.ts` checks the new frames | this ticket                                                |

## H. Run record

Where a part ran, and what it gave; "not run" says why (BQ-11). Laptop runs: Playwright 1.64.1 with its pinned
headless Chromium shell, on WSL2, the shipped bundle built from the base, `--retries=0`, each lane's own preview
server, through the heavy-job wrapper, 2026-11-01.

| Run | What                                                                                                                | Where it ran                                       | Result                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------------- |
| H1  | Stub lane, `--grep @e17-regression` (all of A0 and A1 but the F cases)                                              | laptop headless shell                              | 39 passed, 0 failed; four runs, one of them on one worker |
| H2  | The specs that call the changed harness: `ws-harness.spec.ts`, `break-glass-notice.spec.ts`, `auth/session.spec.ts` | laptop headless shell                              | 25 passed, 0 failed                                       |
| H3  | Flagged lane, Q04-F01 to F08                                                                                        | laptop headless shell                              | 8 passed, 0 failed                                        |
| H4  | Real-time lane, Q04-R01                                                                                             | laptop headless shell                              | 1 passed, 0 failed; treatment 40 ms, reconnect 854 ms     |
| H5  | `test/e2e-axe-tags.test.ts`, which pins the new tagged scan's site                                                  | laptop node                                        | 4 passed, 0 failed                                        |
| H6  | The mutation record (section A2)                                                                                    | not run (written in part 1; run with the sign-off) | not run                                                   |
| H7  | The Electron pair                                                                                                   | not run (parked row E-1)                           | not run                                                   |
| H8  | Ten consecutive green nightlies                                                                                     | not run (no nightly has run the E17 specs yet)     | not run                                                   |
