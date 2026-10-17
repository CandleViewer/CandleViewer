import type { Preview } from "@storybook/react";
import { DENSITIES, MOTION_OVERRIDES, THEMES } from "../src/theme/index.js";
import { withThemeRuntime } from "./withThemeRuntime.js";
import "../src/theme/theme.css";

// Token CSS only exists after `pnpm --filter @candleviewer/ui build:tokens`; before that the glob is empty.
import.meta.glob("../build/css/tokens.*.css", { eager: true });

// Zero serious/critical a11y violations is the bar (CONSTITUTION §9 #9).
const preview: Preview = {
  parameters: {
    a11y: {
      test: "error",
    },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
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
  decorators: [withThemeRuntime],
};

export default preview;
