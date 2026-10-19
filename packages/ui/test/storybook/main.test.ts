import { afterEach, describe, expect, it, vi } from "vitest";

/** `.storybook/main.ts` as Storybook loads it, under the given fixture switch. */
async function mainConfig(fixtures?: string) {
  vi.resetModules();
  if (fixtures !== undefined) vi.stubEnv("CV_STORYBOOK_A11Y_FIXTURES", fixtures);
  return (await import("../../.storybook/main.js")).default;
}

afterEach(() => vi.unstubAllEnvs());

describe("Storybook main config", () => {
  it("builds the band stories and docs pages, never the a11y gate fixtures", async () => {
    for (const unset of [undefined, "", "0"]) {
      const { stories } = await mainConfig(unset);
      expect(stories).toEqual(["../src/**/*.mdx", "../src/**/*.stories.@(ts|tsx)"]);
    }
  });

  it("builds the fixtures alone when the gate self-test sets the switch", async () => {
    expect((await mainConfig("1")).stories).toEqual(["./__fixtures__/*.stories.tsx"]);
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

  it("binds the dev server to loopback itself, not through Storybook's default host", async () => {
    // C-12.9: 10.6.2 listens on 127.0.0.1 when no host is given; the flag keeps a changed default
    // from widening the dev server's exposure.
    const { scripts } = (await import("../../package.json")).default;
    expect(scripts.storybook).toMatch(/^storybook dev .* --host 127\.0\.0\.1 /);
    expect(scripts.storybook.match(/--host\b|\s-h\s/g)).toEqual(["--host"]);
  });
});
