// @vitest-environment node
import { PORT_COMPAT, toIr, type GraphModel } from "@candleviewer/rule-graph";
import { describe, expect, it, vi } from "vitest";
import { REFUSAL } from "../../../src/features/rule-builder-graph/a11y/copy.js";
import {
  editorStateOf,
  intentsOf,
  reduce,
  type CommandEffect,
  type EditorState,
  type GraphCommand,
  type NodeSpec,
} from "../../../src/features/rule-builder-graph/model/commands.js";
import {
  dispatch,
  historyOf,
  undo,
} from "../../../src/features/rule-builder-graph/model/history.js";
import { edge, node } from "./fixtures.js";

const TRIGGER: NodeSpec = { type: "trigger", data: { type: "on_bar_close", timeframe: "1m" } };
const CONDITION: NodeSpec = {
  type: "condition",
  data: { kind: "comparison", op: "gt", left: { metric: "close" }, right: { const: "1" } },
};
const ACTION: NodeSpec = { type: "action", data: { type: "flatten_position", params: {} } };
const GATE: NodeSpec = { type: "logicGate", data: { op: "all_of", children: [] } };

const empty = (): EditorState =>
  editorStateOf({ envelope: { name: "Flatten on breakout", ir_version: 1 }, nodes: [], edges: [] });

/** Commands in order, each against the state the last one left. */
function run(state: EditorState, commands: readonly GraphCommand[]) {
  let now = state;
  const effects: CommandEffect[] = [];
  for (const command of commands) {
    const outcome = reduce(now, command);
    now = outcome.state;
    effects.push(outcome.effect);
  }
  return { state: now, effects };
}

/** s-form's three nodes, one edge from the condition into the action. */
const SFORM: GraphModel = {
  envelope: { name: "S-form" },
  nodes: [
    node("n1", "trigger", { type: "on_bar_close" }),
    node("n2", "condition", { kind: "comparison", op: "gt" }),
    node("n3", "action", { type: "modify_stop_loss" }),
  ],
  edges: [edge("e1", "n2", "n3", "when")],
};

describe("Author a minimal graph by pointer (AC 1, the model's half)", () => {
  it("holds a trigger, a condition and an action dropped from the palette and connected port to port", () => {
    const { state, effects } = run(empty(), [
      { type: "addNode", node: TRIGGER, position: { x: 0, y: 0 } },
      { type: "addNode", node: CONDITION, position: { x: 240, y: 0 } },
      { type: "addNode", node: ACTION, position: { x: 480, y: 0 } },
      { type: "connect", source: "n2", sourcePort: "out", target: "n3", targetPort: "when" },
    ]);
    expect(effects).toEqual([
      { kind: "added", node: "n1" },
      { kind: "added", node: "n2" },
      { kind: "added", node: "n3" },
      { kind: "connected", edge: "e1" },
    ]);
    expect(state.graph.nodes.map((n) => [n.id, n.type])).toEqual([
      ["n1", "trigger"],
      ["n2", "condition"],
      ["n3", "action"],
    ]);
    expect(state.graph.edges).toEqual([edge("e1", "n2", "n3", "when")]);
    expect(state.layout.positions).toEqual({
      n1: { x: 0, y: 0 },
      n2: { x: 240, y: 0 },
      n3: { x: 480, y: 0 },
    });
    // The app's state is the rule: rule-graph builds its IR from it, nothing else.
    const { ir } = toIr(state.graph, state.layout);
    expect(ir).toMatchObject({
      name: "Flatten on breakout",
      trigger: TRIGGER.data,
      conditions: { node_id: "n2", op: "gt" },
      actions: [{ node_id: "n3", type: "flatten_position" }],
    });
  });

  it("refuses a connect verdictFor refuses, and the refusal changes nothing", () => {
    const state = editorStateOf(SFORM);
    const outcome = reduce(state, {
      type: "connect",
      source: "n2",
      sourcePort: "out",
      target: "n2",
      targetPort: "left",
    });
    expect(outcome.effect).toEqual({
      kind: "refused",
      reason: REFUSAL.selfLoop,
      fromType: "boolean",
      toType: "number",
    });
    expect(outcome.state).toBe(state);
    expect(outcome.edit).toBeUndefined();
  });

  it("refuses a type mismatch with the matrix's sentence and both port types", () => {
    const state = editorStateOf({
      ...SFORM,
      nodes: [...SFORM.nodes, node("n4", "condition", { kind: "comparison", op: "gt" })],
    });
    const outcome = reduce(state, {
      type: "connect",
      source: "n2",
      sourcePort: "out",
      target: "n4",
      targetPort: "left",
    });
    expect(outcome.effect).toEqual({
      kind: "refused",
      reason: PORT_COMPAT.boolean.number,
      fromType: "boolean",
      toType: "number",
    });
    expect(outcome.state.graph).toBe(state.graph);
  });

  it("names no port types when an end of the refused pair is not in the graph", () => {
    const outcome = reduce(editorStateOf(SFORM), {
      type: "connect",
      source: "n9",
      sourcePort: "out",
      target: "n3",
      targetPort: "when",
    });
    expect(outcome.effect).toEqual({ kind: "refused", reason: REFUSAL.unknownNode });
  });

  it("reads a drag that starts on an input as output to input", () => {
    const state = editorStateOf({ ...SFORM, edges: [] });
    const outcome = reduce(state, {
      type: "connect",
      source: "n3",
      sourcePort: "when",
      target: "n2",
      targetPort: "out",
    });
    expect(outcome.effect).toEqual({ kind: "connected", edge: "e1" });
    expect(outcome.state.graph.edges).toEqual([edge("e1", "n2", "n3", "when")]);
  });

  it("refuses an input dropped on an input: no output port was chosen", () => {
    const state = editorStateOf({ ...SFORM, edges: [] });
    const outcome = reduce(state, {
      type: "connect",
      source: "n3",
      sourcePort: "when",
      target: "n2",
      targetPort: "left",
    });
    expect(outcome.effect).toEqual({ kind: "refused", reason: REFUSAL.noSource });
    expect(outcome.state).toBe(state);
  });

  it("appends a new edge, so a list input keeps its edges in connect order", () => {
    const state = editorStateOf({
      envelope: {},
      nodes: [
        node("a", "condition", { kind: "comparison", op: "gt" }),
        node("b", "condition", { kind: "comparison", op: "lt" }),
        node("g", "logicGate", { op: "all_of" }),
      ],
      edges: [edge("e1", "b", "g", "in")],
    });
    const outcome = reduce(state, {
      type: "connect",
      source: "a",
      sourcePort: "out",
      target: "g",
      targetPort: "in",
    });
    expect(outcome.state.graph.edges.map((e) => [e.id, e.source])).toEqual([
      ["e1", "b"],
      ["e2", "a"],
    ]);
  });
});

