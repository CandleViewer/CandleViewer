// E11-S11's error codes (BQ-272), in a leaf module so the main-thread protocol re-exports them
// without pulling the atlas graph into the host bundle. The cache one is informational (a bad
// record is regenerated); the generation one is not (no atlas, chart text is not drawn).
export const ENGINE_ATLAS_CACHE_INVALID = "ENGINE_ATLAS_CACHE_INVALID";
export const ENGINE_ATLAS_GENERATION_FAILED = "ENGINE_ATLAS_GENERATION_FAILED";
