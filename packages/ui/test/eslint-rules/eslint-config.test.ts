import path from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

/** packages/ui, the cwd of its `eslint .`: the real eslint.config.mjs, as the lint job loads it. */
const UI = fileURLToPath(new URL("../..", import.meta.url));
const eslint = new ESLint({ cwd: UI });

const ICON_RULES = [
  "candleviewer/icon-label-required",
  "candleviewer/icon-only-control-label",
  "candleviewer/icon-beside-text-hidden",
  "candleviewer/no-raw-svg",
];

/** The icon rules a file is linted with, as the computed config writes them (`error` is `[2]`). */
async function iconRules(file: string): Promise<Record<string, unknown>> {
  const { rules } = (await eslint.calculateConfigForFile(file)) as {
    rules: Record<string, unknown>;
  };
  return Object.fromEntries(Object.entries(rules).filter(([id]) => ICON_RULES.includes(id)));
}

const atError = (ids: string[]) => Object.fromEntries(ids.map((id) => [id, [2]]));

// Loading the config, and the type-aware parser's first file, take seconds on a cold worker.
describe("packages/ui's eslint.config.mjs", { timeout: 60_000 }, () => {
  it("holds src/, stories and the registry included, to all four icon rules at error", async () => {
    for (const file of [
      "src/components/IconButton.tsx",
      "src/components/IconButton.stories.tsx",
      "src/icons/Icon.tsx",
    ]) {
      expect(await iconRules(file), file).toEqual(atError(ICON_RULES));
    }
  });

  it("holds test/ and .storybook/ to no-raw-svg alone", async () => {
    for (const file of [
      "test/IconButton.test.tsx",
      "test/eslint-rules/icon-a11y.test.ts",
      ".storybook/decorators.tsx",
      ".storybook/__fixtures__/A11yGate.stories.tsx",
    ]) {
      expect(await iconRules(file), file).toEqual(atError(["candleviewer/no-raw-svg"]));
    }
  });

  it("lets src/icons/, the registry, draw the raw <svg> that no other src/ file may", async () => {
    const svg = 'export const Glyph = () => <svg viewBox="0 0 24 24" />;\n';
    const raw = async (file: string) => {
      const [result] = await eslint.lintText(svg, { filePath: path.join(UI, file) });
      return result?.messages.filter(({ ruleId }) => ruleId === "candleviewer/no-raw-svg");
    };
    expect(await raw("src/icons/IconSvg.tsx")).toEqual([]);
    expect(await raw("src/components/IconButton.tsx")).toEqual([
      expect.objectContaining({ message: expect.stringContaining("Raw <svg> in src/components/") }),
    ]);
  });
});
