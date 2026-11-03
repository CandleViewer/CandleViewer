import type { JSX } from "react";
import type { OiSnapshot } from "../oiFeed";
import type { OiGap, OiRow } from "../series";
import { OiPane, type OiPaneProps } from "./OiPane";

// CMP-186 OiFundingLiqPane, the `OiOnly` sub-pane (E24-S01 #776), every state of D02 §9 the OI pane has. Values are
// read off the recorded fixtures (C-13.5): REST `openInterest` from `bybit/2026-10-05/rest/open_interest_BTCUSDT_5min_
// page0.json`, live `openInterest` / `openInterestValue` from `ws/recorded_tickers_BTCUSDT.jsonl`. Plain CSF.
export default { title: "Chart primitives/OiFundingLiqPane/OiOnly", component: OiPane };

const MIN = 60_000;
const T0 = Date.parse("2023-11-15T19:25:00Z");
const LIVE_T = Date.parse("2026-10-21T09:14:02Z");
const REST_OI = [
  "51283.25000000",
  "51286.00000000",
  "51378.75000000",
  "51373.50000000",
  "51347.25000000",
];

const rest: OiRow[] = REST_OI.map((base, i) => ({
  tMs: T0 + i * 5 * MIN,
  spanMs: 5 * MIN,
  base,
  valueUsdt: null,
  source: "rest",
  forming: false,
  asOfMs: T0 + i * 5 * MIN,
}));
const live: OiRow = {
  tMs: LIVE_T - (LIVE_T % (5 * MIN)),
  spanMs: 5 * MIN,
  base: "57911.602",
  valueUsdt: "4792254559.42",
  source: "ws_ticker",
  forming: true,
  asOfMs: LIVE_T,
};
const gap: OiGap = { fromMs: T0 + 25 * MIN, toMs: live.tMs, kind: "recorded" };

const base: OiSnapshot = {
  feed: "live",
  history: { phase: "ready", empty: false, truncated: null },
  latest: live,
  stale: { tier: "fresh", ageMs: 0, lastTsMs: LIVE_T },
  note: null,
  coverageFromMs: T0,
  rows: [...rest, live],
  gaps: [gap],
};

const noop = (): void => undefined;
const At = (
  props: Omit<Partial<OiPaneProps>, "snapshot"> & { snapshot?: Partial<OiSnapshot> },
): JSX.Element => (
  <OiPane symbol="BTCUSDT" onRetry={noop} {...props} snapshot={{ ...base, ...props.snapshot }} />
);

/** History then live: the readout in USDT from the ticker, both sides. */
export const Populated = { render: () => <At /> };

/** The served per-bar delta, labelled "Δ per bar" (BQ 2). */
export const WithDeltaPerBar = { render: () => <At delta={{ value: "4.354", unit: "BTC" }} /> };

/** Only REST history so far: the readout falls back to base coin. */
export const RestOnly = {
  render: () => (
    <At snapshot={{ latest: rest[4] ?? null, rows: rest, gaps: [], feed: "pending" }} />
  ),
};

/** A fresh pane: the skeleton, nothing drawn. */
export const Loading = {
  render: () => (
    <At
      snapshot={{
        history: { phase: "loading" },
        latest: null,
        rows: [],
        gaps: [],
        feed: "pending",
      }}
    />
  ),
};

/** Live values while the history loads. */
export const Backfilling = {
  render: () => <At snapshot={{ history: { phase: "loading" }, rows: [live], gaps: [] }} />,
};

/** The backfill failed after an earlier success: the gap, Retry and the last-loaded time. */
export const BackfillFailed = {
  render: () => (
    <At
      snapshot={{
        history: { phase: "failed", status: 503, lastSuccessAtMs: LIVE_T - 6 * MIN },
        rows: [live],
        gaps: [{ fromMs: T0, toMs: live.tMs, kind: "failed" }],
      }}
      defaultTableOpen
    />
  ),
};

/** The first load failed: no last-loaded line. */
export const BackfillFailedNeverLoaded = {
  render: () => (
    <At
      snapshot={{ history: { phase: "failed", status: null, lastSuccessAtMs: null }, rows: [live] }}
    />
  ),
};

/** Never recorded and the exchange gave nothing: the designed empty state, live streaming. */
export const EmptyNeverRecorded = {
  render: () => (
    <At
      symbol="SOLUSDT"
      snapshot={{
        history: { phase: "ready", empty: true, truncated: null },
        coverageFromMs: null,
        rows: [live],
        gaps: [],
      }}
    />
  ),
};

/** Nothing in this window, but the store starts later: `coverage.from` names it (BQ 7). */
export const EmptyWithCoverageFrom = {
  render: () => (
    <At
      snapshot={{
        history: { phase: "ready", empty: true, truncated: null },
        coverageFromMs: LIVE_T - 60 * MIN,
        latest: null,
        rows: [],
        gaps: [],
      }}
    />
  ),
};

/** 5 s without an update: the CMP-239 chip and the last-good time (T1). */
export const StaleT1 = {
  render: () => <At snapshot={{ stale: { tier: "t1", ageMs: 7_000, lastTsMs: LIVE_T } }} />,
};

/** 15 s or a served stale flag: the strong chip (T2). */
export const StaleT2 = {
  render: () => <At snapshot={{ stale: { tier: "t2", ageMs: 15_000, lastTsMs: LIVE_T } }} />,
};

/** A 1 m chart on 5 min history: the note from `coverage.native_interval`. */
export const NativeGranularity = {
  render: () => <At snapshot={{ note: "Native granularity 5 min" }} />,
};

/** The read stopped at its page bound. */
export const Truncated = {
  render: () => <At snapshot={{ history: { phase: "ready", empty: false, truncated: "older" } }} />,
};

/** The table alternative open: points, the gap as a row, the source in words. */
export const TableOpen = { render: () => <At defaultTableOpen /> };

/** A long symbol and every qualifier together, wrapping. */
export const LongText = {
  render: () => (
    <At
      symbol="1000000BABYDOGEUSDT"
      delta={{ value: "-1234567.123456", unit: "1000000BABYDOGE" }}
      snapshot={{
        note: "Native granularity 15 min",
        history: { phase: "ready", empty: false, truncated: "older" },
        stale: { tier: "t2", ageMs: 125_000, lastTsMs: LIVE_T },
      }}
    />
  ),
};

/** D02 §12 narrow variant: 360 px, everything wraps, nothing truncated, every unit kept. */
export const Narrow360 = {
  render: () => (
    // the story's frame width, not a design value: D02 §12's docked minimum (rec. 7)
    <div style={{ inlineSize: "360px" }}>
      <At
        symbol="1000PEPEUSDT"
        delta={{ value: "4.354", unit: "1000PEPE" }}
        defaultTableOpen
        snapshot={{
          note: "Native granularity 5 min",
          stale: { tier: "t1", ageMs: 7_000, lastTsMs: LIVE_T },
        }}
      />
    </div>
  ),
};

/** D03 §9 `dense`: chart-only, so the chrome keeps compact rows and 24 px targets. */
export const Dense = { render: () => <At density="dense" defaultTableOpen /> };
