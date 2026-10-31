import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  ...baseConfig,
  {
    ignores: ["coverage/**", "raw/**", "golden/**"],
  },
  // E10-Q02: the `e2e` subpath (the Playwright support both e2e suites share) is TypeScript.
  ...tseslint.configs.recommended.map((c) => ({ ...c, files: ["**/*.ts"] })),
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
);
