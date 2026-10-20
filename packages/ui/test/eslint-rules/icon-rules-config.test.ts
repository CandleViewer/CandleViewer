import path from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint, Linter } from "eslint";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ICON_A11Y = ["candleviewer/icon-only-control-label", "candleviewer/icon-beside-text-hidden"];
const RAW_SVG = "candleviewer/no-raw-svg";
const eslint = new ESLint({ cwd: PACKAGE });
const linter = new Linter();

/** Each rule's severity for a package file, as eslint.config.mjs resolves it (0 when off). */
async function severities(
  file: string,
  rules: readonly string[] = [...ICON_A11Y, RAW_SVG],
): Promise<number[]> {
  // calculateConfigForFile is typed `any`: the resolved config of a flat config file.
  const config = (await eslint.calculateConfigForFile(path.join(PACKAGE, file))) as {
    readonly rules: Readonly<Record<string, readonly [number, ...unknown[]]>>;
  };
  return rules.map((rule) => config.rules[rule]?.[0] ?? 0);
}

/** What `no-restricted-imports`, as eslint.config.mjs resolves it for a package file, reports. */
async function restrictedImports(file: string, code: string): Promise<string[]> {
  // calculateConfigForFile is typed `any`; a resolved rule entry is a Linter.RuleEntry.
  const config = (await eslint.calculateConfigForFile(path.join(PACKAGE, file))) as {
    readonly rules: Readonly<Record<string, Linter.RuleEntry>>;
  };
  const rule = config.rules["no-restricted-imports"];
  if (rule === undefined) throw new Error(`${file}: no-restricted-imports is not configured`);
  return linter
    .verify(
      code,
      [
        {
          files: ["**/*.tsx"],
          languageOptions: { parser: tseslint.parser },
          rules: { "no-restricted-imports": rule },
        },
      ],
      { filename: "probe.tsx" },
    )
    .map((message) => message.message);
}

describe("the icon rules' wiring (eslint.config.mjs)", () => {
  it.each([
    "src/components/ColorConventionLegend.tsx",
    "src/theme/ThemeRuntime.stories.tsx",
    "src/icons/generated/CloseIcon.tsx",
    "src/icons/Icons.stories.tsx",
  ])("binds all three icon rules in component code, the registry's included: %s", async (file) => {
    expect(await severities(file)).toEqual([2, 2, 2]);
  });

  it("lets only the grid, src/icons/IconSvg.tsx, draw the <svg>, under the a11y rules", async () => {
    expect(await severities("src/icons/IconSvg.tsx")).toEqual([2, 2, 0]);
  });

  it.each([
    "src/components/ColorConventionLegend.tsx",
    "src/icons/IconSvg.tsx",
    ".storybook/decorators.tsx",
  ])(
    "fails markup strings, an SVG one included, with react/no-danger (SR-127): %s",
    async (file) => {
      expect(await severities(file, ["react/no-danger"])).toEqual([2]);
    },
  );

  it("binds the Storybook harness too, but not the a11y gate fixtures that fail on purpose", async () => {
    expect(await severities(".storybook/decorators.tsx")).toEqual([2, 2, 2]);
    expect(await severities(".storybook/__fixtures__/IconOnlyButton.stories.tsx")).toEqual([
      0, 0, 0,
    ]);
  });
});

describe("the grid's one door (no-restricted-imports in eslint.config.mjs)", () => {
  const COMPONENT = "src/components/ColorConventionLegend.tsx";
  const GENERATED = "src/icons/generated/CloseIcon.tsx";

  it.each([
    'import { IconSvg } from "../icons/IconSvg.js";',
    'import { IconSvg as Grid } from "../icons/IconSvg";',
    'import * as grid from "../icons/IconSvg.js";',
    'export { IconSvg } from "./IconSvg.js";',
    'export * from "./IconSvg.js";',
  ])("keeps any other code from drawing in the grid: %s", async (code) => {
    for (const file of [COMPONENT, "src/icons/index.ts", "src/icons/Icons.stories.tsx"]) {
      expect(await restrictedImports(file, code), file).toEqual([
        expect.stringContaining("packages/ui/src/icons/registry.ts"),
      ]);
    }
    expect(await restrictedImports(".storybook/decorators.tsx", code)).toHaveLength(1);
  });

  it("lets the generated modules draw in it, and any code take its types and sizes", async () => {
    const grid = 'import { IconSvg, type IconProps } from "../IconSvg.js";';
    expect(await restrictedImports(GENERATED, grid)).toEqual([]);
    const types = 'import { ICON_SIZES, type IconProps } from "../icons/IconSvg.js";';
    expect(await restrictedImports(COMPONENT, types)).toEqual([]);
  });

  it("keeps the shared rule set beside it, since a rule's options replace, never merge", async () => {
    for (const file of [COMPONENT, GENERATED]) {
      expect(
        await restrictedImports(file, 'import "@candleviewer/ui/src/tokens/x.js";'),
      ).toHaveLength(1);
      expect(await restrictedImports(file, 'import { map } from "lodash";')).toHaveLength(1);
    }
  });
});
