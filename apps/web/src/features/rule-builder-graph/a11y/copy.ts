/**
 * Every string the graph editor's keyboard core announces or shows (E47-S03 BQ-11). All PROPOSED:
 * E37-D04 (keyboard authoring map) and E37-D05 (copy) have not landed, so rewording is an edit to
 * this file alone, and each entry is a deviation row for E47-D06 #1305 / E37-D04 to confirm.
 * User content (node names, parameter values) is interpolated as plain text and must be rendered
 * as a text node, never as markup. Sentences end with a full stop; a refusal names the reason.
 */
import type { A11yNodeType } from "./graph.js";

export const TYPE_LABEL: Readonly<Record<A11yNodeType, string>> = {
  trigger: "Trigger",
  condition: "Condition",
  action: "Action",
  logicGate: "Logic gate",
  comment: "Comment",
};

/** Input port names as read aloud (rule-graph's `targetPort` values); others read as is. */
export const PORT_LABEL: Readonly<Record<string, string>> = {
  left: "input A",
  right: "input B",
  right2: "input C",
  child: "input",
  in: "input",
  when: "run when",
};

export const portLabel = (port: string): string =>
  Object.hasOwn(PORT_LABEL, port) ? (PORT_LABEL[port] as string) : port;

/** The local refusals; type mismatches use the oracle's (rule-graph PORT_COMPAT) sentence. */
export const REFUSAL = {
  selfLoop: "A node can't connect to itself.",
  occupied: "That input already has a connection.",
  duplicate: "Those ports are already connected.",
  loop: "That connection would make a loop.",
  noOutput: "This node has no output.",
  noInput: "That port is not an input of this node.",
  noSource: "Choose an output port first.",
  noTarget: "Choose an input port first.",
  unknownNode: "That node is no longer in the rule.",
} as const;

export type Direction = "left" | "right" | "up" | "down";

const DIRECTION_WORD: Readonly<Record<Direction, string>> = {
  left: "left",
  right: "right",
  up: "up",
  down: "down",
};

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

export const copy = {
  connectStarted: (source: string): string =>
    `Connecting from ${source} output. Choose an input, then press Enter. Escape cancels.`,
  candidate: (target: string, port: string, index: number, size: number): string =>
    `${target} ${portLabel(port)}, ${index} of ${size}.`,
  candidateRefused: (target: string, port: string, reason: string): string =>
    `${target} ${portLabel(port)} not available. ${reason}`,
  connected: (source: string, target: string, port: string): string =>
    `Connected ${source} output to ${target} ${portLabel(port)}.`,
  disconnected: (source: string, target: string, port: string): string =>
    `Disconnected ${source} from ${target} ${portLabel(port)}.`,
  refused: (reason: string): string => `Can't connect. ${reason}`,
  cancelled: (): string => "Connection cancelled.",
  nodeAdded: (name: string): string => `Added ${name}.`,
  nodeDeleted: (name: string): string => `Deleted ${name}.`,
  moved: (name: string, dir: Direction, step: number, x: number, y: number): string =>
    `Moved ${name} ${step} ${DIRECTION_WORD[dir]}, now x ${x}, y ${y}.`,
  atEdge: (name: string, x: number, y: number): string =>
    `${name} is at the edge of the canvas, x ${x}, y ${y}.`,
  movedTo: (name: string, x: number, y: number): string => `Moved ${name} to x ${x}, y ${y}.`,
  validationClean: (): string => "No problems found.",
  validationFailed: (count: number, first: string): string =>
    `${plural(count, "problem", "problems")}. First: ${first}`,
  validationItem: (message: string, where?: string): string =>
    where === undefined ? message : `${where}: ${message}`,
  noParameters: (): string => "no parameters",
  noConnections: (): string => "none",
  inboundFrom: (source: string, port: string): string => `${source} into ${portLabel(port)}`,
  outboundTo: (target: string, port: string): string => `${target} ${portLabel(port)}`,
  /** A node's accessible description: type, name, parameters, then its connections. */
  node: (type: string, name: string, params: string, inbound: string, outbound: string): string =>
    `${type} ${name}, ${params}. Inputs: ${inbound}. Output connects to: ${outbound}.`,
  position: (index: number, size: number): string => `Node ${index} of ${size}.`,
} as const;
