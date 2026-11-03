import type { JSX } from "react";
import type { LiqCoverage } from "../history";
import type { LiqSnapshot } from "../liquidationFeed";
import type { HeldPrint } from "../ring";
import { LiquidationPane, type LiquidationPaneProps } from "./LiquidationPane";

// CMP-186's liquidations sub-pane, the feed (E24-S05 #780), every state of slice 1. No recorded liquidation
// capture is on `main` yet (#5273 adds `bybit/2026-10-05/ws/allLiquidation_BTCUSDT_burst.jsonl`), so every value
// is a declared contract or design sample, never invented:
// - `22` `getLiquidations` example `liqs`: 2026-09-14T10:12:44.120Z, BTCUSDT, sell, 62880.00, 3.220, 202473.60, ×1;
// - D02 §6 / D03 S54-41's row: 09:14:02, Long liquidated, 0.498 BTC, 82,751.20, 41,210.10 USDT, ×8;
// - D02 §6's cascade, one 500 ms push of 620 prints (600 long at avg 82,500.00 over 48.00 BTC, 20 short at avg
//   82,600.00 over 1.20 BTC), so 1,240 prints/s; each print here is that bucket's average print;
// - coverage: `22` example `liqs` `meta.coverage` (first 2026-09-01T00:00:00.250Z, covered 10:00–11:00Z), and D02 §6
//   / D03 S54-44's partial sample (recorded from 09:14 UTC, 34 min, in a 24 h window); SOLUSDT never recorded (S54-46).
// Plain CSF.
export default {
  title: "Chart primitives/OiFundingLiqPane/LiquidationFeed",
  component: LiquidationPane,
  // the samples the RTL test reuses are data, not stories
  excludeStories: ["EXAMPLE_PRINT", "DESIGN_ROW", "CASCADE_ROWS", "base", "EXAMPLE_COVERAGE"],
};

const T_EXAMPLE = Date.parse("2026-09-14T10:12:44.120Z");
const T_ROW = Date.parse("2026-10-21T09:14:02Z");
const T_CASCADE = Date.parse("2026-10-21T09:31:10Z");

export const EXAMPLE_PRINT: HeldPrint = {
  seq: 0,
  tsMs: T_EXAMPLE,
  side: "long", // `sell` (BQ 1)
  price: "62880.00",
  size: "3.220",
  notionalUsd: "202473.60",
  clusterSize: 1,
};
export const DESIGN_ROW: HeldPrint = {
  seq: 1,
  tsMs: T_ROW,
  side: "long",
  price: "82751.20",
  size: "0.498",
  notionalUsd: "41210.10",
  clusterSize: 8,
};

/** The cascade push, newest first and bounded to the 40 rows in view (D02 §6). */
export const CASCADE_ROWS: HeldPrint[] = Array.from({ length: 40 }, (_, k) => {
  const short = k % 31 === 0; // 20 of 620 are shorts: roughly one in 31
  return {
    seq: 659 - k,
    tsMs: T_CASCADE,
    side: short ? "short" : "long",
    price: short ? "82600.00" : "82500.00",
    size: short ? "0.060" : "0.080",
    notionalUsd: short ? "4956.00" : "6600.00",
    clusterSize: 1,
  };
});

/** `22` example `liqs`, `meta.coverage`. */
export const EXAMPLE_COVERAGE: LiqCoverage = {
  firstAvailableMs: Date.parse("2026-09-01T00:00:00.250Z"),
  coveredFromMs: Date.parse("2026-09-14T10:00:00Z"),
  coveredToMs: Date.parse("2026-09-14T11:00:00Z"),
  noCoverage: false,
};
const EXAMPLE_WINDOW = {
  fromMs: Date.parse("2026-09-14T10:00:00Z"),
  toMs: Date.parse("2026-09-14T11:00:00Z"),
};

export const base: LiqSnapshot = {
  feed: "live",
  rows: [DESIGN_ROW, EXAMPLE_PRINT],
  newestSeq: 1,
  ratePerSec: 0,
  minNotionalUsd: null,
  window: EXAMPLE_WINDOW,
  history: { phase: "ready", coverage: EXAMPLE_COVERAGE, truncated: false },
};

/** D02 §6 / D03 S54-44: recorded from 09:14 UTC, a 24 h window ending 34 min later. */
const T_FIRST = Date.parse("2026-10-21T09:14:00Z");
const PARTIAL_WINDOW = { fromMs: T_FIRST + 34 * 60_000 - 86_400_000, toMs: T_FIRST + 34 * 60_000 };
const LAST_LOADED = Date.parse("2026-10-21T09:14:02Z");

const noop = (): void => undefined;
const At = (
  props: Omit<Partial<LiquidationPaneProps>, "snapshot"> & { snapshot?: Partial<LiqSnapshot> },
): JSX.Element => (
  <LiquidationPane
    symbol="BTCUSDT"
    onRetry={noop}
    {...props}
    snapshot={{ ...base, ...props.snapshot }}
  />
);

