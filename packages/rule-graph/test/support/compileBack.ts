// The server's graph compile, mirrored for the tests (rules/compiler/graph.py:226-305): what
// `compile_graph` builds from a compile model, with none of its checks. A test helper, never shipped:
// the server stays the compiler, and the contract test holds the models it is sent to its hashes.
import type { CompileModel, CompileNode } from "../../src/index.js";

type Doc = Record<string, unknown>;

export function compileBack(model: CompileModel): Doc {
  const byId = new Map<string, CompileNode>(model.nodes.map((node) => [node.id, node]));
  const ins = new Map<string, Map<string, string[]>>(); // node -> port -> sources, in edge order
  for (const { from, to, port } of model.edges) {
    const ports = ins.get(to) ?? new Map<string, string[]>();
    ports.set(port, [...(ports.get(port) ?? []), from]);
    ins.set(to, ports);
  }
  const actions = model.nodes.filter((node) => node.type === "action");
  const fed = (id: string, port: string): string[] => ins.get(id)?.get(port) ?? [];
  const roots = [...new Set(actions.flatMap((action) => fed(action.id, "when")))].sort();
  const build = (id: string): Doc => {
    const node = byId.get(id) as CompileNode; // the models under test join only their own nodes
    if (node.type === "operand") return { ...node.data };
    const out: Doc = { ...node.data, node_id: id };
    if (node.type === "comparison") {
      for (const port of ["left", "right", "right2"]) {
        const [first] = fed(id, port);
        if (first !== undefined) out[port] = build(first);
      }
    } else if (node.type === "temporal") {
      out["child"] = build(fed(id, "child")[0] as string);
    } else {
      out[node.type === "boolean" ? "children" : "operands"] = fed(id, "in").map(build);
    }
    return out;
  };
  const doc: Doc = { ...model };
  delete doc["nodes"];
  delete doc["edges"];
  return {
    ...doc,
    editor: "graph",
    conditions: build(roots[0] as string),
    actions: actions.map(({ id, data }) => ({ ...data, node_id: id })),
  };
}
