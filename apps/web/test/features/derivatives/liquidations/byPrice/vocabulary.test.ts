// E24-S07 (#782) slice 2, BQ 9 (ruled 6624627875): "Not available to rules" is true of this layer. No rule metric
// reads the by-price read (the rule vocabulary names none of it), this feature imports nothing of the rule engine,
// and every string keeps to K01 §6a: never "estimated liquidation levels", never "liquidation zones" without
// "recorded", never a predictive claim.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as copy from "../../../../../src/features/derivatives/liquidations/byPrice/copy";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../../../..");
const FEATURE = join(ROOT, "apps/web/src/features/derivatives/liquidations/byPrice");
const VOCABULARY = join(ROOT, "services/api/candleviewer/rules/vocabulary");

const strings = (): string[] =>
  Object.values(copy).flatMap((v) =>
    typeof v === "string"
      ? [v]
      : typeof v === "function" && v.length === 1
        ? [String((v as (a: string) => string)("09:14 UTC"))]
        : [],
  );

describe("the recorded layer is not available to rules", () => {
  it("is absent from the rule vocabulary", () => {
    const files = readdirSync(VOCABULARY).filter((f) => f.endsWith(".py"));
    expect(files.length).toBeGreaterThan(0);
    for (const f of files) {
      const text = readFileSync(join(VOCABULARY, f), "utf8");
      expect(text, f).not.toMatch(/by[-_]price|liq_by_price|getLiquidationsByPrice/i);
    }
  });

  it("imports nothing of the rule engine", () => {
    for (const f of readdirSync(FEATURE)) {
      const text = readFileSync(join(FEATURE, f), "utf8");
      expect(text, f).not.toMatch(/from\s+"[^"]*(rule-graph|rule-builder|rules)[^"]*"/);
    }
  });

  it("keeps to K01 §6a's permitted copy", () => {
    const all = strings();
    expect(all.length).toBeGreaterThan(10);
    for (const s of all) {
      expect(s).not.toMatch(/estimated liquidation level/i);
      expect(s.replace(/not a prediction/i, "")).not.toMatch(/predict/i);
      if (/liquidation zones?/i.test(s)) expect(s).toMatch(/recorded/i);
      if (/forecast/i.test(s)) expect(s).toMatch(/not a forecast/i);
    }
    expect(copy.K01_SENTENCE).toBe(
      "Histogram of recorded liquidations by price level. Not a prediction.",
    );
  });

  it("names the rules exclusion on the switch and the legend", () => {
    expect(copy.TOGGLE_LABEL).toContain("Not available to rules");
    expect(copy.NOT_FOR_RULES).toBe("Not available to rules");
  });
});
