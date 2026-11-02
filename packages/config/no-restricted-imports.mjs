// `no-restricted-imports` rule set (E02-T01 stub, extended by E02-T06).
// Mirrors the deep-import ban and cross-app/cross-package boundary rules
// enforced authoritatively by `.dependency-cruiser.js` (fast editor
// feedback; `.dependency-cruiser.js` remains the CI gate of record — see
// `docs/plan/module-contracts.toml` for the manifest both read).

/** @typedef {{ paths?: Array<{ name: string, message: string }>, patterns?: Array<{ group: string[], message: string }> }} RestrictedImportsRuleSet */

/** @type {RestrictedImportsRuleSet} */
export const noRestrictedImportsRuleSet = {
  paths: [
    {
      name: "lodash",
      message:
        "Use native ES2022+ methods or a scoped lodash/<fn> import instead of the full package.",
    },
  ],
  patterns: [
    {
      group: ["**/dist/**", "**/src/generated/**/*.internal"],
      message:
        "Import from a package's public entrypoint, not its build output or internal generated files.",
    },
    {
      // §9 #18 deep-import ban: only a package's declared `exports` entry
      // points may be imported.
      group: [
        "@candleviewer/ui/src/*",
        "@candleviewer/ui/src/**/*",
        "@candleviewer/chart-engine/src/*",
        "@candleviewer/chart-engine/src/**/*",
        "@candleviewer/protocol/src/*",
        "@candleviewer/protocol/src/**/*",
        "@candleviewer/fixtures/src/*",
        "@candleviewer/fixtures/src/**/*",
        "@candleviewer/rule-graph/src/*",
        "@candleviewer/rule-graph/src/**/*",
        "@candleviewer/dock/src/*",
        "@candleviewer/dock/src/**/*",
      ],
      message: "Deep import banned (§9 #18) — import the package's declared entry point instead.",
    },
    {
      // C-3.5: apps/web must never import another app; C-2.16: chart-engine
      // stays framework-free.
      group: ["*/apps/desktop/*", "**/apps/desktop/**"],
      message: "C-3.5: apps/web (and packages/*) must never import apps/desktop.",
    },
  ],
};

export default noRestrictedImportsRuleSet;
