// E37-S01: the rule-graph editor's generated fixtures (E37-D05 hand-off §D; E37-D03 §11.1). The
// 60-node auto-layout review graph, the first Tier B graph (it plus one comparison), the first Tier
// C graph (a long `all_of` of comparisons, nested to the IR's 32-child bound) and the 200-node
// benchmark graph (about 260 edges: shared comparisons feed a second gate). Each is `{model,
// layout}`, a rule-graph GraphModel and GraphLayout: ids n1…, positions on the 240-unit grid,
// version 3, every timestamp 13:42:10 UTC. Seeded (mulberry32): no wall clock, no random id.
// `node scripts/rule-graph-editor.mjs` writes them; test/rule-graph-editor.test.mjs fails on drift.
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { mulberry32 } from "../src/synthetic-ticks.mjs";

export const EDITOR_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "golden/rule-graph/editor",
);
/** The grid step, both axes, in canvas units. */
export const GRID = 240;
/** 13:42:10 UTC on 2026-10-24 (E37-D02's base date), in milliseconds. */
export const SAVED_AT = Date.UTC(2026, 9, 24, 13, 42, 10);
const MAX_CHILDREN = 32; // the IR's BooleanNode bound (rules/ir/rule-ir.json)
const METRICS = ["price", "atr", "rsi", "vwap", "cvd", "spread_bps"];
const ACTIONS = [
  { type: "modify_stop_loss", params: { mode: "atr", value: 2, only_tighten: true } },
  { type: "send_notification", params: { channel: "ui" } },
  { type: "flatten_position", params: {} },
];

/** The rule's other fields, as every editor fixture carries them. */
export function envelope(ruleId, name) {
  return {
    rule_id: ruleId,
    version: 3,
    name,
    description: "",
    enabled: false,
    mode: "disabled",
    scope: { level: "position", symbols: ["BTCUSDT"], environments: ["demo"] },
    limits: {},
    editor: "graph",
    ir_version: 1,
    created_at: SAVED_AT,
    updated_at: SAVED_AT,
  };
}

/** A graph under construction: ids n1… and e1… in creation order. */
function builder() {
  const nodes = [];
  const edges = [];
  const add = (type, data) => {
    const node = { id: `n${nodes.length + 1}`, type, data };
    nodes.push(node);
    return node;
  };
  const link = (source, target, targetPort) => {
    edges.push({
      id: `e${edges.length + 1}`,
      source: source.id,
      sourcePort: "out",
      target: target.id,
      targetPort,
    });
    if (targetPort === "in") target.data.children.push(null); // an item per `in` edge
  };
  return { nodes, edges, add, link };
}

/** Columns by producer depth (trigger 0, a comparison 1, a gate past its inputs, actions last). */
function layoutOf(nodes, edges) {
  const inputs = new Map(nodes.map((node) => [node.id, []]));
  for (const edge of edges) inputs.get(edge.target)?.push(edge.source);
  const column = new Map();
  const depth = (node) => {
    if (!column.has(node.id)) {
      const from = (inputs.get(node.id) ?? []).map((id) => depth(nodes.find((n) => n.id === id)));
      column.set(node.id, node.type === "trigger" ? 0 : Math.max(0, ...from) + 1);
    }
    return column.get(node.id);
  };
  const rows = new Map();
  const positions = {};
  for (const node of nodes) {
    const x = depth(node);
    const y = rows.get(x) ?? 0;
    rows.set(x, y + 1);
    positions[node.id] = { x: x * GRID, y: y * GRID };
  }
  return { positions, collapsed: [], comments: [], extra: {} };
}

const comparison = (rand) => ({
  kind: "comparison",
  op: ["gt", "lt", "gte", "lte"][Math.floor(rand() * 4)],
  left: { metric: METRICS[Math.floor(rand() * METRICS.length)] },
  right: { const: Math.floor(rand() * 100) },
});

/**
 * A rule of `count` nodes: the trigger, a tree of gates and comparisons under one root `all_of`
 * (a gate about one node in `gateEvery`, each gate given its first input next), `actions` actions
 * run by the root, then `shared` edges from a comparison into a second gate.
 */
