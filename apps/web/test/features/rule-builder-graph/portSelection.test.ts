import { describe, expect, it } from "vitest";
import { REFUSAL } from "../../../src/features/rule-builder-graph/a11y/copy.js";
import type { A11yGraph } from "../../../src/features/rule-builder-graph/a11y/graph.js";
import {
  deletedText,
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

/** Three inputs that can take S's output (X, G1, G2) and three that cannot. */
const MIXED: A11yGraph = {
  nodes: [
    node("s", "logicGate", { name: "S" }),
    node("g1", "logicGate", { name: "G1" }),
    node("x", "logicGate", { name: "X" }),
    node("act", "action", { name: "Act" }),
    node("cmp", "condition", { kind: "comparison", name: "Cmp" }),
    node("g2", "logicGate", { name: "G2" }),
  ],
  edges: [edge("e1", "x", "act", "when")],
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
      text:
        // D02 §6 P12 :220 verbatim, then the PROPOSED count (a11y lens A-4).
        "Connecting from output port, boolean — choose an input. 1 input available.",
    });
    expect(effects[1]).toEqual({
      kind: "announce",
      text: "Alert, Input port, action, not connected — can connect, 1 of 1",
    });
    expect(effects[2]).toEqual({
      kind: "connect",
      edge: { source: "cmp", sourcePort: "out", target: "act", targetPort: "when" },
      text: "connected Price above output to Alert input 1", // D02 §6 :231 verbatim
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
      text: "Alert, Input port, action, connected to AND. This input already has a connection.",
    });
    expect(effects[2]).toMatchObject({ kind: "refuse", reason: REFUSAL.occupied });
    expect(state.kind).toBe("pending");
  });

  it("says how many inputs can and cannot take it, once, at the start (a11y lens A-4)", () => {
    expect(run(MIXED, [{ type: "start", node: "s" }]).effects[0]).toEqual({
      kind: "announce",
      text: "Connecting from output port, boolean — choose an input. 3 inputs available, 3 not available.",
    });
  });

  it("cycles only the available inputs and counts k of n over them (a11y lens A-4)", () => {
    const { effects } = run(MIXED, [
      { type: "start", node: "s" },
      { type: "cycle", step: 1 },
      { type: "cycle", step: 1 },
      { type: "cycle", step: 1 },
      { type: "cycle", step: 1 },
    ]);
    expect(effects.slice(1).map((e) => (e.kind === "announce" ? e.text : e.kind))).toEqual([
      "X, Input port, boolean, not connected — can connect, 1 of 3",
      "G1, Input port, boolean, not connected — can connect, 2 of 3",
      "G2, Input port, boolean, not connected — can connect, 3 of 3",
      "X, Input port, boolean, not connected — can connect, 1 of 3",
    ]);
  });

  it("cycles backwards and wraps, and moves on from a picked unavailable input", () => {
    const back = run(MIXED, [
      { type: "start", node: "s" },
      { type: "cycle", step: -1 },
    ]);
    expect(back.effects[1]).toEqual({
      kind: "announce",
      text: "G2, Input port, boolean, not connected — can connect, 3 of 3",
    });
    const picked = (step: 1 | -1) =>
      run(MIXED, [
        { type: "start", node: "s" },
        { type: "pick", node: "act", port: "when" },
        { type: "cycle", step },
      ]).effects[2];
    expect(picked(1)).toMatchObject({ text: expect.stringMatching(/^G1, .*, 2 of 3$/) as unknown });
    expect(picked(-1)).toMatchObject({ text: expect.stringMatching(/^X, .*, 1 of 3$/) as unknown });
  });

  it("says so once when no input can take it", () => {
    const { effects } = run(RULE, [
      { type: "start", node: "cmp1" },
      { type: "cycle", step: 1 },
    ]);
    expect(effects[0]).toMatchObject({
      text: expect.stringContaining("0 inputs available, 5 not available.") as unknown,
    });
    expect(effects[1]).toEqual({ kind: "announce", text: "No input can take this connection." });
  });

  it("builds the adjacency once per event, not once per candidate (code lens L4)", () => {
    const reads = (size: number): number => {
      let count = 0;
      const nodes = Array.from({ length: size }, (_, i) => node(`g${i}`, "logicGate"));
      const graph: A11yGraph = {
        nodes,
        get edges() {
          count += 1;
          return [];
        },
      };
      stepPortSelection(IDLE, { type: "start", node: "g0" }, graph, oracle);
      return count;
    };
    expect(reads(60)).toBe(reads(3));
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
    expect(effects[1]).toEqual({ kind: "cancelled", text: "Cancelled" }); // D02 §13 :368
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

describe("port selection: D02's input {n} (§6 :231)", () => {
  const confirmText = (graph: A11yGraph, source: string, target: string, port: string) =>
    run(graph, [
      { type: "start", node: source },
      { type: "pick", node: target, port },
      { type: "confirm" },
    ]).effects[2];

  it("counts the slot a list input's new edge takes", () => {
    const graph: A11yGraph = {
      nodes: ["g", "c1", "c2", "c3"].map((id) => node(id, "logicGate", { name: id.toUpperCase() })),
      edges: [edge("e1", "c1", "g", "in"), edge("e2", "c2", "g", "in")],
    };
    expect(confirmText(graph, "c3", "g", "in")).toMatchObject({
      kind: "connect",
      text: "connected C3 output to G input 3",
    });
  });

  it("numbers a single input by its place among the node's inputs", () => {
    const graph: A11yGraph = {
      nodes: [
        node("m", "condition", { kind: "arithmetic", name: "ATR" }),
        node("cmp", "condition", { kind: "comparison", name: "Above" }),
      ],
      edges: [],
    };
    expect(confirmText(graph, "m", "cmp", "right")).toMatchObject({
      text: "connected ATR output to Above input 2",
    });
    expect(confirmText(graph, "m", "cmp", "left")).toMatchObject({
      text: "connected ATR output to Above input 1",
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
      reason: "A trigger can't be used as true or false.",
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
    // D02 §15 :414 verbatim: g3 already depends on g1.
    expect(verdictFor(graph, oracle, "g3", "g1", "in")).toEqual({
      ok: false,
      reason: "This would make a loop — Logic gate g3 already depends on Logic gate g1.",
    });
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
      // Each single input (left, right, when: not the list port `in`) takes at most one edge.
      const feeds = graph.edges
        .filter((e) => e.targetPort !== "in")
        .map((e) => `${e.target}:${e.targetPort}`);
      expect(new Set(feeds).size).toBe(feeds.length);
    }
  });
});

describe("disconnect", () => {
  it("removes the focused edge and announces it", () => {
    const out = disconnect(RULE, "e3");
    expect(out?.edges.map((e) => e.id)).toEqual(["e1", "e2", "e4"]);
    expect(out?.text).toBe("Disconnected AND from Alert"); // D02 §13 :369 verbatim
    expect(out?.focusNodeId).toBe("and"); // focus after: the source node
  });

  it("is undefined for an edge that is gone, and names a dangling end by its id", () => {
    expect(disconnect(RULE, "nope")).toBeUndefined();
    const graph = { nodes: [], edges: [edge("x", "a", "b", "left")] };
    expect(disconnect(graph, "x")?.text).toBe("Disconnected a from b");
  });

  it("tells two nodes with one name apart (a11y lens A-9)", () => {
    const graph = {
      nodes: [node("x", "logicGate", { name: "Check" }), node("y", "logicGate", { name: "Check" })],
      edges: [edge("e1", "x", "y", "in")],
    };
    expect(disconnect(graph, "e1")?.text).toBe("Disconnected Check (node 1) from Check (node 2)");
  });
});

describe("deletedText (a11y lens A-8)", () => {
  it("says how many connections went with the node", () => {
    // D02 O4 :291 verbatim for every n (plural forms are E37-D05's to add).
    expect(deletedText(RULE, "and")).toBe("Deleted AND and 4 connections");
    expect(deletedText(RULE, "act1")).toBe("Deleted Alert and 1 connections");
    expect(deletedText(RULE, "note")).toBe("Deleted why and 0 connections");
    expect(deletedText(RULE, "gone")).toBeUndefined();
  });
});
