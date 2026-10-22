import { describe, expect, it } from "vitest";
import { RULE_GRAPH_ERROR_CODES, RuleGraphError, isRuleGraphError } from "../src/errors.js";

// E37-T01 Observability: the codes below are what the editor UI and telemetry classify failures
// on, so the list and its order are part of the package contract.

describe("RULE_GRAPH_ERROR_CODES", () => {
  it("lists exactly the five stable codes, in order", () => {
    expect([...RULE_GRAPH_ERROR_CODES]).toEqual([
      "CYCLE_DETECTED",
      "DANGLING_PORT",
      "ORPHAN_NODE",
      "NOT_FORM_REPRESENTABLE",
      "SCHEMA_VIOLATION",
    ]);
  });

  it("is frozen, so a consumer cannot add or reorder a code", () => {
    expect(Object.isFrozen(RULE_GRAPH_ERROR_CODES)).toBe(true);
  });
});

describe("RuleGraphError", () => {
  it("carries its code, message and node ids", () => {
    const error = new RuleGraphError("CYCLE_DETECTED", "a feeds b feeds a", ["a", "b"]);
    expect(error.code).toBe("CYCLE_DETECTED");
    expect(error.message).toBe("a feeds b feeds a");
    expect(error.nodeIds).toEqual(["a", "b"]);
  });

  it("is an Error and a RuleGraphError named RuleGraphError", () => {
    const error = new RuleGraphError("SCHEMA_VIOLATION", "unknown key");
    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(RuleGraphError);
    expect(error.name).toBe("RuleGraphError");
  });

  it("keeps its own frozen copy of the node ids", () => {
    const ids = ["n1", "n2"];
    const error = new RuleGraphError("ORPHAN_NODE", "reaches no action", ids);
    ids.push("n3");
    expect(error.nodeIds).toEqual(["n1", "n2"]);
    expect(Object.isFrozen(error.nodeIds)).toBe(true);
  });

  it("defaults the node ids to an empty list", () => {
    const error = new RuleGraphError("NOT_FORM_REPRESENTABLE", "nested arithmetic");
    expect(error.nodeIds).toEqual([]);
    expect(Object.isFrozen(error.nodeIds)).toBe(true);
  });
});

describe("isRuleGraphError", () => {
  it("is true for a RuleGraphError", () => {
    expect(isRuleGraphError(new RuleGraphError("DANGLING_PORT", "input unconnected", ["c1"]))).toBe(
      true,
    );
  });

  it("is false for a plain Error that merely has a code property", () => {
    const lookalike = Object.assign(new Error("boom"), { code: "CYCLE_DETECTED" });
    expect(isRuleGraphError(lookalike)).toBe(false);
  });

  it("is false for an object literal shaped like a RuleGraphError", () => {
    const literal = { name: "RuleGraphError", code: "CYCLE_DETECTED", message: "x", nodeIds: [] };
    expect(isRuleGraphError(literal)).toBe(false);
  });

  it("is false for null", () => {
    expect(isRuleGraphError(null)).toBe(false);
  });
});
