// The rule editor's typed ports (E37-T01): the types, which output feeds which input, why not.
import { isTree } from "./adapter/toGraph.js";
import { check } from "./errors.js";
import type { GraphNode } from "./model.js";

const frozen = <T extends object>(value: T): T => {
  for (const item of Object.values(value)) if (typeof item === "object" && item) frozen(item);
  return Object.freeze(value);
};
const TYPES = ["boolean", "number", "price", "side", "action", "trigger"] as const;
/** The port types: CMP-237's, and the trigger's. */
export const PORT_TYPES = frozen(TYPES);
export type PortType = (typeof PORT_TYPES)[number];
/**
 * PORT_COMPAT[from][to]: true when an output of type `from` may feed an input of type `to`, else
 * why not. Only these connect: a true or false result to a gate, temporal node or action, a side to
 * a side, and a number or a price to either (rules/validator.py:134, :157 checks their units).
 * DRAFT wording for E37-D04/D05 sign-off (OQ9): the reason a screen reader announces (E37-S05),
 * by E09-D09 §3.1's rule (docs/design/E09/E09-D09.md:85): one sentence with a full stop, at most
 * 80 characters, no user data, naming the capability. Rewording is an edit to this table alone.
 */
export const PORT_COMPAT = frozen({
  boolean: {
    boolean: true,
    number: "A true or false result can't be used as a number.",
    price: "A true or false result can't be used as a price.",
    side: "A true or false result can't be used as a side.",
    action: true,
    trigger: "A true or false result can't connect to a trigger.",
  },
  number: {
    boolean: "A number can't be used as true or false.",
    number: true,
    price: true,
    side: "A number can't be used as a side.",
    action: "A number can't run an action.",
    trigger: "A number can't connect to a trigger.",
  },
  price: {
    boolean: "A price can't be used as true or false.",
    number: true,
    price: true,
    side: "A price can't be used as a side.",
    action: "A price can't run an action.",
    trigger: "A price can't connect to a trigger.",
  },
  side: {
    boolean: "A side can't be used as true or false.",
    number: "A side can't be used as a number.",
    price: "A side can't be used as a price.",
    side: true,
    action: "A side can't run an action.",
    trigger: "A side can't connect to a trigger.",
  },
  action: {
    boolean: "An action can't be used as true or false.",
    number: "An action can't be used as a number.",
    price: "An action can't be used as a price.",
    side: "An action can't be used as a side.",
    action: "An action can't run another action.",
    trigger: "An action can't connect to a trigger.",
  },
  trigger: {
    boolean: "A trigger can't be used as true or false.",
    number: "A trigger can't be used as a number.",
    price: "A trigger can't be used as a price.",
    side: "A trigger can't be used as a side.",
    action: "A trigger can't run an action without a condition.",
    trigger: "A trigger can't connect to another trigger.",
  },
} as const satisfies Record<PortType, Record<PortType, true | string>>);
export type Connect = { ok: true } | { ok: false; reason: string };

/** Whether an output of type `from` may feed an input of type `to`: PORT_COMPAT's answer. */
export function canConnect(from: PortType, to: PortType): Connect {
  const known = PORT_TYPES.includes(from) && PORT_TYPES.includes(to);
  check(known, "SCHEMA_VIOLATION", `Not a pair of port types: ${String(from)}, ${String(to)}.`);
  const cell: true | string = PORT_COMPAT[from][to];
  return cell === true ? { ok: true } : { ok: false, reason: cell };
}
const OPERANDS = { left: "number", right: "number", right2: "number" } as const;
/** Per node kind (a condition's `data.kind`, else its type): its type, output and inputs. Every
 * input needs an edge or an inline operand (rules/compiler/graph.py:118-139). */
export const NODE_PORTS = frozen({
  trigger: { type: "trigger", output: "trigger", inputs: {} },
  comment: { type: "comment", output: null, inputs: {} },
  action: { type: "action", output: null, inputs: { when: "action" } },
  logicGate: { type: "logicGate", output: "boolean", inputs: { in: "boolean" } },
  comparison: { type: "condition", output: "boolean", inputs: OPERANDS },
  temporal: { type: "condition", output: "boolean", inputs: { child: "boolean" } },
  arithmetic: { type: "condition", output: "number", inputs: { in: "number" } },
} as const);
export type NodeKind = keyof typeof NODE_PORTS;
export type NodePorts = { kind: NodeKind; output: PortType | null; inputs: [string, PortType][] };
type Kind = { type: string; output: PortType | null; inputs: Readonly<Record<string, PortType>> };
// The operands a comparison op takes (graph.py:130-138); any other op takes two.
const ONE = ["is_true", "is_false", "changed", "in_set", "not_in_set"];
const ARITY = new Map([...ONE.map((op) => [op, 1] as const), ["between", 3], ["outside", 3]]);
/** The ports of `node`: its kind's (an output of null: none), a comparison's as its op needs. */
export function portsOf(node: GraphNode): NodePorts {
  const { id, type, data } = (isTree(node) ? node : {}) as Partial<GraphNode>;
  const kind = String(type === "condition" && isTree(data) ? data["kind"] : type) as NodeKind;
  const entry: Kind | undefined = Object.hasOwn(NODE_PORTS, kind) ? NODE_PORTS[kind] : undefined;
  const ok = typeof id === "string" && isTree(data) && entry !== undefined && entry.type === type;
  const ids = typeof id === "string" ? [id] : [];
  check(ok, "SCHEMA_VIOLATION", `Node ${String(id)} is malformed or of no known kind.`, ids);
  const inputs = Object.entries((entry as Kind).inputs);
  const op = String((data as GraphNode["data"])["op"]);
  const arity = kind === "comparison" ? (ARITY.get(op) ?? 2) : inputs.length;
  return { kind, output: (entry as Kind).output, inputs: inputs.slice(0, arity) };
}
// A metric descriptor's units and value types (rules/vocabulary/registry.py:14-17).
const NUMBERS = ["qty", "notional", "ratio", "pct", "bps", "count", "ms", "zscore"] as const;
const OWN = { price: "price", enum: "side", bool: "boolean" } as const;
export type MetricUnit = (typeof NUMBERS)[number] | keyof typeof OWN;
export type MetricValueType = "number" | "bool" | "enum" | "series";

/** A metric's port type by its unit, as the server types a vocabulary signal (vocabulary/build.py:
 * 32-38): an enum is a side. A series is not one value: it has none, as has a unit not listed. */
export function portTypeOfMetric(unit: MetricUnit, valueType: MetricValueType) {
  if (valueType === "series") return undefined;
  if (Object.hasOwn(OWN, unit)) return OWN[unit as keyof typeof OWN];
  return (NUMBERS as readonly string[]).includes(unit) ? ("number" as const) : undefined;
}
