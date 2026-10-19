import type { StorybookConfig } from "@storybook/react-vite";

// The a11y gate's self-test switch (E05-T03): "1" builds the fixtures alone; otherwise the band
// globs never reach `.storybook/__fixtures__/`, so no fixture is built or published.
const fixturesOnly = process.env["CV_STORYBOOK_A11Y_FIXTURES"] === "1";

// Story-level lazy compilation: the Vite builder imports each story file on demand and Vite
// transforms modules on request (`lazyCompilation` is the webpack builder's switch).
const config: StorybookConfig = {
  stories: fixturesOnly
    ? ["./__fixtures__/*.stories.tsx"]
    : ["../src/**/*.mdx", "../src/**/*.stories.@(ts|tsx)"],
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
