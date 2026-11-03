/**
 * The node-graph editor's reducer (E37-S01): the one place the graph changes. rule-graph's
 * `GraphModel` is the single source of truth (ticket Technical notes); the canvas, the palette and
 * E37-S05's outline (CMP-257) only send intents, named after CMP-146's and CMP-257's props
 * (`onConnect(source, sourcePort, target, targetPort)`, A-2; `onDisconnect`, `onDelete`, `onMove`,
 * `onSelect`, A-16; CMP-236's `onAddNode(type, position?)`, A-13), and render what this returns.
 *
 * A command that changes the graph or its layout returns its `Edit`: the reversible ops it made,
 * which `history.ts` records so undo and redo replay them without planning again. A connect is
 * refused unless E47-S03's `verdictFor` answers ok, so a drag, a click and the keyboard share one
 * verdict and its sentence. Selection is UI state: a selection change makes no edit. Pure.
 */
import type {
  GraphEdge,
  GraphLayout,
  GraphModel,
  GraphNode,
  GraphNodeType,
} from "@candleviewer/rule-graph";
import { REFUSAL } from "../a11y/copy.js";
import { OUTPUT_PORT, type PortOracle } from "../a11y/graph.js";
import type { Point } from "../a11y/nudge.js";
import { verdictFor } from "../a11y/portSelection.js";
import { planInsert } from "./insert.js";
import { normaliseLayout, pointOf } from "./layout.js";
import { placeNodes, positionOf } from "./placement.js";
import { portOracle } from "./portOracle.js";
import { NODE_BOX, tierOf } from "./tiers.js";

export interface Selection {
  readonly nodes: readonly string[];
  readonly edges: readonly string[];
}

export const NO_SELECTION: Selection = Object.freeze({ nodes: [], edges: [] });

export interface EditorState {
  readonly graph: GraphModel;
  readonly layout: GraphLayout;
  readonly selection: Selection;
}

/** A node as the palette describes it; the reducer gives it its id. */
export interface NodeSpec {
  readonly type: GraphNodeType;
  readonly data: Readonly<Record<string, unknown>>;
}

export interface NodeMove {
  readonly id: string;
  readonly position: Point;
}

/** A canvas-unit rectangle; a negative width or height spans back from its corner. */
export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export type SelectMode = "replace" | "add" | "toggle";

export type GraphCommand =
  /** With a position, a palette drop there, unconnected; without one, D02 §7's insertion. */
  | { readonly type: "addNode"; readonly node: NodeSpec; readonly position?: Point }
  | {
      readonly type: "connect";
      readonly source: string;
      readonly sourcePort: string;
      readonly target: string;
      readonly targetPort: string;
    }
  | { readonly type: "disconnect"; readonly edge: string }
  /** The nodes with every edge on them, and the edges named. */
  | {
      readonly type: "delete";
      readonly nodes: readonly string[];
      readonly edges: readonly string[];
    }
  /** One drag is one undo entry: its moves share a `gesture` key, one fresh key per drag. */
  | { readonly type: "move"; readonly moves: readonly NodeMove[]; readonly gesture?: string }
  | {
      readonly type: "select";
      readonly nodes: readonly string[];
      readonly edges: readonly string[];
      readonly mode: SelectMode;
    }
  | { readonly type: "selectAll" }
  | { readonly type: "marquee"; readonly rect: Rect; readonly mode: "replace" | "add" };

export type EditKind = "addNode" | "connect" | "disconnect" | "delete" | "move";

/** One reversible step; an index is the item's place in its array when the step runs. */
export type Op =
  | {
      readonly op: "addNode" | "removeNode";
      readonly index: number;
      readonly node: GraphNode;
      readonly position: Point | undefined;
    }
  | { readonly op: "addEdge" | "removeEdge"; readonly index: number; readonly edge: GraphEdge }
  | {
      readonly op: "position";
      readonly id: string;
      readonly from: Point | undefined;
      readonly to: Point | undefined;
    };

export interface Edit {
  readonly kind: EditKind;
  readonly ops: readonly Op[];
  readonly gesture?: string;
}

export type CommandEffect =
  | { readonly kind: "none" }
  /** `reason` is the verdict's sentence (PORT_COMPAT's on a type mismatch), shown at the target. */
  | {
      readonly kind: "refused";
      readonly reason: string;
      readonly fromType?: string;
      readonly toType?: string;
    }
  | { readonly kind: "added"; readonly node: string; readonly edge?: string }
  | { readonly kind: "connected"; readonly edge: string }
  | {
      readonly kind: "removed";
      readonly nodes: readonly string[];
      readonly edges: readonly string[];
    }
  | { readonly kind: "moved"; readonly nodes: readonly string[] }
  | {
      readonly kind: "selected";
      readonly nodes: readonly string[];
      readonly edges: readonly string[];
    };

