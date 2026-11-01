import { describe, expect, it } from "vitest";
import { REFUSAL } from "../../../src/features/rule-builder-graph/a11y/copy.js";
import type { A11yGraph } from "../../../src/features/rule-builder-graph/a11y/graph.js";
import {
  disconnect,
  IDLE,
  stepPortSelection,
  verdictFor,
  type PortEvent,
  type PortSelection,
} from "../../../src/features/rule-builder-graph/a11y/portSelection.js";
import { edge, node, oracle, randomGraph, rng, RULE } from "./fixtures.js";

const run = (graph: A11yGraph, events: PortEvent[], from: PortSelection = IDLE) => {
  let state = from;
  const effects = events.map((event) => {
    const step = stepPortSelection(state, event, graph, oracle);
    state = step.state;
    return step.effect;
  });
  return { state, effects };
};

const AUTHORED: A11yGraph = {
  nodes: [
    node("trigger", "trigger"),
    node("cmp", "condition", { kind: "comparison", name: "Price above" }),
    node("act", "action", { name: "Alert" }),
  ],
  edges: [],
};

describe("port selection: Gherkin 1, an edge connected without a pointer", () => {
  it("starts on the source output, cycles to the target input, and Enter connects", () => {
    const { state, effects } = run(AUTHORED, [
      { type: "start", node: "cmp" },
      { type: "cycle", step: 1 },
      { type: "confirm" },
    ]);
    expect(effects[0]).toEqual({
      kind: "announce",
      text: "Connecting from Price above output. Choose an input, then press Enter. Escape cancels.",
    });
    expect(effects[1]).toEqual({ kind: "announce", text: "Alert run when, 1 of 1." });
    expect(effects[2]).toEqual({
      kind: "connect",
      edge: { source: "cmp", sourcePort: "out", target: "act", targetPort: "when" },
      text: "Connected Price above output to Alert run when.",
    });
    expect(state).toBe(IDLE);
  });

  it("a Tab-picked target connects the same way", () => {
    const { effects } = run(AUTHORED, [
      { type: "start", node: "cmp" },
      { type: "pick", node: "act", port: "when" },
      { type: "confirm" },
    ]);
    expect(effects[2]?.kind).toBe("connect");
  });
});

describe("port selection: refusals keep the connection pending", () => {
  it("announces an unavailable candidate with its reason and refuses its confirm", () => {
    const { state, effects } = run(RULE, [
      { type: "start", node: "cmp2" },
      { type: "pick", node: "act1", port: "when" },
      { type: "confirm" },
    ]);
    expect(effects[1]).toEqual({
      kind: "announce",
      text: "Alert run when not available. That input already has a connection.",
    });
    expect(effects[2]).toMatchObject({ kind: "refuse", reason: REFUSAL.occupied });
    expect(state.kind).toBe("pending");
  });

  it("cycles backwards and wraps", () => {
    const { state } = run(RULE, [
      { type: "start", node: "cmp1" },
      { type: "cycle", step: -1 },
    ]);
    expect(state).toMatchObject({ kind: "pending", index: 4 }); // 5 inputs: and, act1/2, cmp2 x2
  });

  it("refuses confirm before a target, and every event before a source", () => {
    expect(
      run(RULE, [{ type: "start", node: "cmp1" }, { type: "confirm" }]).effects[1],
    ).toMatchObject({ kind: "refuse", reason: REFUSAL.noTarget });
    expect(run(RULE, [{ type: "confirm" }]).effects[0]).toMatchObject({ reason: REFUSAL.noSource });
    expect(run(RULE, [{ type: "pick", node: "and", port: "in" }]).effects[0]).toMatchObject({
      reason: REFUSAL.noSource,
    });
    expect(run(RULE, [{ type: "cycle", step: 1 }]).effects[0]).toEqual({ kind: "none" });
    expect(run(RULE, [{ type: "cancel" }]).effects[0]).toEqual({ kind: "none" });
  });

  it("refuses a source with no output, an unknown node and a port that is not an input", () => {
    expect(run(RULE, [{ type: "start", node: "act1" }]).effects[0]).toMatchObject({
      reason: REFUSAL.noOutput,
    });
    expect(run(RULE, [{ type: "start", node: "gone" }]).effects[0]).toMatchObject({
      reason: REFUSAL.unknownNode,
    });
    const picked = run(RULE, [
      { type: "start", node: "cmp1" },
      { type: "pick", node: "and", port: "left" },
    ]);
    expect(picked.effects[1]).toMatchObject({ reason: REFUSAL.noInput });
  });

  it("Esc cancels and returns to idle", () => {
    const { state, effects } = run(RULE, [{ type: "start", node: "cmp1" }, { type: "cancel" }]);
    expect(effects[1]).toEqual({ kind: "cancelled", text: "Connection cancelled." });
    expect(state).toBe(IDLE);
  });

  it("re-checks on confirm against the graph it is given", () => {
    const pending = run(AUTHORED, [
      { type: "start", node: "cmp" },
      { type: "cycle", step: 1 },
    ]).state;
    const taken = { ...AUTHORED, edges: [edge("e1", "trigger", "act", "when")] };
    expect(stepPortSelection(pending, { type: "confirm" }, taken, oracle).effect).toMatchObject({
      kind: "refuse",
      reason: REFUSAL.occupied,
    });
  });
});

