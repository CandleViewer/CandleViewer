// @vitest-environment node
import type { GraphLayout, GraphModel } from "@candleviewer/rule-graph";
import { describe, expect, it } from "vitest";
import {
  CANVAS_LIMIT,
  normaliseLayout,
  pointOf,
} from "../../../src/features/rule-builder-graph/model/layout.js";
import { placeNodes } from "../../../src/features/rule-builder-graph/model/placement.js";
import { node } from "./fixtures.js";

const GRAPH: GraphModel = {
  envelope: {},
  nodes: [
    node("t", "trigger"),
    node("c", "condition", { kind: "comparison" }),
    node("a", "action"),
  ],
  edges: [],
};
/** A layout as stored: whatever its writer sent, so the type does not hold for it. */
const stored = (positions: unknown, collapsed: unknown = []): GraphLayout =>
  ({ positions, collapsed, comments: [], extra: {} }) as unknown as GraphLayout;

describe("normalising a stored layout at load (SR-E37-04, #1073's threat model §9)", () => {
  it.each([
    ["null", null],
    ["a string", "12,40"],
    ["a string coordinate", { x: "12", y: 40 }],
    ["a missing coordinate", { x: 12 }],
    ["NaN", { x: Number.NaN, y: 0 }],
    ["an infinity", { x: 0, y: Number.NEGATIVE_INFINITY }],
    ["a list", [12, 40]],
  ])("leaves a node whose stored position is %s unplaced", (_, value) => {
    expect(normaliseLayout(GRAPH, stored({ c: value })).positions).toEqual({});
  });

  it.each([1e19, -1e19, 2 ** 61, -(2 ** 61)])("clamps a stored %d to the canvas bound", (v) => {
    const bound = Math.sign(v) * CANVAS_LIMIT;
    expect(normaliseLayout(GRAPH, stored({ c: { x: v, y: -v } })).positions).toEqual({
      c: { x: bound, y: -bound },
    });
  });

  it("keeps a usable position as a fresh object, and drops one naming no node", () => {
    const at = { x: 240, y: -480 };
    const { positions } = normaliseLayout(GRAPH, stored({ c: at, gone: { x: 0, y: 0 } }));
    expect(positions).toEqual({ c: { x: 240, y: -480 } });
    expect(positions["c"]).not.toBe(at);
  });

  it("keeps only the collapsed entries that are string ids naming a node", () => {
    const collapsed = ["c", "gone", 7, null, { id: "a" }, "a"];
    expect(normaliseLayout(GRAPH, stored({}, collapsed)).collapsed).toEqual(["c", "a"]);
  });

  it("reads positions or a collapsed list that are no object or list as empty", () => {
    expect(normaliseLayout(GRAPH, stored(null, "c"))).toMatchObject({
      positions: {},
      collapsed: [],
    });
  });

  it("lets placement place every node whose stored position it drops", () => {
    const raw = stored({ t: null, c: "x", a: { x: 1e19, y: 0 } });
    expect(placeNodes(GRAPH, normaliseLayout(GRAPH, raw)).positions).toEqual({
      t: { x: 0, y: 0 },
      c: { x: 240, y: 0 },
      a: { x: CANVAS_LIMIT, y: 0 },
    });
  });

  it("gives a move or a drop the same check: a finite point clamped, anything else none", () => {
    expect(pointOf({ x: 1e308, y: -0 })).toEqual({ x: CANVAS_LIMIT, y: 0 });
    expect(Object.is(pointOf({ x: 1, y: -0 })?.y, 0)).toBe(true);
    expect([pointOf(undefined), pointOf({ x: 1, y: "2" }), pointOf(7)]).toEqual([
      undefined,
      undefined,
      undefined,
    ]);
  });
});
