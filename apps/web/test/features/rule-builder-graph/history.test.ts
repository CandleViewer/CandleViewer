// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  editorStateOf,
  type EditorState,
  type GraphCommand,
  type NodeSpec,
  type SelectMode,
} from "../../../src/features/rule-builder-graph/model/commands.js";
import { isDirty, markSaved } from "../../../src/features/rule-builder-graph/model/dirty.js";
import {
  canRedo,
  canUndo,
  dispatch,
  HISTORY_DEPTH,
  historyOf,
  invert,
  redo,
  undo,
  type History,
} from "../../../src/features/rule-builder-graph/model/history.js";
import { portOracle } from "../../../src/features/rule-builder-graph/model/portOracle.js";
import { edge, node, randomGraph, rng } from "./fixtures.js";

const SPECS: readonly NodeSpec[] = [
  { type: "trigger", data: { type: "on_bar_close" } },
  { type: "condition", data: { kind: "comparison", op: "gt" } },
  { type: "condition", data: { kind: "arithmetic", op: "add" } },
  { type: "condition", data: { kind: "temporal", op: "sustained_for" } },
  { type: "logicGate", data: { op: "any_of" } },
  { type: "action", data: { type: "flatten_position" } },
  { type: "comment", data: { text: "why" } },
];
const PORTS = ["in", "left", "right", "child", "when", "out"];
const MODES: readonly SelectMode[] = ["replace", "add", "toggle"];

const run = (history: History, commands: readonly GraphCommand[]): History =>
  commands.reduce((h, command) => dispatch(h, command).history, history);

/** Any command at all against `state`: unknown ids, refused pairs and empty deletes included. */
function randomCommand(rand: () => number, state: EditorState): GraphCommand {
  const pick = <T>(items: readonly T[], fallback: T): T =>
    items[Math.floor(rand() * items.length)] ?? fallback;
  const nodeIds = state.graph.nodes.map((n) => n.id);
  const edgeIds = state.graph.edges.map((e) => e.id);
  const some = (ids: readonly string[]) => ids.filter(() => rand() < 0.3);
  const point = () => ({ x: Math.floor(rand() * 9) * 120, y: Math.floor(rand() * 9) * 120 });
  switch (Math.floor(rand() * 8)) {
    case 0:
      return { type: "addNode", node: pick(SPECS, SPECS[1] as NodeSpec), position: point() };
    case 1:
      return { type: "addNode", node: pick(SPECS, SPECS[1] as NodeSpec) };
    case 2:
    case 3: {
      const target = pick(nodeIds, "x");
      const into = state.graph.nodes.find((n) => n.id === target);
      const ports = into === undefined ? PORTS : portOracle.inputsOf(into).map(([p]) => p);
      return {
        type: "connect",
        source: pick(nodeIds, "x"),
        sourcePort: rand() < 0.9 ? "out" : "in",
        target,
        targetPort: pick(ports, "in"),
      };
    }
    case 4:
      return { type: "disconnect", edge: pick(edgeIds, "e0") };
    case 5:
      return { type: "delete", nodes: some(nodeIds), edges: some(edgeIds) };
    case 6:
      return {
        type: "move",
        moves: [{ id: pick(nodeIds, "x"), position: point() }],
        ...(rand() < 0.5 ? { gesture: `g${Math.floor(rand() * 2)}` } : {}),
      };
    default:
      return {
        type: "select",
        nodes: some(nodeIds),
        edges: some(edgeIds),
        mode: pick(MODES, "add"),
      };
  }
}

const S_FORM = editorStateOf({
  envelope: { name: "S-form" },
  nodes: [
    node("n1", "trigger", { type: "on_bar_close" }),
    node("n2", "condition", { kind: "comparison", op: "gt" }),
    node("n3", "action", { type: "modify_stop_loss" }),
  ],
  edges: [edge("e1", "n2", "n3", "when")],
});

