import type { JSX } from "react";
import type { OiSnapshot } from "../oiFeed";
import { buildOiBars } from "../quadrant/bars";
import {
  DELTA_SERIES,
  FIXTURE_BAR_MS,
  FIXTURE_ROWS,
  FIXTURE_T0,
  QUADRANT_SERIES,
} from "../quadrant/fixture";
import { OiPane, type OiPaneProps } from "./OiPane";

// E24-S02 (#777): the OI pane's delta mode and quadrant classification (D03 S54-10..16), on the typed #5341
// fixture (`quadrant/fixture.ts`). The plot itself waits for the engine's styled histogram (#534).
export default { title: "Chart primitives/OiFundingLiqPane/OiQuadrant", component: OiPane };

const last = FIXTURE_ROWS[FIXTURE_ROWS.length - 1] ?? null;
const snapshot: OiSnapshot = {
  feed: "pending",
  history: { phase: "ready", empty: false, truncated: null },
  latest: last,
  stale: { tier: "fresh", ageMs: 0, lastTsMs: FIXTURE_T0 },
  note: "Native granularity 5 min",
  coverageFromMs: FIXTURE_T0,
  rows: FIXTURE_ROWS,
  gaps: [],
};
const bars = buildOiBars(DELTA_SERIES, QUADRANT_SERIES, FIXTURE_ROWS, FIXTURE_BAR_MS, "BTCUSDT");
const noop = (): void => undefined;
const At = (props: Partial<OiPaneProps>): JSX.Element => (
  <OiPane
    symbol="BTCUSDT"
    snapshot={snapshot}
    onRetry={noop}
    bars={bars}
    {...(props.mode === undefined ? {} : { onModeChange: noop })}
    {...props}
  />
);

/** S54-13: quadrants on, the key row counts each in words; the crosshair reads the quadrant. */
export const QuadrantsOn = {
  render: () => (
    <At
      mode="delta"
      delta={{ value: "20", unit: "qty", quadrant: "long_buildup" }}
      defaultTableOpen
    />
  ),
};

/** S54-14: no lane, no width step; the key row says so and the table keeps its Quadrant column. */
export const QuadrantsOff = {
  render: () => <At mode="delta" quadrantColouring={false} defaultTableOpen />,
};

/** S54-10: the absolute level mode. */
export const Absolute = { render: () => <At mode="absolute" /> };

/** S54-16 / BQ-3: a bar with no OI sample and a flat bar, worded apart. */
export const Unclassified = {
  render: () => (
    <At mode="delta" delta={{ value: null, unit: "qty", quadrant: null }} defaultTableOpen />
  ),
};

/** Every bar classified: the key row has no unclassified tail. */
export const AllClassified = {
  render: () => (
    <At
      bars={buildOiBars(
        { unit: "qty", points: DELTA_SERIES.points.slice(0, 3) },
        { unit: "enum", points: QUADRANT_SERIES.points.slice(0, 3) },
        FIXTURE_ROWS,
        FIXTURE_BAR_MS,
        "BTCUSDT",
      )}
    />
  ),
};

/** D02 §12 narrow variant: the key row wraps at 360 px. */
export const Narrow360 = {
  render: () => (
    // the story's frame width, not a design value: D02 §12's docked minimum
    <div style={{ inlineSize: "360px" }}>
      <At mode="delta" instrumentBaseCoin="BTC" defaultTableOpen />
    </div>
  ),
};

/** A long unit word and symbol wrap, nothing truncated. */
export const LongText = {
  render: () => (
    <At
      symbol="1000000BABYDOGEUSDT"
      mode="delta"
      delta={{ value: "-1234567.123456", unit: "1000000BABYDOGE", quadrant: "long_unwind" }}
      bars={buildOiBars(
        { ...DELTA_SERIES, unit: "1000000BABYDOGE" },
        QUADRANT_SERIES,
        FIXTURE_ROWS,
        FIXTURE_BAR_MS,
        "BTCUSDT",
      )}
    />
  ),
};

/** Narrow with colouring off: "Quadrants off", the mode switch still in row 0. */
export const Narrow360QuadrantsOff = {
  render: () => (
    <div style={{ inlineSize: "360px" }}>
      <At mode="delta" quadrantColouring={false} defaultTableOpen />
    </div>
  ),
};

/** One unclassified bar: the singular forms. */
export const SingleUnclassified = {
  render: () => (
    <At
      bars={buildOiBars(
        { unit: "qty", points: DELTA_SERIES.points.slice(2, 4) },
        { unit: "enum", points: QUADRANT_SERIES.points.slice(2, 4) },
        FIXTURE_ROWS,
        FIXTURE_BAR_MS,
        "BTCUSDT",
      )}
    />
  ),
};

/** Every bar unclassified: no quadrant counts, the key row's tail says how many and why. */
export const AllUnclassified = {
  render: () => (
    <At
      mode="delta"
      defaultTableOpen
      bars={buildOiBars(
        { unit: "qty", points: DELTA_SERIES.points.map((p) => ({ ...p, v: null })) },
        { unit: "enum", points: [] },
        [],
        FIXTURE_BAR_MS,
        "BTCUSDT",
      )}
    />
  ),
};
