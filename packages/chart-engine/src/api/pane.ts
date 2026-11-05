// Pane facade (stub). Series, overlay and indicator handles record their lifecycle only; the
// stores, batches and plugin hosting behind them are E11-T03 / E11-S01 / E12+.
import { encodeCandles, type BufferLayout, type DataOp, type StoreId } from "../worker/protocol.js";
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
  /** E11-S09 (BQ-1): the wire key the facade minted (-1 when absent). */
  readonly key?: number;
  /** Called once when the pane is removed (by `Pane.remove` or `Chart.removePane`). */
  onRemoved(id: PaneId): void;
  /** Throws once the owning chart is disposed. */
  assertLive(): void;
  /** Hands a batch to the render runtime (buffer transferred). */
  data(store: StoreId, op: DataOp, layout: BufferLayout, buffer: ArrayBuffer): void;
  /** Forwards this pane's price-scale fields (E11-S05, a `setPriceScale` command). */
  scale?(id: PaneId, fields: ScaleFields): void;
  /** E11-S09 (BQ-3): forwards `setHeightRatio`; the worker rescales the others and normalises. */
  ratio?(id: PaneId, r: number): void;
}

/** A series handle plus the state the stub records (read by tests; no renderer yet). */
export interface SeriesInternal<T extends SeriesType> extends SeriesHandle<T> {
  readonly type: T;
  readonly options: SeriesOptionsMap[T];
  readonly visible: boolean;
}

export interface PaneInternal extends Pane {
  readonly priceScale: PriceScaleState;
  readonly heightRatio: number;
  readonly seriesCount: number;
  readonly removed: boolean;
  /** E11-S09 (BQ-4): true while the worker shows this pane as a collapsed stub. */
  readonly collapsed: boolean;
  /**
   * E11-S09 (BQ-4): the worker's `layout` row. `heightRatio` mirrors an open pane's normalised
   * share and keeps the last open share while collapsed, so it stays in (0, 1].
   */
  observeShare(share: number, collapsed: boolean): void;
  /** E11-S09 (BQ-1): the wire key the facade minted for this pane (never reused). */
  readonly key: number;
  /**
   * E11-S09 (BQ-11a rider, R58): this pane's slot in the last `layout`, or -1 when that layout
   * does not list its key (not laid out yet, or removed). Re-mapped from every `layout`.
   */
  readonly slot: number;
  observeSlot(slot: number): void;
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
  let slot = -1;
  let collapsed = false;
  const series = new Set<object>();
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
    get collapsed(): boolean {
      return collapsed;
    },
    observeShare(share: number, folded: boolean): void {
      collapsed = folded;
      if (!folded && share > 0) heightRatio = share;
    },
    key: host.key ?? -1,
    get slot(): number {
      return removed ? -1 : slot;
    },
    observeSlot(s: number): void {
      slot = s;
    },
    addSeries<T extends SeriesType>(type: T, opts: SeriesOptionsMap[T]): SeriesInternal<T> {
      live();
      let options: SeriesOptionsMap[T] = { ...opts };
      let visible = true;
      // Candle, hollow (E12-S07) and OHLC bars feed the `bars` store; the other stores' encoders
      // arrive with them (E11-T03 / E12, README BQ-13). The batch's buffer is transferred: after
      // `setData`, `append` or `prependHistory` the caller's arrays are detached (length 0), so
      // the same object cannot be sent twice.
      const send =
        type === "candles" || type === "hollow" || type === "bars"
          ? (op: DataOp, d: unknown): void => {
              live();
              const { layout, buffer } = encodeCandles(d as CandleData);
              host.data("bars", op, layout, buffer);
            }
          : (): void => undefined;
      const handle: SeriesInternal<T> = {
        type,
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
      host.ratio?.(id, r);
    },
    remove(): void {
      if (removed) return;
      removed = true;
      series.clear();
      host.onRemoved(id);
    },
  };
}
