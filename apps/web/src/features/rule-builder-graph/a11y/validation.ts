/**
 * The announcement for a validate or save attempt (E47-S03 Gherkin 1 and 6; 05 §6.2): one polite
 * sentence with the problem count and the first problem, and the node focus moves to. "First" is
 * by the documented node order, so the announcement, the structural view and focus agree; a
 * problem not tied to a node (a rule-level one) comes before any node's.
 */
import { copy } from "./copy.js";
import type { A11yGraph } from "./graph.js";
import { nodeName } from "./outline.js";
import { traversalOrder } from "./traversal.js";

export interface Problem {
  readonly message: string;
  /** The node the problem is on, when it is on one. */
  readonly nodeId?: string;
}

export interface ValidationAnnouncement {
  readonly text: string;
  /** The node to focus, if the first problem is on a node still in the graph. */
  readonly focusNodeId: string | undefined;
}

export function validationAnnouncement(
  graph: A11yGraph,
  problems: readonly Problem[],
): ValidationAnnouncement {
  if (problems.length === 0) return { text: copy.validationClean(), focusNodeId: undefined };
  const rank = new Map(traversalOrder(graph).map((entry, i) => [entry.id, i]));
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const rankOf = (p: Problem): number =>
    p.nodeId === undefined ? -1 : (rank.get(p.nodeId) ?? Number.MAX_SAFE_INTEGER);
  // A stable sort keeps the caller's order among equals.
  const first = [...problems].sort((a, b) => rankOf(a) - rankOf(b))[0] as Problem;
  const node = first.nodeId === undefined ? undefined : nodes.get(first.nodeId);
  const where = node === undefined ? undefined : nodeName(node);
  return {
    text: copy.validationFailed(problems.length, copy.validationItem(first.message, where)),
    focusNodeId: node?.id,
  };
}
