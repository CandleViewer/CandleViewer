/**
 * Every string the graph editor's keyboard core announces or shows (E47-S03 BQ-11, as ruled).
 * Strings marked D02 are E37-D02's (`docs/design/E37/E37-D02.md` at origin/main; the line is
 * cited beside each) and are used VERBATIM: same words, same case, no full stop added. Strings
 * marked PROPOSED are this core's own (the nudge / move wording, plus the few the a11y lens asked
 * for that D02 has no string for); each is a deviation row for E37-D04 #949 / E37-D05 #950 /
 * E47-D06 #1305 to confirm, and rewording is an edit to this file alone.
 * User content (node names, parameter values) is interpolated as plain text and must be rendered
 * as a text node, never as markup.
 */
import type { GraphNodeType } from "./graph.js";

export const TYPE_LABEL: Readonly<Record<GraphNodeType, string>> = {
  trigger: "Trigger",
  condition: "Condition",
  action: "Action",
  logicGate: "Logic gate",
  comment: "Comment",
};

/**
 * Input port names in the outline's connection text, "output connects to Multiply input A"
 * (D02 §8 :282, quoting `14`:1867); others read as is.
 */
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

/** The local refusals; a type mismatch speaks the oracle's (rule-graph PORT_COMPAT) sentence. */
export const REFUSAL = {
  /** D02 §15 :414 (PROPOSED there, a D02-A for `ports.ts`), verbatim. */
  occupied: "This input already has a connection.",
  /** PROPOSED: the core's own guards, no D02 string. */
  selfLoop: "A node can't connect to itself.",
  duplicate: "Those ports are already connected.",
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

export const copy = {
  // ---- D02, verbatim ----
  /** D02 §6 P12 :220: the source output port once a connect starts. */
  connectStarted: (type: string): string =>
    `Connecting from output port, ${type} — choose an input`,
  /** D02 §6 :231, O2 :289, §13 :367, §15 :418: a completed connect. */
  connected: (source: string, target: string, input: number): string =>
    `connected ${source} output to ${target} input ${input}`,
  /** D02 O3 :290, §13 :369, §15 :418: Delete on a focused connection. */
  disconnected: (source: string, target: string): string => `Disconnected ${source} from ${target}`,
  /** D02 §13 :368: Esc aborts the connect. */
  cancelled: (): string => "Cancelled",
  /** D02 O1 :288, §15 :418: added connected to the selection. */
  nodeAddedAfter: (name: string, selection: string): string => `Added ${name} after ${selection}`,
  /** D02 §7 :278, §15 :418: added with no compatible port on the selection. */
  nodeAdded: (name: string): string => `Added ${name} — not connected`,
  /** D02 O4 :291, §13 :370, §15 :418 (for every n: plural forms are E37-D05's to add). */
  nodeDeleted: (name: string, connections: number): string =>
    `Deleted ${name} and ${connections} connections`,
  /** D02 §15 :414 (PROPOSED there): a connect that would close a cycle. */
  loop: (source: string, target: string): string =>
    `This would make a loop — ${source} already depends on ${target}.`,
  /** D02 §6 :205, §14 :392: "{Input | Output} port, {type}, {connected to {node} | not connected}". */
  port: (output: boolean, type: string, names: readonly string[]): string =>
    `${output ? "Output" : "Input"} port, ${type}, ` +
    (names.length === 0 ? "not connected" : `connected to ${listOf(names)}`),
  /** D02 §6 P2 / P10 :210, :218: a compatible target during a connect, after its port name. */
  canConnect: (): string => " — can connect",

  // ---- PROPOSED: no D02 string ----
  /** The a11y lens's count at start (A-4), after `connectStarted`. */
  availability: (available: number, unavailable: number): string =>
    `. ${plural(available, "input", "inputs")} available` +
    (unavailable === 0 ? "." : `, ${unavailable} not available.`),
  /** The target node's name before its D02 port name, and the position among available ones. */
  candidate: (target: string, portName: string, index: number, size: number): string =>
    `${target}, ${portName}${copy.canConnect()}, ${index} of ${size}`,
  /** An unavailable target: its port name, then its refusal sentence (D02 §14 :404 picker rule). */
  candidateRefused: (target: string, portName: string, reason: string): string =>
    `${target}, ${portName}. ${reason}`,
  noneAvailable: (): string => "No input can take this connection.",
  /** A refusal at the target is the refusal sentence itself (D02 §6 :231, §13 :367). */
  refused: (reason: string): string => reason,
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
  noOutput: (): string => "No output.",
  noPorts: (): string => "No ports.",
  /** A node's accessible description: type, name, parameters, then each port. */
  node: (type: string, name: string, params: string, ports: string): string =>
    `${type} ${name}, ${params}. ${ports}`,
  position: (index: number, size: number): string => `Node ${index} of ${size}.`,
} as const;
