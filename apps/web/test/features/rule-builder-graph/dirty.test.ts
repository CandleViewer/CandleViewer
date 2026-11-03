// @vitest-environment node
import type { GraphModel } from "@candleviewer/rule-graph";
import { describe, expect, it } from "vitest";
import { isDirty, markSaved } from "../../../src/features/rule-builder-graph/model/dirty.js";
import { edge, node } from "./fixtures.js";

const LOADED: GraphModel = {
  envelope: { name: "S-form", version: 3 },
  nodes: [
    node("n1", "trigger", { type: "on_bar_close" }),
    node("n2", "condition", { kind: "comparison", op: "gt" }),
    node("n3", "action", { type: "modify_stop_loss" }),
  ],
  edges: [edge("e1", "n2", "n3", "when")],
};

describe("unsaved changes: the graph against the one last saved", () => {
  const saved = markSaved(LOADED);

  it("is clean as loaded", () => {
    expect(isDirty(LOADED, saved)).toBe(false);
  });

  it("is clean for new lists of the very same nodes and edges, as an undo restores them", () => {
    const restored: GraphModel = { ...LOADED, nodes: [...LOADED.nodes], edges: [...LOADED.edges] };
    expect(isDirty(restored, saved)).toBe(false);
  });

  it("is dirty when an edge goes or comes", () => {
    expect(isDirty({ ...LOADED, edges: [] }, saved)).toBe(true);
    const more = [...LOADED.edges, edge("e2", "n2", "n3", "when")];
    expect(isDirty({ ...LOADED, edges: more }, saved)).toBe(true);
  });

  it("counts a node made anew as a change, though its content is the same", () => {
    const remade: GraphModel = { ...LOADED, nodes: LOADED.nodes.map((n) => ({ ...n })) };
    expect(isDirty(remade, saved)).toBe(true);
  });

  it("counts an envelope change as a change", () => {
    const renamed: GraphModel = { ...LOADED, envelope: { ...LOADED.envelope, name: "Other" } };
    expect(isDirty(renamed, saved)).toBe(true);
  });

  it("is clean against a mark taken after a save", () => {
    const edited: GraphModel = { ...LOADED, edges: [] };
    expect(isDirty(edited, markSaved(edited))).toBe(false);
    expect(isDirty(LOADED, markSaved(edited))).toBe(true);
  });
});
