import type { RuleIr as GeneratedRuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, expectTypeOf, it } from "vitest";
import type * as Api from "../src/index.js";
import type { RuleGraphErrorCode, RuleIr } from "../src/index.js";

// The public entry is the package's contract: pin what it exports at runtime. The RuleIr and
// RuleGraphErrorCode types are erased, so only the values show.
describe("the public entry", () => {
  it("exports exactly the error contract, mirror, adapter, ports and analysis", async () => {
    expect(Object.keys(await import("../src/index.js")).sort()).toEqual([
      "NODE_PORTS",
      "PORT_COMPAT",
      "PORT_TYPES",
      "RULE_GRAPH_ERROR_CODES",
      "RuleGraphError",
      "canConnect",
      "canonicalise",
      "compareWithServer",
      "findCycles",
      "findDanglingPorts",
      "findOrphans",
      "hash",
      "isFormRepresentable",
      "isRuleGraphError",
      "nodesNeedingLayout",
      "portTypeOfMetric",
      "portsOf",
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

  it("re-exports the port types, each by its name", () => {
    type Named = [
      Api.Connect,
      Api.DanglingPort,
      Api.FormReason,
      Api.MetricUnit,
      Api.MetricValueType,
      Api.NodeKind,
    ];
    expectTypeOf<Api.PortType>().toEqualTypeOf<
      "boolean" | "number" | "price" | "side" | "action" | "trigger"
    >();
    expectTypeOf<Named>().not.toBeAny();
    expectTypeOf<Api.NodePorts["kind"]>().toEqualTypeOf<Api.NodeKind>();
  });
});
