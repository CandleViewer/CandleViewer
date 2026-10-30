// Time and price scale facades. The viewport lives in the render runtime (E11-S03's
// `ChartViewport`): a set range is forwarded, clamped there in bar space, and the derived range
// the worker reports back (the `viewport` message) is what the getters answer from then on.
import type { PriceRange, PriceScale, TimeRange, TimeScale } from "./types.js";

export interface TimeScaleState extends TimeScale {
  /** The range the runtime derived (after clamping), from its `viewport` message. */
  observe(range: TimeRange): void;
}

/** `onChange` forwards an accepted range to the renderer (a `setViewport` command). */
export function createTimeScale(
  onChange: (range: TimeRange) => void = () => undefined,
): TimeScaleState {
  let range: TimeRange | null = null;
  return {
    getVisibleRange: () => range,
    setVisibleRange(next: TimeRange): void {
      if (!Number.isFinite(next.from) || !Number.isFinite(next.to) || next.to <= next.from) {
        throw new RangeError("chart-engine: a time range must be finite with to > from");
      }
      range = { from: next.from, to: next.to };
      onChange(range);
    },
    observe(next: TimeRange): void {
      range = { from: next.from, to: next.to };
    },
  };
}

export interface PriceScaleState extends PriceScale {
  readonly autoScale: boolean;
  /** The pane's window in ticks from `priceOrigin`, as the runtime reports it (null: none). */
  observe(range: PriceRange | null): void;
}

export function createPriceScale(): PriceScaleState {
  let auto = true;
  let range: PriceRange | null = null;
  return {
    get autoScale(): boolean {
      return auto;
    },
    getVisibleRange: () => range,
    setAutoScale(on: boolean): void {
      auto = on;
    },
    observe(next: PriceRange | null): void {
      range = next;
    },
  };
}
