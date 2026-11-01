import type { Preview } from "@storybook/react-vite";
import { DENSITIES, MOTION_OVERRIDES, THEMES } from "../src/theme/index.js";
import { withMountCount, withTokenBackground } from "./decorators.js";
import { inVitestTester, muteIdlePointer } from "./idlePointer.js";
import { mountAfterEffects, withMountSignal } from "./mountAfterEffects.js";
import "./theme-bundles.js";
import { withThemeRuntime } from "./withThemeRuntime.js";

const preview: Preview = {
  parameters: {
    // Serious and critical violations fail a story, moderate and minor are only reported
    // (03-testing-strategy.md): the addon's `toHaveNoViolations` keeps the `impactLevels` axe echoes.
    a11y: {
      test: "error",
      options: { impactLevels: ["critical", "serious"] },
    },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    options: {
      // The catalogue's band order (15-component-catalogue.md §0.3 rule 8), overview pages first.
      storySort: {
        order: [
          "Foundations",
          ["Tokens", "*"],
          "Atoms",
          ["Overview", "*"],
          "Molecules",
          ["Overview", "*"],
          "Organisms",
          ["Overview", "*"],
          "Trading",
          ["Overview", "*"],
          "RuleEngine",
          ["Overview", "*"],
          "ChartEngine",
          ["Overview", "*"],
        ],
      },
    },
  },
  initialGlobals: { theme: "dark", density: "compact", motion: "system" },
  globalTypes: {
    theme: {
      description: "Theme",
      toolbar: { title: "Theme", icon: "paintbrush", items: [...THEMES], dynamicTitle: true },
    },
    density: {
      description: "Density",
      toolbar: { title: "Density", icon: "ruler", items: [...DENSITIES], dynamicTitle: true },
    },
    motion: {
      description: "Reduced-motion override",
      toolbar: {
        title: "Motion",
        icon: "lightning",
        items: [...MOTION_OVERRIDES],
        dynamicTitle: true,
      },
    },
  },
  // Innermost first: the mount counter sits on the story, the theme runtime outside it, and the mount
  // signal outside everything, so its effect runs after every other effect of the story's commit.
  decorators: [withMountCount, withTokenBackground, withThemeRuntime, withMountSignal],
  // A play starts once those effects ran, in a production build too (mountAfterEffects.tsx).
  mount: mountAfterEffects,
  // In Vitest's tester a play is the story's only pointer: the runner's idle one is muted (idlePointer.ts, #5274).
  beforeEach: () => (inVitestTester() ? muteIdlePointer() : undefined),
};

export default preview;
