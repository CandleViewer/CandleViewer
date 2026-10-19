import { afterEach, describe, expect, it, vi } from "vitest";
import { StyleRecalcBenchmark } from "../../src/theme/ThemeRuntime.stories.js";

// The real plugin factory loads Storybook's presets; the config only hands it options.
const storybookTest = vi.hoisted(() => vi.fn<(options: unknown) => unknown[]>(() => []));
vi.mock("@storybook/addon-vitest/vitest-plugin", () => ({ storybookTest }));

/** A variable, not a literal: tsc has no declarations for the `.mjs` config and never checks it. */
const CONFIG: string = "../../vitest.config.mjs";

interface Project {
  readonly test: { readonly name: string; readonly browser?: { readonly api?: unknown } };
}

/** packages/ui's `storybook` Vitest project and its plugin's options, under the perf switch. */
async function storybookProject(perf: string | undefined) {
  vi.resetModules();
  storybookTest.mockClear();
  vi.stubEnv("CV_STORYBOOK_PERF", perf);
  const { default: config } = (await import(/* @vite-ignore */ CONFIG)) as {
    default: { test: { projects: Project[] } };
  };
  const project = config.test.projects.find(({ test }) => test.name === "storybook");
  return { project, options: storybookTest.mock.calls[0]?.[0] };
}

afterEach(() => vi.unstubAllEnvs());

describe("the storybook Vitest project", () => {
  it("turns the browser API's file writes and exec off, as the GHSA-82fw register reason says", async () => {
    const { project } = await storybookProject(undefined);
    expect(project?.test.browser?.api).toEqual({ allowWrite: false, allowExec: false });
  });

  it("skips perf stories, the wall-clock benchmark among them, unless CV_STORYBOOK_PERF=1", async () => {
    expect(StyleRecalcBenchmark.tags).toContain("perf");
    for (const off of [undefined, "", "0", "true"]) {
      const { options } = await storybookProject(off);
      expect(options).toEqual({ configDir: ".storybook", tags: { skip: ["perf"] } });
    }
    const { options } = await storybookProject("1");
    expect(options).toEqual({ configDir: ".storybook", tags: { skip: [] } });
  });
});
