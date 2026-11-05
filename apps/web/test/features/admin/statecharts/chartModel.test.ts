/**
 * E42-S08 (#1137) §4.1: the chart model the inspector lists (AC4, "State diagram matches the
 * running chart"). It is read over every committed chart, each made into its export as
 * `exportStatechart` serves it (the six CV policy keys dropped, `22`), each checked against an
 * independent walk of its own JSON, and pinned against golden lists for the frozen B18
 * `kill_switch`, B04 `oco` and B01 `order` (`frozenCharts.ts`), which no chart bump moves. The
 * current states come from a served configuration alone (C-2.19 to C-2.22).
 */
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  currentIds,
  MAX_ARMS,
  MAX_DEPTH,
  MAX_STATES,
  vetStately,
  type ChartEdge,
  type ChartModel,
} from "../../../../src/features/admin/statecharts/chartModel";
import { B_NUMBERS } from "../../../../src/features/admin/statecharts/kinds";
import { frozenChart, type FrozenChart } from "./frozenCharts";

const MACHINES = resolve(
  import.meta.dirname,
  "../../../../../../services/api/candleviewer/statechart/machines",
);
const HASH = "a".repeat(64);
/** `registry.export_stately`'s six keys, dropped at every depth. */
const POLICY = new Set([
  "strictConfig",
  "strict",
  "strictTargets",
  "actionErrorPolicy",
  "guardErrorPolicy",
  "spawnBlockingTimeout",
]);

function exported(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(exported);
  if (typeof node !== "object" || node === null) return node;
  return Object.fromEntries(
    Object.entries(node)
      .filter(([name]) => !POLICY.has(name))
      .map(([name, value]) => [name, exported(value)]),
  );
}

const FILES = readdirSync(MACHINES)
  .filter((name) => name.endsWith(".machine.json"))
  .sort();
/** Each committed chart's export, by file name. */
const EXPORTS = new Map(
  FILES.map((file) => [file, exported(JSON.parse(readFileSync(resolve(MACHINES, file), "utf8")))]),
);

function modelOf(file: string): ChartModel {
  const model = vetStately(EXPORTS.get(file), file.split(".")[1] ?? "", HASH);
  if (model === null) throw new Error(`${file}: refused`);
  return model;
}

/** A frozen chart's model (`frozenCharts.ts`): the goldens' oracle, which no chart bump moves. */
function frozenModel(name: FrozenChart): ChartModel {
  const model = vetStately(frozenChart(name), name.split(".")[1] ?? "", HASH);
  if (model === null) throw new Error(`${name}: refused`);
  return model;
}

/** An edge as one line: from, to (`-` for none), how and on what. */
const line = (edge: ChartEdge): string =>
  `${edge.from}|${edge.to ?? "-"}|${edge.via}|${edge.event}`;

/** A raw chart node, as the authoring schema writes one (`statechart/schema.py`). */
interface RawNode {
  readonly id?: string;
  readonly type?: string;
  readonly states?: Readonly<Record<string, RawNode>>;
  readonly on?: Readonly<Record<string, unknown>>;
  readonly after?: Readonly<Record<string, unknown>>;
  readonly always?: unknown;
  readonly invoke?: unknown;
  readonly onDone?: unknown;
}

/** A committed chart as its JSON parses: the schema's shape (`statechart/schema.py`). */
const rawOf = (file: string): RawNode => EXPORTS.get(file) as RawNode;

/** Every state path under `node`, depth first, by an independent walk of the raw chart. */
function paths(node: RawNode, prefix: string): string[] {
  return Object.entries(node.states ?? {}).flatMap(([name, child]) => [
    `${prefix}.${name}`,
    ...paths(child, `${prefix}.${name}`),
  ]);
}

/**
 * A target's state id from the state `source` (whose parent is `parent`, `""` for the root): an
 * absolute `#<root>.<path>`, a `.child` under the source, or a sibling's bare name. The committed
 * charts write `#<id>` today; the model reads all three, so this walk does too (C-1137-d01).
 */
function resolveIn(target: string, source: string, parent: string): string {
  if (target.startsWith("#")) return target.slice(1);
  if (target.startsWith(".")) return `${source}${target}`;
  if (parent === "") throw new Error(`${source}: a bare target from the root: ${target}`);
  return `${parent}.${target}`;
}