/** `Enter` on a palette entry: an add with no position, after selecting `selected`. */
function enter(state: EditorState, spec: NodeSpec, selected: readonly string[] = []) {
  const chosen = reduce(state, { type: "select", nodes: selected, edges: [], mode: "replace" });
  return reduce(chosen.state, { type: "addNode", node: spec });
}

describe("Non-drag insertion works (AC 3, the command)", () => {
  it("inserts the node connected to the selection where types allow, and it becomes the selection", () => {
    const state = editorStateOf({
      envelope: {},
      nodes: [node("g", "logicGate", { op: "all_of" })],
      edges: [],
    });
    const outcome = enter(state, CONDITION, ["g"]);
    expect(outcome.effect).toEqual({ kind: "added", node: "n1", edge: "e1" });
    expect(outcome.state.graph.edges).toEqual([edge("e1", "n1", "g", "in")]);
    expect(outcome.state.selection).toEqual({ nodes: ["n1"], edges: [] });
  });

  it("builds s-form by Enter alone: each node right of the last, the action connected", () => {
    let state = empty();
    state = enter(state, TRIGGER).state;
    state = enter(state, CONDITION, state.selection.nodes).state;
    const last = enter(state, ACTION, state.selection.nodes);
    expect(last.state.graph.nodes.map((n) => n.id)).toEqual(["n1", "n2", "n3"]);
    expect(last.state.graph.edges).toEqual([edge("e1", "n2", "n3", "when")]);
    expect(last.state.layout.positions).toEqual({
      n1: { x: 0, y: 0 },
      n2: { x: 240, y: 0 },
      n3: { x: 480, y: 0 },
    });
  });

  it("is one undo entry, and one undo takes back the node and its connection", () => {
    const state = editorStateOf({
      envelope: {},
      nodes: [node("g", "logicGate", { op: "all_of" })],
      edges: [],
    });
    let history = dispatch(historyOf(state), {
      type: "select",
      nodes: ["g"],
      edges: [],
      mode: "replace",
    }).history;
    history = dispatch(history, { type: "addNode", node: CONDITION }).history;
    expect(history.past.map((entry) => entry.ops.map((op) => op.op))).toEqual([
      ["addNode", "addEdge"],
    ]);
    expect(undo(history).history.state.graph).toEqual(state.graph);
  });
});

