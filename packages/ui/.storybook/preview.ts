import type { Preview } from "@storybook/react-vite";
import { DENSITIES, MOTION_OVERRIDES, THEMES } from "../src/theme/index.js";
import { withMountCount, withTokenBackground } from "./decorators.js";
import "./theme-bundles.js";
import { withThemeRuntime } from "./withThemeRuntime.js";

const preview: Preview = {
  parameters: {
    // Zero serious/critical a11y violations is the bar (CONSTITUTION §9 #9).
    a11y: {
      test: "error",
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
  // Innermost first: the mount counter sits on the story, the theme runtime outside everything.
  decorators: [withMountCount, withTokenBackground, withThemeRuntime],
};

export default preview;
