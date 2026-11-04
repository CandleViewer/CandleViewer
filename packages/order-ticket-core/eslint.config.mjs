// E30-T01: packages/order-ticket-core is pure TypeScript (the C-2.16 shape). Nothing under src/
// may import React, the chart engine, another UI package, an app or a Node built-in, or touch a
// network, DOM, storage, clock, channel, locale or process global: the property tests run it in
// plain Node, and a worker can host it (E30-K01). Violations fail lint with the message below.
import { builtinModules } from "node:module";
import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";
import { noRestrictedImportsRuleSet } from "@candleviewer/config/no-restricted-imports";

const PURE =
  "E30-T01: packages/order-ticket-core is pure TypeScript (no React, UI, chart engine, DOM, network or Node APIs).";

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
          "crypto", // the Idempotency-Key comes from an injected ids port (BQ 6, slice S4)
          "performance", // the metric hooks take an injected clock (slice S4)
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
          "Date", // time comes through an injected clock port (S4)
          "MessageChannel", // a channel (and a timer by another name): the host owns messaging
          "Intl", // a locale read, and a clock read through `new Intl.DateTimeFormat().format()`
        ].map((name) => ({ name, message: PURE })),
      ],
      // Randomness comes through an injected ids port (BQ 6), never Math.random.
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
              message: "E30-T01: import @candleviewer/protocol with `import type` only.",
            },
          ],
        },
      ],
      // no-restricted-imports does not see import(), so a dynamic import is refused outright.
      "no-restricted-syntax": ["error", { selector: "ImportExpression", message: PURE }],
    },
  },
);
