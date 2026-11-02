import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  close,
  isDockError,
  layoutRects,
  leavesOf,
  move,
  panelBoxes,
  resize,
  separatorId,
  split,
  toLayoutInput,
  type DockErrorCode,
  type DockNode,
  type DockTree,
  type OpContext,
  type Zone,
} from "../src/index.js";
import { VIEWPORT, ctx, invariantViolations, leaf, paneIds, preset } from "./fixtures.js";

type Command =
  | { op: "split"; target: number; side: number }
  | { op: "move"; pane: number; target: number; zone: number }
  | { op: "close"; pane: number }
  | { op: "resize"; split: number; at: number; delta: number };

const ZONES: Zone[] = ["left", "right", "top", "bottom", "centre"];

const arbCommand: fc.Arbitrary<Command> = fc.oneof(
  fc.record({ op: fc.constant("split" as const), target: fc.nat(), side: fc.nat(3) }),
  fc.record({
    op: fc.constant("move" as const),
    pane: fc.nat(),
    target: fc.nat(),
    zone: fc.nat(4),
  }),
  fc.record({ op: fc.constant("close" as const), pane: fc.nat() }),
  fc.record({
    op: fc.constant("resize" as const),
    split: fc.nat(),
    at: fc.nat(),
    delta: fc.double({ min: -1, max: 1, noNaN: true }),
  }),
);

function splits(node: DockNode | null): DockNode[] {
  if (node === null || (node.type !== "row" && node.type !== "column")) return [];
  return [node, ...node.children.flatMap(splits)];
}

/**
 * The refusals a valid command may meet: a cap, or an operation that cannot apply (a split below
 * the minimums). Every target is picked from the tree, so any other `DockError` is a bug.
 */
const EXPECTED: ReadonlySet<DockErrorCode> = new Set([
  "tree_too_deep",
  "tree_too_large",
  "invalid_operation",
]);

/** Applies one command; an expected refusal leaves the tree as it was. */
function apply(tree: DockTree, command: Command, serial: number, c: OpContext): DockTree {
  const leaves = leavesOf(tree.root);
  const pick = <T>(xs: readonly T[], i: number): T | undefined => xs[i % Math.max(xs.length, 1)];
  try {
    switch (command.op) {
      case "split": {
        const target = pick(panelBoxes(tree), command.target);
        const side = ZONES[command.side] as "left";
        return target === undefined ? tree : split(tree, target.id, side, leaf(`s${serial}`), c);
      }
      case "move": {
        const pane = pick(leaves, command.pane);
        const target = pick(panelBoxes(tree), command.target);
        if (pane === undefined || target === undefined) return tree;
        return move(tree, pane.paneId, target.id, ZONES[command.zone] as Zone, c);
      }
      case "close": {
        const pane = pick(leaves, command.pane);
        return pane === undefined ? tree : close(tree, pane.paneId, c);
      }
      case "resize": {
        const node = pick(splits(tree.root), command.split);
        if (node === undefined || node.type === "leaf" || node.type === "tabset") return tree;
        const at = command.at % (node.children.length - 1);
        return resize(tree, separatorId(node.id, at), command.delta, c);
      }
    }
  } catch (error) {
    if (isDockError(error) && EXPECTED.has(error.code)) return tree;
    throw error;
  }
}

function belowMinimum(tree: DockTree): string[] {
  const rects = layoutRects(tree, VIEWPORT);
  return leavesOf(tree.root)
    .filter((l) => {
      const r = rects.get(l.id);
      return r === undefined || r.width < l.minWidth - 1e-6 || r.height < l.minHeight - 1e-6;
    })
    .map((l) => l.paneId);
}

describe("every operation returns a normalised tree (property)", () => {
  // 10 × 1,000 operations took 5.5 s under coverage on a loaded CI runner (the 5 s default timed
  // out): a 60 s bound keeps the assertions while the runner's load varies.
  it(
    "1000 random split/move/close/resize operations keep every invariant",
    { timeout: 60_000 },
    () => {
      let emptied = 0;
      fc.assert(
        fc.property(fc.array(arbCommand, { minLength: 1000, maxLength: 1000 }), (commands) => {
          // One minter per run, as in the app: node ids stay unique across operations.
          const c = ctx();
          let tree = preset("2x2", ["a", "b", "c", "d"]);
          commands.forEach((command, serial) => {
            const before = new Map(leavesOf(tree.root).map((l) => [l.paneId, l]));
            const next = apply(tree, command, serial, c);
            expect(invariantViolations(next)).toEqual([]);
            expect(belowMinimum(next)).toEqual([]);
            // Exactly one pane is added by an applied split and removed by an applied close; every
            // other pane survives with its leaf object (a move is a re-parent, never a new panel),
            // and a resize keeps every container id.
            const after = paneIds(next);
            const kept = after.filter((id) => before.has(id));
            expect(kept.length).toBe(
              after.length - (command.op === "split" && next !== tree ? 1 : 0),
            );
            if (command.op === "close" && next !== tree) expect(kept.length).toBe(before.size - 1);
            else expect(kept.length).toBe(before.size);
            for (const l of leavesOf(next.root))
              if (before.has(l.paneId)) expect(l).toBe(before.get(l.paneId));
            if (command.op === "resize")
              expect(splits(next.root).map((n) => n.id)).toEqual(
                splits(tree.root).map((n) => n.id),
              );
            if (next.root === null) {
              // The last docked pane closed: the empty dock stores, and the run starts over.
              expect(toLayoutInput(next, new Map()).panes).toEqual([]);
              emptied += 1;
              tree = preset("2x2", [`a${serial}`, `b${serial}`, `c${serial}`, `d${serial}`]);
            } else tree = next;
          });
        }),
        // 10 runs of 1000 operations each; a failure reports unshrunk (shrinking 1000-long runs takes
        // minutes): the shrinking test below holds the shrinker itself.
        { numRuns: 10, seed: 403, endOnFailure: true },
      );
      // The walk does reach the empty dock (50 times at seed 403), so its stored form is exercised.
      expect(emptied).toBeGreaterThan(0);
    },
  );

  it("reports a violating sequence minimally (shrinking)", () => {
    // A deliberately false property, "never more than 3 panes": from one pane the shortest
    // counterexample is three splits, and the shrunk report must be exactly that.
    const result = fc.check(
      fc.property(fc.array(arbCommand, { maxLength: 60 }), (commands) => {
        const c = ctx();
        let tree = preset("1x1", ["a"]);
        commands.forEach((command, serial) => {
          tree = apply(tree, command, serial, c);
        });
        return leavesOf(tree.root).length <= 3;
      }),
      { seed: 403, numRuns: 500 },
    );
    expect(result.failed).toBe(true);
    const [commands] = result.counterexample ?? [[]];
    expect(commands.map((c: Command) => c.op)).toEqual(["split", "split", "split"]);
  });
});
