import type { JSX } from "react";
import type { BasisSnapshot } from "../basisFeed";
import type { BasisTick } from "../ticker";
import type { BasisSource } from "../settings";
import { BasisReadout } from "./BasisReadout";

// E24-S08 (#783): the basis header readout, slice 1 states. Values are read off the recorded capture
// (C-13.5): `bybit/2026-10-05/ws/recorded_tickers_BTCUSDT.jsonl`, first (snapshot) line: `lastPrice`
// 82751.20, `markPrice` 82751.20, `indexPrice` 82782.37 (the D03 §3 sample). Plain CSF.
export default { title: "Chart primitives/BasisReadout", component: BasisReadout };

const T = Date.parse("2026-10-21T09:14:02Z");
const tick: BasisTick = {
  tsMs: T,
  last: "82751.20",
  mark: "82751.20",
  index: "82782.37",
  stale: false,
};
const base: BasisSnapshot = {
  feed: "live",
  latest: tick,
  stale: { tier: "fresh", ageMs: 0, lastTsMs: T },
};
const noop = (): void => undefined;
const At = ({
  source = "last",
  snapshot,
}: {
  source?: BasisSource;
  snapshot?: Partial<BasisSnapshot>;
}): JSX.Element => (
  <BasisReadout
    symbol="BTCUSDT"
    source={source}
    onSourceChange={noop}
    snapshot={{ ...base, ...snapshot }}
  />
);

/** The contract default: `basis = last − index`. */
export const SourceLast = { render: () => <At /> };

/** `basis = mark − index`: the source line says so. */
export const SourceMark = { render: () => <At source="mark" /> };

/** A positive basis: the sign is text. */
export const PositiveBasis = {
  render: () => <At snapshot={{ latest: { ...tick, last: "82790.00" } }} />,
};

/** No ticker item yet: every figure reads "no value yet", never 0. */
export const WaitingForTicker = {
  render: () => <At snapshot={{ feed: "pending", latest: null }} />,
};

/** The ticker carries no mark: `mark` has no basis, `last` still does. */
export const NoMark = {
  render: () => <At source="mark" snapshot={{ latest: { ...tick, mark: null } }} />,
};

/** Stale from 5 s: the CMP-239 chip and the last-good time. */
export const StaleT1 = {
  render: () => <At snapshot={{ stale: { tier: "t1", ageMs: 7_000, lastTsMs: T } }} />,
};

/** Stale from 15 s, or a served `stale: true`: escalated. */
export const StaleT2 = {
  render: () => <At snapshot={{ stale: { tier: "t2", ageMs: 21_000, lastTsMs: T } }} />,
};

/** The readout in a 360 px column (the narrow host): the rows and the selector wrap, nothing clips. */
export const Narrow360 = {
  render: () => (
    <div style={{ inlineSize: "360px" }}>
      <At />
    </div>
  ),
};

/** The compact density the derivatives header row uses. */
export const Dense = {
  render: () => (
    <div data-density="compact">
      <At />
    </div>
  ),
};

// States: Loading = WaitingForTicker; Delayed = StaleT1 / StaleT2. Disconnected (a failed source) is slice 2's
// SourceFailed on the panel.