/** Every `target` string anywhere in the raw chart, resolved from the state it is written in. */
function targetsIn(chart: RawNode): string[] {
  const found: string[] = [];
  const walk = (value: unknown, id: string, parent: string): void => {
    if (Array.isArray(value)) return value.forEach((item) => walk(item, id, parent));
    if (typeof value !== "object" || value === null) return;
    for (const [name, inner] of Object.entries(value)) {
      if (name === "target" && typeof inner === "string") found.push(resolveIn(inner, id, parent));
      else if (name === "states" && typeof inner === "object" && inner !== null) {
        for (const [child, raw] of Object.entries(inner)) walk(raw, `${id}.${child}`, id);
      } else walk(inner, id, parent);
    }
  };
  walk(chart, chart.id ?? "", "");
  return found;
}

/**
 * Every transition of a raw chart once, as `from|to|via|event`, by an independent walk of its
 * JSON: each arm of `on`, `after`, `always`, an invoke's `onDone` and `onError` and a state's own
 * `onDone`, to each of its targets (`resolveIn`), or to `-` when it has none.
 */
function transitionsIn(chart: RawNode): Set<string> {
  const out = new Set<string>();
  const visit = (node: RawNode, id: string, name: string, parent: string): void => {
    const add = (value: unknown, via: string, event: string): void => {
      for (const arm of [value].flat()) {
        const target: unknown = typeof arm === "string" ? arm : Reflect.get(Object(arm), "target");
        const targets = [target ?? []].flat();
        if (targets.length === 0) out.add(`${id}|-|${via}|${event}`);
        for (const to of targets) {
          if (typeof to !== "string") {
            throw new Error(`${id}: a target that is not a string: ${JSON.stringify(to)}`);
          }
          out.add(`${id}|${resolveIn(to, id, parent)}|${via}|${event}`);
        }
      }
    };
    for (const [event, arm] of Object.entries(node.on ?? {})) add(arm, "on", event);
    for (const [delay, arm] of Object.entries(node.after ?? {})) add(arm, "after", delay);
    if (node.always !== undefined) add(node.always, "always", "");
    for (const invoke of [node.invoke ?? []].flat()) {
      const src: unknown = Reflect.get(Object(invoke), "src");
      const named: unknown = Reflect.get(Object(invoke), "id");
      const service = typeof src === "string" ? src : typeof named === "string" ? named : "";
      const done: unknown = Reflect.get(Object(invoke), "onDone");
      const error: unknown = Reflect.get(Object(invoke), "onError");
      if (done !== undefined) add(done, "done", service);
      if (error !== undefined) add(error, "error", service);
    }
    if (node.onDone !== undefined) add(node.onDone, "done", name);
    for (const [child, raw] of Object.entries(node.states ?? {})) {
      visit(raw, `${id}.${child}`, child, id);
    }
  };
  const root = chart.id ?? "";
  visit(chart, root, root, "");
  return out;
}

describe("the chart model over every committed chart", () => {
  it("test_chart_model_reads_every_catalogue_kinds_committed_chart", () => {
    // B1 to B20: one chart per catalogue kind (kinds.test.ts pins the file names).
    expect(FILES.map((file) => file.split(".")[1]).sort()).toEqual(Object.keys(B_NUMBERS).sort());
  });

  it.each(FILES)(
    "test_chart_model_%s_lists_each_state_and_transition_once_as_its_json_has_them",
    (file) => {
      const model = modelOf(file);
      const raw = rawOf(file);
      const root = raw.id ?? "";
      expect(model.root).toBe(root);
      expect(model.rootKind).toBe(raw.type === "parallel" ? "parallel" : "compound");
      expect(model.states.map((s) => s.id)).toEqual(paths(raw, root));
      for (const state of model.states) {
        expect(state.id).toBe(`${state.parent}.${state.name}`);
        expect(state.id.split(".")).toHaveLength(state.depth + 1);
      }
      // Every transition once: as many edges as the walk finds, and the same ones.
      const transitions = transitionsIn(raw);
      expect(model.edges).toHaveLength(transitions.size);
      expect(new Set(model.edges.map(line))).toEqual(transitions);
    },
  );

  it.each(FILES)("test_chart_model_%s_resolves_every_target_to_a_listed_state", (file) => {
    const model = modelOf(file);
    const ids = new Set(model.states.map((s) => s.id));
    const reached = new Set(model.edges.map((e) => e.to));
    for (const target of targetsIn(rawOf(file))) {
      expect(ids.has(target), target).toBe(true);
      expect(reached.has(target), target).toBe(true);
    }
    for (const edge of model.edges) {
      expect(edge.from === model.root || ids.has(edge.from), edge.from).toBe(true);
    }
  });

  it("test_chart_model_carries_the_exports_kind_and_hash", () => {
    const model = vetStately(frozenChart("B18.kill_switch"), "kill_switch", HASH);
    expect(model?.kind).toBe("kill_switch");
    expect(model?.hash).toBe(HASH);
  });

  it("test_chart_model_walk_reads_sibling_and_child_targets_as_the_model_does", () => {
    // No committed chart writes one today: a chart that does still meets the loops above.
    const raw = {
      id: "rel",
      initial: "a",
      states: {
        a: {
          initial: "x",
          on: { NEXT: "b", IN: { target: ".y" } },
          states: { x: { on: { ON: "y" } }, y: {} },
        },
        b: { on: { BACK: { target: "#rel.a.x" } } },
      },
    };
    const model = vetStately(raw, "rel", HASH);
    expect(new Set(model?.edges.map(line))).toEqual(transitionsIn(raw));
    expect([...transitionsIn(raw)].sort()).toEqual([
      "rel.a.x|rel.a.y|on|ON",
      "rel.a|rel.a.y|on|IN",
      "rel.a|rel.b|on|NEXT",
      "rel.b|rel.a.x|on|BACK",
    ]);
    expect(targetsIn(raw).sort()).toEqual(["rel.a.x", "rel.a.y"]);
  });
});

