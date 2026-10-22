import { describe, expect, it } from "vitest";

// The public entry is the package's contract: pin what it exports at runtime. The RuleIr and
// RuleGraphErrorCode types are erased, so only the values show.
describe("the public entry", () => {
  it("exports exactly the error contract", async () => {
    expect(Object.keys(await import("../src/index.js")).sort()).toEqual([
      "RULE_GRAPH_ERROR_CODES",
      "RuleGraphError",
      "isRuleGraphError",
    ]);
  });
});
