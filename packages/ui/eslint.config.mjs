import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import baseConfig from "@candleviewer/config/eslint";
import { iconBesideTextHidden, iconOnlyControlLabel } from "./eslint-rules/icon-a11y.mjs";
import noRawDesignValues from "./eslint-rules/no-raw-design-values.mjs";
import noRawSvg from "./eslint-rules/no-raw-svg.mjs";
import storyTitleBands from "./eslint-rules/story-title-bands.mjs";

/** The package's own rules, one plugin object for every block that uses them. */
const candleviewer = {
  rules: {
    "icon-beside-text-hidden": iconBesideTextHidden,
    "icon-only-control-label": iconOnlyControlLabel,
    "no-raw-design-values": noRawDesignValues,
    "no-raw-svg": noRawSvg,
    "story-title-bands": storyTitleBands,
  },
};
/** Component code the icon rules bind; the a11y gate's fixtures break them on purpose. */
const ICON_RULE_FILES = ["src/**/*.{ts,tsx}", ".storybook/**/*.{ts,tsx}"];
const FIXTURES = ".storybook/__fixtures__/**";

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
      // SR-127 (04-security-program.md §6.12): no markup strings, SVG included; the CI Semgrep
      // rule cv-shell-dangerously-set-inner-html is its twin.
      "react/no-danger": "error",
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
    // The decorative-vs-meaningful icon rule (16-design-system-brief.md §5, CMP-002, CMP-019).
    files: ICON_RULE_FILES,
    ignores: [FIXTURES],
    plugins: { candleviewer },
    rules: {
      "candleviewer/icon-only-control-label": "error",
      "candleviewer/icon-beside-text-hidden": "error",
    },
  },
  {
    // Glyphs come from the icon registry; its grid, src/icons/IconSvg.tsx, draws the one <svg>.
    files: ICON_RULE_FILES,
    ignores: ["src/icons/IconSvg.tsx", FIXTURES],
    plugins: { candleviewer },
    rules: {
      "candleviewer/no-raw-svg": "error",
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
