// E13-S01 (#423) S1: catalogue descriptors as `listIndicators` serves them, transcribed from the
// server's definitions (`services/api/candleviewer/orderflow/indicators/catalogue.py`: `ParamSpec
// .schema()`, `params_schema()`, `limits.py`) and typed against the generated contract, so the
// shape is the server's, never invented (C-13.5 spirit; no network).
import type { IndicatorDescriptor } from "../../../src/features/indicators/model/types";

const period = (dflt: number, title = "Period") => ({
  type: "integer",
  title,
  minimum: 1,
  maximum: 5000,
  default: dflt,
});
const schema = (properties: Record<string, unknown>) => ({
  type: "object",
  additionalProperties: false,
  properties,
});

export const EMA = {
  id: "ema",
  name: "Exponential moving average",
  category: "trend",
  pane: "price",
  compute: "server",
  estimated: false,
  params_schema: schema({ n: period(21) }),
  defaults: { n: 21 },
  outputs: [{ id: "ema", name: "EMA" }],
  unit: "price",
  nullable_when: "None until n bars exist.",
  warmup_bars: 21,
} satisfies IndicatorDescriptor;

export const BOLLINGER = {
  id: "bollinger",
  name: "Bollinger Bands",
  category: "volatility",
  pane: "price",
  compute: "client_worker",
  estimated: false,
  params_schema: schema({
    n: period(20),
    mult: {
      type: "number",
      title: "Standard deviations",
      minimum: 0.1,
      maximum: 10,
      multipleOf: 0.1,
      default: 2,
    },
  }),
  defaults: { n: 20, mult: 2 },
  outputs: [
    { id: "upper", name: "Upper band" },
    { id: "middle", name: "Middle line" },
    { id: "lower", name: "Lower band" },
  ],
  unit: "price",
  warmup_bars: 20,
} satisfies IndicatorDescriptor;

export const CVD = {
  id: "cvd",
  name: "Cumulative volume delta",
  category: "orderflow",
  pane: "sub",
  compute: "server",
  estimated: false,
  params_schema: schema({
    anchor: {
      type: "string",
      title: "Reset anchor",
      enum: ["session", "utc_day"],
      default: "session",
    },
  }),
  defaults: { anchor: "session" },
  outputs: [{ id: "cvd", name: "CVD" }],
  unit: "qty",
  warmup_bars: 1,
} satisfies IndicatorDescriptor;

export const RSI = {
  id: "rsi",
  name: "Relative strength index",
  category: "momentum",
  pane: "sub",
  compute: "server",
  estimated: false,
  params_schema: schema({ n: period(14) }),
  defaults: { n: 14 },
  outputs: [{ id: "rsi", name: "RSI" }],
  unit: "pct",
  warmup_bars: 15,
} satisfies IndicatorDescriptor;

export const VOLUME = {
  id: "volume",
  name: "Volume",
  category: "volume",
  pane: "both",
  compute: "server",
  estimated: false,
  params_schema: schema({}),
  defaults: {},
  outputs: [{ id: "volume", name: "Volume" }],
  unit: "qty",
  warmup_bars: 1,
} satisfies IndicatorDescriptor;

export const ZIGZAG = {
  id: "zigzag",
  name: "Zig Zag",
  category: "trend",
  pane: "price",
  compute: "server",
  estimated: false,
  params_schema: schema({
    depth: period(5, "Depth"),
    deviation_pct: {
      type: "number",
      title: "Deviation (%)",
      minimum: 0,
      maximum: 50,
      multipleOf: 0.1,
      default: 0,
    },
  }),
  outputs: [
    { id: "swing_high", name: "Swing high" },
    { id: "swing_low", name: "Swing low" },
  ],
  unit: "price",
} satisfies IndicatorDescriptor;

export const CATALOGUE: readonly IndicatorDescriptor[] = [EMA, ZIGZAG, BOLLINGER, RSI, VOLUME, CVD];
