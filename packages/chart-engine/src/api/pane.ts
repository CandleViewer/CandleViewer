// Pane facade. A bar series (candles, hollow, OHLC bars) is runtime-backed (E12-S11 PR A1): it
// is registered under a chart-unique id and its batches are tagged with it (26 §6 `addSeries`,
// `data.series`, `removeSeries`). Other series, overlay and indicator handles still record their
// lifecycle only; their stores and plugin hosting are E11-S01 / E12+.
import {
  encodeCandles,
  type BarSeriesKind,
  type BufferLayout,
  type DataOp,
  type StoreId,
} from "../worker/protocol.js";
import { createPriceScale, type PriceScaleState, type ScaleFields } from "./scales.js";
import type {
  CandleData,
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
  /** Hands a batch to the render runtime (buffer transferred), for runtime series `series`. */
  data(
    store: StoreId,
    op: DataOp,
    layout: BufferLayout,
    buffer: ArrayBuffer,
    series?: number,
  ): void;
  /** E12-S11: registers a runtime-backed series on this pane; returns its chart-unique id. */
  addSeries(id: PaneId, kind: BarSeriesKind): number;
  /** E12-S11: the runtime series `series` is gone (its store and lane are released). */
  removeSeries(series: number): void;
  /** Forwards this pane's price-scale fields (E11-S05, a `setPriceScale` command). */
  scale?(id: PaneId, fields: ScaleFields): void;
}

/** A series handle plus the state the facade records (read by tests). */
export interface SeriesInternal<T extends SeriesType> extends SeriesHandle<T> {
  readonly type: T;
  /** E12-S11: the runtime series id its batches carry; null for a kind with no runtime store. */
  readonly seriesId: number | null;
  readonly options: SeriesOptionsMap[T];
  readonly visible: boolean;
}

export interface PaneInternal extends Pane {
  readonly priceScale: PriceScaleState;
  readonly heightRatio: number;
  readonly seriesCount: number;
  readonly removed: boolean;
}

/** The §8 series types a runtime `BarStore` backs (26 §6 `addSeries` kinds). */
const BAR_KINDS: ReadonlySet<SeriesType> = new Set<SeriesType>(["candles", "hollow", "bars"]);

function checkRatio(r: number): number {
  if (!Number.isFinite(r) || r <= 0 || r > 1) {
    throw new RangeError("chart-engine: a pane height ratio must be in (0, 1]");
  }
  return r;
}

export function createPane(id: PaneId, opts: PaneOptions, host: PaneHost): PaneInternal {
  let heightRatio = checkRatio(opts.heightRatio ?? 1);
  let removed = false;
  const series = new Set<{ drop(): void }>();
  const priceScale = createPriceScale((fields) => {
    live();
    host.scale?.(id, fields);
  });

  function live(): void {
    host.assertLive();
    if (removed) throw new Error(`chart-engine: pane ${id} was removed`);
  }

  return {
    id,
    priceScale,
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
      let gone = false;
      // Candle, hollow (E12-S07) and OHLC bars feed their own runtime `bars` store (E12-S11);
      // the other stores' encoders arrive with them (E11-T03 / E12, README BQ-13). The batch's
      // buffer is transferred: after `setData`, `append` or `prependHistory` the caller's arrays
      // are detached (length 0), so the same object cannot be sent twice.
      const sid = BAR_KINDS.has(type) ? host.addSeries(id, type as BarSeriesKind) : null;
      const send =
        sid !== null
          ? (op: DataOp, d: unknown): void => {
              live();
              if (gone) throw new Error("chart-engine: the series was removed");
              const { layout, buffer } = encodeCandles(d as CandleData);
              host.data("bars", op, layout, buffer, sid);
            }
          : (): void => undefined;
      /** Releases the runtime series once (by `remove`, or by the pane's removal). */
      const drop = (): void => {
        if (gone) return;
        gone = true;
        if (sid !== null) host.removeSeries(sid);
      };
      const handle: SeriesInternal<T> & { drop(): void } = {
        type,
        seriesId: sid,
        drop,
        get options(): SeriesOptionsMap[T] {
          return options;
        },
        get visible(): boolean {
          return visible;
        },
        setData: (d) => send("replace", d),
        append: (d) => send("append", d),
        prependHistory: (d) => send("prepend", d),
        setOptions(next: Partial<SeriesOptionsMap[T]>): void {
          options = { ...options, ...next };
        },
        setVisible(v: boolean): void {
          visible = v;
        },
        remove(): void {
          series.delete(handle);
          drop();
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
      for (const s of series) s.drop();
      series.clear();
      host.onRemoved(id);
    },
  };
}
