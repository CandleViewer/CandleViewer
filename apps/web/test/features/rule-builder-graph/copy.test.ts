import { describe, expect, it } from "vitest";
import { copy, listOf, portLabel } from "../../../src/features/rule-builder-graph/a11y/copy.js";

describe("copy: E37-D02's strings verbatim (E47-S03 BQ-11 as ruled)", () => {
  it("announces an added or deleted node in D02's words (O1 :288, §7 :278, O4 :291)", () => {
    expect(copy.nodeAdded("Alert")).toBe("Added Alert — not connected");
    expect(copy.nodeAddedAfter("Alert", "AND")).toBe("Added Alert after AND");
    expect(copy.nodeDeleted("Alert", 2)).toBe("Deleted Alert and 2 connections");
  });

  it("names a port and a connect in D02's words (§14 :392, §6 P2 :210, P12 :220, §13 :368)", () => {
    expect(copy.port(false, "boolean", [])).toBe("Input port, boolean, not connected");
    expect(copy.port(true, "number", ["A", "B"])).toBe("Output port, number, connected to A and B");
    expect(copy.port(false, "boolean", []) + copy.canConnect()).toBe(
      "Input port, boolean, not connected — can connect",
    );
    expect(copy.connectStarted("boolean")).toBe(
      "Connecting from output port, boolean — choose an input",
    );
    expect(copy.cancelled()).toBe("Cancelled");
  });
});

describe("copy: the PROPOSED strings not covered through the modules", () => {
  it("announces a node's position", () => {
    expect(copy.position(3, 7)).toBe("Node 3 of 7.");
  });

  it("joins names as a list", () => {
    expect([listOf([]), listOf(["A"]), listOf(["A", "B"]), listOf(["A", "B", "C"])]).toEqual([
      "",
      "A",
      "A and B",
      "A, B and C",
    ]);
  });

  it("reads a known port by its label and an unknown one as is", () => {
    expect(portLabel("right2")).toBe("input C");
    expect(portLabel("custom")).toBe("custom");
  });

  it("interpolates user text verbatim, as text", () => {
    expect(copy.connected("<b>x</b>", "y", 1)).toBe("connected <b>x</b> output to y input 1");
  });
});
