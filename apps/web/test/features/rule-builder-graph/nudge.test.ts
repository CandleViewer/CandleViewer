import { describe, expect, it } from "vitest";
import {
  moveTo,
  nudge,
  settledNudge,
  NUDGE_LARGE_STEP,
  NUDGE_STEP,
  type Bounds,
} from "../../../src/features/rule-builder-graph/a11y/nudge.js";
import { rng } from "./fixtures.js";

const B: Bounds = { minX: 0, minY: 0, maxX: 1000, maxY: 600 };

describe("nudge: Gherkin 2, a discrete step per press, announced", () => {
  it("moves by the step, or the large step with Shift, in each direction", () => {
    expect(NUDGE_STEP).toBe(8);
    expect(NUDGE_LARGE_STEP).toBe(32);
    const from = { x: 240, y: 120 };
    expect(nudge("AND", from, "right", false, B)).toEqual({
      position: { x: 248, y: 120 },
      clamped: false,
      text: "Moved AND 8 right, now x 248, y 120.",
    });
    expect(nudge("AND", from, "left", true, B).position).toEqual({ x: 208, y: 120 });
    expect(nudge("AND", from, "up", false, B).position).toEqual({ x: 240, y: 112 });
    expect(nudge("AND", from, "down", true, B).position).toEqual({ x: 240, y: 152 });
  });

  it("stops at the canvas edge and says so", () => {
    expect(nudge("AND", { x: 4, y: 10 }, "left", false, B)).toEqual({
      position: { x: 0, y: 10 },
      clamped: true,
      text: "AND is at the edge of the canvas, x 0, y 10.",
    });
    expect(nudge("AND", { x: 1000, y: 600 }, "down", true, B).clamped).toBe(true);
  });

  it("brings an off-canvas, fractional or non-finite start back on the grid first", () => {
    expect(nudge("n", { x: -50, y: 3.6 }, "right", false, B).position).toEqual({ x: 8, y: 4 });
    expect(nudge("n", { x: Number.NaN, y: 0 }, "down", false, B).position).toEqual({ x: 0, y: 8 });
  });

  it("never yields a negative zero (code lens L2)", () => {
    const below = { minX: -10, minY: -10, maxX: 10, maxY: 10 };
    const { position } = moveTo("n", { x: -0.4, y: -0.2 }, below);
    expect(Object.is(position.x, 0) && Object.is(position.y, 0)).toBe(true);
  });

  it("tolerates inverted bounds", () => {
    const inverted = { minX: 100, minY: 100, maxX: 0, maxY: 0 };
    expect(nudge("n", { x: 50, y: 50 }, "right", true, inverted).position).toEqual({
      x: 82,
      y: 50,
    });
  });

  it("property: every result is a whole number inside the bounds", () => {
    const rand = rng(257);
    const dirs = ["left", "right", "up", "down"] as const;
    for (let i = 0; i < 2000; i += 1) {
      const from = { x: (rand() - 0.25) * 1400, y: (rand() - 0.25) * 900 };
      const dir = dirs[Math.floor(rand() * 4)] as (typeof dirs)[number];
      const { position } = nudge("n", from, dir, rand() < 0.5, B);
      expect(Number.isInteger(position.x) && Number.isInteger(position.y)).toBe(true);
      expect(position.x >= B.minX && position.x <= B.maxX).toBe(true);
      expect(position.y >= B.minY && position.y <= B.maxY).toBe(true);
    }
  });
});

describe("moveTo: the Move node... menu path", () => {
  it("moves to an exact position and announces it", () => {
    expect(moveTo("AND", { x: 300, y: 200 }, B)).toEqual({
      position: { x: 300, y: 200 },
      clamped: false,
      text: "Moved AND to x 300, y 200.",
    });
  });

  it("clamps and rounds a typed position", () => {
    expect(moveTo("AND", { x: 2000, y: 10.4 }, B)).toEqual({
      position: { x: 1000, y: 10 },
      clamped: true,
      text: "AND is at the edge of the canvas, x 1000, y 10.",
    });
  });
});

describe("settledNudge: one announcement per settled burst (a11y lens A-5)", () => {
  const burst = (
    dirs: readonly ("left" | "right" | "up" | "down")[],
    from = { x: 240, y: 120 },
  ) => {
    let at = from;
    let last = nudge("AND", at, dirs[0] ?? "right", false, B);
    for (const dir of dirs) {
      last = nudge("AND", at, dir, false, B);
      at = last.position;
    }
    return settledNudge("AND", from, last, B);
  };

  it("sums a held key's repeats into one sentence", () => {
    expect(burst(["right", "right", "right", "right", "right"])).toBe(
      "Moved AND 40 right, now x 280, y 120.",
    );
  });

  it("names both axes, and where it stopped at the edge", () => {
    expect(burst(["right", "down"])).toBe("Moved AND 8 right and 8 down, now x 248, y 128.");
    expect(burst(["left", "left"], { x: 10, y: 50 })).toBe(
      "Moved AND 10 left, now x 0, y 50. Stopped at the edge of the canvas.",
    );
  });

  it("says where the node is when the burst cancels out or never moved", () => {
    expect(burst(["right", "left"])).toBe("Moved AND to x 240, y 120.");
    expect(burst(["left"], { x: 0, y: 50 })).toBe("AND is at the edge of the canvas, x 0, y 50.");
  });
});