export interface Outcome {
  readonly state: EditorState;
  readonly effect: CommandEffect;
  readonly edit?: Edit;
}

const BLANK_LAYOUT: GraphLayout = Object.freeze({
  positions: {},
  collapsed: [],
  comments: [],
  extra: {},
});

/**
 * A loaded graph ready to edit, nothing selected: its stored layout normalised (`layout.ts`), every
 * node placed (`placement.ts`), and only the presentation keys the client owns kept (SR-E37-03).
 */
export function editorStateOf(graph: GraphModel, layout: GraphLayout = BLANK_LAYOUT): EditorState {
  const { positions, collapsed, comments } = placeNodes(graph, normaliseLayout(graph, layout));
  return { graph, layout: { positions, collapsed, comments, extra: {} }, selection: NO_SELECTION };
}

const unchanged = (state: EditorState): Outcome => ({ state, effect: { kind: "none" } });

export const samePoint = (a: Point | undefined, b: Point | undefined): boolean =>
  a === b || (a !== undefined && b !== undefined && a.x === b.x && a.y === b.y);

const unique = (ids: readonly string[]): string[] => [...new Set(ids)];

/**
 * `${prefix}${n}`, n one above the highest short suffix in use (one to nine digits), stepped past
 * any id `items` hold: deterministic, and never one in use whatever ids a loaded rule carries.
 */