describe("golden lists: the frozen B18 kill_switch, B04 oco and B01 order", () => {
  it("test_chart_model_b18_kill_switch_is_its_six_states_and_fifteen_transitions", () => {
    const model = frozenModel("B18.kill_switch");
    expect(model.states.map((s) => [s.id, s.kind, s.initial, s.depth, s.label])).toEqual([
      ["kill_switch.clear", "atomic", true, 1, "clear"],
      ["kill_switch.engaging", "atomic", false, 1, "engaging"],
      ["kill_switch.cancelling", "atomic", false, 1, "cancelling"],
      ["kill_switch.flattening", "atomic", false, 1, "flattening"],
      ["kill_switch.engaged", "atomic", false, 1, "engaged"],
      ["kill_switch.engaged_incomplete", "atomic", false, 1, "engaged_incomplete"],
    ]);
    expect(model.edges.map(line)).toEqual([
      "kill_switch|kill_switch.engaged_incomplete|on|KILL",
      "kill_switch.clear|kill_switch.engaging|on|ENGAGE",
      "kill_switch.engaging|kill_switch.cancelling|always|",
      "kill_switch.engaging|kill_switch.engaged|always|",
      "kill_switch.cancelling|kill_switch.flattening|done|cancel_all_working_orders",
      "kill_switch.cancelling|kill_switch.engaged|done|cancel_all_working_orders",
      "kill_switch.cancelling|kill_switch.engaged|error|cancel_all_working_orders",
      "kill_switch.flattening|kill_switch.engaged|done|flatten_all_positions",
      "kill_switch.flattening|kill_switch.engaged_incomplete|done|flatten_all_positions",
      "kill_switch.flattening|kill_switch.engaged_incomplete|error|flatten_all_positions",
      "kill_switch.engaged|kill_switch.clear|on|RELEASE",
      // RELEASE's second arm: the guard refusal's audit arm, no state change (B18).
      "kill_switch.engaged|-|on|RELEASE",
      "kill_switch.engaged_incomplete|kill_switch.flattening|on|RETRY_FLATTEN",
      "kill_switch.engaged_incomplete|kill_switch.clear|on|RELEASE",
      "kill_switch.engaged_incomplete|-|on|RELEASE",
    ]);
  });

  it("test_chart_model_b04_oco_is_its_eleven_states_and_thirty_one_transitions", () => {
    const model = frozenModel("B04.oco");
    expect(model.states.map((s) => `${s.name}:${s.kind}${s.initial ? ":initial" : ""}`)).toEqual([
      "arming:atomic:initial",
      "racing:atomic",
      "settling_b:atomic",
      "settling_a:atomic",
      "overshoot:atomic",
      "reconciling:atomic",
      "cancelling_all:atomic",
      "completing:atomic",
      "completed:final",
      "cancelled:final",
      "failed:final",
    ]);
    expect(model.edges.map(line)).toEqual([
      "oco|oco.failed|on|KILL",
      "oco.arming|oco.racing|done|submit_both_legs",
      "oco.arming|oco.failed|error|submit_both_legs",
      "oco.racing|oco.overshoot|on|LEG_A_FILL",
      "oco.racing|oco.settling_b|on|LEG_A_FILL",
      "oco.racing|oco.overshoot|on|LEG_B_FILL",
      "oco.racing|oco.settling_a|on|LEG_B_FILL",
      "oco.racing|oco.cancelling_all|on|POSITION_FLAT",
      "oco.racing|-|on|POSITION_FLAT",
      "oco.racing|oco.cancelling_all|on|USER_CANCEL",
      "oco.settling_b|oco.completing|done|settle_other_leg",
      "oco.settling_b|oco.racing|done|settle_other_leg",
      "oco.settling_b|oco.reconciling|error|settle_other_leg",
      "oco.settling_b|oco.settling_b|error|settle_other_leg",
      "oco.settling_b|oco.failed|error|settle_other_leg",
      "oco.settling_a|oco.completing|done|settle_other_leg",
      "oco.settling_a|oco.racing|done|settle_other_leg",
      "oco.settling_a|oco.reconciling|error|settle_other_leg",
      "oco.settling_a|oco.settling_a|error|settle_other_leg",
      "oco.settling_a|oco.failed|error|settle_other_leg",
      "oco.overshoot|oco.completing|done|reduce_only_market_excess",
      "oco.overshoot|oco.failed|error|reduce_only_market_excess",
      "oco.reconciling|oco.completing|done|reconcile_children",
      "oco.reconciling|oco.failed|error|reconcile_children",
      "oco.cancelling_all|oco.cancelled|done|cancel_all_children",
      "oco.cancelling_all|oco.failed|error|cancel_all_children",
      "oco.completing|oco.completed|on|CHILDREN_TERMINAL",
      "oco.completing|oco.overshoot|on|LEG_A_FILL",
      "oco.completing|-|on|LEG_A_FILL",
      "oco.completing|oco.overshoot|on|LEG_B_FILL",
      "oco.completing|-|on|LEG_B_FILL",
    ]);
  });

  it("test_chart_model_b01_parallel_root_has_two_regions_none_initial", () => {
    const model = frozenModel("B01.order");
    // B1 v8, the largest chart: 23 states, 148 transitions, 76 source → target pairs.
    const pairs = new Set(model.edges.filter((e) => e.to !== null).map((e) => `${e.from}>${e.to}`));
    expect([model.states.length, model.edges.length, pairs.size]).toEqual([23, 148, 76]);
    const regions = model.states.filter((s) => s.depth === 1);
    expect(regions.map((s) => [s.name, s.kind, s.initial])).toEqual([
      ["lifecycle", "compound", false],
      ["protection", "compound", false],
    ]);
    expect(model.states.filter((s) => s.initial).map((s) => s.id)).toEqual([
      "order.lifecycle.draft",
      "order.protection.not_required",
    ]);
    expect(model.states.filter((s) => s.kind === "final").map((s) => s.name)).toEqual([
      "filled",
      "cancelled",
      "rejected",
      "expired",
      "killed",
    ]);
  });
});

