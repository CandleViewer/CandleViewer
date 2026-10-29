// Pane facade (stub). Series, overlay and indicator handles record their lifecycle only; the
// stores, batches and plugin hosting behind them are E11-T03 / E11-S01 / E12+.
import { createPriceScale } from "./scales.js";
import type {
  IndicatorHandle,
  OverlayHandle,
  Pane,
  PaneId,
  PaneOptions,
  SeriesHandle,
  SeriesOptionsMap,
  SeriesType,
} from "./types.js";

export interface PaneHost {
  /** Called once when the pane is removed (by `Pane.remove` or `Chart.removePane`). */
  onRemoved(id: PaneId): void;
  /** Throws once the owning chart is disposed. */
  assertLive(): void;
}

/** A series handle plus the state the stub records (read by tests; no renderer yet). */
export interface SeriesInternal<T extends SeriesType> extends SeriesHandle<T> {
  readonly type: T;
  readonly options: SeriesOptionsMap[T];
  readonly visible: boolean;
}

export interface PaneInternal extends Pane {
  readonly heightRatio: number;
  readonly seriesCount: number;
  readonly removed: boolean;
}

function checkRatio(r: number): number {
  if (!Number.isFinite(r) || r <= 0 || r > 1) {
    throw new RangeError("chart-engine: a pane height ratio must be in (0, 1]");
  }
  return r;
}

export function createPane(id: PaneId, opts: PaneOptions, host: PaneHost): PaneInternal {
  let heightRatio = checkRatio(opts.heightRatio ?? 1);
  let removed = false;
  const series = new Set<object>();

  function live(): void {
    host.assertLive();
    if (removed) throw new Error(`chart-engine: pane ${id} was removed`);
  }

  return {
    id,
    priceScale: createPriceScale(),
    get heightRatio(): number {
      return heightRatio;
    },
    get seriesCount(): number {
      return series.size;
    },
    get removed(): boolean {
      return removed;
    },
    addSeries<T extends SeriesType>(type: T, opts: SeriesOptionsMap[T]): SeriesInternal<T> {
      live();
      let options: SeriesOptionsMap[T] = { ...opts };
      let visible = true;
      const handle: SeriesInternal<T> = {
        type,
        get options(): SeriesOptionsMap[T] {
          return options;
        },
        get visible(): boolean {
          return visible;
        },
        setData: () => undefined,
        append: () => undefined,
        prependHistory: () => undefined,
        setOptions(next: Partial<SeriesOptionsMap[T]>): void {
          options = { ...options, ...next };
        },
        setVisible(v: boolean): void {
          visible = v;
        },
        remove(): void {
          series.delete(handle);
        },
      };
      series.add(handle);
      return handle;
    },
    // Plugin hosting is E11-S01 / E12+: the stub takes no argument it would only discard.
    addOverlay(): OverlayHandle {
      live();
      return { setOptions: () => undefined, remove: () => undefined };
    },
    addIndicator(): IndicatorHandle {
      live();
      return { setParams: () => undefined, remove: () => undefined };
    },
    setHeightRatio(r: number): void {
      live();
      heightRatio = checkRatio(r);
    },
    remove(): void {
      if (removed) return;
      removed = true;
      series.clear();
      host.onRemoved(id);
    },
  };
}
