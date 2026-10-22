// E37-T01: packages/rule-graph is pure TypeScript. Nothing under src/ may import React, the node
// graph libraries, another UI package or a Node built-in, or touch a network, DOM, storage or
// process global: the code runs on the editor thread, and the round-trip property tests run it in
// plain Node. Violations fail lint with the message below.
import { builtinModules } from "node:module";
import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";
import { noRestrictedImportsRuleSet } from "@candleviewer/config/no-restricted-imports";

const PURE =
  "E37-T01: packages/rule-graph is pure TypeScript (no React, DOM, network or Node APIs in src/).";

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
              "@xyflow/react",
              "@xyflow/system",
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
          "globalThis",
          "self",
        ].map((name) => ({ name, message: PURE })),
      ],
      // no-restricted-imports does not see import(), so a dynamic import is refused outright.
      "no-restricted-syntax": ["error", { selector: "ImportExpression", message: PURE }],
    },
  },
);
