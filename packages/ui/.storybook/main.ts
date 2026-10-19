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
    // Telemetry and what's-new notices are off once this file loads; the scripts also pass
    // --disable-telemetry (errors before it loads) and dev's --no-version-updates (update check).
    disableTelemetry: true,
    disableWhatsNewNotifications: true,
  },
};

export default config;
