// Scenario: One projection serves every renderer (E11-S03, US-CHART-007 NFR). In-memory fixtures
// are linted against the package's REAL eslint.config.mjs, as c216-boundary.test.ts does, so no
// violating file is committed and the assertions follow any later edit of the config.
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint, Linter } from "eslint";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SLOW = 20_000;
const eslint = new ESLint({ cwd: PKG });

async function lint(path: string, code: string): Promise<string[]> {
  const config = (await eslint.calculateConfigForFile(path)) as { rules: Linter.RulesRecord };
  const rule = config.rules["no-restricted-syntax"] ?? "off";
  const flat = [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tseslint.parser },
      rules: { "no-restricted-syntax": rule },
    },
  ];
  return new Linter({ configType: "flat" })
    .verify(code, flat, path)
    .map((m) => `${path}:${m.line} ${m.message}`);
}

const PROJECTION =
  "US-CHART-007: arithmetic on priceLow/priceHigh outside src/viewport/transform.ts is a second " +
  "projection; map prices through the shared transform.";

describe("Scenario: One projection serves every renderer", () => {
  it.each([
    ["src/layers/candles.ts", "export const k = (p: P) =>\n  1 / (p.priceHigh - p.priceLow);"],
    ["src/gl/backend.ts", "export const y = (p: P, t: number) =>\n  t - p.priceLow;"],
    ["src/scene/drawing.ts", "export const s = (priceLow: number) =>\n  priceLow * 2;"],
    ["src/api/chart.ts", "export function f(p: P): void {\n  p.priceHigh += 1;\n}"],
    ["src/worker/runtime.ts", "export function f(p: P): void {\n  p.priceLow++;\n}"],
    ["bench/scenes/x.ts", "export const k = (p: P) =>\n  p.priceHigh ** 2;"],
    ["src/gl/shaders/x.ts", "export const k = (p: P) =>\n  p.priceHigh % 2;"],
  ])(
    "%s: arithmetic on the price window fails, naming the module and US-CHART-007",
    async (path, body) => {
      const code = `type P = { priceLow: number; priceHigh: number };\n${body}\n`;
      expect(await lint(path, code)).toEqual([`${path}:3 ${PROJECTION}`]);
    },
    SLOW,
  );

  it.each([
    // The worker's `viewport` message and the facade pass the window through; comparing is fine.
    [
      "src/worker/runtime.ts",
      "export const m = (p: P) => ({ priceLow: p.priceLow, high: p.priceHigh });",
    ],
    ["src/api/chart.ts", "export const ok = (m: P) => m.priceHigh > m.priceLow;"],
    [
      "src/api/chart.ts",
      "export const r = (m: P) => { const o = { low: 0 }; o.low = m.priceLow; return o; };",
    ],
    ["src/viewport/transform.ts", "export const k = (p: P) => -1 / (p.priceHigh - p.priceLow);"],
  ])(
    "%s: a pass-through, a comparison or the transform itself is not flagged",
    async (path, body) => {
      expect(
        await lint(path, `type P = { priceLow: number; priceHigh: number };\n${body}\n`),
      ).toEqual([]);
    },
    SLOW,
  );
});