/** S54-41: prints with the side word and glyph, size, `p`, notional and cluster. */
export const Populated = { render: () => <At /> };

/** S54-43: a cascade, the counter "1,240 prints/s" and at most 40 rows in view. */
export const Cascade = {
  render: () => <At snapshot={{ rows: CASCADE_ROWS, newestSeq: 659, ratePerSec: 1_240 }} />,
};

/** US-DERIV-006 sc. 2: the server-side filter stated in the pane. */
export const Filtered = { render: () => <At snapshot={{ minNotionalUsd: "50000" }} /> };

/** Paused: `Pause` pressed, the view held. */
export const Paused = { render: () => <At defaultPaused /> };

/** Nothing received and coverage not yet known: never worded as "no liquidations". */
export const Waiting = {
  render: () => <At snapshot={{ rows: [], newestSeq: -1, history: { phase: "loading" } }} />,
};

/** 360 px: the row's words and units kept (D03 S54-63). */
export const Narrow = {
  render: () => (
    <div style={{ inlineSize: 360 }}>
      <At />
    </div>
  ),
};

// slice 2: the read, the coverage and the topic's states

/** S54-70: a fresh pane, the skeleton (no lock, no chip). */
export const Loading = {
  render: () => (
    <At snapshot={{ feed: "pending", rows: [], newestSeq: -1, history: { phase: "loading" } }} />
  ),
};

/** S54-71: live prints drawn while the read runs. */
export const Backfilling = { render: () => <At snapshot={{ history: { phase: "loading" } }} /> };

/** S54-45 / the ticket's sc. 3: the chip names the first available time; the sentence says why. */
export const Partial = {
  render: () => (
    <At
      snapshot={{
        rows: [DESIGN_ROW],
        newestSeq: 1,
        window: PARTIAL_WINDOW,
        history: {
          phase: "ready",
          truncated: false,
          coverage: {
            firstAvailableMs: T_FIRST,
            coveredFromMs: T_FIRST,
            coveredToMs: PARTIAL_WINDOW.toMs,
            noCoverage: false,
          },
        },
      }}
    />
  ),
};

/** S54-44: a cascade inside a partial window keeps the chip and the counter. */
export const CascadePartial = {
  render: () => (
    <At
      snapshot={{
        rows: CASCADE_ROWS,
        newestSeq: 659,
        ratePerSec: 1_240,
        window: PARTIAL_WINDOW,
        history: {
          phase: "ready",
          truncated: false,
          coverage: {
            firstAvailableMs: T_FIRST,
            coveredFromMs: T_FIRST,
            coveredToMs: PARTIAL_WINDOW.toMs,
            noCoverage: false,
          },
        },
      }}
    />
  ),
};

/** S54-46: the symbol was never recorded; live prints stream. */
export const NeverRecorded = {
  render: () => (
    <At
      symbol="SOLUSDT"
      snapshot={{
        rows: [],
        newestSeq: -1,
        window: PARTIAL_WINDOW,
        history: {
          phase: "ready",
          truncated: false,
          coverage: {
            firstAvailableMs: null,
            coveredFromMs: null,
            coveredToMs: null,
            noCoverage: true,
          },
        },
      }}
    />
  ),
};

/** S54-47 / the ticket's sc. 4: the window ends before coverage — never an empty list. */
export const BeforeCoverage = {
  render: () => (
    <At
      snapshot={{
        rows: [],
        newestSeq: -1,
        window: { fromMs: T_FIRST - 3 * 3_600_000, toMs: T_FIRST - 3_600_000 },
        history: {
          phase: "ready",
          truncated: false,
          coverage: {
            firstAvailableMs: T_FIRST,
            coveredFromMs: null,
            coveredToMs: null,
            noCoverage: true,
          },
        },
      }}
    />
  ),
};

/** Inside coverage with no print: what was recorded, never "no liquidations". */
export const EmptyRecorded = { render: () => <At snapshot={{ rows: [], newestSeq: -1 }} /> };

/** S54-49: the read failed; live prints continue; Retry with the last loaded time. */
export const HistoryFailed = {
  render: () => (
    <At snapshot={{ history: { phase: "failed", status: 500, lastSuccessAtMs: LAST_LOADED } }} />
  ),
};

/** S54-50: the server's 503, the coverage sentence verbatim. */
export const CoverageRetry = {
  render: () => (
    <At
      snapshot={{
        rows: [],
        newestSeq: -1,
        history: { phase: "failed", status: 503, lastSuccessAtMs: null },
      }}
    />
  ),
};

/** The read stopped at its page bound. */
export const Truncated = {
  render: () => (
    <At snapshot={{ history: { phase: "ready", coverage: EXAMPLE_COVERAGE, truncated: true } }} />
  ),
};

/** S54-72: the topic is stale (CMP-239), last print time named. */
export const Stale = { render: () => <At snapshot={{ feed: "stale" }} /> };

/** S54-75: disconnected, the pane frozen with its last-good time. */
export const Disconnected = { render: () => <At snapshot={{ feed: "resyncing" }} /> };