describe("currentIds reads the served configuration only", () => {
  /** `latched_machine.py`'s configuration (SC-CHAIN-TRIPS): triggered, its stop-loss present. */
  const LATCHED = [
    "order",
    "order.lifecycle",
    "order.lifecycle.triggered",
    "order.protection",
    "order.protection.sl_present",
  ];

  it("test_current_ids_b01_latched_configuration_gives_its_two_leaves", () => {
    const model = frozenModel("B01.order");
    expect([...currentIds(model, LATCHED)].sort()).toEqual([
      "order.lifecycle.triggered",
      "order.protection.sl_present",
    ]);
  });

  it("test_current_ids_unknown_ids_and_an_empty_configuration_give_nothing", () => {
    const model = frozenModel("B18.kill_switch");
    expect([...currentIds(model, ["kill_switch", "kill_switch.clear"])]).toEqual([
      "kill_switch.clear",
    ]);
    expect(currentIds(model, []).size).toBe(0);
    expect(currentIds(model, ["kill_switch", "kill_switch.gone", "other.clear"]).size).toBe(0);
  });
});

/** A flat chart of `n` atomic states `s0`…, the first initial. */
function flat(n: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
  const states = Object.fromEntries(Array.from({ length: n }, (_, i) => [`s${i}`, {}]));
  return { id: "m", initial: "s0", states, ...extra };
}

