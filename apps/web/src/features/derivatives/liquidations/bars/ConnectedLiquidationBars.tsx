// E24-S06 (#781): the bars pane wired to its read, its settings and #780's coverage. The host (SCR-054) owns the one
// liquidation feed and passes its snapshot: this component opens no subscription and makes no coverage read (BQ-2).
// The settings are the HOST's (`useLiqBarSettings`, component state until #5699): the host gives the same value to
// the feed (`feedMinNotional(settings)` as its `minNotionalUsd` option) and to this pane, so they share one source (BQ-1).
import type { JSX } from "react";
import type { LiqSnapshot } from "../liquidationFeed";
import { LiquidationBarsPane, type BarsCoverage } from "./LiquidationBarsPane";
import { BARS_FILTER_SERVER_SIDE, type BarsRead, type BarsRequest } from "./barsRead";
import type { LiqBarSettings } from "./settings";
import { useLiquidationBars } from "./useLiquidationBars";

export interface ConnectedLiquidationBarsProps {
  readonly symbol: string;
  /** `22`'s `bar_type=time` `param` of the price chart: the bar grid the bars share. */
  readonly param: string;
  readonly snapshot: Pick<LiqSnapshot, "coverage" | "history" | "minNotionalUsd">;
  readonly settings: LiqBarSettings;
  readonly onSettingsChange: (patch: Partial<LiqBarSettings>) => void;
  /** Reads the feed's window again (the coverage comes with it). */
  readonly onRetryCoverage: () => void;
  readonly crosshairMs?: number | null | undefined;
  readonly now?: (() => number) | undefined;
  readonly read?: ((req: BarsRequest) => Promise<BarsRead>) | undefined;
}

export function ConnectedLiquidationBars({
  symbol,
  param,
  snapshot,
  settings,
  onSettingsChange,
  onRetryCoverage,
  crosshairMs,
  now = Date.now,
  read,
}: ConnectedLiquidationBarsProps): JSX.Element {
  const { coverage, history } = snapshot;
  const view = useLiquidationBars({
    symbol,
    param,
    coverage,
    minNotionalUsd: settings.minNotionalUsd,
    serverThreshold: BARS_FILTER_SERVER_SIDE,
    enabled: settings.mode === "bars",
    now,
    read,
  });
  const known: BarsCoverage =
    coverage !== null
      ? { kind: "ok", coverage }
      : history.phase === "failed"
        ? { kind: "failed", onRetry: onRetryCoverage }
        : { kind: "loading" };
  return (
    <LiquidationBarsPane
      symbol={symbol}
      view={view}
      coverage={known}
      settings={settings}
      feedMinNotionalUsd={snapshot.minNotionalUsd}
      onSettingsChange={onSettingsChange}
      crosshairMs={crosshairMs}
      nowMs={now()}
    />
  );
}