describe("adding a node", () => {
  it("selects the new node and gives it the next free id", () => {
    const state = editorStateOf({
      envelope: {},
      nodes: [node("n7", "trigger"), node("c1", "condition", { kind: "comparison" })],
      edges: [],
    });
    const outcome = reduce(state, { type: "addNode", node: GATE, position: { x: 720, y: 0 } });
    expect(outcome.effect).toEqual({ kind: "added", node: "n8" });
    expect(outcome.state.selection).toEqual({ nodes: ["n8"], edges: [] });
    expect(outcome.state.graph.nodes.at(-1)).toEqual({ id: "n8", ...GATE });
    expect(outcome.edit?.kind).toBe("addNode");
  });

  it("refuses a second trigger: a rule has one", () => {
    const state = editorStateOf(SFORM);
    const outcome = reduce(state, { type: "addNode", node: TRIGGER, position: { x: 0, y: 480 } });
    expect(outcome.effect).toEqual({ kind: "none" });
    expect(outcome.state).toBe(state);
  });

  it("ignores a drop at a position that is not a number", () => {
    const state = empty();
    const outcome = reduce(state, { type: "addNode", node: ACTION, position: { x: NaN, y: 0 } });
    expect(outcome.state).toBe(state);
    expect(outcome.edit).toBeUndefined();
  });
});

describe("deleting and disconnecting", () => {
  it("deletes the selected nodes with every edge on them, and no edge is left dangling", () => {
    const state = editorStateOf({
      envelope: {},
      nodes: [
        node("a", "condition", { kind: "comparison", op: "gt" }),
        node("b", "condition", { kind: "comparison", op: "lt" }),
        node("g", "logicGate", { op: "all_of" }),
        node("act", "action"),
      ],
      edges: [
        edge("e1", "a", "g", "in"),
        edge("e2", "b", "g", "in"),
        edge("e3", "g", "act", "when"),
      ],
    });
    const selected = reduce(state, {
      type: "select",
      nodes: ["g", "b"],
      edges: [],
      mode: "replace",
    });
    const outcome = reduce(selected.state, { type: "delete", nodes: ["g"], edges: [] });
    expect(outcome.effect).toEqual({ kind: "removed", nodes: ["g"], edges: ["e1", "e2", "e3"] });
    const ids = new Set(outcome.state.graph.nodes.map((n) => n.id));
    expect(ids).toEqual(new Set(["a", "b", "act"]));
    for (const e of outcome.state.graph.edges) {
      expect(ids.has(e.source) && ids.has(e.target)).toBe(true);
    }
    expect(outcome.state.graph.edges).toEqual([]);
    expect(outcome.state.layout.positions).not.toHaveProperty("g");
    expect(outcome.state.selection).toEqual({ nodes: ["b"], edges: [] });
    expect(outcome.edit?.kind).toBe("delete");
  });

  it("deletes a selected edge on its own, keeping its nodes", () => {
    const outcome = reduce(editorStateOf(SFORM), { type: "delete", nodes: [], edges: ["e1"] });
    expect(outcome.effect).toEqual({ kind: "removed", nodes: [], edges: ["e1"] });
    expect(outcome.state.graph.nodes).toHaveLength(3);
  });

  it("disconnects one edge", () => {
    const outcome = reduce(editorStateOf(SFORM), { type: "disconnect", edge: "e1" });
    expect(outcome.state.graph.edges).toEqual([]);
    expect(outcome.edit?.kind).toBe("disconnect");
  });

  it("changes nothing for ids not in the graph", () => {
    const state = editorStateOf(SFORM);
    expect(reduce(state, { type: "disconnect", edge: "e9" }).state).toBe(state);
    expect(reduce(state, { type: "delete", nodes: ["n9"], edges: ["e9"] }).effect).toEqual({
      kind: "none",
    });
  });
});

describe("moving", () => {
  it("moves nodes in the layout only: the graph object stays the same", () => {
    const state = editorStateOf(SFORM);
    const outcome = reduce(state, {
      type: "move",
      moves: [{ id: "n2", position: { x: 256, y: 32 } }],
      gesture: "drag-1",
    });
    expect(outcome.state.graph).toBe(state.graph);
    expect(outcome.state.layout.positions["n2"]).toEqual({ x: 256, y: 32 });
    expect(outcome.effect).toEqual({ kind: "moved", nodes: ["n2"] });
    expect(outcome.edit).toEqual({
      kind: "move",
      gesture: "drag-1",
      ops: [{ op: "position", id: "n2", from: { x: 240, y: 0 }, to: { x: 256, y: 32 } }],
    });
  });

  it("skips a move to where the node is, to a non-number, or of a node not in the graph", () => {
    const state = editorStateOf(SFORM);
    const outcome = reduce(state, {
      type: "move",
      moves: [
        { id: "n2", position: { x: 240, y: 0 } },
        { id: "n3", position: { x: Infinity, y: 0 } },
        { id: "n9", position: { x: 0, y: 0 } },
      ],
    });
    expect(outcome.state).toBe(state);
    expect(outcome.edit).toBeUndefined();
  });

  it("chains two moves of one node in one command", () => {
    const outcome = reduce(editorStateOf(SFORM), {
      type: "move",
      moves: [
        { id: "n2", position: { x: 260, y: 0 } },
        { id: "n2", position: { x: 280, y: 0 } },
      ],
    });
    expect(outcome.edit?.ops).toEqual([
      { op: "position", id: "n2", from: { x: 240, y: 0 }, to: { x: 260, y: 0 } },
      { op: "position", id: "n2", from: { x: 260, y: 0 }, to: { x: 280, y: 0 } },
    ]);
  });
});