describe("the undo stack: a seeded sweep over any command sequence", () => {
  it(
    "undoes every edit back to the start, and redoes them all to the end",
    { timeout: 60_000 },
    () => {
      for (let seed = 1; seed <= 150; seed += 1) {
        const rand = rng(seed);
        const start = editorStateOf({ envelope: {}, ...randomGraph(rand, 8) });
        let history = historyOf(start);
        for (let i = 0; i < 25; i += 1)
          history = dispatch(history, randomCommand(rand, history.state)).history;
        const end = history.state;
        expect(history.past.length, `seed ${seed}`).toBeLessThanOrEqual(25);
        while (canUndo(history)) history = undo(history).history;
        expect(history.state.graph, `seed ${seed}`).toEqual(start.graph);
        expect(history.state.layout.positions, `seed ${seed}`).toEqual(start.layout.positions);
        // The very node and edge objects come back, so the start counts as unchanged.
        expect(isDirty(history.state.graph, markSaved(start.graph)), `seed ${seed}`).toBe(false);
        while (canRedo(history)) history = redo(history).history;
        expect(history.state.graph, `seed ${seed}`).toEqual(end.graph);
        expect(history.state.layout.positions, `seed ${seed}`).toEqual(end.layout.positions);
        expect(isDirty(history.state.graph, markSaved(end.graph)), `seed ${seed}`).toBe(false);
      }
    },
  );

  it("inverts any op list exactly: the inverse of the inverse is the list", () => {
    const rand = rng(7);
    let history = historyOf(S_FORM);
    for (let i = 0; i < 60; i += 1)
      history = dispatch(history, randomCommand(rand, history.state)).history;
    for (const entry of history.past) expect(invert(invert(entry.ops))).toEqual(entry.ops);
  });
});

describe("one entry per operation", () => {
  it("records an insert that also connects as one entry, and one undo removes both halves", () => {
    const selected = dispatch(historyOf(S_FORM), {
      type: "select",
      nodes: ["n2"],
      edges: [],
      mode: "replace",
    }).history;
    const { history, effect } = dispatch(selected, {
      type: "addNode",
      node: { type: "action", data: { type: "flatten_position" } },
    });
    expect(effect).toEqual({ kind: "added", node: "n4", edge: "e2" });
    expect(history.past).toHaveLength(1);
    const back = undo(history);
    expect(back.entry?.kind).toBe("addNode");
    expect(back.history.state.graph).toEqual(S_FORM.graph);
    expect(back.history.state.selection).toEqual({ nodes: ["n2"], edges: [] });
  });

  it("folds the moves of one drag into one entry, and its undo returns to where the drag began", () => {
    const drag = (x: number, gesture = "drag-1"): GraphCommand => ({
      type: "move",
      moves: [{ id: "n2", position: { x, y: 0 } }],
      gesture,
    });
    const dragged = run(historyOf(S_FORM), [drag(250), drag(260), drag(300)]);
    expect(dragged.past).toHaveLength(1);
    expect(dragged.past[0]?.ops).toEqual([
      { op: "position", id: "n2", from: { x: 240, y: 0 }, to: { x: 300, y: 0 } },
    ]);
    const next = run(dragged, [drag(400, "drag-2")]);
    expect(next.past).toHaveLength(2);
    const back = undo(undo(next).history).history;
    expect(back.state.layout.positions["n2"]).toEqual({ x: 240, y: 0 });
  });

  it("keeps no entry for a drag that ends where it began", () => {
    const drag = (x: number): GraphCommand => ({
      type: "move",
      moves: [{ id: "n2", position: { x, y: 0 } }],
      gesture: "drag-1",
    });
    expect(run(historyOf(S_FORM), [drag(300), drag(240)]).past).toEqual([]);
  });

  it("keeps the start of a drag that first places a node with no position", () => {
    const start: EditorState = { ...S_FORM, layout: { ...S_FORM.layout, positions: {} } };
    const drag = (x: number): GraphCommand => ({
      type: "move",
      moves: [{ id: "n2", position: { x, y: 0 } }],
      gesture: "drag-1",
    });
    const dragged = run(historyOf(start), [drag(10), drag(20)]);
    expect(dragged.past[0]?.ops).toEqual([
      { op: "position", id: "n2", from: undefined, to: { x: 20, y: 0 } },
    ]);
    expect(undo(dragged).history.state.layout.positions).toEqual({});
  });

  it("gives moves without a gesture an entry each", () => {
    const move = (x: number): GraphCommand => ({
      type: "move",
      moves: [{ id: "n2", position: { x, y: 0 } }],
    });
    expect(run(historyOf(S_FORM), [move(250), move(260)]).past).toHaveLength(2);
  });
});

