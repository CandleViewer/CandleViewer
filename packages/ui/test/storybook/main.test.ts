import { describe, expect, it, vi } from "vitest";

/** `.storybook/main.ts` as Storybook loads it. */
async function mainConfig() {
  vi.resetModules();
  return (await import("../../.storybook/main.js")).default;
}

describe("Storybook main config", () => {
  it("builds the band stories and docs pages", async () => {
    const { stories } = await mainConfig();
    expect(stories).toEqual(["../src/**/*.mdx", "../src/**/*.stories.@(ts|tsx)"]);
  });

  it("loads the E05-T03 addon set and keeps telemetry and update notifications off", async () => {
    expect(await mainConfig()).toMatchObject({
      addons: ["@storybook/addon-docs", "@storybook/addon-a11y", "@storybook/addon-vitest"],
      features: { backgrounds: false },
      core: { disableTelemetry: true, disableWhatsNewNotifications: true },
    });
    const { scripts } = (await import("../../package.json")).default;
    expect(scripts.storybook).toMatch(/ --disable-telemetry --no-version-updates$/);
    expect(scripts["storybook:build"]).toMatch(/ --disable-telemetry$/);
  });
});
