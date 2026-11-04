// E24-S01 (#776) slice 2: the OI pane wired to its feed. The host (SCR-054, slice 3) passes the chart's
// bar and a stable window; the plot slot stays empty until the engine's line series exists (#5593).
import type { JSX, ReactNode } from "react";
import { useOiFeed, type OiFeedHookOptions } from "../useOiFeed";
import { INITIAL_OI_SNAPSHOT, useOiSnapshot } from "../oiFeed";
import { OiPane, type OiPaneProps } from "./OiPane";
import type { OiDelta } from "./OiReadout";

export interface ConnectedOiPaneProps extends OiFeedHookOptions {
  readonly symbol: string;
  readonly delta?: OiDelta | undefined;
  readonly bars?: OiPaneProps["bars"];
  readonly instrumentBaseCoin?: OiPaneProps["instrumentBaseCoin"];
  readonly plot?: ReactNode;
  readonly visible?: { readonly fromMs: number; readonly toMs: number } | undefined;
}

export function ConnectedOiPane({
  symbol,
  delta,
  bars,
  instrumentBaseCoin,
  plot,
  visible,
  ...feedOptions
}: ConnectedOiPaneProps): JSX.Element {
  const feed = useOiFeed(symbol, feedOptions);
  const snapshot = useOiSnapshot(feed);
  return (
    <OiPane
      symbol={symbol}
      snapshot={feed === null ? INITIAL_OI_SNAPSHOT : snapshot}
      onRetry={() => feed?.retry()}
      delta={delta}
      bars={bars}
      instrumentBaseCoin={instrumentBaseCoin}
      plot={plot}
      visible={visible}
    />
  );
}
