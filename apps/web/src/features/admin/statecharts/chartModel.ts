/**
 * A served chart's structure, as the inspector lists it (E42-S08; E42-D05 §11 SI-4). Pure: no React
 * and no DOM. It reads `exportStatechart`'s `stately` projection (the registered chart without the
 * six CV policy keys, `22`) and lists its states and transitions. It never evaluates a guard, never
 * predicts a next state and never asks an interpreter anything (C-2.19 to C-2.22): the current
 * states are the served `configuration`'s, nothing else. A chart over a bound, with a name off its
 * pattern, a shape this reader does not know or a target that does not resolve is no model
 * (`null`): its export reads as unusable, and nothing is guessed.
 */

/** The most states, transition arms and nesting levels a chart may have (B1: 23, 152 and 2). */
export const MAX_STATES = 200;
export const MAX_ARMS = 600;
export const MAX_DEPTH = 6;
/**
 * A chart id or state name. The authoring schema constrains none, so any letter, digit, `_` or `-`
 * reads; a dot never does, as it would make an id (`<root>.<path>`) ambiguous.
 */
const NAME = /^[A-Za-z0-9_-]{1,64}$/;
/** The longest event name, delay or invoked service name read. */
const MAX_EVENT = 64;

export type StateKind = "atomic" | "compound" | "parallel" | "final";

/**
 * How a transition is taken: an event (`on`, the root's included, so from any state), an eventless
 * one (`always`), a delay (`after`), an invoked service finishing (`done`, also a state's own
 * `onDone`) or failing (`error`).
 */
export type EdgeVia = "on" | "always" | "after" | "done" | "error";

export interface ChartState {
  /** `<root>.<path>`: the form `getStatechart`'s `configuration` uses (`kill_switch.clear`). */
  readonly id: string;
  readonly name: string;
  /** The name, or its path under the root when another state of the chart has the same name. */
  readonly label: string;
  /** The parent's id: the root's (`ChartModel.root`) for a top-level state. */
  readonly parent: string;
  readonly kind: StateKind;
  /** The `initial` child of a compound parent (a parallel parent's regions all start together). */
  readonly initial: boolean;
  /** 1 for a top-level state. */
  readonly depth: number;
}

export interface ChartEdge {
  /** The source state's id; `ChartModel.root` for the root's own transitions (from any state). */
  readonly from: string;
  /** The target state's id; `null` for an arm with no target ("no state change"). */
  readonly to: string | null;
  readonly via: EdgeVia;
  /** The event name, the delay (`after`), the invoked service (`done`, `error`) or `""`. */
  readonly event: string;
}

export interface ChartModel {
  /** The export's `machine_kind` and `machine_hash`, as served. */
  readonly kind: string;
  readonly hash: string;
  /** The chart's `id`: the first segment of every state id. */
  readonly root: string;
  readonly rootKind: "compound" | "parallel";
  /** Every state but the root, in document order (depth first). */
  readonly states: readonly ChartState[];
  /** Every transition once per source, target, kind and event, in document order. */
  readonly edges: readonly ChartEdge[];
}

type Json = Record<string, unknown>;

const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);

/** The one way out of a chart this reader refuses: `vetStately` answers `null`. */
class Refused extends Error {}
function refuse(): never {
  throw new Refused("chart refused");
}

interface Node {
  readonly id: string;
  readonly name: string;
  readonly parent: string;
  readonly raw: Json;
  readonly depth: number;
  readonly kind: StateKind;
  readonly initial: boolean;
}

/** A node's children by name, in document order; none when it has no `states`. */
function children(raw: Json): [string, unknown][] {
  const states = raw["states"];
  if (states === undefined) return [];
  if (!isRecord(states)) refuse();
  return Object.entries(states);
}

/** The kind a node's `type` and children make; a history state, or anything unknown, is refused. */
function kindOf(raw: Json, parent: boolean): StateKind {
  const type = raw["type"];
  if (type === undefined) return parent ? "compound" : "atomic";
  if (type === "compound" && parent) return "compound";
  if (type === "parallel" && parent) return "parallel";
  if ((type === "atomic" || type === "final") && !parent) return type;
  return refuse();
}

/** An event, delay or service name: a non-empty string of at most 64 characters. */
function word(value: unknown): string {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_EVENT) refuse();
  return value;
}

/** A transition's arms: a target string, one arm object, or a list of either. */
function armsOf(value: unknown): Json[] {
  const list = Array.isArray(value) ? value : [value];
  return list.map((arm) => {
    if (typeof arm === "string") return { target: arm };
    if (!isRecord(arm)) refuse();
    return arm;
  });
}

