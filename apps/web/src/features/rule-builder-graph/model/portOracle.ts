/**
 * The production port oracle of the node-graph editor (E37-S01): the `PortOracle` the E47-S03
 * core (`a11y/graph.ts`) asks for, built from `@candleviewer/rule-graph`'s own port catalogue and
 * matrix (`portsOf`, `canConnect`), never a hand copy. Every connect path (a pointer drag, a click,
 * the keyboard) reads its port types and its refusal sentences through this one object, so they
 * share `PORT_COMPAT`'s wording.
 */
import {
  canConnect,
  isRuleGraphError,
  portsOf,
  type GraphNode,
  type NodePorts,
  type PortType,
} from "@candleviewer/rule-graph";
import type { PortOracle } from "../a11y/graph.js";

/** rule-graph's list input: one port taking many edges, filling a list's empty items in order. */
export const LIST_PORT = "in";

type Ports = Pick<NodePorts, "output" | "inputs">;

const NO_PORTS: Ports = Object.freeze({ output: null, inputs: [] });

/** The node's ports; a node rule-graph refuses (an unknown kind, a malformed one) has none. */
function portsFor(node: GraphNode): Ports {
  try {
    return portsOf(node);
  } catch (error) {
    if (isRuleGraphError(error)) return NO_PORTS;
    throw error;
  }
}

export const portOracle: PortOracle = Object.freeze({
  outputOf: (node: GraphNode) => portsFor(node).output,
  inputsOf: (node: GraphNode) => portsFor(node).inputs,
  // The oracle hands out rule-graph's port types only, and rule-graph's `canConnect` refuses any
  // other pair with SCHEMA_VIOLATION: the casts narrow nothing it does not check.
  canConnect: (from: string, to: string) => canConnect(from as PortType, to as PortType),
  acceptsMany: (port: string) => port === LIST_PORT,
});
