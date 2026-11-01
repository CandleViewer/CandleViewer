// Render layers (26 §3): the series host node, the candle instance ring, the candle and OHLC
// series and their gap seams (E12-S06); footprint, profile, CVD and heatmap layers follow.
// Internal: the package root re-exports none of it (the §8 surface test).
export * from "./candle/ring.js";
export * from "./host.js";
export type * from "./plugin-api.js";
export * from "./candle/geometry.js";
export * from "./candle/palette.js";
export * from "./candle/series.js";
export * from "./candle/bars.js";
export * from "./candle/seams.js";
