import type { JSX } from "react";
import { LiquidationBarsPane, type LiquidationBarsPaneProps } from "./LiquidationBarsPane";
import { buildBars, type LiqBar } from "./model";
import {
  COVERAGE,
  DAY_COVERAGE,
  DAY_LONG,
  DAY_SHORT,
  H,
  HOUR,
  NOW,
  SERVED_LONG,
  SERVED_SHORT,
} from "./samples";
import { DEFAULT_LIQ_BAR_SETTINGS } from "./settings";
import type { LiqBarsView } from "./useLiquidationBars";

// E24-S06 (#781) slice 2: CMP-186's liquidation bars, every state, on the declared samples of `samples.ts`. The plot
// (#534) is not drawn: the pane has the legend, the states and the table. Plain CSF.
export default {
  title: "Chart primitives/OiFundingLiqPane/LiquidationBars",
  component: LiquidationBarsPane,
  excludeStories: ["viewOf"],
};

export const viewOf = (bars: readonly LiqBar[], over: Partial<LiqBarsView> = {}): LiqBarsView => ({
  phase: "ready",
  bars,
  window: { fromMs: H(7), toMs: NOW, bars: 500 },
  intervalMs: HOUR,
  malformed: 0,
  loadedAtMs: NOW,
  stale: false,
  error: null,
  retry: (): void => undefined,
  ...over,
});

const partial = buildBars(SERVED_LONG, SERVED_SHORT, COVERAGE, HOUR);
const noop = (): void => undefined;
const At = (props: Partial<LiquidationBarsPaneProps>): JSX.Element => (
  <LiquidationBarsPane
    symbol="BTCUSDT"
    view={viewOf(partial)}
    coverage={{ kind: "ok", coverage: COVERAGE }}
    settings={DEFAULT_LIQ_BAR_SETTINGS}
    feedMinNotionalUsd={null}
    onSettingsChange={noop}
    nowMs={NOW}
    {...props}
  />
);

/** S54-45 / the ticket's sc. 4 and 5: the boundary label, unknown before it, a genuine zero after it. */
export const PartialBoundary = { render: () => <At /> };

/** Sc. 1, 2: both sides in text, the UTC day boundary inside the window, no filter. */
export const DayBoundary = {
  render: () => (
    <At
      view={viewOf(buildBars(DAY_LONG, DAY_SHORT, DAY_COVERAGE, HOUR), {
        window: { fromMs: H(22, "2026-10-20"), toMs: NOW, bars: 500 },
      })}
      coverage={{ kind: "ok", coverage: DAY_COVERAGE }}
    />
  ),
};

/** Sc. 3: the minimum notional, stated; the bars read unfiltered until #723, and the legend says so. */
export const Filtered = {
  render: () => (
    <At
      settings={{ ...DEFAULT_LIQ_BAR_SETTINGS, minNotionalUsd: "50000" }}
      feedMinNotionalUsd="50000"
    />
  ),
};

/** The crosshair on the 11:00 bar: both figures with units; on an unknown bar the words, never a zero. */
export const CrosshairRecorded = { render: () => <At crosshairMs={H(11) + 60_000} /> };
export const CrosshairUnknown = { render: () => <At crosshairMs={H(7) + 60_000} /> };

/** S54-47: the whole window precedes the recorder; no mark, no zero, no table. */
export const BeforeCoverage = {
  render: () => (
    <At
      view={viewOf(
        buildBars(
          SERVED_LONG,
          SERVED_SHORT,
          { ...COVERAGE, firstAvailableMs: NOW + HOUR, noCoverage: true },
          HOUR,
        ),
      )}
      coverage={{
        kind: "ok",
        coverage: { ...COVERAGE, firstAvailableMs: NOW + HOUR, noCoverage: true },
      }}
    />
  ),
};

/** S54-46: nothing stored for the symbol. */
export const NeverRecorded = {
  render: () => (
    <At
      symbol="SOLUSDT"
      view={viewOf([])}
      coverage={{
        kind: "ok",
        coverage: {
          firstAvailableMs: null,
          coveredFromMs: null,
          coveredToMs: null,
          noCoverage: true,
        },
      }}
    />
  ),
};

