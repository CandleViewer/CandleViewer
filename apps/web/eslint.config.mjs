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
