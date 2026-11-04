# Workspace SyncBus (E15-T03, slices 1 and 2 of 3)

The app-layer sync coordinator for docked panes (`14` SCR-023, `15` CMP-196). One bus per workspace
lets the panes of a group (A, B or C) follow each other's symbol, interval, crosshair, time range and
price levels (the drawings axis), once per frame and with no loops.

**Status: no caller until E15-S03/S04, old path unchanged (C-4.13).** Nothing mounts a
`SyncBusProvider` or calls `useMultiChartLinker` yet, so this code is dormant and needs no flag.

Slice map:

- **Slice 1 (#5695):** the bus, the CMP-196 hook and provider, the announcement, the D-7 notice.
- **Slice 2 (this one):** `layoutSync.ts` (below), `sync.perf.test.ts`, and three bus minors
  (pruned empty memory maps, rotation before a throwing listener or announcer, and
  `createSyncAnnouncer()` for a per-instance queue and timer).
- **Slice 3 (after #446's `Chart.setSyncGroup`):** `engineMember.ts`, the `Chart.tsx` rider, the
  4-pane integration test with real charts, the six-pane end-to-end sweep and the e2e. Still carried:
  no engine crosshair event for a remote crosshair (#446).

## Layout mapping (BQ-07, slice 2)

`layoutSync.ts` maps only fields already in `22`: `symbol_sync` is the symbol axis, `crosshair_sync`
the crosshair, `level_sync` the drawings axis. `axesToLayout` is a pure single-set mapping, and
`applyLayoutAxes` gives that one set to all three groups. How per-group axes (A, B, C) collapse to
the one stored set is G-1's open question for E15-S04's contract PR, not a default chosen here.
Interval and time range have no stored field (G-2): they are off unless the caller holds them on.
Grid cells stay out (D11 G-1); presets are plain input to `groupsFromPanes`.

Stored values are untrusted: a flag reads as on only when it is the boolean `true`, and a
`pane_config.sync_group` reads as a group only by membership of `SYNC_GROUPS` (A, B, C). The dock's
`fromLayout` never reads `pane_config` (it passes it through as opaque pane fields), so this file is
the client boundary for the sync fields. `withGroup` keeps every other `pane_config` key
(`settings`) and the difference between `sync_group: null` and no `sync_group` key (`22`: both
mean "not synced"); a round-trip test holds both. E15-S03 (save and restore) and E15-S04 (the
SCR-023 switches) import it.

## Perf

`test/features/workspace/sync/sync.perf.test.ts` runs in the vitest `perf` project
(`pnpm --filter @candleviewer/web test:perf`): six fake members, every axis on, 300 simulated frames
(the "5 s sweep" is frame count, never a wait) with 4 pointer moves each. It asserts
`expect(t, why(t, 4)).toBeLessThanOrEqual(budget(4))` on the worst frame; `test/perf-budget-guard.test.ts`
(unit project) checks every bound in the package goes through `budget(<spec>)` (`06`, wall-clock unit budgets).
It measures the bus share only. **No CI job runs `sync.perf.test.ts` until the web `test:perf` step
lands** (a pending item on #435); the end-to-end figure with real engines is slice 3's.

Measured on the dev host, **not the reference machine (OL-1)**; 6 runs of `test:perf`, calibration
cpu 14.8 to 15.4 ms against reference 17.984 ms (scale 1.000, so `budget(4)` = 4 ms). Per run, per
frame cost over 300 frames; the middle row is the median across runs:

| Statistic (ms)   | median of 6 runs | range over runs  |
| ---------------- | ---------------- | ---------------- |
| p50              | 0.0052           | 0.0050 to 0.0085 |
| p95              | 0.0075           | 0.0072 to 0.0131 |
| p99              | 0.0645           | 0.0549 to 0.1128 |
| worst (asserted) | 0.340            | 0.303 to 0.458   |

All are far under the 4 ms AC and, including the worst frame, under E15-K01's 0.5 ms main-thread
rule (one further run measured a worst frame of 0.437). The 0.65 ms quoted in #5695's body was
not labelled there; it was measured by the slice-1 form of this test, which asserted the worst
frame, so it is a worst-frame figure on a different run, not a p95. The six-pane AC and the DoD
box stay open for slice 3's real-engine sweep.

## How a value moves

1. A pane's handler calls `bus.publish(paneId, payload)`. The payload is written to the group's slot
   for that axis (the last write in a frame wins), and the bus asks for one animation frame.
2. The frame's flush gives each slot to every other member of the group whose kind receives that
   axis. In this slice that is `chart` members only (BQ-05). A drawings level goes only to members on
   the origin's symbol (D-8).
3. **Origin token.** The bus remembers the value it gave each member on each axis until the end of
   the next flush (the engine's one-frame echo, no longer). If that member publishes the same value
   back by then, it is an echo and is dropped once (`suppressedEchoes`); after that, or with a
   different value, the publish is a real update and propagates.

The bus holds no axis defaults (BQ-04). A group propagates nothing until `setAxes` gives it the stored
flags. E15-S04 writes AD-4's defaults when it creates a group. The mapping from the stored layout
(`symbol_sync`, `crosshair_sync`, `level_sync`, `sync_group`; BQ-07) is `layoutSync.ts`.

**Armed charts (BQ-05).** An armed order-capable chart (CMP-221) returns `held` for a symbol; the bus
drops it, never replays it, and has no arm call, so no sync write re-arms a pane (OQ-1 stays open).

**Time alignment (BQ-06).** The bus carries the crosshair's bar time, never a price, and only
derives the D-7 notice. The containing-bar AC (the bar that opens at or before t) is resolved by
the engine in #388 / #446, so this slice has no test for it.

## Dev re-entrancy assertion and counters

- **Re-entrancy.** A publish during a flush that is not an echo is refused and counted as
  `reentrancyHits`. In dev builds (`import.meta.env.DEV`) the bus throws `SyncBusAssertionError` after
  the flush ends, so every member still gets that frame's values. Production counts the hit and does
  not throw.
- **Allow-list.** A payload outside the allow-list is refused and counted as `rejectedPayloads`. In
  dev it throws at once. The payload is `axis` plus exactly one of `symbol`, `interval` (`22`
  `PaneIntervalCode`'s pattern), `crosshair`, `timeRange` or `priceLevel`; never an account or an
  environment.
- **A throwing `apply`** is counted as `applyErrors`; the frame still reaches every other member and
  group, then the first error is rethrown (in production too).
- **Counters.** `bus.devCounters()` adds `flushes`, `dispatches`, `lastFrameDispatches`, `coalesced`
  and `held` (A-7). Collected members are pruned, never counted as linked.

## Announcement (CMP-196 A11y and Tests): met in this slice

`createSyncBus({ announce: announceSyncState })` says, through the shell's one polite region, when a
group becomes linked (two or more members, an axis on), changes its axes, or stops being linked;
never on a crosshair, time-range or level update. Every group that changed in a frame is joined into
one message. The writer keeps the region's budget (`REGION_BUDGET_MS` from `lastWrittenAt`): a
change inside it waits, and later text joins the queued message. `linker.test.tsx` runs axe after a
later change and after unlink then relink.

Copy deviations (PROPOSED, for E15-D15 / E15-S04):

- CMP-196's "Panes linked: crosshair, levels" gains the group as D-12 names it: "Panes linked in
  sync group A: crosshair, levels." The words symbol, interval and time range are SCR-023's
  switches; the drawings axis is said "levels".
- "Panes in sync group A are no longer linked." has no signed-off copy.
- D-12's join and leave strings (SR-30 / SR-31) name a panel, which the bus does not know: E15-S04
  says them, and decides whether to pass `announceSyncState` too, so one change is said once.
  #446 BQ-21's engine announcement must be off for docked charts (A-10).

## Scope notes

- **Departure from E15-K01 §8 (BQ-01):** the app coordinates the axes and, in slice 2, the engine
  fans crosshair and time range out, because `15` CMP-196 and E15-D06 §15 are the signed-off contract.
- **Out of scope:** a floated Electron window (A-3), the `scale` axis (E15-S05) and an account axis.
  No new dependency (A-1).
