import path from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ICON_A11Y = ["candleviewer/icon-only-control-label", "candleviewer/icon-beside-text-hidden"];
const RAW_SVG = "candleviewer/no-raw-svg";
const eslint = new ESLint({ cwd: PACKAGE });

/** Each icon rule's severity for a package file, as eslint.config.mjs resolves it (0 when off). */
async function severities(file: string): Promise<number[]> {
  // calculateConfigForFile is typed `any`: the resolved config of a flat config file.
  const config = (await eslint.calculateConfigForFile(path.join(PACKAGE, file))) as {
    readonly rules: Readonly<Record<string, readonly [number, ...unknown[]]>>;
  };
  return [...ICON_A11Y, RAW_SVG].map((rule) => config.rules[rule]?.[0] ?? 0);
}

describe("the icon rules' wiring (eslint.config.mjs)", () => {
  it.each(["src/components/ColorConventionLegend.tsx", "src/theme/ThemeRuntime.stories.tsx"])(
    "binds all three icon rules in component code: %s",
    async (file) => {
      expect(await severities(file)).toEqual([2, 2, 2]);
    },
  );

  it.each([
    "src/icons/IconSvg.tsx",
    "src/icons/generated/CloseIcon.tsx",
    "src/icons/Icons.stories.tsx",
  ])("lets the registry's own modules draw the <svg>, under the a11y rules: %s", async (file) => {
    expect(await severities(file)).toEqual([2, 2, 0]);
  });

  it("binds the Storybook harness too, but not the a11y gate fixtures that fail on purpose", async () => {
    expect(await severities(".storybook/decorators.tsx")).toEqual([2, 2, 2]);
    expect(await severities(".storybook/__fixtures__/IconOnlyButton.stories.tsx")).toEqual([
      0, 0, 0,
    ]);
  });
});
