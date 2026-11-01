import { describe, expect, it } from "vitest";
import { copy, listOf, portLabel } from "../../../src/features/rule-builder-graph/a11y/copy.js";

describe("copy: the PROPOSED strings not covered through the modules", () => {
  it("announces an added or deleted node and a node's position", () => {
    expect(copy.nodeAdded("Alert")).toBe("Added Alert, not connected.");
    expect(copy.nodeDeleted("Alert", 2)).toBe("Deleted Alert and 2 connections.");
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
    expect(copy.connected("<b>x</b>", "y", "left")).toBe("Connected <b>x</b> output to y input A.");
  });
});
