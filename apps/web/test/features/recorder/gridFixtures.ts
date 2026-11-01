/**
 * E16-S01, SCR-140's grid fixtures: E16-D02 §1's sample set (board 01 `running`; illustrative values, not a
 * capture) as model rows on one clock, and the cells' context (D02's policy, a 200 GB budget).
 */
import type { RowContext } from "../../../src/features/recorder/grid";
import type { RecorderRow } from "../../../src/features/recorder/model";
import { POLICY } from "./modelFixtures";

/** The examples' second (the step-up fixture's challenge is five minutes on), 2026-09-14 10:31:02 UTC. */
export const NOW = Date.parse("2026-09-14T10:31:02Z");

/** A recording manual row; `patch` sets the rest. */
export const row = (symbol: string, patch: Partial<RecorderRow> = {}): RecorderRow => ({
  symbol,
  id: `id-${symbol.toLowerCase()}`,
  reason: "manual",
  state: "recording",
  refusal: null,
  stopBlockedReason: null,
  recordAgainBlockedReason: null,
  lingerUntilMs: null,
  startedAt: "2026-09-01T09:00:00Z",
  depth: 200,
  retentionDays: 30,
  pinned: false,
  diskBytes: 1e9,
  lastEventAtMs: NOW - 1_000,
  droppedMessages: 0,
  ...patch,
});

/** D02 §1's five rows: BTC pinned, SOL held by its chart, XRP by a position, ADA stopped. */
export const D02_ROWS: readonly RecorderRow[] = [
  row("BTCUSDT", { pinned: true, retentionDays: null, diskBytes: 34.8e9 }),
  row("ETHUSDT", { startedAt: "2026-09-04T08:00:00Z", diskBytes: 15.6e9 }),
  row("SOLUSDT", {
    reason: "chart_open",
    stopBlockedReason: "chart_open",
    startedAt: "2026-09-14T10:14:00Z",
    depth: 50,
    diskBytes: 1.3e6,
  }),
  row("XRPUSDT", {
    reason: "position_open",
    stopBlockedReason: "position_open",
    startedAt: "2026-09-14T09:02:00Z",
    diskBytes: 6.9e6,
  }),
  row("ADAUSDT", { state: "stopped", startedAt: "2026-09-10T07:00:00Z", diskBytes: 11.0e9 }),
];

/** The cells' context at NOW: D02's policy, a 200 GB budget at level 0, D02 §1's rates. */
export const CONTEXT: RowContext = {
  nowMs: NOW,
  stale: false,
  policy: POLICY,
  diskLevel: 0,
  capBytes: 200e9,
  growth: new Map([
    ["BTCUSDT", 0.71e9],
    ["ETHUSDT", 0.52e9],
    ["SOLUSDT", 0.11e9],
    ["XRPUSDT", 0.11e9],
  ]),
  estimated: new Set(["SOLUSDT"]),
  stoppedAtMs: new Map(),
  gaps: new Map(),
};