/** A chain of `depth` compound states, each the next one's parent, ending in a leaf. */
function deep(depth: number): Record<string, unknown> {
  let node: Record<string, unknown> = {};
  for (let level = depth; level > 1; level -= 1) node = { initial: "n", states: { n: node } };
  return { id: "m", initial: "n", states: { n: node } };
}

const vet = (raw: unknown): ChartModel | null => vetStately(raw, "m", HASH);
const edgesOf = (raw: unknown): string[] => vet(raw)?.edges.map(line) ?? ["refused"];

describe("the bounds: over one, the chart is refused, never cut", () => {
  it("test_vet_stately_states_over_the_bound_give_null", () => {
    expect(vet(flat(MAX_STATES))?.states).toHaveLength(MAX_STATES);
    expect(vet(flat(MAX_STATES + 1))).toBeNull();
  });

  it("test_vet_stately_arms_over_the_bound_give_null", () => {
    const on = (n: number) =>
      Object.fromEntries(Array.from({ length: n }, (_, i) => [`E${i}`, { target: "#m.s1" }]));
    expect(vet(flat(2, { on: on(MAX_ARMS) }))?.edges).toHaveLength(MAX_ARMS);
    expect(vet(flat(2, { on: on(MAX_ARMS + 1) }))).toBeNull();
  });

  it("test_vet_stately_depth_over_the_bound_gives_null", () => {
    expect(vet(deep(MAX_DEPTH))?.states.at(-1)?.depth).toBe(MAX_DEPTH);
    expect(vet(deep(MAX_DEPTH + 1))).toBeNull();
  });
});

describe("names and shapes: anything off is refused", () => {
  it.each([
    ["no chart", null],
    ["a list", []],
    ["no id", { initial: "a", states: { a: {} } }],
    ["a dotted id", { id: "m.x", states: { a: {} } }],
    ["no states", { id: "m" }],
    ["empty states", { id: "m", states: {} }],
    ["states not an object", { id: "m", states: ["a"] }],
    ["a state name with a dot", { id: "m", states: { "a.b": {} } }],
    ["a state name over 64 characters", { id: "m", states: { ["a".repeat(65)]: {} } }],
    ["a state that is not an object", { id: "m", states: { a: 1 } }],
    ["an atomic root", { id: "m", type: "atomic", states: { a: {} } }],
    ["a history state", { id: "m", states: { a: {}, h: { type: "history" } } }],
    [
      "a final state with children",
      { id: "m", states: { a: { type: "final", states: { b: {} } } } },
    ],
    [
      "an atomic state with children",
      { id: "m", states: { a: { type: "atomic", states: { b: {} } } } },
    ],
    ["a compound state without children", { id: "m", states: { a: { type: "compound" } } }],
    ["a parallel state without children", { id: "m", states: { a: { type: "parallel" } } }],
    ["an initial naming no child", { id: "m", initial: "z", states: { a: {} } }],
    ["an initial that is not a name", { id: "m", initial: { target: "a" }, states: { a: {} } }],
    ["an initial on an atomic state", { id: "m", states: { a: { initial: "b" } } }],
    ["`on` that is not an object", flat(2, { on: ["E"] })],
    ["an empty event name", flat(2, { on: { "": "#m.s1" } })],
    ["an event name over 64 characters", flat(2, { on: { ["E".repeat(65)]: "#m.s1" } })],
    ["an arm that is a number", flat(2, { on: { E: 1 } })],
    ["a target that is a number", flat(2, { on: { E: { target: 1 } } })],
    ["a target list holding a number", flat(2, { on: { E: { target: ["#m.s1", 2] } } })],
    ["a target that resolves nowhere", flat(2, { on: { E: "#m.nope" } })],
    ["a target of the root itself", flat(2, { on: { E: "#m" } })],
    ["a bare name from the root", flat(2, { on: { E: "s1" } })],
    [
      "an invoke with no service name",
      flat(2, { states: { s0: { invoke: { onDone: "s1" } }, s1: {} } }),
    ],
    ["an invoke that is not an object", flat(2, { states: { s0: { invoke: [1] }, s1: {} } })],
    ["`after` that is not an object", flat(2, { after: 5 })],
  ])("test_vet_stately_%s_gives_null", (_name, raw) => {
    expect(vet(raw)).toBeNull();
  });
});

