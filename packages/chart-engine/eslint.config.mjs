// C-2.16 enforcement: packages/chart-engine must not import React, the DOM,
// `fetch`, or any Bybit/exchange-specific module. Violations fail lint with a
// message citing C-2.16 (ticket E02-T03 acceptance criterion #2).
import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";

// C-2.16 network ban, shared by src/** and the worker override below (no I/O anywhere here).
const NETWORK_GLOBALS = [
  { name: "fetch", message: "C-2.16: packages/chart-engine must not call fetch (no I/O)." },
  {
    name: "XMLHttpRequest",
    message: "C-2.16: packages/chart-engine must not use XMLHttpRequest (no I/O).",
  },
  {
    name: "WebSocket",
    message: "C-2.16: packages/chart-engine must not open a WebSocket (no I/O).",
  },
];

// C-2.16 DOM ban for src/core|layers|scene: every browser global (`globals.browser`) that is
// neither an ES built-in nor a Node global, plus `navigator`, which Node also defines. The
// package tsconfig.core.json carries no DOM lib either (only tsconfig.dom.json, for src/api and
// src/host, does), so a DOM type there fails `tsc` as well (E11-T01).
const NODE_OR_ES = new Set([...Object.keys(globals.node), ...Object.keys(globals.es2021)]);
const DOM_GLOBALS = [
  ...Object.keys(globals.browser).filter((name) => !NODE_OR_ES.has(name)),
  "navigator",
  "Navigator",
].map((name) => ({
  name,
  message: "C-2.16: no DOM globals in src/core|layers|scene (DOM glue is the host adapter's).",
}));

// C-2.16 exchange-knowledge ban on symbol names and string literals (E11-T01), and the network
// globals reached through a global object, which `no-restricted-globals` does not see.
const C216_SYNTAX = [
  {
    selector: "Identifier[name=/bybit/i]",
    message: "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge (symbol name).",
  },
  {
    // Static import/export paths are no-restricted-imports' (one report each); a dynamic
    // `import("…bybit…")` is caught here.
    selector:
      "Literal[value=/bybit/i]:not(ImportDeclaration > Literal, ExportNamedDeclaration > Literal," +
      " ExportAllDeclaration > Literal), TemplateElement[value.raw=/bybit/i]",
    message:
      "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge (string literal).",
  },
  {
    selector:
      "MemberExpression[object.name=/^(globalThis|self|window)$/]" +
      "[property.name=/^(fetch|XMLHttpRequest|WebSocket)$/]",
    message: "C-2.16: packages/chart-engine must not do network I/O (fetch/XHR/WebSocket).",
  },
];

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  ...baseConfig,
  {
    ignores: ["dist/**", "coverage/**", "bench/results.json", "bench/baseline.json"],
  },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.ts"],
    languageOptions: {
      parserOptions: {
        // The project service lints the text it is given (stdin, editors), not the file on disk.
        // tsconfig.json is solution-style: each file resolves to tsconfig.core.json (no DOM lib)
        // or tsconfig.dom.json (src/index.ts, src/api, src/host, test/api).
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: [
      "bench/run-bench.mjs",
      "bench/scenes/run-scene-a.mjs",
      "bench/scenes/scene-a.mjs",
      "bench/scenes/run-scene-b.mjs",
      "bench/scenes/scene-b.mjs",
      "bench/scenes/run-scene-c.mjs",
      "bench/scenes/scene-c.mjs",
      "bench/scenes/atlas.mjs",
    ],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    files: ["src/**/*.ts", "bench/**/*.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "react",
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
            {
              name: "react-dom",
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
          ],
          patterns: [
            {
              group: ["react/*", "react-dom/*"],
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
            {
              group: ["**/apps/**", "@candleviewer/web", "@candleviewer/web/*"],
              message: "C-2.16 / C-3.5: packages/chart-engine must never import an app (apps/*).",
            },
            {
              group: ["**/exchange/**", "**/bybit/**"],
              message: "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge.",
            },
            {
              regex: "bybit",
              caseSensitive: false,
              message: "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge.",
            },
            {
              group: ["**/spike/**"],
              message:
                "E06-X02: the promoted benchmark harness must never import from a spike-only " +
                "(throwaway prototype) path. See tools/ci/check_spike_containment.py.",
            },
          ],
        },
      ],
      "no-restricted-globals": [
        "error",
        ...NETWORK_GLOBALS,
        { name: "document", message: "C-2.16: no DOM globals in src/core or src/layers." },
        { name: "window", message: "C-2.16: no DOM globals in src/core or src/layers." },
      ],
      "no-restricted-syntax": ["error", ...C216_SYNTAX],
    },
  },
  {
    // The bench harness/runner/driver `.mjs` files are not covered by the
    // `**/*.ts` glob above but are exactly the "promoted harness" this
    // boundary protects (E06-X02 acceptance criterion "The harness does not
    // depend on the prototype").
    files: ["bench/**/*.mjs"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/spike/**"],
              message:
                "E06-X02: the promoted benchmark harness must never import from a spike-only " +
                "(throwaway prototype) path. See tools/ci/check_spike_containment.py.",
            },
          ],
        },
      ],
    },
  },
  {
    // E06-T01 cross-runtime matrix (spike-only harness): the runner/compare/manifest code
    // is Node; page/ and scenes/ run inside Chromium/Electron/WebView2 (browser + worker);
    // the Electron shell files are CommonJS by necessity (sandboxed preload).
    files: ["bench/machine.mjs", "bench/matrix/**/*.mjs", "bench/matrix/**/*.cjs"],
    languageOptions: {
      globals: { ...globals.node, ...globals.browser, ...globals.worker },
    },
  },
  {
    files: ["bench/matrix/**/*.cjs"],
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  {
    // C-2.16: core, layers and the scene graph touch no DOM at all, not just `document` /
    // `window` (E11-T01, E11-S01: requestAnimationFrame is bound in the worker or host only).
    files: ["src/core/**/*.ts", "src/layers/**/*.ts", "src/scene/**/*.ts"],
    rules: {
      "no-restricted-globals": ["error", ...NETWORK_GLOBALS, ...DOM_GLOBALS],
    },
  },
  {
    // E14-X03 (#549; DR6, SR-E14-01): no inline comment lifts a rule in the drawing layer, C-2.16's
    // DOM ban among them. tools/ci/no-inline-suppression-paths.json lists the same path.
    files: ["src/layers/drawings/**/*.{ts,mts,cts}"],
    linterOptions: { noInlineConfig: true },
  },
  {
    files: ["src/worker/**/*.ts"],
    rules: {
      // The worker glue is the one place OffscreenCanvas/postMessage globals
      // are expected; core/layers stay DOM-free (C-2.16). The network ban still holds here.
      "no-restricted-globals": ["error", ...NETWORK_GLOBALS],
    },
  },
);
