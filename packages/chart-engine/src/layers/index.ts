// Render layers (26 §3): the series host node and the candle instance ring (E12-S06); the
// candle/OHLC programs, footprint, profile, CVD and heatmap layers follow. Internal: the package
// root re-exports none of it (the §8 surface test).
export * from "./candle/ring.js";
export * from "./host.js";
export type * from "./plugin-api.js";