/** Builds the model, or throws `Refused`. */
function build(raw: unknown, kind: string, hash: string): ChartModel {
  if (!isRecord(raw)) refuse();
  const root = raw["id"];
  if (typeof root !== "string" || !NAME.test(root)) refuse();
  if (children(raw).length === 0) refuse();
  const rootType = raw["type"];
  if (rootType !== undefined && rootType !== "compound" && rootType !== "parallel") refuse();
  const rootKind = rootType === "parallel" ? "parallel" : "compound";

  const rootNode: Node = {
    id: root,
    name: root,
    parent: "",
    raw,
    depth: 0,
    kind: rootKind,
    initial: false,
  };
  const nodes: Node[] = [];
  const byId = new Map<string, Node>([[root, rootNode]]);
  const walk = (parent: Node): void => {
    const kids = children(parent.raw);
    const initial = parent.raw["initial"];
    if (initial !== undefined && !kids.some(([name]) => name === initial)) refuse();
    for (const [name, child] of kids) {
      if (!NAME.test(name) || !isRecord(child)) refuse();
      if (parent.depth + 1 > MAX_DEPTH || nodes.length + 1 > MAX_STATES) refuse();
      const node: Node = {
        id: `${parent.id}.${name}`,
        name,
        parent: parent.id,
        raw: child,
        depth: parent.depth + 1,
        kind: kindOf(child, children(child).length > 0),
        initial: parent.kind === "compound" && initial === name,
      };
      nodes.push(node);
      byId.set(node.id, node);
      walk(node);
    }
  };
  walk(rootNode);

  /** A target's state id: `#<root>.<path>`, `.child` (under the source) or a sibling's name. */
  const resolve = (target: string, source: Node): string => {
    let id: string;
    if (target.startsWith("#")) id = target.slice(1);
    else if (target.startsWith(".")) id = `${source.id}${target}`;
    else if (source !== rootNode) id = `${source.parent}.${target}`;
    else return refuse(); // a bare name from the root names no sibling
    if (id === root || !byId.has(id)) refuse();
    return id;
  };
  const targets = (arm: Json, source: Node): (string | null)[] => {
    const target = arm["target"];
    if (target === undefined) return [null];
    if (typeof target === "string") return [resolve(target, source)];
    if (!Array.isArray(target)) return refuse();
    if (target.length === 0) return [null];
    return target.map((t) => (typeof t === "string" ? resolve(t, source) : refuse()));
  };

  const edges: ChartEdge[] = [];
  const seen = new Set<string>();
  let arms = 0;
  const add = (source: Node, value: unknown, via: EdgeVia, event: string): void => {
    for (const arm of armsOf(value)) {
      arms += 1;
      if (arms > MAX_ARMS) refuse();
      for (const to of targets(arm, source)) {
        const seenAs = `${source.id}|${to ?? ""}|${via}|${event}`;
        if (seen.has(seenAs)) continue;
        seen.add(seenAs);
        edges.push({ from: source.id, to, via, event });
      }
    }
  };
  const invokes = (source: Node, value: unknown): void => {
    for (const invoke of Array.isArray(value) ? value : [value]) {
      if (!isRecord(invoke)) refuse();
      const src = invoke["src"];
      const service = word(typeof src === "string" ? src : invoke["id"]);
      if (invoke["onDone"] !== undefined) add(source, invoke["onDone"], "done", service);
      if (invoke["onError"] !== undefined) add(source, invoke["onError"], "error", service);
    }
  };
  // Each node's transitions in its own key order, so the list reads as the chart is written.
  for (const node of [rootNode, ...nodes]) {
    for (const [field, value] of Object.entries(node.raw)) {
      if (field === "on" || field === "after") {
        if (!isRecord(value)) refuse();
        for (const [event, arm] of Object.entries(value)) add(node, arm, field, word(event));
      } else if (field === "always") {
        add(node, value, "always", "");
      } else if (field === "invoke") {
        invokes(node, value);
      } else if (field === "onDone") {
        add(node, value, "done", node.name);
      }
    }
  }

  const named = new Map<string, number>();
  for (const node of nodes) named.set(node.name, (named.get(node.name) ?? 0) + 1);
  const states = nodes.map((node): ChartState => ({
    id: node.id,
    name: node.name,
    label: (named.get(node.name) ?? 0) > 1 ? node.id.slice(root.length + 1) : node.name,
    parent: node.parent,
    kind: node.kind,
    initial: node.initial,
    depth: node.depth,
  }));
  return { kind, hash, root, rootKind, states, edges };
}

/**
 * The model of an exported chart (`StatechartExport.stately`), with the export's `machine_kind` and
 * `machine_hash`; `null` when this reader refuses it (a bound, a name, a shape or a target).
 */
export function vetStately(raw: unknown, kind: string, hash: string): ChartModel | null {
  try {
    return build(raw, kind, hash);
  } catch (error) {
    if (error instanceof Refused) return null;
    throw error;
  }
}

/**
 * The current states: the leaves of the served `configuration` (every active state id, ancestors
 * included, `22` `getStatechart`) that the model knows. Read from the configuration alone, never
 * from events.
 */
export function currentIds(
  model: ChartModel,
  configuration: readonly string[],
): ReadonlySet<string> {
  const active = new Set(configuration);
  const known = model.states.filter((state) => active.has(state.id));
  const parents = new Set(known.map((state) => state.parent));
  return new Set(known.filter((state) => !parents.has(state.id)).map((state) => state.id));
}
