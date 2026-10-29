// The pre-§8 engine handle (E02-T03 scaffold, E47-S07 render flags, US-SET-005 palette seam),
// served at `@candleviewer/chart-engine/compat` so its apps/web callers keep working while the
// package root carries exactly the §8 surface (README "Design deltas" BQ-2). E11-T09 (#1404, the
// public-API freeze) removes it: before the freeze the appearance and a11y-preference hosts drive a
// `Chart` through `setTheme`, and this entry is deleted.

export const CHART_ENGINE_VERSION = "0.1.0";

export type { EngineHandle, EngineOptions, EngineStats, EngineTheme } from "./core/handle.js";
export { createEngine } from "./core/handle.js";
export type { RenderFlags, FrameState } from "./core/flags.js";
export { DEFAULT_RENDER_FLAGS, animationWorkUnits, stepFrame } from "./core/flags.js";
