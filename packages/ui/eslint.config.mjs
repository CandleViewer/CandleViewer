import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import baseConfig from "@candleviewer/config/eslint";
import { noRestrictedImportsRuleSet } from "@candleviewer/config/no-restricted-imports";
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
/**
 * The grid's one door (16-design-system-brief.md §5): only the generated icon modules draw in
 * `IconSvg`, so every glyph on a page passed the registry's generator and tests. Its types and
 * sizes stay importable. ESLint reads static imports and re-exports only;
 * test/icons/registry.test.ts covers an `import()` call and the MDX pages.
 */
const GRID_DOOR = {
  group: ["**/IconSvg", "**/IconSvg.js", "**/IconSvg.jsx", "**/IconSvg.ts", "**/IconSvg.tsx"],
  importNames: ["IconSvg"],
  message:
    'Only the generated icon modules draw in the grid. Render the icon\'s component (e.g. <CloseIcon />), or add the glyph to the icon registry, packages/ui/src/icons/registry.ts (packages/ui/README.md, "Icons").',
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
    // GRID_DOOR, beside the shared rule set: a rule's options replace the base config's.
    files: ICON_RULE_FILES,
    ignores: ["src/icons/generated/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          ...noRestrictedImportsRuleSet,
          patterns: [...(noRestrictedImportsRuleSet.patterns ?? []), GRID_DOOR],
        },
      ],
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
