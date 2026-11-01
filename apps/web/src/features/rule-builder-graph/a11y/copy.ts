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

/** "A", "A and B", "A, B and C": user names joined as plain text. */
export const listOf = (items: readonly string[]): string =>
  items.length <= 1
    ? (items[0] ?? "")
    : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1] as string}`;

const capitalised = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

export const copy = {
  connectStarted: (source: string, available: number, unavailable: number): string =>
    `Connecting from ${source} output. ${plural(available, "input", "inputs")} available` +
    (unavailable === 0 ? "" : `, ${unavailable} not available`) +
    ". Choose an input, then press Space. Escape cancels.",
  candidate: (target: string, port: string, type: string, index: number, size: number): string =>
    `${target} ${portLabel(port)}, ${type}, ${index} of ${size}.`,
  candidateRefused: (target: string, port: string, reason: string): string =>
    `${target} ${portLabel(port)} not available. ${reason}`,
  noneAvailable: (): string => "No input can take this connection.",
  connected: (source: string, target: string, port: string): string =>
    `Connected ${source} output to ${target} ${portLabel(port)}.`,
  disconnected: (source: string, target: string, port: string): string =>
    `Disconnected ${source} from ${target} ${portLabel(port)}.`,
  refused: (reason: string): string => `Can't connect. ${reason}`,
  cancelled: (): string => "Connection cancelled.",
  nodeAdded: (name: string): string => `Added ${name}, not connected.`,
  nodeDeleted: (name: string, connections: number): string =>
    connections === 0
      ? `Deleted ${name}. It had no connections.`
      : `Deleted ${name} and ${plural(connections, "connection", "connections")}.`,
  moved: (name: string, dir: Direction, step: number, x: number, y: number): string =>
    `Moved ${name} ${step} ${DIRECTION_WORD[dir]}, now x ${x}, y ${y}.`,
  /** One sentence for a settled burst of nudges: "Moved AND 40 right and 8 down, now x 280, y 128." */
  movedBy: (name: string, parts: readonly string[], x: number, y: number): string =>
    `Moved ${name} ${listOf(parts)}, now x ${x}, y ${y}.`,
  distance: (step: number, dir: Direction): string => `${step} ${DIRECTION_WORD[dir]}`,
  atEdge: (name: string, x: number, y: number): string =>
    `${name} is at the edge of the canvas, x ${x}, y ${y}.`,
  stoppedAtEdge: (): string => " Stopped at the edge of the canvas.",
  movedTo: (name: string, x: number, y: number): string => `Moved ${name} to x ${x}, y ${y}.`,
  validationClean: (): string => "No problems found.",
  validationFailed: (count: number, first: string): string =>
    `${plural(count, "problem", "problems")}. First: ${first}` +
    (count > 1
      ? ` ${plural(count - 1, "more problem", "more problems")} in the problems list.`
      : ""),
  validationItem: (message: string, where?: string): string =>
    where === undefined ? message : `${where}: ${message}`,
  noParameters: (): string => "no parameters",
  /** Only settings that are not plain values (nested lists, records): not read out one by one. */
  parametersSet: (): string => "parameters set",
  moreSettings: (n: number): string => `plus ${plural(n, "more setting", "more settings")}`,
  /** Two nodes with one name: each is told apart by its position in the order. */
  disambiguated: (name: string, index: number): string => `${name} (node ${index})`,
  noConnections: (): string => "none",
  inboundFrom: (source: string, port: string): string => `${source} into ${portLabel(port)}`,
  outboundTo: (target: string, port: string): string => `${target} ${portLabel(port)}`,
  unknownType: (): string => "type unknown",
  /** E37-D02 §14: "{Input | Output} port, {type}, {connected to {node} | not connected}". */
  port: (output: boolean, port: string, type: string, names: readonly string[]): string =>
    `${output ? "Output" : capitalised(portLabel(port))} port, ${type}, ` +
    `${names.length === 0 ? "not connected" : `connected to ${listOf(names)}`}.`,
  noOutput: (): string => "No output.",
  noPorts: (): string => "No ports.",
  /** A node's accessible description: type, name, parameters, then each port. */
  node: (type: string, name: string, params: string, ports: string): string =>
    `${type} ${name}, ${params}. ${ports}`,
  position: (index: number, size: number): string => `Node ${index} of ${size}.`,
} as const;