describe("redo, selection and the bound", () => {
  const deleteE1: GraphCommand = { type: "delete", nodes: [], edges: ["e1"] };

  it("clears the redo stack on a new edit", () => {
    const undone = undo(dispatch(historyOf(S_FORM), deleteE1).history).history;
    expect(canRedo(undone)).toBe(true);
    const edited = dispatch(undone, {
      type: "move",
      moves: [{ id: "n1", position: { x: 0, y: 480 } }],
    }).history;
    expect(edited.future).toEqual([]);
    expect(redo(edited).history).toBe(edited);
  });

  it("keeps both stacks across a selection change and a refused command", () => {
    const undone = undo(dispatch(historyOf(S_FORM), deleteE1).history).history;
    const selected = dispatch(undone, { type: "selectAll" }).history;
    expect(selected.past).toBe(undone.past);
    expect(selected.future).toBe(undone.future);
    const refused = dispatch(selected, {
      type: "connect",
      source: "n2",
      sourcePort: "out",
      target: "n2",
      targetPort: "left",
    });
    expect(refused.effect.kind).toBe("refused");
    expect(refused.history).toBe(selected);
  });

  it("restores the selection an edit started from on undo, and the one it ended with on redo", () => {
    const selected = dispatch(historyOf(S_FORM), {
      type: "select",
      nodes: ["n3"],
      edges: [],
      mode: "replace",
    }).history;
    const added = dispatch(selected, {
      type: "addNode",
      node: { type: "comment", data: { text: "note" } },
      position: { x: 0, y: 480 },
    }).history;
    expect(added.state.selection.nodes).toEqual(["n4"]);
    const back = undo(added).history;
    expect(back.state.selection.nodes).toEqual(["n3"]);
    expect(redo(back).history.state.selection.nodes).toEqual(["n4"]);
  });

  it("is a no-op at either end of the stack", () => {
    const history = historyOf(S_FORM);
    expect(undo(history)).toEqual({ history, entry: undefined });
    expect(redo(history)).toEqual({ history, entry: undefined });
  });

  it(`keeps the latest ${HISTORY_DEPTH} entries`, () => {
    const moves = Array.from({ length: HISTORY_DEPTH + 5 }, (_, i): GraphCommand => ({
      type: "move",
      moves: [{ id: "n1", position: { x: 0, y: (i + 1) * 10 } }],
    }));
    let history = run(historyOf(S_FORM), moves);
    expect(history.past).toHaveLength(HISTORY_DEPTH);
    while (canUndo(history)) history = undo(history).history;
    expect(history.state.layout.positions["n1"]).toEqual({ x: 0, y: 50 });
  });
});

describe("unsaved changes across the undo stack", () => {
  const saved = markSaved(S_FORM.graph);
  const disconnect: GraphCommand = { type: "disconnect", edge: "e1" };

  it("is dirty after an edit to the graph, and clean again once it is undone", () => {
    const edited = run(historyOf(S_FORM), [disconnect]);
    expect(isDirty(edited.state.graph, saved)).toBe(true);
    const back = undo(edited).history;
    expect(isDirty(back.state.graph, saved)).toBe(false);
    expect(isDirty(redo(back).history.state.graph, saved)).toBe(true);
  });

  it("never turns dirty for a move or a selection: layout and selection are not the rule", () => {
    const moved = run(historyOf(S_FORM), [
      { type: "move", moves: [{ id: "n2", position: { x: 256, y: 64 } }] },
      { type: "selectAll" },
    ]);
    expect(moved.state.graph).toBe(S_FORM.graph);
    expect(isDirty(moved.state.graph, saved)).toBe(false);
  });
});
