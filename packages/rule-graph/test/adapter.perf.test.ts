// E37-T01's budget: toGraph, toIr and canonicalise each take <= 20 ms on a 200-node graph (the
// ticket's performance notes: they run on save and on a mode switch, inside SCR-082's 500 ms). The
// median of 9 runs of 5 calls after a warm-up holds it, with a wide margin. The scaling is the best
// run's ratio from 200 nodes to toIr's cap of 1 000, a 5x size: linear is x5 and quadratic x25, and
// the bound keeps protocol's 2.5x slack on linear (packages/protocol/test/cvwb-decode.perf.test.ts,
// its bestMs). The perf project: no coverage.
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, it } from "vitest";
import { toGraph } from "../src/adapter/toGraph.js";
import { toIr } from "../src/adapter/toIr.js";
import { canonicalise } from "../src/canonical/canonicalise.js";

/** A rule of 3 + `gates` + 2 x `leaves` graph nodes: the trigger, an action and an all_of root
 * over any_of gates, each leaf a comparison with an arithmetic operand. */
function rule(gates: number, leaves: number): RuleIr {
  const operands = [{ metric: "price", params: { n: 14 } }, { const: 1.5 }];
  const left = (i: number) => ({ node_id: `x${i}`, op: "add", operands });
  const leaf = (i: number) => ({ node_id: `c${i}`, op: "gt", left: left(i), right: { const: i } });
  const gate = (g: number) => ({ node_id: `g${g}`, op: "any_of", children: [] as object[] });
  const children = Array.from({ length: gates }, (_, g) => gate(g));
  for (let i = 0; i < leaves; i++) children[i % gates]?.children.push(leaf(i));
  const conditions = { node_id: "root", op: "all_of", children };
  const actions = [{ node_id: "a1", type: "send_notification", params: { channel: "ui" } }];
  const envelope = { rule_id: "00000000-0000-4000-8000-000000000001", version: 1, name: "budget" };
  const settings = { enabled: true, mode: "simulate", scope: { level: "symbol" } };
  const trigger = { type: "on_price_update" };
  return { ...envelope, ...settings, trigger, conditions, actions } as unknown as RuleIr;
}

/** A call's times, fastest first: 9 timed runs of 5 calls each, after 20 untimed calls. */
function timesMs(run: () => unknown): number[] {
  for (let i = 0; i < 20; i++) run();
  const times = Array.from({ length: 9 }, () => {
    const start = performance.now();
    for (let i = 0; i < 5; i++) run();
    return (performance.now() - start) / 5;
  });
  return times.sort((a, b) => a - b);
}

const STEPS = ["toGraph", "toIr", "canonicalise"] as const;
function steps(doc: RuleIr): Record<(typeof STEPS)[number], () => unknown> {
  const graph = toGraph(doc);
  const { ir } = toIr(graph); // what a save hashes
  return {
    toGraph: () => toGraph(doc),
    toIr: () => toIr(graph),
    canonicalise: () => canonicalise(ir),
  };
}
const [SMALL, LARGE] = [rule(7, 95), rule(33, 482)]; // 1 000 nodes, about 7 400 values

describe("the adapter's budget: 20 ms per step on a 200-node graph (E37-T01)", () => {
  it("builds rules of 200 and 1 000 graph nodes", () => {
    expect([toGraph(SMALL).nodes.length, toGraph(LARGE).nodes.length]).toEqual([200, 1_000]);
  });

  it.each(STEPS)("%s on 200 nodes: the median of 9 runs is at most 20 ms", (step) => {
    const ms = timesMs(steps(SMALL)[step])[4] as number; // the median
    console.info(`${step}, 200 nodes: ${ms.toFixed(3)} ms (median of 9)`);
    expect(ms).toBeGreaterThan(0);
    expect(ms).toBeLessThanOrEqual(20);
  });

  it.each(STEPS)("%s scales linearly: 1 000 nodes take under 12.5 times as long as 200", (step) => {
    const best = (doc: RuleIr) => timesMs(steps(doc)[step])[0] as number; // protocol's bestMs
    const ratio = best(LARGE) / best(SMALL);
    console.info(`${step}, 1 000:200 nodes: x${ratio.toFixed(2)} time (best of 9)`);
    expect(ratio).toBeLessThan(12.5); // linear x5, quadratic x25
  });
});
