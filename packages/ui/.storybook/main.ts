import type { StorybookConfig } from "@storybook/react-vite";

// Story-level lazy compilation: the Vite builder imports each story file on demand and Vite
// transforms modules on request (`lazyCompilation` is the webpack builder's switch).
const config: StorybookConfig = {
  stories: ["../src/**/*.mdx", "../src/**/*.stories.@(ts|tsx)"],
  // The E05-T03 addon set: docs pages, the a11y panel and its gate, and the Vitest addon that runs
  // every story's play function and axe check. Controls, toolbars and interactions are core.
  addons: ["@storybook/addon-docs", "@storybook/addon-a11y", "@storybook/addon-vitest"],
  // The canvas background is the token decorator's, not the backgrounds toolbar's.
  features: { backgrounds: false },
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  core: {
    // No usage telemetry or update notification leaves the dev server, the build, the Vitest
    // plugin or a CLI that reads this file.
    disableTelemetry: true,
    disableWhatsNewNotifications: true,
  },
};

export default config;
