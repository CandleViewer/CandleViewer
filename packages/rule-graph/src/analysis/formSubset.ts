// The form subset (24-internal-schemas.md §11.4) as the server tests it, rules/ir/form.py:20-92,
// each reason in form.py's own words (:23-87), which a vector test holds to the server's output.
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { type Tree, isTree } from "../adapter/toGraph.js";
import { byCodePoint } from "../canonical/canonicalise.js";
import { dump } from "../canonical/schema.js";

/** A graph-only construct: the node it sits on, and the server's reason. */
export type FormReason = { nodeId: string; reason: string };
const OPERANDS = ["left", "right", "right2"];
const has = (v: unknown, key: string): v is Tree => isTree(v) && Object.hasOwn(v, key);

/**
 * Why the form editor cannot show `ir`, node by node in form.py's order; none when it can. An IR
 * the canonical mirror cannot read is refused (SCHEMA_VIOLATION), as `canonicalise` refuses it.
 */
export function isFormRepresentable(ir: RuleIr): FormReason[] {
  dump(ir);
  const out: FormReason[] = [];
  const say = (n: Tree, reason: string) => out.push({ nodeId: n["node_id"] as string, reason });
  const operands = (n: Tree) => {
    for (const key of OPERANDS) {
      if (has(n[key], "operands")) say(n, `arithmetic operand in '${key}' (graph-only construct)`);
    }
  };
  const leaf = (n: Tree): void => {
    const [op, child] = [String(n["op"]), n["child"]];
    if (has(n, "children")) say(n, `boolean '${op}' nested deeper than two levels`);
    else if (!has(n, "child")) operands(n);
    else {
      if (op !== "sustained_for") say(n, `temporal op '${op}' is graph-only`);
      const deeper = has(child, "children") || has(child, "child"); // a gate or temporal node
      if (deeper) say(n, "temporal node must directly wrap a comparison");
      else operands(child as Tree);
    }
  };
  const group = (n: Tree, depth: number): void => {
    const op = String(n["op"]);
    if (op !== "all_of" && op !== "any_of") return void say(n, `boolean op '${op}' is graph-only`);
    for (const c of n["children"] as Tree[]) {
      if (!has(c, "children")) leaf(c);
      else if (depth === 0 && op === "all_of" && c["op"] === "any_of") group(c, 1);
      else if (depth === 0 && op === "any_of")
        say(c, "boolean nested inside root any_of (exceeds subset)");
      else leaf(c);
    }
  };
  const root: Tree = { ...ir.conditions }; // a copy, as toGraph reads it
  if (has(root, "children")) group(root, 0);
  else leaf(root);
  // Each node's uses, as form.py counts them: every copy of a shared subtree counts again.
  const uses = new Map<string, number>();
  const count = (n: Tree): void => {
    uses.set(n["node_id"] as string, (uses.get(n["node_id"] as string) ?? 0) + 1);
    const inputs = n["children"] ?? n["operands"] ?? [n["child"], ...OPERANDS.map((k) => n[k])];
    for (const item of inputs as unknown[]) if (has(item, "node_id")) count(item);
  };
  count(root);
  for (const [id, n] of [...uses].sort(([a], [b]) => byCodePoint(a, b))) {
    if (n > 1) say({ node_id: id }, `node fans out to ${n} consumers (shared node, graph-only)`);
  }
  return out;
}