export const Loading = {
  render: () => <At view={viewOf([], { phase: "loading", window: null })} />,
};
export const CoveragePending = {
  render: () => <At view={viewOf([])} coverage={{ kind: "loading" }} />,
};
/** S54-50: no coverage, no zero. */
export const CoverageFailed = {
  render: () => <At view={viewOf([])} coverage={{ kind: "failed", onRetry: noop }} />,
};
export const Failed = {
  render: () => (
    <At view={viewOf([], { phase: "failed", error: { status: 503, code: null }, window: null })} />
  ),
};
/** `22` 422: the code is registered but the server does not compute it. */
export const NotComputed = {
  render: () => (
    <At
      view={viewOf([], {
        phase: "failed",
        error: {
          status: 422,
          code: "validation_failed",
          detail: "not computed by this server yet: liquidation_notional",
        },
        window: null,
      })}
    />
  ),
};
/** #5341's router also 422s an unlisted symbol: that is the generic retry, not "not available yet". */
export const UnlistedSymbol = {
  render: () => (
    <At
      view={viewOf([], {
        phase: "failed",
        error: { status: 422, code: "validation_failed", detail: "BTCUSDT is not listed" },
        window: null,
      })}
    />
  ),
};
/** A refresh failed: the last good bars, marked stale with their time. */
export const Stale = {
  render: () => (
    <At
      view={viewOf(partial, {
        stale: true,
        error: { status: null, code: null },
        loadedAtMs: NOW - 5 * 60_000,
      })}
    />
  ),
};
export const Empty = { render: () => <At view={viewOf([])} /> };
/** BQ-6: the heatmap waits for a recorded-density surface (NG-15); never bucketed on the client. */
export const HeatmapPending = {
  render: () => <At settings={{ ...DEFAULT_LIQ_BAR_SETTINGS, mode: "heatmap" }} />,
};
/** Values the server sent that were not numbers read "not recorded", with the count. */
export const Malformed = { render: () => <At view={viewOf(partial, { malformed: 2 })} /> };
/** The history bound (`22`: 400 days): a weekly chart holds 57 bars. */
export const HistoryBound = {
  render: () => <At view={viewOf(partial, { window: { fromMs: H(7), toMs: NOW, bars: 57 } })} />,
};
export const Narrow = {
  render: () => (
    <div style={{ inlineSize: 360 }}>
      <At />
    </div>
  ),
};

/** A bar that opens before the recorder began but holds recorded prints: its state says from when. */
export const StraddlingBar = {
  render: () => (
    <At
      view={viewOf(
        buildBars(new Map([...SERVED_LONG, [H(9), "1500.25"]]), SERVED_SHORT, COVERAGE, HOUR),
      )}
    />
  ),
};

const MANY = 250;
const manyBars = (value: string) => {
  const side = new Map(
    Array.from({ length: MANY }, (_, i) => [H(0, "2026-10-01") + i * HOUR, value] as const),
  );
  return buildBars(side, side, DAY_COVERAGE, HOUR);
};
/** 250 bars: the table shows the newest 200 and says so. */
export const TableCut = {
  render: () => (
    <At
      view={viewOf(manyBars("1250.5"), {
        window: { fromMs: H(0, "2026-10-01"), toMs: NOW, bars: 250 },
      })}
      coverage={{ kind: "ok", coverage: DAY_COVERAGE }}
    />
  ),
};
/** The longest figures and symbol at 360 px: nothing is cut, the units stay in the headers. */
export const LongText = {
  render: () => (
    <div style={{ inlineSize: 360 }}>
      <At
        symbol="1000000MOGUSDT"
        view={viewOf(manyBars("123456789012345.12345678").slice(-6))}
        coverage={{ kind: "ok", coverage: DAY_COVERAGE }}
        settings={{ ...DEFAULT_LIQ_BAR_SETTINGS, minNotionalUsd: "123456789012345.12345678" }}
        feedMinNotionalUsd="123456789012345.12345678"
      />
    </div>
  ),
};
