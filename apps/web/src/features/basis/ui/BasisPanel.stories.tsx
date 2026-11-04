import type { JSX } from "react";
import type { BasisSnapshot } from "../basisFeed";
import type { BasisSource } from "../settings";
import type { BasisTick } from "../ticker";
import { BasisPanel } from "./BasisPanel";

// E24-S08 (#783) slice 2: the basis panel with its state band and table alternative. Values are read off
// the recorded capture (C-13.5): `bybit/2026-10-05/ws/recorded_tickers_BTCUSDT.jsonl`, first (snapshot) line:
// `lastPrice` 82751.20, `markPrice` 82751.20, `indexPrice` 82782.37 (the D03 §3 sample). The failed states are
// the declared client view model (`last_success_at`), not a recorded payload. Plain CSF.
export default { title: "Chart primitives/BasisPanel", component: BasisPanel };

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
  source: { state: "ok" },
  latest: tick,
  stale: { tier: "fresh", ageMs: 0, lastTsMs: T },
};
const noop = (): void => undefined;
const At = ({
  source = "last",
  snapshot,
  defaultTableOpen,
}: {
  source?: BasisSource;
  snapshot?: Partial<BasisSnapshot>;
  defaultTableOpen?: boolean;
}): JSX.Element => (
  <BasisPanel
    symbol="BTCUSDT"
    source={source}
    onSourceChange={noop}
    onRetry={noop}
    snapshot={{ ...base, ...snapshot }}
    {...(defaultTableOpen === undefined ? {} : { defaultTableOpen })}
  />
);

/** Live values, the ratio row saying its source is unavailable (never a series). */
export const Populated = { render: () => <At /> };

/** The source failed: the retry band with the last successful time; the last values stay. */
export const SourceFailed = {
  render: () => (
    <At
      snapshot={{
        feed: "revoked",
        source: { state: "failed", status: "revoked", lastSuccessAtMs: T },
        stale: { tier: "t2", ageMs: 21_000, lastTsMs: T },
      }}
    />
  ),
};

/** The source failed before any item arrived: no timestamp is invented. */
export const FailedNeverLoaded = {
  render: () => (
    <At
      snapshot={{
        feed: "revoked",
        latest: null,
        source: { state: "failed", status: "revoked", lastSuccessAtMs: null },
      }}
    />
  ),
};

/** The table alternative, open: mark, index, basis, basis %, source, and the L/S row. */
export const TableOpen = { render: () => <At defaultTableOpen /> };

/** The table alternative with the mark source. */
export const TableOpenMark = { render: () => <At source="mark" defaultTableOpen /> };

/** Waiting for the first ticker item: the table says so, the ratio row still reads unavailable. */
export const TableEmpty = {
  render: () => <At snapshot={{ feed: "pending", latest: null }} defaultTableOpen />,
};

/** The panel in a 360 px column (the narrow host): the rows and the selector wrap, nothing clips. */
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
      <At defaultTableOpen />
    </div>
  ),
};

// Loading = WaitingForTicker (BasisReadout stories) and TableEmpty; Delayed = StaleT1 / StaleT2 (readout
// stories); Disconnected = SourceFailed. They exist in the model, so no state is deferred.
