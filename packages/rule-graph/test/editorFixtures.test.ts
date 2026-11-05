// E37-S01: the rule-graph editor fixtures (packages/fixtures/golden/rule-graph/editor/, E37-D05
// hand-off §D) hold what the hand-off names them for, judged by this package's own analysis: the
// rules build an IR, and the invalid ones fail the way their frames draw.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, it } from "vitest";
import { toIr } from "../src/adapter/toIr.js";
import { findCycles } from "../src/analysis/cycles.js";
import { findDanglingPorts } from "../src/analysis/dangling.js";
import { findOrphans } from "../src/analysis/orphans.js";
import { canonicalise } from "../src/canonical/canonicalise.js";
import { isRuleGraphError } from "../src/errors.js";
import type { GraphLayout, GraphModel, GraphNode } from "../src/model.js";
import { PORT_COMPAT, type PortType, canConnect, portsOf } from "../src/ports.js";

type Connect = { source: string; sourcePort: string; target: string; targetPort: string };
type Fixture = { model: GraphModel; layout: GraphLayout; counterpart?: RuleIr; connect?: Connect };
const DIR = join(import.meta.dirname, "..", "..", "fixtures/golden/rule-graph/editor");
const read = (name: string) =>
  JSON.parse(readFileSync(join(DIR, `${name}.json`), "utf8")) as Fixture;
const byId = (model: GraphModel, id: string) =>
  model.nodes.find((node) => node.id === id) as GraphNode;
const RULES = {
  "s-form": 3,
  "s-graph": 5,
  "s-form-mismatch": 3,
  "review-60": 60,
  "tier-b-61": 61,
  "over-budget-121": 121,
  "budget-200": 200,
};

describe("the editor fixtures that are rules", () => {
  it.each(Object.entries(RULES))(
    "%s builds an IR, with no cycle, orphan or empty input",
    (name, count) => {
      const { model, layout } = read(name);
      expect(model.nodes).toHaveLength(count);
      expect([findCycles(model), findOrphans(model), findDanglingPorts(model)].flat()).toEqual([]);
      expect(() => toIr(model, layout)).not.toThrow();
    },
  );

  it("s-form-mismatch: the second IR differs from the graph's only in the action's ATR multiple", () => {
    const { model, layout, counterpart } = read("s-form-mismatch");
    const { ir } = toIr(model, layout);
    type Action = { node_id: string; params: Record<string, unknown> };
    // Both documents are this fixture's own rule IR: one action, read by its fields.
    const action = (doc: unknown) => (doc as { actions: Action[] }).actions[0] as Action;
    expect([action(ir).params["value"], action(counterpart).params["value"]]).toEqual([2, 2.5]);
    expect(action(counterpart).node_id).toBe("n3");
    const aligned = structuredClone(counterpart);
    action(aligned).params["value"] = 2;
    expect(canonicalise(aligned)).toBe(canonicalise(ir));
  });
});

describe("the editor fixtures that draw a refusal", () => {
  it("invalid-connect: the connect in flight joins a boolean output to a number input, which the matrix refuses", () => {
    const { model, connect } = read("invalid-connect");
    const { source, target, targetPort } = connect as Connect;
    const from = portsOf(byId(model, source)).output as PortType;
    const to = portsOf(byId(model, target)).inputs.find(([port]) => port === targetPort)?.[1];
    expect([from, to]).toEqual(["boolean", "number"]);
    expect(canConnect(from, to as PortType)).toEqual({
      ok: false,
      reason: PORT_COMPAT.boolean.number,
    });
  });

  it("cycle: the path n3 -> n4 -> n3, which toIr refuses", () => {
    const { model, layout } = read("cycle");
    expect(findCycles(model)).toEqual(["n3", "n4", "n3"]);
    let code = "";
    try {
      toIr(model, layout);
    } catch (error) {
      if (isRuleGraphError(error)) code = error.code;
    }
    expect(code).toBe("CYCLE_DETECTED");
  });

  it("orphan: n2 and n4 reach no action, and n3's when input is empty", () => {
    const { model } = read("orphan");
    expect(findOrphans(model)).toEqual(["n2", "n4"]);
    expect(findDanglingPorts(model).map((fault) => [fault.nodeId, fault.port])).toEqual([
      ["n3", "when"],
    ]);
  });
});
