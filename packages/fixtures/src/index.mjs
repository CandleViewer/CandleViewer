// Public entrypoint for @candleviewer/fixtures.
// Real fixture loaders (per-format readers, golden comparison helpers) land
// alongside recorded fixtures in E08; this scaffold exposes the redaction
// scanner so other packages/tools can reuse it without shelling out.
export { scanForSecrets } from "../scripts/verify.mjs";
export * from "./synthetic-ticks.mjs";
