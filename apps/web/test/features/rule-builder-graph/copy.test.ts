import { describe, expect, it } from "vitest";
import { copy, portLabel } from "../../../src/features/rule-builder-graph/a11y/copy.js";

describe("copy: the PROPOSED strings not covered through the modules", () => {
  it("announces an added or deleted node and a node's position", () => {
    expect(copy.nodeAdded("Alert")).toBe("Added Alert.");
    expect(copy.nodeDeleted("Alert")).toBe("Deleted Alert.");
    expect(copy.position(3, 7)).toBe("Node 3 of 7.");
  });

  it("reads a known port by its label and an unknown one as is", () => {
    expect(portLabel("right2")).toBe("input C");
    expect(portLabel("custom")).toBe("custom");
  });

  it("interpolates user text verbatim, as text", () => {
    expect(copy.connected("<b>x</b>", "y", "left")).toBe("Connected <b>x</b> output to y input A.");
  });
});
