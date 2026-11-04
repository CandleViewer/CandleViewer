# Workspace SyncBus (E15-T03, slice 1)

The app-layer sync coordinator for docked panes (`14` SCR-023, `15` CMP-196). One bus per workspace
lets the panes of a group (A, B or C) follow each other's symbol, interval, crosshair, time range and
price levels (the drawings axis), once per frame and with no loops.

**Status: no caller until slice 2, old path unchanged (C-4.13).** Nothing mounts a
`SyncBusProvider` or calls `useMultiChartLinker` yet, so this code is dormant and needs no flag.
Slice 2 adds `engineMember.ts` (a chart bound through #446's `Chart.setSyncGroup`), the
`Chart.tsx` rider, `layoutSync`, the perf test (A-6), the integration test and the e2e. All wait for #446 to merge
(ruling BQ-03), with four carried minors: an empty memory map's extra frame, a throwing `subscribe` /
announce skipping its rotation, the announcer timer's test reset, and no engine echo of a remote crosshair.

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
(`symbol_sync`, `crosshair_sync`, `level_sync`, `sync_group`; BQ-07) moves to slice 2 with its caller;
interval and time range have no stored field (G-2) and stay off there unless the caller holds them on.

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
