import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import baseConfig from "@candleviewer/config/eslint";
import noRawDesignValues from "./eslint-rules/no-raw-design-values.mjs";
import storyTitleBands from "./eslint-rules/story-title-bands.mjs";

/** The package's own rules, one plugin object for every block that uses them. */
const candleviewer = {
  rules: { "no-raw-design-values": noRawDesignValues, "story-title-bands": storyTitleBands },
};

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  ...baseConfig,
  {
    ignores: ["dist/**", "coverage/**", "storybook-static/**", "build/**"],
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
    files: ["src/**/*.{ts,tsx}", ".storybook/**/*.{ts,tsx}"],
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
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: {
      globals: {
        console: "readonly",
        process: "readonly",
      },
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { candleviewer },
    rules: {
      "candleviewer/no-raw-design-values": "error",
    },
  },
  {
    // Storybook organisation (15-component-catalogue.md §0.3 rule 8): every story under a band.
    files: ["**/*.stories.{ts,tsx}"],
    plugins: { candleviewer },
    rules: {
      "candleviewer/story-title-bands": "error",
    },
  },
);
