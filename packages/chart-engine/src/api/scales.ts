// Time and price scale facades (stubs). The viewport math behind them is E11-S03's.
import type { PriceScale, TimeRange, TimeScale } from "./types.js";

export function createTimeScale(): TimeScale {
  let range: TimeRange | null = null;
  return {
    getVisibleRange: () => range,
    setVisibleRange(next: TimeRange): void {
      if (!Number.isFinite(next.from) || !Number.isFinite(next.to) || next.to <= next.from) {
        throw new RangeError("chart-engine: a time range must be finite with to > from");
      }
      range = { from: next.from, to: next.to };
    },
  };
}

export interface PriceScaleState extends PriceScale {
  readonly autoScale: boolean;
}

/** The stub holds no series data, so its visible price range stays null until E11-S03. */
export function createPriceScale(): PriceScaleState {
  let auto = true;
  return {
    get autoScale(): boolean {
      return auto;
    },
    getVisibleRange: () => null,
    setAutoScale(on: boolean): void {
      auto = on;
    },
  };
}
