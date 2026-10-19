// GENERATED-STYLE hand-written config (not machine-generated, but treat edits
// with the same care): dependency-cruiser contracts for the frontend module
// boundaries in `CONSTITUTION.md` §3 ("Frontend module boundaries" table),
// C-2.16 (chart-engine independence) and C-3.5 (`apps/web` never imports
// another app; `packages/*` never import `apps/*`).
//
// E02-T06 (§9 #18: "architecture — import-linter module-boundary contracts
// (§3) + dependency-cruiser for TS + deep-import ban"). Every `comment`
// field below cites the exact rule id so a CI failure is self-explanatory
// (Constitution preamble: "reviewers cite rule ids in PRs").
//
// The descriptive mirror of these rules lives in
// `docs/plan/module-contracts.toml` under `[[frontend_package]]`; keep the
// two in sync by hand when either changes (there is no TS-side manifest
// parser — the drift test's frontend half only checks the rule count, see
// `services/api/tests/unit/architecture/test_module_contracts_drift.py`).

/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "not-to-unresolvable",
      severity: "error",
      comment: "Every import must resolve to a real module (typo / missing dep guard).",
      from: {},
      to: { couldNotResolve: true },
    },
    {
      name: "no-circular",
      severity: "error",
      comment: "C-3.1: dependencies flow one way; cycles are forbidden.",
      from: {},
      to: { circular: true },
    },
    {
      name: "packages-not-to-apps",
      severity: "error",
      comment: "C-3.5: `packages/*` must never import from `apps/*`.",
      from: { path: "^packages" },
      to: { path: "^apps" },
    },
    {
      name: "web-not-to-desktop",
      severity: "error",
      comment: "C-3.5 / §3 frontend table: `apps/web` must never import from another app.",
      from: { path: "^apps/web" },
      to: { path: "^apps/desktop" },
    },
    {
      name: "desktop-not-to-web",
      severity: "error",
      comment:
        "§3: `apps/desktop` is the Electron shell only — no business logic, and never " +
        "reaches into `apps/web`'s internals (the reverse of `web-not-to-desktop`).",
      from: { path: "^apps/desktop" },
      to: { path: "^apps/web" },
    },
    {
      name: "no-deep-imports-chart-engine",
      severity: "error",
      comment:
        "§9 #18 deep-import ban: only `@candleviewer/chart-engine`'s declared entry points " +
        "may be imported, never `packages/chart-engine/src/**` directly from outside it.",
      from: { pathNot: "^packages/chart-engine" },
      to: { path: "^packages/chart-engine/src" },
    },
    {
      name: "no-deep-imports-ui",
      severity: "error",
      comment:
        "§9 #18 deep-import ban: only `@candleviewer/ui`'s declared entry points may be " +
        "imported, never `packages/ui/src/**` directly from outside it.",
      from: { pathNot: "^packages/ui" },
      to: { path: "^packages/ui/src" },
    },
    {
      name: "no-deep-imports-protocol",
      severity: "error",
      comment:
        "§9 #18 deep-import ban: only `@candleviewer/protocol`'s declared entry points may " +
        "be imported, never `packages/protocol/src/**` directly from outside it.",
      from: { pathNot: "^packages/protocol" },
      to: { path: "^packages/protocol/src" },
    },
    {
      name: "no-deep-imports-fixtures",
      severity: "error",
      comment:
        "§9 #18 deep-import ban: only `@candleviewer/fixtures`'s declared entry points may " +
        "be imported, never `packages/fixtures/src/**` directly from outside it.",
      from: { pathNot: "^packages/fixtures" },
      to: { path: "^packages/fixtures/src" },
    },
    {
      name: "chart-engine-no-react",
      severity: "error",
      comment: "C-2.16: chart-engine must not depend on React/ReactDOM (framework-free core).",
      from: { path: "^packages/chart-engine/src/(core|layers)" },
      to: {
        path: "^(react|react-dom)($|/)",
      },
    },
    {
      name: "chart-engine-core-no-dom-host",
      severity: "error",
      comment:
        "C-2.16: src/core and src/layers stay DOM-free; DOM glue lives only in the host adapter.",
      from: { path: "^packages/chart-engine/src/(core|layers)" },
      to: { path: "^packages/chart-engine/src/host" },
    },
    {
      name: "chart-engine-harness-no-spike",
      severity: "error",
      comment:
        "E06-X02: the promoted M0 benchmark harness (src/**, bench/**) must never import from " +
        "a spike-only throwaway-prototype path (docs/plan/02-definition-of-ready-done.md §5.2). " +
        "See tools/ci/check_spike_containment.py.",
      from: { path: "^packages/chart-engine/(src|bench)" },
      to: { path: "^packages/chart-engine/spike" },
    },
    {
      name: "protocol-not-to-ui",
      severity: "error",
      comment: "§3 frontend table: packages/protocol must never depend on packages/ui.",
      from: { path: "^packages/protocol" },
      to: { path: "^packages/ui" },
    },
    {
      name: "protocol-not-to-apps",
      severity: "error",
      comment: "§3 frontend table: packages/protocol must never depend on apps/*.",
      from: { path: "^packages/protocol" },
      to: { path: "^apps" },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    // packages/ui's `storybook:build` output (gitignored): bundled chunks, not source modules.
    exclude: { path: "(^|/)storybook-static/" },
    tsPreCompilationDeps: true,
    enhancedResolveOptions: {
      exportsFields: ["exports"],
      conditionNames: ["import", "require", "node", "default"],
    },
  },
};