describe("verdictFor", () => {
  it("names each reason", () => {
    expect(verdictFor(RULE, oracle, "and", "and", "in")).toMatchObject({
      reason: REFUSAL.selfLoop,
    });
    expect(verdictFor(RULE, oracle, "cmp1", "and", "in")).toMatchObject({
      reason: REFUSAL.duplicate,
    });
    expect(verdictFor(RULE, oracle, "note", "and", "in")).toMatchObject({
      reason: REFUSAL.noOutput,
    });
    expect(verdictFor(RULE, oracle, "trigger", "and", "in")).toEqual({
      ok: false,
      reason: "A trigger can't feed a boolean.",
    });
    expect(verdictFor(RULE, oracle, "cmp2", "act1", "when")).toMatchObject({
      reason: REFUSAL.occupied,
    });
    expect(verdictFor(RULE, oracle, "cmp1", "cmp2", "when")).toMatchObject({
      reason: REFUSAL.noInput,
    });
    expect(verdictFor(RULE, oracle, "gone", "and", "in")).toMatchObject({
      reason: REFUSAL.unknownNode,
    });
  });

  it("refuses an edge that closes a loop, and takes a second edge into a list input", () => {
    const graph: A11yGraph = {
      nodes: [node("g1", "logicGate"), node("g2", "logicGate"), node("g3", "logicGate")],
      edges: [edge("e1", "g1", "g2", "in"), edge("e2", "g2", "g3", "in")],
    };
    expect(verdictFor(graph, oracle, "g3", "g1", "in")).toMatchObject({ reason: REFUSAL.loop });
    expect(verdictFor(graph, oracle, "g1", "g3", "in")).toEqual({ ok: true });
  });
});

describe("port selection: property, never an invalid edge", () => {
  it("applying every connect it yields keeps the graph loop-free, typed and single-fed", () => {
    const rand = rng(2507);
    const kinds = ["start", "cycle", "cycle", "pick", "confirm", "confirm", "cancel"] as const;
    for (let trial = 0; trial < 150; trial += 1) {
      const base = randomGraph(rand, 8);
      let graph: A11yGraph = { nodes: base.nodes, edges: [] };
      let state: PortSelection = IDLE;
      for (let press = 0; press < 40; press += 1) {
        const kind = kinds[Math.floor(rand() * kinds.length)] as (typeof kinds)[number];
        const id = `n${Math.floor(rand() * graph.nodes.length)}`;
        const event: PortEvent =
          kind === "start"
            ? { type: "start", node: id }
            : kind === "cycle"
              ? { type: "cycle", step: rand() < 0.5 ? 1 : -1 }
              : kind === "pick"
                ? { type: "pick", node: id, port: rand() < 0.5 ? "in" : "when" }
                : { type: kind };
        const step = stepPortSelection(state, event, graph, oracle);
        state = step.state;
        if (step.effect.kind !== "connect") continue;
        const e = step.effect.edge;
        expect(verdictFor(graph, oracle, e.source, e.target, e.targetPort)).toEqual({ ok: true });
        graph = { ...graph, edges: [...graph.edges, { id: `k${press}`, ...e }] };
      }
      const feeds = graph.edges.filter((e) => e.targetPort !== "in").map((e) => e.target);
      expect(new Set(feeds).size).toBe(feeds.length);
    }
  });
});

describe("disconnect", () => {
  it("removes the focused edge and announces it", () => {
    const out = disconnect(RULE, "e3");
    expect(out?.edges.map((e) => e.id)).toEqual(["e1", "e2", "e4"]);
    expect(out?.text).toBe("Disconnected AND from Alert run when.");
  });

  it("is undefined for an edge that is gone, and names a dangling end by its id", () => {
    expect(disconnect(RULE, "nope")).toBeUndefined();
    const graph = { nodes: [], edges: [edge("x", "a", "b", "left")] };
    expect(disconnect(graph, "x")?.text).toBe("Disconnected a from b input A.");
  });
});
