// The pinned software-GL Chromium flags of the engine bench. Provenance: copied from
// `PINNED_CHROMIUM_FLAGS` in packages/chart-engine/bench/report.mjs (E06-K01). Not imported: that file
// is no declared export of the engine package, so reaching it would be a deep import. Drift is caught
// by test/e2e-engine/chromium-flags.test.ts, which reads report.mjs as text and compares the lists.
export const PINNED_CHROMIUM_FLAGS: readonly string[] = [
  "--use-gl=angle",
  "--use-angle=swiftshader",
  "--disable-gpu-vsync",
  "--enable-webgl2",
  "--force-color-profile=srgb",
];
