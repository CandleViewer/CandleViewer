// E15-T02: packages/dock is pure TypeScript (the C-2.16 shape, for the dock). Nothing under src/
// may import React, the chart engine, another UI package, an app or a Node built-in, or touch a
// network, DOM, storage, clock or process global: the 1000-operation property tests run it in plain
// Node. Violations fail lint with the message below (the TS form of the ticket's import contract).
import { builtinModules } from "node:module";
import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";
import { noRestrictedImportsRuleSet } from "@candleviewer/config/no-restricted-imports";

const PURE =
  "E15-T02: packages/dock is pure TypeScript (no React, chart engine, DOM, network or Node APIs).";

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
          "crypto", // ids come from an injected minter (src/ids.ts)
          "performance", // pure and synchronous: the caller times an operation
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
        ].map((name) => ({ name, message: PURE })),
      ],
      // no-restricted-imports does not see import(), so a dynamic import is refused outright.
      "no-restricted-syntax": ["error", { selector: "ImportExpression", message: PURE }],
    },
  },
);
