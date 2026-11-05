// E36-T01: packages/rule-editor-core is pure TypeScript (the C-2.16 shape). Nothing under src/
// may import React, the chart engine, another UI package, an app or a Node built-in, or touch a
// network, DOM, storage, clock or process global: the server bindings take an injected fetch, the
// counters an injected sink, and the property tests run it in plain Node. Violations fail lint.
import { builtinModules } from "node:module";
import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";
import { noRestrictedImportsRuleSet } from "@candleviewer/config/no-restricted-imports";

const PURE =
  "E36-T01: packages/rule-editor-core is pure TypeScript (no React, UI, chart engine, DOM, network or Node APIs).";

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  ...baseConfig,
  {
    ignores: ["dist/**", "coverage/**"],
  },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.ts"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ["**/*.mjs"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    files: ["src/**/*.ts"],
    rules: {
      // A package-level rule replaces the shared one, so the shared paths and patterns (the
      // deep-import ban of §9 #18 among them) are merged in, not dropped.
      "no-restricted-imports": [
        "error",
        {
          paths: [
            ...(noRestrictedImportsRuleSet.paths ?? []),
            ...[
              "react",
              "react-dom",
              // Bare built-in names ("fs", "fs/promises"), the deprecated `_`-prefixed aliases
              // (`_http_agent`, `_stream_readable`, ...) too; `node:*` is a pattern below.
              ...builtinModules,
            ].map((name) => ({ name, message: PURE })),
          ],
          patterns: [
            ...(noRestrictedImportsRuleSet.patterns ?? []),
            {
              group: ["node:*", "**/apps/**", "@candleviewer/ui", "@candleviewer/chart-engine"],
              message: PURE,
            },
          ],
        },
      ],
      "no-restricted-globals": [
        "error",
        ...[
          "fetch",
          "XMLHttpRequest",
          "WebSocket",
          "window",
          "document",
          "navigator",
          "localStorage",
          "sessionStorage",
          "process",
          "Buffer",
          "crypto",
          "performance", // the latency counters take an injected clock (PR-3)
          "setTimeout",
          "setInterval",
          "setImmediate",
          "queueMicrotask",
          "console",
          "indexedDB",
          "location",
          "Worker",
          "globalThis",
          "self",
          "global",
          "EventSource",
          "BroadcastChannel",
          "Request",
          "Response",
          "caches",
          "eval",
          "Function",
          "postMessage",
          "importScripts",
          "require",
          "Date",
          "TextEncoder", // limits.ts counts UTF-8 bytes itself, with no copy of a 2 MB body
          "TextDecoder",
        ].map((name) => ({ name, message: PURE })),
      ],
      // Nothing here is random: row ids derive from the IR's own node ids.
      "no-restricted-properties": ["error", { object: "Math", property: "random", message: PURE }],
      // The protocol is types only (C-4.16): a value import would pull runtime decoders in.
      "@typescript-eslint/consistent-type-imports": ["error", { prefer: "type-imports" }],
      "@typescript-eslint/no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@candleviewer/protocol",
              allowTypeImports: true,
              message: "E36-T01: import @candleviewer/protocol with `import type` only.",
            },
          ],
          // The subpaths (`/rule-ir` also ships a runtime module) are held to the same rule.
          patterns: [
            {
              group: ["@candleviewer/protocol/*"],
              allowTypeImports: true,
              message: "E36-T01: import @candleviewer/protocol/* with `import type` only.",
            },
          ],
        },
      ],
      // no-restricted-imports does not see import(), so a dynamic import is refused outright.
      "no-restricted-syntax": ["error", { selector: "ImportExpression", message: PURE }],
    },
  },
);
