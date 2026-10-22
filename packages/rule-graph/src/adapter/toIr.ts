// The graph back to rule IR (E37-T01), as the server's `compile_graph` builds it
// (rules/compiler/graph.py:205-248): a shared node expands at each use, and a graph with no IR
// that keeps all of it is refused. Pure and synchronous.
import { MAX_VALUES, checkBounds } from "../canonical/schema.js";
import { check } from "../errors.js";
import type { CommentNode, GraphLayout, GraphModel, GraphNode, RuleIrDraft } from "../model.js";
import { SLOTS, type Tree } from "./toGraph.js";

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

/** The IR of `graph`, which stores `layout` with the graph's comments as its `graph_layout`. */
export function toIr(graph: GraphModel, layout = BLANK): { ir: RuleIrDraft; layout: GraphLayout } {
  const { nodes, edges } = graph; // within the server's caps (rules/compiler/common.py:19-20)
  check(nodes.length <= 1_000 && edges.length <= 4_000, SV, "Over 1 000 nodes or 4 000 edges.");
  const kinds = new Map<string, string>();
  for (const { id, type, data } of nodes) {
    const kind = String(type === "condition" ? data["kind"] : type);
    const known = !kinds.has(id) && KINDS[kind]?.[0] === type;
    check(known, SV, `Node ${id} is a repeat, or of no known kind.`, [id]);
    kinds.set(id, kind);
  }
  const fed = new Map<string, string[]>(); // [target, port]: the sources, in edge order
  const slot = (target: string, port: string) => JSON.stringify([target, port]);
  for (const { id, source, target, targetPort: port } of edges) {
    const [from, to] = [String(kinds.get(source)), String(kinds.get(target))];
    const joins = from in SLOTS && Number(KINDS[to]?.indexOf(port)) > 0;
    check(joins, SV, `Edge ${id} does not join a condition to an input.`, [source, target]);
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
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const built = new Set<string>();
  let budget = MAX_VALUES;
  const build = (id: string, path: readonly string[]): Tree => {
    const cycle = path.slice(path.indexOf(id)); // from `id` back to it, if it repeats
    const loop = `The graph has a cycle: ${[...cycle, id].join(" -> ")}.`;
    check(!path.includes(id), "CYCLE_DETECTED", loop, cycle);
    check(--budget >= 0, SV, `The graph expands past ${MAX_VALUES} nodes.`);
    built.add(id);
    const out: Tree = { ...(byId.get(id) as GraphNode).data };
    delete out["kind"];
    for (const [key, port] of Object.entries(SLOTS[kinds.get(id) as keyof typeof SLOTS])) {
      const sources = [...(fed.get(slot(id, port)) ?? [])];
      const value = out[key];
      const next = () => build(sources.shift() as string, [...path, id]);
      if (Array.isArray(value)) {
        const fits = value.filter((item) => item === null).length === sources.length;
        check(fits, SV, `Node ${id} needs one ${port} edge per empty slot.`, [id]);
        out[key] = value.map((item) => (item === null ? next() : item));
      } else if (sources.length > 0) {
        const once = sources.length === 1 && value === undefined;
        check(once, SV, `Node ${id} has two values for its ${port} input.`, [id]);
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
