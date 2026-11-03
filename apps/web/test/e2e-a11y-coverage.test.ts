// @vitest-environment node
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { describe, expect, it } from "vitest";
import { loadCases, renderCoverage } from "../e2e/a11y-nav/coverage";
import { PROBES } from "../e2e/a11y-nav/probes";

/** E47-Q03 BQ-05/BQ-10: the 36-case map agrees with the plan, the README table and the probes. */
const PLAN = readFileSync(
  new URL("../../../qa/plans/e47-accessibility-test-plan.md", import.meta.url),
  "utf8",
);
const README = readFileSync(new URL("../e2e/a11y-nav/README.md", import.meta.url), "utf8");
const cases = loadCases();

const planIds = [...PLAN.matchAll(/^\| E47-TC-(\d+) .*\| (Q03[^|]*) \|$/gm)].map((m) =>
  Number(m[1]),
);

describe("the Q03 coverage map", () => {
  it("holds exactly the plan's Q03-tagged cases, with 110, 115, 118 and 306 manual", () => {
    expect(planIds).toHaveLength(36);
    expect(cases.map((c) => c.id)).toEqual([...planIds].sort((a, b) => a - b));
    for (const manual of [110, 115, 118, 306]) expect(planIds).not.toContain(manual);
  });

  it("is rendered verbatim as the README table", () => {
    // Prettier pads the table's cells, so compare with runs of spaces and dashes collapsed.
    const flat = (t: string): string[] =>
      t.split("\n").map((l) =>
        l
          .replace(/-{3,}/g, "---")
          .replace(/\s*\|\s*/g, "|")
          .replace(/\s+/g, " ")
          .trim(),
      );
    const readme = flat(README);
    for (const row of flat(renderCoverage(cases))) expect(readme).toContain(row);
  });

  it("names a remediation ticket for every expected-fail case, matched by one probe", () => {
    for (const c of cases.filter((x) => x.status === "expected-fail")) {
      const probes = PROBES.filter((p) => p.cases.includes(c.id));
      expect(probes, `E47-TC-${c.id}`).toHaveLength(1);
      expect(probes[0]?.ticket).toBe(c.where);
    }
    for (const p of PROBES)
      for (const id of p.cases)
        expect(cases.find((c) => c.id === id)?.status, `E47-TC-${id}`).toBe("expected-fail");
  });

  it("never drives Ctrl+Tab and has no F6 probe", () => {
    const keys = PROBES.flatMap((p) => p.keys ?? []);
    expect(keys.filter((k) => /Control\+Tab|^F6$/.test(k))).toEqual([]);
  });

  it("finds every surface by role plus accessible name, never CSS or a test id", () => {
    for (const p of PROBES) {
      const calls: unknown[][] = [];
      const page = new Proxy(
        {},
        {
          get: (_t, member) => {
            if (member !== "getByRole") throw new Error(`${String(member)} is not a role selector`);
            return (...args: unknown[]) => (calls.push(args), {});
          },
        },
      );
      p.find(page as Page);
      expect(calls, `E47-TC-${p.cases.join("/")}`).toHaveLength(1);
      expect(typeof calls[0]?.[0]).toBe("string");
      expect(calls[0]?.[1], `E47-TC-${p.cases.join("/")}: a name option`).toHaveProperty("name");
    }
  });
});
