import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  dropZones,
  layoutRects,
  leavesOf,
  move,
  neighbour,
  panelBoxes,
  relocate,
  resolveDirectionalMove,
  resolveDrop,
  tabify,
  type ChooserStep,
  type DockTree,
  type NodeId,
  type Zone,
} from "../src/index.js";
import { VIEWPORT, arbPresetTree, ctx, preset } from "./fixtures.js";

const STEPS: ChooserStep[] = ["left", "right", "up", "down", "next", "prev"];

/** The shortest chooser walk from `from` to `to` (breadth first over all six steps). */
function path(tree: DockTree, from: NodeId, to: NodeId): ChooserStep[] | null {
  const seen = new Map<NodeId, ChooserStep[]>([[from, []]]);
  const queue = [from];
  while (queue.length > 0) {
    const at = queue.shift() as NodeId;
    if (at === to) return seen.get(at) ?? null;
    for (const step of STEPS) {
      const next = neighbour(tree, VIEWPORT, at, step);
      if (next !== null && !seen.has(next)) {
        seen.set(next, [...(seen.get(at) ?? []), step]);
        queue.push(next);
      }
    }
  }
  return null;
}

/** Varied trees: presets with a tab group made in them. */
const arbTree = fc.tuple(arbPresetTree, fc.nat(), fc.nat()).map(([tree, a, b]) => {
  const leaves = leavesOf(tree.root);
  const from = leaves[a % leaves.length];
  const onto = leaves[b % leaves.length];
  return from && onto && from !== onto && leaves.length > 2
    ? tabify(tree, from.paneId, onto.paneId, ctx())
    : tree;
});

describe("keyboard move and pointer drop agree (Gherkin)", () => {
  it("for any pane and any zone of any target, both paths produce the identical tree", () => {
    fc.assert(
      fc.property(arbTree, fc.nat(), (tree, pick) => {
        const leaves = leavesOf(tree.root);
        const moving = leaves[pick % leaves.length];
        if (moving === undefined) return;
        const own = panelBoxes(tree).find((box) => leavesOf(box).includes(moving));
        for (const zone of dropZones(tree, VIEWPORT, moving.paneId)) {
          const centre = {
            x: zone.rect.x + zone.rect.width / 2,
            y: zone.rect.y + zone.rect.height / 2,
          };
          const pointer = resolveDrop(tree, VIEWPORT, moving.paneId, centre);
          const steps = path(tree, own?.id as NodeId, zone.targetId);
          expect(steps).not.toBeNull();
          const keyboard = resolveDirectionalMove(
            tree,
            VIEWPORT,
            moving.paneId,
            steps ?? [],
            zone.zone,
          );
          expect(pointer).toEqual({ targetId: zone.targetId, zone: zone.zone });
          expect(keyboard).toEqual(pointer);
          const viaPointer = relocate(
            tree,
            moving.paneId,
            pointer as NonNullable<typeof pointer>,
            ctx(),
          );
          const viaKeyboard = relocate(
            tree,
            moving.paneId,
            keyboard as NonNullable<typeof keyboard>,
            ctx(),
          );
          expect(viaKeyboard).toEqual(viaPointer);
        }
      }),
      { seed: 403, numRuns: 150 },
    );
  });
});

describe("drop zones (CMP-214 geometry)", () => {
  const grid = preset("2x2", ["a", "b", "c", "d"]);

  it("gives each other panel four edges and a centre, never its own box", () => {
    const zones = dropZones(grid, VIEWPORT, "a");
    expect(zones).toHaveLength(15);
    expect(zones.some((z) => z.targetId === "leaf-a")).toBe(false);
    const own = dropZones(tabify(grid, "a", "b", ctx()), VIEWPORT, "a");
    expect(own.filter((z) => z.zone === "centre")).toHaveLength(2);
  });

  it("bands are 25 % clamped to 48..160 px and a small box has no centre", () => {
    const right = dropZones(grid, VIEWPORT, "a").find(
      (z) => z.targetId === "leaf-b" && z.zone === "left",
    );
    expect(right?.rect.width).toBe(160);
    const small = dropZones(grid, { width: 150, height: 150 }, "a").filter(
      (z) => z.targetId === "leaf-d",
    );
    expect(small.map((z) => z.zone)).toEqual(["left", "right", "top", "bottom"]);
  });

  it("resolveDrop is null outside every zone; the chooser is null off an edge or on an absent zone", () => {
    expect(resolveDrop(grid, VIEWPORT, "a", { x: -5, y: 5 })).toBeNull();
    expect(resolveDirectionalMove(grid, VIEWPORT, "a", ["up"], "left")).toBeNull();
    expect(resolveDirectionalMove(grid, VIEWPORT, "a", ["up", "left"], "left")).toBeNull();
    expect(resolveDirectionalMove(grid, VIEWPORT, "zz", ["right"], "left")).toBeNull();
    expect(resolveDirectionalMove(grid, VIEWPORT, "a", [], "left")).toBeNull();
    expect(neighbour(grid, VIEWPORT, "nope", "right")).toBeNull();
    expect(resolveDirectionalMove(grid, VIEWPORT, "a", ["right"], "bottom")).toEqual({
      targetId: "leaf-b",
      zone: "bottom",
    });
  });

  it("relocate is move: the same leaf, and an unknown target is refused", () => {
    const zone: Zone = "centre";
    expect(relocate(grid, "a", { targetId: "leaf-d", zone }, ctx())).toEqual(
      move(grid, "a", "leaf-d", zone, ctx()),
    );
    expect(() => relocate(grid, "a", { targetId: "nope", zone }, ctx())).toThrow(/no node/);
  });

  it("layoutRects tiles the viewport", () => {
    const rects = layoutRects(grid, VIEWPORT);
    expect(rects.get("leaf-d")).toEqual({ x: 960, y: 540, width: 960, height: 540 });
  });
});
