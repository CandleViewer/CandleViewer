import { describe, expect, it } from "vitest";
import { RULE_IDS, validate } from "../src/index.js";
import { MATRIX } from "./matrix.js";

describe("validate: the rule matrix", () => {
  it.each(MATRIX.map((row) => [`${row.rule} — ${row.name}`, row] as const))("%s", (_, row) => {
    const result = validate(row.draft, row.ctx);
    const hits = result.failures.filter((f) => f.rule === row.rule);
    if (row.expect === "pass") {
      expect(hits).toEqual([]);
      return;
    }
    const [hit] = hits;
    expect(hit, JSON.stringify(result.failures)).toBeDefined();
    expect(hit?.field).toBe(row.expect.field);
    expect(hit?.params).toMatchObject(row.expect.params);
    expect(result.status).toBe("blocked");
  });

  it("matrix_coversEveryRule_bothWays", () => {
    const rules = new Set(MATRIX.map((row) => row.rule));
    for (const rule of rules) {
      const rows = MATRIX.filter((row) => row.rule === rule);
      const both = rows.some((r) => r.expect === "pass") && rows.some((r) => r.expect !== "pass");
      expect(both, rule).toBe(true);
    }
    expect([...rules].sort()).toEqual([...RULE_IDS].sort());
  });
});
