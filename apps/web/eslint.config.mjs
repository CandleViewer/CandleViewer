import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import security from "eslint-plugin-security";
import noUnsanitized from "eslint-plugin-no-unsanitized";
import baseConfig from "@candleviewer/config/eslint";

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
  // E11-Q02 (#444): no sleeps in the engine suite: wait on an engine event or a frame.
  {
    files: ["e2e/specs/e11-chart/**/*.ts", "e2e/support/engine/**/*.ts"],
    rules: {
      "no-restricted-properties": [
        "error",
        {
          property: "waitForTimeout",
          message: "E11-Q02: no sleeps; await an engine event or a frame.",
        },
      ],
      "no-restricted-globals": [
        "error",
        { name: "setTimeout", message: "E11-Q02: no sleeps." },
        { name: "setInterval", message: "E11-Q02: no timers." },
      ],
    },
  },
  // E11-Q02 (#444, AC1): the keyboard-only specs may not use a pointer API, so a feature that became
  // pointer-only fails here; support/engine/nav-guard.ts proves it again at run time.
  {
    files: ["e2e/specs/e11-chart/nav-only/**/*.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "MemberExpression[property.name=/^(mouse|touchscreen)$/]",
          message: "E11-Q02: nav-only specs dispatch no pointer events (page.mouse / touchscreen).",
        },
        {
          selector:
            "CallExpression[callee.property.name=/^(click|dblclick|hover|tap|dragTo|wheel)$/]",
          message: "E11-Q02: nav-only specs dispatch no pointer events; use focus() and keys.",
        },
      ],
    },
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
);