function freshId(items: readonly { readonly id: string }[], prefix: string): string {
  const used = new Set(items.map((item) => item.id));
  let highest = 0;
  for (const id of used) {
    const digits = id.startsWith(prefix) ? id.slice(prefix.length) : "";
    if (/^\d{1,9}$/.test(digits)) highest = Math.max(highest, Number(digits));
  }
  let n = highest + 1;
  while (used.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

/** `state` with `ops` applied in order; ops that only move nodes keep the graph object itself. */
export function applyOps(state: EditorState, ops: readonly Op[]): EditorState {
  const nodes = [...state.graph.nodes];
  const edges = [...state.graph.edges];
  const positions = new Map(Object.entries(state.layout.positions));
  const place = (id: string, at: Point | undefined) =>
    at === undefined ? positions.delete(id) : positions.set(id, at);
  let graphChanged = false;
  for (const op of ops) {
    switch (op.op) {
      case "addNode":
        nodes.splice(op.index, 0, op.node);
        place(op.node.id, op.position);
        break;
      case "removeNode":
        nodes.splice(op.index, 1);
        place(op.node.id, undefined);
        break;
      case "addEdge":
        edges.splice(op.index, 0, op.edge);
        break;
      case "removeEdge":
        edges.splice(op.index, 1);
        break;
      case "position":
        place(op.id, op.to);
        continue; // layout only: the graph is kept as is
    }
    graphChanged = true;
  }
  const graph = graphChanged ? { ...state.graph, nodes, edges } : state.graph;
  const layout = { ...state.layout, positions: Object.fromEntries(positions) };
  return { graph, layout, selection: state.selection };
}

/** `state` selecting `selection`, less any id no longer in the graph. */
export function withSelection(state: EditorState, selection: Selection): EditorState {
  const nodeIds = new Set(state.graph.nodes.map((n) => n.id));
  const edgeIds = new Set(state.graph.edges.map((e) => e.id));
  const nodes = selection.nodes.filter((id) => nodeIds.has(id));
  const edges = selection.edges.filter((id) => edgeIds.has(id));
  return { ...state, selection: { nodes, edges } };
}

function addNode(
  state: EditorState,
  spec: NodeSpec,
  position: Point | undefined,
  oracle: PortOracle,
): Outcome {
  const { graph, layout } = state;
  // One trigger per rule (D02 §7: the palette offers none while the graph has one).
  if (spec.type === "trigger" && graph.nodes.some((n) => n.type === "trigger")) {
    return unchanged(state);
  }
  // A drop is a fresh point, clamped to the canvas bound; one that is no point changes nothing.
  const at = position === undefined ? undefined : pointOf(position);
  if (position !== undefined && at === undefined) return unchanged(state);
  const data = { ...spec.data }; // the palette entry's own object stays the palette's
  const node: GraphNode = { id: freshId(graph.nodes, "n"), type: spec.type, data };
  const plan =
    at === undefined
      ? planInsert(graph, layout, state.selection.nodes, node, oracle)
      : { position: at, edge: undefined };
  const ops: Op[] = [{ op: "addNode", index: graph.nodes.length, node, position: plan.position }];
  const edge =
    plan.edge === undefined ? undefined : { id: freshId(graph.edges, "e"), ...plan.edge };
  if (edge !== undefined) ops.push({ op: "addEdge", index: graph.edges.length, edge });
  const next = { ...applyOps(state, ops), selection: { nodes: [node.id], edges: [] } };
  return {
    state: next,
    effect:
      edge === undefined
        ? { kind: "added", node: node.id }
        : { kind: "added", node: node.id, edge: edge.id },
    edit: { kind: "addNode", ops },
  };
}

/** The port types a refused pair would join, when both ends exist. */
function typesOf(
  graph: GraphModel,
  oracle: PortOracle,
  source: string,
  target: string,
  targetPort: string,
): { fromType?: string; toType?: string } {
  const from = graph.nodes.find((n) => n.id === source);
  const to = graph.nodes.find((n) => n.id === target);
  const fromType = from === undefined ? null : oracle.outputOf(from);
  const input = to === undefined ? undefined : oracle.inputsOf(to).find(([p]) => p === targetPort);
  return fromType === null || input === undefined ? {} : { fromType, toType: input[1] };
}

function connect(
  state: EditorState,
  command: Extract<GraphCommand, { type: "connect" }>,
  oracle: PortOracle,
): Outcome {
  // A drag may start at either end: an input dropped on an output is read output -> input.
  const reversed = command.sourcePort !== OUTPUT_PORT && command.targetPort === OUTPUT_PORT;
  const [source, sourcePort, target, targetPort] = reversed
    ? [command.target, command.targetPort, command.source, command.sourcePort]
    : [command.source, command.sourcePort, command.target, command.targetPort];
  const { graph } = state;
  if (sourcePort !== OUTPUT_PORT) {
    return { state, effect: { kind: "refused", reason: REFUSAL.noSource } };
  }
  const verdict = verdictFor(graph, oracle, source, target, targetPort);
  if (!verdict.ok) {
    const types = typesOf(graph, oracle, source, target, targetPort);
    return { state, effect: { kind: "refused", reason: verdict.reason, ...types } };
  }
  const edge: GraphEdge = { id: freshId(graph.edges, "e"), source, sourcePort, target, targetPort };
  const ops: Op[] = [{ op: "addEdge", index: graph.edges.length, edge }];
  return {
    state: applyOps(state, ops),
    effect: { kind: "connected", edge: edge.id },
    edit: { kind: "connect", ops },
  };
}

/** Removes the nodes named, every edge on them and the edges named: one edit. */
function remove(
  state: EditorState,
  nodeIds: readonly string[],
  edgeIds: readonly string[],
  kind: "delete" | "disconnect",
): Outcome {
  const { graph, layout } = state;
  const goingNodes = new Set(nodeIds);
  const goingEdges = new Set(edgeIds);
  const nodeAt = graph.nodes.flatMap((node, index) => (goingNodes.has(node.id) ? [index] : []));
  const edgeAt = graph.edges.flatMap((edge, index) =>
    goingEdges.has(edge.id) || goingNodes.has(edge.source) || goingNodes.has(edge.target)
      ? [index]
      : [],
  );
  if (nodeAt.length === 0 && edgeAt.length === 0) return unchanged(state);
  // Last index first, so each index still names its item; undo replays them backwards.
  const ops: Op[] = [
    ...[...edgeAt].reverse().map((index): Op => {
      const edge = graph.edges[index] as GraphEdge; // index came from this array
      return { op: "removeEdge", index, edge };
    }),
    ...[...nodeAt].reverse().map((index): Op => {
      const node = graph.nodes[index] as GraphNode; // index came from this array
      return { op: "removeNode", index, node, position: positionOf(layout, node.id) };
    }),
  ];
  const next = applyOps(state, ops);
  return {
    state: withSelection(next, state.selection),
    effect: {
      kind: "removed",
      nodes: nodeAt.map((index) => (graph.nodes[index] as GraphNode).id),
      edges: edgeAt.map((index) => (graph.edges[index] as GraphEdge).id),
    },
    edit: { kind, ops },
  };
}

function move(state: EditorState, moves: readonly NodeMove[], gesture?: string): Outcome {
  const ids = new Set(state.graph.nodes.map((n) => n.id));
  const now = new Map<string, Point | undefined>();
  const ops: Op[] = [];
  for (const { id, position } of moves) {
    const to = pointOf(position); // a fresh point, clamped to the canvas bound
    if (!ids.has(id) || to === undefined) continue;
    const from = now.has(id) ? now.get(id) : positionOf(state.layout, id);
    if (samePoint(from, to)) continue;
    ops.push({ op: "position", id, from, to });
    now.set(id, to);
  }
  if (ops.length === 0) return unchanged(state);
  return {
    state: applyOps(state, ops),
    effect: { kind: "moved", nodes: [...now.keys()] },
    edit: gesture === undefined ? { kind: "move", ops } : { kind: "move", ops, gesture },
  };
}

function selected(state: EditorState, selection: Selection): Outcome {
  const next = withSelection(state, selection);
  return { state: next, effect: { kind: "selected", ...next.selection } };
}

/** `current` changed by `ids` under `mode`, in selection order. */
function pick(current: readonly string[], ids: readonly string[], mode: SelectMode): string[] {
  const wanted = unique(ids);
  if (mode === "replace") return wanted;
  if (mode === "add") return unique([...current, ...wanted]);
  const toggled = new Set(wanted);
  return [
    ...current.filter((id) => !toggled.has(id)),
    ...wanted.filter((id) => !current.includes(id)),
  ];
}

/** The nodes whose card box (the tier's, at the node's position) meets `rect`. */
function inside(state: EditorState, rect: Rect): string[] {
  const box = NODE_BOX[tierOf(state.graph.nodes.length)];
  const left = Math.min(rect.x, rect.x + rect.width);
  const top = Math.min(rect.y, rect.y + rect.height);
  const right = Math.max(rect.x, rect.x + rect.width);
  const bottom = Math.max(rect.y, rect.y + rect.height);
  return unique(
    state.graph.nodes.flatMap((node) => {
      const at = positionOf(state.layout, node.id);
      const meets =
        at !== undefined &&
        at.x <= right &&
        at.x + box.width >= left &&
        at.y <= bottom &&
        at.y + box.height >= top;
      return meets ? [node.id] : [];
    }),
  );
}

/** One command against `state`, with rule-graph's port oracle unless another is given. */
export function reduce(
  state: EditorState,
  command: GraphCommand,
  oracle: PortOracle = portOracle,
): Outcome {
  switch (command.type) {
    case "addNode":
      return addNode(state, command.node, command.position, oracle);
    case "connect":
      return connect(state, command, oracle);
    case "disconnect":
      return remove(state, [], [command.edge], "disconnect");
    case "delete":
      return remove(state, command.nodes, command.edges, "delete");
    case "move":
      return move(state, command.moves, command.gesture);
    case "select":
      return selected(state, {
        nodes: pick(state.selection.nodes, command.nodes, command.mode),
        edges: pick(state.selection.edges, command.edges, command.mode),
      });
    case "selectAll":
      return selected(state, { nodes: unique(state.graph.nodes.map((n) => n.id)), edges: [] });
    case "marquee": {
      const hit = inside(state, command.rect);
      const nodes = command.mode === "add" ? unique([...state.selection.nodes, ...hit]) : hit;
      const edges = command.mode === "add" ? state.selection.edges : [];
      return selected(state, { nodes, edges });
    }
  }
}

/**
 * The intents CMP-146, CMP-236 and CMP-257 call, each one command; `R` is what dispatch gives.
 * `onMove` moves positions, one fresh `gesture` key per drag; action reorder is E37-S05's command.
 */
export interface GraphIntents<R = void> {
  readonly onAddNode: (node: NodeSpec, position?: Point) => R;
  readonly onConnect: (source: string, sourcePort: string, target: string, targetPort: string) => R;
  readonly onDisconnect: (edge: string) => R;
  readonly onDelete: (nodes: readonly string[], edges?: readonly string[]) => R;
  readonly onMove: (moves: readonly NodeMove[], gesture?: string) => R;
  readonly onSelect: (nodes: readonly string[], edges?: readonly string[], mode?: SelectMode) => R;
}

export function intentsOf<R>(dispatch: (command: GraphCommand) => R): GraphIntents<R> {
  return Object.freeze({
    onAddNode: (node: NodeSpec, position?: Point) =>
      dispatch(
        position === undefined ? { type: "addNode", node } : { type: "addNode", node, position },
      ),
    onConnect: (source: string, sourcePort: string, target: string, targetPort: string) =>
      dispatch({ type: "connect", source, sourcePort, target, targetPort }),
    onDisconnect: (edge: string) => dispatch({ type: "disconnect", edge }),
    onDelete: (nodes: readonly string[], edges: readonly string[] = []) =>
      dispatch({ type: "delete", nodes, edges }),
    onMove: (moves: readonly NodeMove[], gesture?: string) =>
      dispatch(gesture === undefined ? { type: "move", moves } : { type: "move", moves, gesture }),
    onSelect: (
      nodes: readonly string[],
      edges: readonly string[] = [],
      mode: SelectMode = "replace",
    ) => dispatch({ type: "select", nodes, edges, mode }),
  });
}
