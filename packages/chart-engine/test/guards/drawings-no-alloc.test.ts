// E14-T03: the per-frame path of the drawings layer allocates nothing (31-chart-engine: no
// per-frame allocations). A pan or a drag runs `DrawingsNode.update`, which projects every record
// through `screenBounds`, `extend`, `seg` and `px`; none may build an array, object, closure,
// typed array, spread or string. `reindex` runs only when a record or the bar map changed (DATA).
// Checked on the AST, so the guard is deterministic; a fixture proves it fires. The live half
// (no record or buffer replaced across 100 pans) runs the real node.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";
import { DrawingsNode } from "../../src/layers/drawings/project.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { minuteMap } from "../interaction/fixtures.js";

const FILE = join(dirname(fileURLToPath(import.meta.url)), "../../src/layers/drawings/project.ts");
const HOT = new Set(["update", "screenBounds", "extend", "seg", "px"]);
const ALLOCATING = new Set([
  "NewExpression",
  "ArrayExpression",
  "ObjectExpression",
  "ArrowFunctionExpression",
  "FunctionExpression",
  "SpreadElement",
  "TemplateLiteral",
  "ArrayPattern",
]);
type Node = { type: string; [k: string]: unknown };
/** The hot functions the last `allocations` call found: all five, or the guard checks nothing. */
const seen = new Set<string>();

function visit(n: unknown, cb: (node: Node) => void): void {
  if (Array.isArray(n)) return n.forEach((c) => visit(c, cb));
  if (typeof n !== "object" || n === null || !("type" in n)) return;
  cb(n as Node);
  for (const [k, v] of Object.entries(n)) if (k !== "parent") visit(v, cb);
}

/** The allocating node types inside each hot function's body, as `name: Type`. */
function allocations(code: string): string[] {
  const found: string[] = [];
  seen.clear();
  const named = (x: unknown): string => (x as { name?: string } | null)?.name ?? "";
  visit(tseslint.parser.parseForESLint(code).ast, (node) => {
    let name = "";
    let fn: unknown = null;
    if (node.type === "FunctionDeclaration") [name, fn] = [named(node["id"]), node];
    if (node.type === "MethodDefinition") [name, fn] = [named(node["key"]), node["value"]];
    if (node.type === "VariableDeclarator") [name, fn] = [named(node["id"]), node["init"]];
    if (!HOT.has(name) || fn === null) return;
    seen.add(name);
    visit((fn as Node)["body"], (inner) => {
      if (ALLOCATING.has(inner.type)) found.push(`${name}: ${inner.type}`);
    });
  });
  return found;
}

describe("the drawings layer's per-frame path allocates nothing", () => {
  it("update, screenBounds, extend, seg and px build no array, object, closure or string", () => {
    expect(allocations(readFileSync(FILE, "utf8"))).toEqual([]);
    expect([...seen].sort()).toEqual([...HOT].sort());
  });

  it("the guard fires on a fixture that allocates", () => {
    const code = [
      "class N { update() { const a = [1]; this.f(() => 1); } }",
      "function extend() { return { x: 1 }; }",
      "const px = (v: number) => `${v}`;",
    ].join("\n");
    expect(allocations(code)).toEqual([
      "update: ArrayExpression",
      "update: ArrowFunctionExpression",
      "extend: ObjectExpression",
      "px: TemplateLiteral",
    ]);
  });

  it("100 pans replace no record, typed array or bounds buffer", () => {
    const vp = new ChartViewport(minuteMap());
    vp.setSize(1200, 700, 1);
    vp.setPanePlot(0, 0, 700);
    vp.setPriceRange(0, 0, 2_000);
    const node = new DrawingsNode("n");
    const style = { colour: 0, width: 2, dash: 0 } as const;
    const kinds = ["segment", "ray", "line", "rect", "band", "polyline"] as const;
    const drawings = kinds.map((kind, i) => {
      const points = kind === "band" ? [0, 1, 6e7, 2, 12e7, 3] : [0, 1, 6e7 * (i + 1), 500];
      return { id: kind, kind, points, style };
    });
    node.apply({ op: "replace", drawings });
    const ctx = new FrameContext(vp);
    node.update(ctx);
    const held = node.set.order.flatMap((r) => [r, r.idx, r.box]);
    const { bounds } = node;
    for (let i = 0; i < 100; i += 1) {
      vp.pan(-3);
      node.update(ctx);
    }
    const now = node.set.order.flatMap((r) => [r, r.idx, r.box]);
    expect(now.every((x, i) => x === held[i]) && now.length === held.length).toBe(true);
    expect([node.bounds === bounds, node.reindexed, node.boundsPasses]).toEqual([true, 6, 101]);
  });
});
