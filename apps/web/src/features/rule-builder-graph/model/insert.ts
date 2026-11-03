/**
 * Adding a node without a drag (E37-D02 §7 :278; AC "Non-drag insertion works"): `Enter` on a
 * palette entry inserts the node connected to the current selection when a compatible port exists,
 * at the selection's first free compatible port, else unconnected; either way it is placed right
 * of the selection (in its column at the canvas bound), in the first free cell of that column. The
 * selection's ports are read in E47-S03's left-to-right order (its inputs in port order, then its
 * output), and "free" and "compatible" are `verdictFor`'s whole answer on the graph with the new
 * node in it, so this path refuses exactly what a drag refuses. With nothing selected the node goes
 * in the first free cell of the leftmost column. Pure.
 */
import type { GraphLayout, GraphNode } from "@candleviewer/rule-graph";
import { OUTPUT_PORT, type A11yGraph, type PortOracle } from "../a11y/graph.js";
import type { Point } from "../a11y/nudge.js";
import { verdictFor, type NewEdge } from "../a11y/portSelection.js";
import { CANVAS_LIMIT } from "./layout.js";
import { GRID, Occupancy, positionOf } from "./placement.js";

export interface InsertPlan {
  readonly position: Point;
  /** The connection to the selection, when one of its ports takes the node. */
  readonly edge: NewEdge | undefined;
}

/** The first of the anchor's ports, left to right, that `node` can connect to, as an edge. */
function connectionTo(
  graph: A11yGraph,
  anchor: GraphNode,
  node: GraphNode,
  oracle: PortOracle,
): NewEdge | undefined {
  const withNode: A11yGraph = { nodes: [...graph.nodes, node], edges: graph.edges };
  const into = (port: string): NewEdge => ({
    source: node.id,
    sourcePort: OUTPUT_PORT,
    target: anchor.id,
    targetPort: port,
  });
  const from = (port: string): NewEdge => ({
    source: anchor.id,
    sourcePort: OUTPUT_PORT,
    target: node.id,
    targetPort: port,
  });
  const candidates = [
    ...oracle.inputsOf(anchor).map(([port]) => into(port)),
    ...(oracle.outputOf(anchor) === null ? [] : oracle.inputsOf(node).map(([port]) => from(port))),
  ];
  return candidates.find(
    (edge) => verdictFor(withNode, oracle, edge.source, edge.target, edge.targetPort).ok,
  );
}

/**
 * Where `node` (its id already given) goes and what it connects to. The anchor is the selection's
 * most recent node still in the graph: the one a click or the keyboard selected last.
 */
export function planInsert(
  graph: A11yGraph,
  layout: GraphLayout,
  selected: readonly string[],
  node: GraphNode,
  oracle: PortOracle,
): InsertPlan {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const taken = new Occupancy(
    graph.nodes.flatMap((n) => {
      const at = positionOf(layout, n.id);
      return at === undefined ? [] : [at];
    }),
  );
  const anchorId = [...selected].reverse().find((id) => byId.has(id));
  const anchor = anchorId === undefined ? undefined : byId.get(anchorId);
  if (anchor === undefined) return { position: taken.takeBelow({ x: 0, y: 0 }), edge: undefined };
  const at = positionOf(layout, anchor.id) ?? { x: 0, y: 0 };
  return {
    position: taken.takeBelow({ x: Math.min(at.x + GRID, CANVAS_LIMIT), y: at.y }),
    edge: connectionTo(graph, anchor, node, oracle),
  };
}
