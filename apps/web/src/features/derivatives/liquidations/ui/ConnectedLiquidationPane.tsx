// E24-S05 (#780): the liquidation feed wired to its subscription and its read. The host (SCR-054) passes the pane
// id, a stable window and the optional `min_notional_usd` filter; mounting it on SCR-054 is slice 3's.
import type { JSX } from "react";
import { INITIAL_LIQ_SNAPSHOT, useLiqSnapshot } from "../liquidationFeed";
import { useLiquidationFeed, type LiqFeedHookOptions } from "../useLiquidationFeed";
import { LiquidationPane } from "./LiquidationPane";

export interface ConnectedLiquidationPaneProps extends LiqFeedHookOptions {
  readonly symbol: string;
}

export function ConnectedLiquidationPane({
  symbol,
  ...feedOptions
}: ConnectedLiquidationPaneProps): JSX.Element {
  const feed = useLiquidationFeed(symbol, feedOptions);
  const snapshot = useLiqSnapshot(feed);
  return (
    <LiquidationPane
      symbol={symbol}
      snapshot={feed === null ? INITIAL_LIQ_SNAPSHOT : snapshot}
      onRetry={() => feed?.retry()}
    />
  );
}
