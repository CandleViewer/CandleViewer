// Pane facade (stub). Series, overlay and indicator handles record their lifecycle only; the
// stores, batches and plugin hosting behind them are E11-T03 / E11-S01 / E12+.
import {
  encodeCandles,
  LastPaneError,
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
  /** Hands a batch to the render runtime (buffer transferred). */
  data(store: StoreId, op: DataOp, layout: BufferLayout, buffer: ArrayBuffer): void;
  /** Forwards this pane's price-scale fields (E11-S05, a `setPriceScale` command). */
  scale?(id: PaneId, fields: ScaleFields): void;
  /** E11-S09 (BQ-3): this pane's weight changed; the host sends the whole vector. */
  resized?(id: PaneId): void;
  /** E11-S09 (lens M1): false for the last pane of a live chart: `remove` throws instead. */
  canRemove?(id: PaneId): boolean;
  /** E11-S09 (BQ-16): a `setCollapsed` the host sends (the worker refuses the last plot). */
  collapse?(id: PaneId, collapsed: boolean): void;
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
  /** E11-S09: the stable key on the wire (BQ-1) and the accessible name (BQ-15). */
  readonly key: number;
  readonly label: string;
  /** E11-S09 (BQ-4): the normalised share the worker last laid out; NaN before its first. */
  share: number;
  /** E11-S09 (BQ-11, BQ-16): mirrored from each `layout` message (the worker's truth). */
  collapsed: boolean;
}

function checkRatio(r: number): number {
  if (!Number.isFinite(r) || r <= 0 || r > 1) {
    throw new RangeError("chart-engine: a pane height ratio must be in (0, 1]");
  }
  return r;
}

export function createPane(
  id: PaneId,
  opts: PaneOptions,
  host: PaneHost,
  key = 0,
  label = opts.label ?? "",
): PaneInternal {
  let heightRatio = checkRatio(opts.heightRatio ?? 1);
  let removed = false;
  const series = new Set<object>();
  const priceScale = createPriceScale((fields) => {
    live();
    host.scale?.(id, fields);
  });

  function live(): void {
    host.assertLive();
    if (removed) throw new Error(`chart-engine: pane ${id} was removed`);
  }

  const pane: PaneInternal = {
    id,
    key,
    label,
    share: Number.NaN,
    collapsed: false,
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
      // Candle and OHLC bars feed the `bars` store; the other stores' encoders arrive with them
      // (E11-T03 / E12, README BQ-13). The batch's buffer is transferred: after `setData`,
      // `append` or `prependHistory` the caller's arrays are detached (length 0), so the same
      // object cannot be sent twice.
      const send =
        type === "candles" || type === "bars"
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
      host.resized?.(id);
    },
    setCollapsed(c: boolean): void {
      live();
      if (typeof c !== "boolean") throw new TypeError("chart-engine: collapsed must be a boolean");
      // Always sent (the mirror may lag a call made this tick); `collapsed` follows the next
      // `layout`, so a refusal in the worker never leaves it wrong.
      host.collapse?.(id, c);
    },
    remove(): void {
      if (removed) return;
      if (host.canRemove?.(id) === false) throw new LastPaneError();
      removed = true;
      series.clear();
      host.onRemoved(id);
    },
  };
  return pane;
}