function treeRule({ ruleId, name, count, actions, seed, gateEvery, shared }) {
  const rand = mulberry32(seed);
  const g = builder();
  g.add("trigger", { type: "on_bar_close", timeframe: "1m" });
  const root = g.add("logicGate", { op: "all_of", children: [] });
  const gates = [root];
  const conditions = count - 1 - actions;
  let first = null; // a gate still waiting for its first input
  for (let made = 1; made < conditions; made++) {
    const open = gates.filter((gate) => gate.data.children.length < MAX_CHILDREN);
    const parent = first ?? open[Math.floor(rand() * open.length)];
    const gate = conditions - made > 1 && Math.floor(rand() * gateEvery) === 0;
    const op = rand() < 0.5 ? "all_of" : "any_of";
    const node = gate
      ? g.add("logicGate", { op, children: [] })
      : g.add("condition", comparison(rand));
    g.link(node, parent, "in");
    first = gate ? node : null;
    if (gate) gates.push(node);
  }
  const leaves = g.nodes.filter((node) => node.type === "condition");
  for (let made = 0; made < shared;) {
    const leaf = leaves[Math.floor(rand() * leaves.length)];
    const into = gates[Math.floor(rand() * gates.length)];
    const joined = g.edges.some((edge) => edge.source === leaf.id && edge.target === into.id);
    if (joined || into.data.children.length >= MAX_CHILDREN) continue;
    g.link(leaf, into, "in");
    made++;
  }
  for (let i = 0; i < actions; i++)
    g.link(root, g.add("action", ACTIONS[i % ACTIONS.length]), "when");
  return {
    model: { envelope: envelope(ruleId, name), nodes: g.nodes, edges: g.edges },
    layout: layoutOf(g.nodes, g.edges),
  };
}

/** `count` nodes: the trigger, one action, and the root `all_of` over `all_of` groups of comparisons. */
function longAllOf({ ruleId, name, count, seed }) {
  const rand = mulberry32(seed);
  const g = builder();
  g.add("trigger", { type: "on_bar_close", timeframe: "1m" });
  const root = g.add("logicGate", { op: "all_of", children: [] });
  const below = count - 3; // the groups and their comparisons
  const groups = Array.from({ length: Math.ceil(below / (MAX_CHILDREN + 1)) }, () => {
    const group = g.add("logicGate", { op: "all_of", children: [] });
    g.link(group, root, "in");
    return group;
  });
  for (let i = 0; i < below - groups.length; i++)
    g.link(g.add("condition", comparison(rand)), groups[i % groups.length], "in");
  g.link(root, g.add("action", ACTIONS[0]), "when");
  return {
    model: { envelope: envelope(ruleId, name), nodes: g.nodes, edges: g.edges },
    layout: layoutOf(g.nodes, g.edges),
  };
}

/** The four generated fixtures, by file name. */
export function editorFixtures() {
  const review = treeRule({
    ruleId: "00000000-0000-4000-8000-0000000e3707",
    name: "Auto-layout review graph",
    count: 60,
    actions: 2,
    seed: 60,
    gateEvery: 5,
    shared: 0,
  });
  // review-60 plus one comparison into the root: the first Tier B graph.
  const rand = mulberry32(61);
  const { nodes, edges, envelope: head } = JSON.parse(JSON.stringify(review.model));
  const root = nodes.find((node) => node.id === "n2");
  const added = { id: `n${nodes.length + 1}`, type: "condition", data: comparison(rand) };
  root.data.children.push(null);
  const tierB = {
    model: {
      envelope: {
        ...head,
        rule_id: "00000000-0000-4000-8000-0000000e3708",
        name: "First Tier B graph",
      },
      nodes: [...nodes, added],
      edges: [
        ...edges,
        {
          id: `e${edges.length + 1}`,
          source: added.id,
          sourcePort: "out",
          target: root.id,
          targetPort: "in",
        },
      ],
    },
  };
  tierB.layout = layoutOf(tierB.model.nodes, tierB.model.edges);
  return {
    "review-60": review,
    "tier-b-61": tierB,
    "over-budget-121": longAllOf({
      ruleId: "00000000-0000-4000-8000-0000000e3709",
      name: "First Tier C graph",
      count: 121,
      seed: 121,
    }),
    "budget-200": treeRule({
      ruleId: "00000000-0000-4000-8000-0000000e370a",
      name: "Benchmark graph",
      count: 200,
      actions: 3,
      seed: 200,
      gateEvery: 6,
      shared: 62,
    }),
  };
}

// Run directly (`node scripts/rule-graph-editor.mjs`), it writes the four files; imported, it
// only builds them.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  for (const [name, fixture] of Object.entries(editorFixtures())) {
    // Compact: the commit hook's prettier lays it out, keeping each short object on one line.
    writeFileSync(join(EDITOR_DIR, `${name}.json`), `${JSON.stringify(fixture)}\n`);
  }
}
