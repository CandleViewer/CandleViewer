// SDF text (E11-S11, 26 §3.7): the glyph atlas — configuration, generation, the packed-rows
// cache with F-03 verification and the DOM-free platform seam. The draw path (glyph runs, the
// batcher and the shaders) follows in PR B. Internal: nothing here is on `src/index.ts`.
export * from "./atlas.js";
export * from "./atlas-build.js";
export * from "./atlas-cache.js";
export * from "./config.js";
export * from "./glyph-set.js";
export type * from "./platform.js";
