// E11-T04's error code, in a leaf module (like text/codes.ts) so the main-thread facade and the
// worker protocol can both re-export it without pulling the ingest graph into either bundle.
// Raised synchronously by `ingestTheme` / `densityRecord` (BQ-T04-04): the message names the
// offending key and nothing is installed.
export const ENGINE_THEME_INVALID = "ENGINE_THEME_INVALID";
