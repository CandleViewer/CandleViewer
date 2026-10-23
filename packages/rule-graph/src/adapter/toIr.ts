// The graph back to rule IR (E37-T01), as the server's `compile_graph` builds it
// (rules/compiler/graph.py:205-248): a shared node expands at each use, and a graph with no IR
// that keeps all of it is refused. Pure and synchronous.
import { MAX_VALUES, checkBounds } from "../canonical/schema.js";
import { check } from "../errors.js";
import type { CommentNode, GraphEdge, GraphLayout, GraphModel, GraphNode } from "../model.js";
import type { RuleIrDraft } from "../model.js";
import { SLOTS, type Tree, isTree } from "./toGraph.js";

const SV = "SCHEMA_VIOLATION";
/** Per node kind (a condition's `data.kind`, else the node type): its type, then its inputs. */
const KINDS: Readonly<Record<string, readonly string[]>> = {
  trigger: ["trigger"],
  comment: ["comment"],
  action: ["action", "when"],
  logicGate: ["logicGate", "in"],
  comparison: ["condition", "left", "right", "right2"],
  temporal: ["condition", "child"],
  arithmetic: ["condition", "in"],
};
const BLANK: GraphLayout = { positions: {}, collapsed: [], comments: [], extra: {} };
const named = (...ids: unknown[]) => ids.filter((id): id is string => typeof id === "string");

/**
 * The IR of `graph`, which stores `layout` with the graph's comments as its `graph_layout`. The
 * layout defaults to an empty one, so stored positions need the caller's layout passed in.
 */
export function toIr(graph: GraphModel, layout = BLANK): { ir: RuleIrDraft; layout: GraphLayout } {
  const { nodes = [], edges = [] }: Partial<GraphModel> = isTree(graph) ? graph : {};
  // Lists, within the server's caps (rules/compiler/common.py:19-20).
  const fits = Array.isArray(nodes) && Array.isArray(edges) && nodes.length <= 1_000;
  check(fits && edges.length <= 4_000, SV, "Over 1 000 nodes or 4 000 edges, or not lists.");
  const kinds = new Map<string, string>();
  for (const node of nodes) {
    const { id, type, data } = (isTree(node) ? node : {}) as GraphNode;
    const kind = String(type === "condition" ? data?.["kind"] : type);
    const known =
      typeof id === "string" && isTree(data) && !kinds.has(id) && KINDS[kind]?.[0] === type;
    check(known, SV, `Node ${id} is malformed, a repeat or of no known kind.`, named(id));
    kinds.set(id, kind);
  }
  const fed = new Map<string, string[]>(); // [target, port]: the sources, in edge order
  const slot = (target: string, port: string) => JSON.stringify([target, port]);
  for (const edge of edges) {
    const { id, source, target, targetPort: port } = (isTree(edge) ? edge : {}) as GraphEdge;
    const [from, to] = [String(kinds.get(source)), String(kinds.get(target))];
    const joins = from in SLOTS && Number(KINDS[to]?.indexOf(port)) > 0;
    check(joins, SV, `Edge ${id} does not join a condition to an input.`, named(source, target));
    fed.set(slot(target, port), [...(fed.get(slot(target, port)) ?? []), source]);
  }
  const triggers = nodes.filter((node) => node.type === "trigger");
  const triggerIds = triggers.map((node) => node.id);
  check(triggerIds.length === 1, SV, "A graph has one trigger node.", triggerIds);
  const actions = nodes.filter((node) => node.type === "action");
  const roots = new Set<string>();
  for (const { id } of actions) {
    const sources = fed.get(slot(id, "when")) ?? [];
    check(sources.length > 0, "DANGLING_PORT", `No condition feeds action ${id}.`, [id]);
    sources.forEach((source) => roots.add(source));
  }
  const sinks = [...roots];
  check(sinks.length < 2, "MULTIPLE_SINKS", `The actions hang off ${sinks.join(", ")}.`, sinks);
  const twice = actions.find(({ id }) => (fed.get(slot(id, "when")) as string[]).length > 1)?.id;
  const repeat = `Action ${twice} has more than one condition feeding it.`; // graph.py:166-174
  check(twice === undefined, "MULTIPLE_SINKS", repeat, [String(twice)]);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const built = new Set<string>();
  let budget = MAX_VALUES; // the values the copies add, each charged before it is made
  const over = `The graph expands past ${MAX_VALUES} values.`;
  const spend = (n: number) => check((budget -= n) >= 0, SV, over);
  const build = (id: string, path: readonly string[]): Tree => {
    const cycle = path.slice(path.indexOf(id)); // from `id` back to it, if it repeats
    const loop = `The graph has a cycle: ${[...cycle, id].join(" -> ")}.`;
    check(!path.includes(id), "CYCLE_DETECTED", loop, cycle);
    const { data } = byId.get(id) as GraphNode;
    spend(1 + Object.keys(data).length); // a copy adds at least as many: never past checkBounds
    built.add(id);
    const out: Tree = { ...data };
    delete out["kind"];
    for (const [key, port] of Object.entries(SLOTS[kinds.get(id) as keyof typeof SLOTS])) {
      const sources = [...(fed.get(slot(id, port)) ?? [])];
      const next = () => build(sources.shift() as string, [...path, id]);
      if (port === "in") {
        const list = out[key] ?? sources.map(() => null); // none: a slot per edge, as the server
        const holes = Array.isArray(list) ? list.filter((item) => item === null).length : -1;
        check(holes === sources.length, SV, `Node ${id} needs an edge per empty slot.`, [id]);
        spend((list as unknown[]).length - holes);
        out[key] = (list as unknown[]).map((item) => (item === null ? next() : item));
      } else if (sources.length > 0) {
        const once = sources.length === 1 && out[key] == null; // an edge fills a null input
        check(once, SV, `Node ${id} has two values for its ${port} input.`, [id]);
        budget += Number(key in out); // refund the null the edge replaces: its node is charged
        out[key] = next();
      }
    }
    return { ...out, node_id: id };
  };
  const conditions = sinks.length === 0 ? {} : { conditions: build(sinks[0] as string, []) };
  const lost = nodes.filter((node) => /^(condition|logicGate)$/.test(node.type));
  const orphans = lost.filter((node) => !built.has(node.id)).map((node) => node.id);
  check(orphans.length === 0, "ORPHAN_NODE", `No action follows ${orphans.join(", ")}.`, orphans);
  const notes = nodes.filter((node) => node.type === "comment");
  const comments = notes.map(({ id, data }) => ({ ...data, id }) as CommentNode);
  const { extra, positions, collapsed } = layout;
  const ir = {
    ...graph.envelope,
    trigger: (triggers[0] as GraphNode).data,
    ...conditions,
    actions: actions.map(({ id, data }) => ({ ...data, node_id: id })),
    graph_layout: { ...extra, positions, collapsed, comments },
  };
  checkBounds(ir);
  return { ir, layout: { ...layout, comments } };
}