describe("target forms and transition kinds", () => {
  it("test_vet_stately_sibling_child_and_listed_targets_resolve", () => {
    const raw = {
      id: "m",
      type: "parallel",
      states: {
        a: {
          initial: "x",
          states: {
            x: { on: { GO: "y", BACK: { target: [] } } },
            y: { on: { IN: ".inner" }, initial: "inner", states: { inner: {} } },
          },
          on: { BOTH: { target: ["#m.a.x", "#m.b.p"] } },
        },
        b: { initial: "p", states: { p: { on: { SELF: { target: "p", reenter: true } } } } },
      },
    };
    expect(edgesOf(raw)).toEqual([
      "m.a|m.a.x|on|BOTH",
      "m.a|m.b.p|on|BOTH",
      "m.a.x|m.a.y|on|GO",
      "m.a.x|-|on|BACK",
      "m.a.y|m.a.y.inner|on|IN",
      "m.b.p|m.b.p|on|SELF",
    ]);
  });

  it("test_vet_stately_always_after_and_state_done_are_their_own_kinds", () => {
    const raw = {
      id: "m",
      initial: "w",
      states: {
        w: {
          after: { "1000": "#m.d", retry_delay: [{ target: "#m.d", guard: "g" }, {}] },
          always: [{ target: "#m.d", guard: "ready" }],
        },
        d: { initial: "i", states: { i: { type: "final" } }, onDone: "#m.w" },
      },
    };
    expect(edgesOf(raw)).toEqual([
      "m.w|m.d|after|1000",
      "m.w|m.d|after|retry_delay",
      "m.w|-|after|retry_delay",
      "m.w|m.d|always|",
      "m.d|m.w|done|d",
    ]);
  });

  it("test_vet_stately_invoke_lists_and_inline_machines_take_their_names", () => {
    const raw = flat(2, {
      states: {
        s0: {
          invoke: [
            { id: "one", src: "load", onDone: "#m.s1", onError: [{ target: "#m.s1" }, {}] },
            { id: "inline", src: { id: "child", states: { c: {} } }, onDone: "#m.s1" },
          ],
        },
        s1: {},
      },
    });
    expect(edgesOf(raw)).toEqual([
      "m.s0|m.s1|done|load",
      "m.s0|m.s1|error|load",
      "m.s0|-|error|load",
      "m.s0|m.s1|done|inline",
    ]);
  });

  it("test_vet_stately_drops_a_repeated_transition_once_seen", () => {
    expect(edgesOf(flat(2, { on: { E: ["#m.s1", "#m.s1", { target: "#m.s1" }] } }))).toEqual([
      "m|m.s1|on|E",
    ]);
  });

  it("test_vet_stately_a_name_two_states_share_is_labelled_by_its_path", () => {
    const raw = {
      id: "m",
      type: "parallel",
      states: {
        a: { initial: "idle", states: { idle: {}, busy: {} } },
        b: { initial: "idle", states: { idle: {} } },
      },
    };
    expect(vet(raw)?.states.map((s) => s.label)).toEqual(["a", "a.idle", "busy", "b", "b.idle"]);
  });

  it("test_vet_stately_reads_a_hyphenated_id_and_state_names_dots_alone_split_ids", () => {
    // The authoring schema constrains no name: only a dot is refused, as ids split on ".".
    const raw = {
      id: "m-1",
      initial: "wait-fill",
      states: { "wait-fill": { on: { "FILL-SEEN": "#m-1.done" } }, done: { type: "final" } },
    };
    expect(vet(raw)?.states.map((s) => [s.id, s.initial])).toEqual([
      ["m-1.wait-fill", true],
      ["m-1.done", false],
    ]);
    expect(edgesOf(raw)).toEqual(["m-1.wait-fill|m-1.done|on|FILL-SEEN"]);
  });

  it("test_vet_stately_a_nested_parallel_state_marks_no_region_initial", () => {
    const raw = {
      id: "m",
      initial: "p",
      states: { p: { type: "parallel", initial: "r1", states: { r1: {}, r2: {} } } },
    };
    expect(vet(raw)?.states.map((s) => [s.name, s.kind, s.initial])).toEqual([
      ["p", "parallel", true],
      ["r1", "atomic", false],
      ["r2", "atomic", false],
    ]);
  });
});
