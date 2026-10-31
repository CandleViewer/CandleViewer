// Time and price scale facades. The viewport lives in the render runtime (E11-S03's
// `ChartViewport`): a set range is forwarded, clamped there in bar space, and the derived range
// the worker reports back (the `viewport` message) is what the getters answer from then on.
// E11-S05 (README BQ-121): the price scale forwards mode, invert, lock and options as one
// `setPriceScale` command and answers `getState` from the reported state.
import type { Command } from "../worker/protocol.js";
import type { PriceRange, PriceScale, TimeRange, TimeScale } from "./types.js";

type ScaleState = ReturnType<PriceScale["getState"]>;
/** A `setPriceScale` command's scale fields (the pane is the facade's). */
export type ScaleFields = Omit<Extract<Command, { k: "setPriceScale" }>, "k" | "pane">;
const MODES: readonly ScaleState["mode"][] = ["linear", "log", "percent", "indexed"];

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
  /** The `viewport` message's scale fields (BQ-124). */
  observeState(
    next: Omit<ScaleState, "includeDrawings" | "priceOnly" | "marginTop" | "marginBottom">,
  ): void;
}

const margin = (v: number | undefined, name: string): void => {
  if (v !== undefined && !(v >= 0 && v <= 0.45)) {
    throw new RangeError(`chart-engine: ${name} must be in [0, 0.45]`);
  }
};

/** `PaneOptions.priceScale`'s check, before the pane exists (a RangeError, as `setOptions`). */
export function checkScaleOptions(o: { mode?: string; marginTop?: number; marginBottom?: number }) {
  if (o.mode !== undefined && !MODES.includes(o.mode as ScaleState["mode"])) {
    throw new RangeError(`chart-engine: unknown scale mode ${o.mode}`);
  }
  margin(o.marginTop, "marginTop");
  margin(o.marginBottom, "marginBottom");
}

/** `send` forwards one pane's scale command to the renderer. */
export function createPriceScale(
  send: (cmd: ScaleFields) => void = () => undefined,
): PriceScaleState {
  let range: PriceRange | null = null;
  let state: ScaleState = {
    mode: "linear",
    requestedMode: "linear",
    inverted: false,
    autoScale: true,
    includeDrawings: false,
    priceOnly: false,
    marginTop: 0.05,
    marginBottom: 0.05,
    logAvailable: false,
    logReason: "no-price-origin",
    anchorTick: null,
  };
  return {
    get autoScale(): boolean {
      return state.autoScale;
    },
    getVisibleRange: () => range,
    setAutoScale(on: boolean): void {
      state = { ...state, autoScale: on };
      send({ auto: on });
    },
    setMode(mode): void {
      if (!MODES.includes(mode)) throw new RangeError(`chart-engine: unknown scale mode ${mode}`);
      state = { ...state, requestedMode: mode }; // the drawn `mode` answers from the report:
      send({ mode }); // log may wait for, or be refused on, the data (BQ-120)
    },
    setInverted(on: boolean): void {
      state = { ...state, inverted: on };
      send({ inverted: on });
    },
    setOptions(opts): void {
      margin(opts.marginTop, "marginTop");
      margin(opts.marginBottom, "marginBottom");
      const fields: { -readonly [K in keyof ScaleFields]: ScaleFields[K] } = {};
      if (opts.includeDrawings !== undefined) fields.includeDrawings = opts.includeDrawings;
      if (opts.priceOnly !== undefined) fields.priceOnly = opts.priceOnly;
      if (opts.marginTop !== undefined) fields.marginTop = opts.marginTop;
      if (opts.marginBottom !== undefined) fields.marginBottom = opts.marginBottom;
      state = { ...state, ...fields };
      send(fields);
    },
    getState: () => ({ ...state }),
    observe(next: PriceRange | null): void {
      range = next;
    },
    observeState(next): void {
      state = { ...state, ...next };
    },
  };
}
