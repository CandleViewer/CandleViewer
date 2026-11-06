// Shared fixtures for the rule-builder-graph tests: the production port oracle (E37-S01's
// `model/portOracle.ts`, built from @candleviewer/rule-graph's own `portsOf` / `canConnect`, never a
// hand copy: BQ-12 (d), record 6563473726), node and edge builders, and a seeded PRNG.
import type {
  A11yGraph,
  GraphEdge,
  GraphNode,
} from "../../../src/features/rule-builder-graph/a11y/graph.js";

export { portOracle as oracle } from "../../../src/features/rule-builder-graph/model/portOracle.js";

export const node = (
  id: string,
  type: GraphNode["type"],
  data: Record<string, unknown> = {},
): GraphNode => ({ id, type, data });

export const edge = (
  id: string,
  source: string,
  target: string,
  targetPort: string,
): GraphEdge => ({
  id,
  source,
  sourcePort: "out",
  target,
  targetPort,
});

/** A small rule: trigger; a > b and c < d under an AND gate; the gate runs two actions. */
export const RULE: A11yGraph = {
  nodes: [
    node("trigger", "trigger", { name: "On bar close" }),
    node("cmp1", "condition", { kind: "comparison", name: "ATR above", op: "gt", value: 14 }),
    node("cmp2", "condition", { kind: "comparison", op: "lt" }),
    node("and", "logicGate", { op: "and", name: "AND" }),
    node("act1", "action", { name: "Alert", channel: "toast" }),
    node("act2", "action", { name: "Log" }),
    node("note", "comment", { text: "why" }),
  ],
  edges: [
    edge("e1", "cmp1", "and", "in"),
    edge("e2", "cmp2", "and", "in"),
    edge("e3", "and", "act1", "when"),
    edge("e4", "and", "act2", "when"),
  ],
};

/** mulberry32: a deterministic PRNG for the property-style sweeps. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TYPES: [GraphNode["type"], string | undefined][] = [
  ["trigger", undefined],
  ["condition", "comparison"],
  ["condition", "arithmetic"],
  ["logicGate", undefined],
  ["action", undefined],
  ["comment", undefined],
];

/** A random graph: any edges at all, loops, self-loops and dangling ends included. */
export function randomGraph(rand: () => number, maxNodes = 12): A11yGraph {
  const n = 1 + Math.floor(rand() * maxNodes);
  const nodes = Array.from({ length: n }, (_, i) => {
    const [type, kind] = TYPES[Math.floor(rand() * TYPES.length)] as (typeof TYPES)[number];
    return node(`n${i}`, type, kind === undefined ? {} : { kind });
  });
  const m = Math.floor(rand() * n * 1.5);
  const pick = (): string => `n${Math.floor(rand() * (n + 1))}`; // n<n> is dangling
  const edges = Array.from({ length: m }, (_, i) => edge(`e${i}`, pick(), pick(), "in"));
  return { nodes, edges };
}

export function shuffle<T>(rand: () => number, items: readonly T[]): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j] as T, out[i] as T];
  }
  return out;
}
