import type { RuleIr as GeneratedRuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { RuleGraphErrorCode, RuleIr } from "../src/index.js";

// The public entry is the package's contract: pin what it exports at runtime. The RuleIr and
// RuleGraphErrorCode types are erased, so only the values show.
describe("the public entry", () => {
  it("exports exactly the error contract, the canonical mirror and the graph adapter", async () => {
    expect(Object.keys(await import("../src/index.js")).sort()).toEqual([
      "RULE_GRAPH_ERROR_CODES",
      "RuleGraphError",
      "canonicalise",
      "compareWithServer",
      "hash",
      "isRuleGraphError",
      "nodesNeedingLayout",
      "readLayout",
      "toGraph",
      "toIr",
    ]);
  });

  // Erased at runtime, so `tsc` (typecheck) holds this one: test/ is in tsconfig's include.
  it("re-exports the generated RuleIr type and exactly the error code union", () => {
    expectTypeOf<RuleIr>().toEqualTypeOf<GeneratedRuleIr>();
    expectTypeOf<RuleGraphErrorCode>().toEqualTypeOf<
      | "CYCLE_DETECTED"
      | "DANGLING_PORT"
      | "ORPHAN_NODE"
      | "NOT_FORM_REPRESENTABLE"
      | "SCHEMA_VIOLATION"
      | "MULTIPLE_SINKS"
    >();
  });
});
