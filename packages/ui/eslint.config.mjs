import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import baseConfig from "@candleviewer/config/eslint";
import {
  iconBesideTextHidden,
  iconLabelRequired,
  iconOnlyControlLabel,
} from "./eslint-rules/icon-a11y.mjs";
import noRawDesignValues from "./eslint-rules/no-raw-design-values.mjs";
import noRawSvg from "./eslint-rules/no-raw-svg.mjs";
import storyTitleBands from "./eslint-rules/story-title-bands.mjs";

/** The package's own rules, one plugin object for every block that uses them. */
const candleviewer = {
  rules: {
    "icon-beside-text-hidden": iconBesideTextHidden,
    "icon-label-required": iconLabelRequired,
    "icon-only-control-label": iconOnlyControlLabel,
    "no-raw-design-values": noRawDesignValues,
    "no-raw-svg": noRawSvg,
    "story-title-bands": storyTitleBands,
  },
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
      // E05-X02 (SR-127): no component or story renders raw HTML. Semgrep's
      // cv-shell-dangerously-set-inner-html covers src/ in CI; this catches it in the editor and
      // covers .storybook/ too. test/eslint-rules/eslint-config.test.ts pins it.
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
      // Decorative vs meaningful (16-design-system-brief.md §5) under CMP-019's ids (E05-D02),
      // stories included. Tests are not: they write the unnamed cases on purpose to pin the types
      // (test/IconButton.test.tsx). test/eslint-rules/eslint-config.test.ts pins this wiring.
      "candleviewer/icon-label-required": "error",
      "candleviewer/icon-only-control-label": "error",
      "candleviewer/icon-beside-text-hidden": "error",
    },
  },
  {
    // Raw SVG lives in src/icons/ alone, which the rule exempts by path (E05-T06); stories, tests and
    // .storybook have no reason to draw a raw glyph, so the rest of the package is held to it.
    files: ["**/*.{ts,tsx}"],
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
