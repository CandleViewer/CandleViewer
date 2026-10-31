// @vitest-environment node
// E47-S05 (#1319), WCAG 2.5.8: the base stylesheet keeps bare controls at the minimum target, and the
// floor cannot silently weaken: it is zero-specificity (components win), uses the token and excludes
// only the controls it must (hidden, range, the visually hidden clip).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(import.meta.dirname, "../../src/theme/theme.css"), "utf-8");
const floor = css.slice(css.indexOf("/*\n * Target-size floor"));

describe("theme.css target-size floor", () => {
  it("floors buttons, selects, text inputs and summaries with the min-target token", () => {
    const rule =
      /:where\(([^)]*\([^)]*\)[^)]*|[^)]*)\)\s*:not\(\.cv-visually-hidden\)\s*\{([^}]*)\}/u.exec(
        floor,
      );
    expect(rule?.[1]).toMatch(/\bbutton\b/u);
    expect(rule?.[1]).toMatch(/\bselect\b/u);
    expect(rule?.[1]).toMatch(/\bsummary\b/u);
    expect(rule?.[1]).toMatch(/input:not\(/u);
    expect(rule?.[2]).toContain("min-block-size: var(--size-target-min)");
  });

  it("grows native checkboxes and radios in both axes, so the control is its own 24 px target", () => {
    const rule = /:where\(input\[type="checkbox"\], input\[type="radio"\]\)[^{]*\{([^}]*)\}/u.exec(
      floor,
    );
    expect(rule?.[1]).toContain("min-inline-size: var(--size-target-min)");
    expect(rule?.[1]).toContain("min-block-size: var(--size-target-min)");
  });

  it("never names a pixel size in a declaration: the token owns it", () => {
    const rules = floor.replace(/\/\*[\s\S]*?\*\//gu, "");
    const end = rules.indexOf("/*") === -1 ? rules.length : rules.indexOf("/*");
    expect(rules.slice(0, end).match(/\b\d+px\b/gu) ?? []).toEqual([]);
  });
});
