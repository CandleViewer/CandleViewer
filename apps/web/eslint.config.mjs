import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import security from "eslint-plugin-security";
import noUnsanitized from "eslint-plugin-no-unsanitized";
import baseConfig from "@candleviewer/config/eslint";
import { noRestrictedImportsRuleSet } from "@candleviewer/config/no-restricted-imports";

const PURE_GRAPH =
  "E37-S01: rule-builder-graph's a11y/ and model/ are pure (no React, graph library, DOM, timers, clock or console).";
/**
 * The globals a pure core never reads, by family. The clock, task and log ones are closed as
 * packages/rule-graph closes them: ids and replays stay deterministic.
 */
const IMPURE_GLOBALS = {
  page: ["window", "document", "navigator", "location", "self", "globalThis"],
  storage: ["localStorage", "sessionStorage", "indexedDB"],
  network: ["fetch", "XMLHttpRequest", "WebSocket"],
  rendering: ["requestAnimationFrame", "cancelAnimationFrame", "matchMedia", "getComputedStyle"],
  observers: ["ResizeObserver", "MutationObserver", "IntersectionObserver"],
  elements: ["HTMLElement", "Element", "Event", "CustomEvent"],
  clock: ["setTimeout", "setInterval", "queueMicrotask", "performance"],
  log: ["console"],
};

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  ...baseConfig,
  {
    ignores: ["dist/**", "coverage/**", "playwright-report/**", "test-results/**"],
  },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: {
      react: reactPlugin,
      "react-hooks": reactHooksPlugin,
    },
    rules: {
      ...reactPlugin.configs.recommended.rules,
      ...reactHooksPlugin.configs.recommended.rules,
      "react/react-in-jsx-scope": "off",
    },
    settings: {
      react: { version: "18.3" },
    },
  },
  // E10-X02 (SR-127): security + no-unsanitized on the shell modules, blocking at error level.
  {
    files: ["src/shell/**/*.{ts,tsx}", "src/routes/**/*.{ts,tsx}"],
    plugins: { security, "no-unsanitized": noUnsanitized },
    rules: {
      ...Object.fromEntries(
        Object.keys(security.configs.recommended.rules).map((rule) => [rule, "error"]),
      ),
      "no-unsanitized/method": "error",
      "no-unsanitized/property": "error",
    },
  },
  // E14-X03 (#549; DR6, SR-E14-01): the drawing render paths show stored user text (labels, notes,
  // template names). No raw-HTML sink is allowed there, and no inline comment can lift the ban:
  // with noInlineConfig an `eslint-disable` is inert and ESLint warns about it, which
  // --max-warnings=0 fails. Keep these globs equal to tools/ci/no-inline-suppression-paths.json.
  {
    files: [
      "src/features/drawings/**/*.{ts,tsx,mts,cts}",
      "src/drawings/**/*.{ts,tsx,mts,cts}",
      "src/objecttree/**/*.{ts,tsx,mts,cts}",
    ],
    plugins: { "no-unsanitized": noUnsanitized },
    linterOptions: { noInlineConfig: true },
    rules: {
      "no-unsanitized/method": "error",
      "no-unsanitized/property": "error",
    },
  },
  {
    files: [
      "src/features/drawings/**/*.{ts,tsx}",
      "src/drawings/**/*.{ts,tsx}",
      "src/objecttree/**/*.{ts,tsx}",
    ],
    rules: { "react/no-danger": "error" },
  },
  // E17-T04 S5e-2 (ADR-0005; 50-security): the shared worker's code has no page, so it names none of a page's globals.
  {
    files: ["src/lib/ws/worker/**/*.ts"],
    rules: {
      "no-restricted-globals": [
        "error",
        ...["window", "document", "localStorage", "sessionStorage", "XMLHttpRequest"].map(
          (name) => ({
            name,
            message: "The shared worker's code runs in a worker, which has no page (ADR-0005).",
          }),
        ),
      ],
    },
  },
  // E37-S01 (BQ-1): the rule editor's keyboard core (E47-S03) and its graph model hold no React,
  // React DOM or graph-library import and read none of IMPURE_GLOBALS, as packages/rule-graph's
  // own rule says; the canvas and the screen around them hold those. This rule set replaces the shared one
  // for these files, so the shared paths and patterns (§9 #18's deep-import ban) are merged in.
  {
    files: ["src/features/rule-builder-graph/{a11y,model}/**/*.{ts,tsx,mts,cts}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            ...(noRestrictedImportsRuleSet.paths ?? []),
            ...["react", "react-dom"].map((name) => ({ name, message: PURE_GRAPH })),
          ],
          patterns: [
            ...(noRestrictedImportsRuleSet.patterns ?? []),
            { group: ["react/*", "react-dom/*", "@xyflow/*"], message: PURE_GRAPH },
          ],
        },
      ],
      "no-restricted-globals": [
        "error",
        ...Object.values(IMPURE_GLOBALS)
          .flat()
          .map((name) => ({ name, message: PURE_GRAPH })),
      ],
    },
  },
);
