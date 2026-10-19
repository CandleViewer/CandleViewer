// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { AXE_GATE_TAGS } from "../e2e/a11y/tags";

/**
 * #3700: the a11y gate's tagged axe scans must select every rule for a WCAG 2.2 AA criterion
 * (C-14.1). Without `wcag21a`, `label-content-name-mismatch` (SC 2.5.3 Label in Name) ran only in
 * the untagged scans. One constant feeds every tagged scan, and this file pins the constant.
 */
const E2E = resolve(import.meta.dirname, "../e2e");
const WCAG_A_AA = ["2", "21", "22"].flatMap((v) => [`wcag${v}a`, `wcag${v}aa`]);

interface AxeRule {
  readonly ruleId: string;
  readonly tags: readonly string[];
}
// axe-core comes with @axe-core/playwright (as in test/features/invites.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { getRules(): AxeRule[] };

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    if (e.isDirectory()) return sources(path);
    return /\.[cm]?[jt]sx?$/.test(e.name) ? [path] : [];
  });
}

describe("the a11y gate's axe tags (#3700)", () => {
  it("are levels A and AA of WCAG 2.0, 2.1 and 2.2", () => {
    expect([...AXE_GATE_TAGS].sort()).toEqual([...WCAG_A_AA].sort());
  });

  it("select every axe rule for a WCAG 2.x level A or AA criterion", () => {
    const wcag = axe
      .getRules()
      .filter(
        (r) => !r.tags.includes("experimental") && r.tags.some((t) => /^wcag2\d?a{1,2}$/.test(t)),
      );
    const missed = wcag.filter((r) => !r.tags.some((t) => AXE_GATE_TAGS.includes(t)));
    expect(missed.map((r) => r.ruleId)).toEqual([]);
    expect(wcag.map((r) => r.ruleId)).toContain("label-content-name-mismatch");
  });

  it("are what every tagged axe scan under e2e/ passes", () => {
    const calls = sources(E2E).flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(/\.withTags\(([^)]*)\)/g)].map((m) => ({
        file: relative(E2E, file),
        arg: m[1]?.trim(),
      })),
    );
    expect(calls.filter((c) => c.arg !== "[...AXE_GATE_TAGS]")).toEqual([]);
    // The exact sites. A scan that loses its tags also loses the rules axe runs only when a tag
    // selects them (target-size, aria-roledescription, audio-caption). Add any new tagged scan here.
    expect(calls.map((c) => c.file).sort()).toEqual([
      "a11y/axe.collect.ts",
      "e09-auth-a11y.spec.ts",
      "e09-auth-a11y.spec.ts",
    ]);
  });

  it("are spelled out nowhere else under e2e/", () => {
    const own = join(E2E, "a11y", "tags.ts");
    const spelled = sources(E2E).filter(
      (file) => file !== own && /["'`]wcag2\d?a{1,3}["'`]/.test(readFileSync(file, "utf8")),
    );
    expect(spelled.map((file) => relative(E2E, file))).toEqual([]);
  });
});