describe("selecting", () => {
  const state = editorStateOf(SFORM);
  const select = (nodes: string[], mode: "replace" | "add" | "toggle", from = state) =>
    reduce(from, { type: "select", nodes, edges: [], mode });

  it("replaces, adds to and toggles the selection, dropping ids not in the graph", () => {
    const first = select(["n2", "n9"], "replace");
    expect(first.state.selection).toEqual({ nodes: ["n2"], edges: [] });
    const added = select(["n3", "n2"], "add", first.state);
    expect(added.state.selection.nodes).toEqual(["n2", "n3"]);
    const toggled = select(["n2", "n1"], "toggle", added.state);
    expect(toggled.state.selection.nodes).toEqual(["n3", "n1"]);
    expect(toggled.effect).toEqual({ kind: "selected", nodes: ["n3", "n1"], edges: [] });
    expect(toggled.edit).toBeUndefined();
  });

  it("selects edges as well as nodes", () => {
    const outcome = reduce(state, { type: "select", nodes: [], edges: ["e1"], mode: "replace" });
    expect(outcome.state.selection).toEqual({ nodes: [], edges: ["e1"] });
  });

  it("selects every node with select all", () => {
    expect(reduce(state, { type: "selectAll" }).state.selection).toEqual({
      nodes: ["n1", "n2", "n3"],
      edges: [],
    });
  });

  it("selects the nodes whose card meets the marquee, from either corner", () => {
    const rect = { x: 490, y: 50, width: -300, height: -100 }; // 190..490: n2 (240) and n3 (480)
    const outcome = reduce(state, { type: "marquee", rect, mode: "replace" });
    expect(outcome.state.selection.nodes).toEqual(["n2", "n3"]);
    const none = reduce(state, {
      type: "marquee",
      rect: { x: 0, y: 200, width: 600, height: 40 },
      mode: "replace",
    });
    expect(none.state.selection.nodes).toEqual([]);
  });

  it("adds the marquee's nodes to the selection with the add mode", () => {
    const first = select(["n1"], "replace");
    const outcome = reduce(first.state, {
      type: "marquee",
      rect: { x: 470, y: 0, width: 20, height: 20 },
      mode: "add",
    });
    expect(outcome.state.selection.nodes).toEqual(["n1", "n3"]);
  });
});

describe("the intents CMP-146, CMP-236 and CMP-257 call", () => {
  it("send one command each, in the props' argument order", () => {
    const dispatch = vi.fn((command: GraphCommand) => command.type);
    const intents = intentsOf(dispatch);
    expect(intents.onConnect("n2", "out", "n3", "when")).toBe("connect");
    intents.onDisconnect("e1");
    intents.onDelete(["n2"]);
    intents.onDelete(["n2"], ["e1"]);
    intents.onMove([{ id: "n2", position: { x: 1, y: 2 } }]);
    intents.onMove([{ id: "n2", position: { x: 1, y: 2 } }], "drag-1");
    intents.onSelect(["n2"]);
    intents.onSelect(["n2"], ["e1"], "toggle");
    intents.onAddNode(ACTION);
    intents.onAddNode(ACTION, { x: 0, y: 240 });
    expect(dispatch.mock.calls.map(([command]) => command)).toEqual([
      { type: "connect", source: "n2", sourcePort: "out", target: "n3", targetPort: "when" },
      { type: "disconnect", edge: "e1" },
      { type: "delete", nodes: ["n2"], edges: [] },
      { type: "delete", nodes: ["n2"], edges: ["e1"] },
      { type: "move", moves: [{ id: "n2", position: { x: 1, y: 2 } }] },
      { type: "move", moves: [{ id: "n2", position: { x: 1, y: 2 } }], gesture: "drag-1" },
      { type: "select", nodes: ["n2"], edges: [], mode: "replace" },
      { type: "select", nodes: ["n2"], edges: ["e1"], mode: "toggle" },
      { type: "addNode", node: ACTION },
      { type: "addNode", node: ACTION, position: { x: 0, y: 240 } },
    ]);
  });
});
