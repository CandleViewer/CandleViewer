/**
 * E13-S01 (#423) S2: the indicator store against the in-memory engine fake (BQ-01, BQ-03, BQ-04):
 * add / configure / remove / reorder through the port in order, by the port's opaque key (the
 * served `spec_hash` for `server`, T01's PROPOSED client key for `client_worker`), the client caps
 * (D06 §8.1) and the server's own refusals (`23:779`), undo/redo, D02 D30 analytics, bind / unbind /
 * dispose, subscriptions, and no store update per value (BQ-07). Ruling 6652282467.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IndicatorAnalytics } from "../../../src/features/indicators/analytics";
import {
  NAMED_EVENT_NAMES,
  PROPOSED_EVENT_NAMES,
  reportIndicator,
} from "../../../src/features/indicators/analytics";
import type { EngineKey } from "../../../src/features/indicators/engine/port";
import {
  createFakeEngine,
  fakeClientKey,
  SERVER_INSTANCES,
  type FakeEngine,
} from "../../../src/features/indicators/engine/stub/fakeEngine";
import {
  normaliseDescriptor,
  type CatalogueEntry,
} from "../../../src/features/indicators/model/catalogue";
import {
  asInstanceId,
  CAP_INSTANCES,
  CAP_SUBPANES,
  type InstanceId,
} from "../../../src/features/indicators/model/instances";
import {
  createIndicatorStore,
  type AddInput,
  type IndicatorStore,
  type OpResult,
} from "../../../src/features/indicators/store/indicatorStore";
import { BOLLINGER, EMA, RSI } from "./fixtures";
import { int, SEEDS, withSeed } from "./rng";

const entry = (raw: unknown): CatalogueEntry => {
  const e = normaliseDescriptor(raw);
  if (e === null) throw new Error("bad fixture");
  return e;
};
const ema = entry(EMA);
const bb = entry(BOLLINGER);
const rsi = entry(RSI);
const CHART = "chart-1";

const idOf = (r: OpResult): InstanceId => {
  if (!r.ok) throw new Error(`refused: ${r.reason}`);
  return r.id;
};

let events: IndicatorAnalytics[];
let store: IndicatorStore;
let engine: FakeEngine;
let unbind: () => void;

const addInput = (over: Partial<AddInput> = {}): AddInput => ({
  entry: ema,
  params: { n: 21 },
  target: "overlay",
  source: "library",
  ...over,
});
const key = (id: InstanceId): EngineKey => store.keyOf(CHART, id) as EngineKey;
const ops = (): string[] => engine.calls.map((c) => c.op);

beforeEach(() => {
  let k = 0;
  events = [];
  store = createIndicatorStore({ mint: () => `id${(k += 1)}`, report: (e) => events.push(e) });
  engine = createFakeEngine();
  unbind = store.bind(CHART, engine);
});

describe("indicator store operations", () => {
  it("test_add_validates_params_and_keys_a_server_instance_by_the_served_key", () => {
    const id = idOf(store.add(CHART, addInput({ params: { n: 50 } })));
    const spec = { indicator: "ema", compute: "server", pane: "price", params: { n: 50 } };
    expect(engine.calls).toEqual([{ op: "add", spec, outcome: { ok: true, key: "served:1" } }]);
    expect(store.keyOf(CHART, id)).toBe("served:1");
    const [only] = store.selectInstances(CHART);
    expect(only).toMatchObject({ id, indicator: "ema", slot: 1, tier: 0, visible: true });
    expect(Object.getPrototypeOf(only?.params)).toBeNull();
    expect(events).toEqual([
      {
        name: "indicator.added",
        type: "ema",
        pane_target: "overlay",
        entry: "library",
        compute: "server",
      },
    ]);
  });

  it("test_a_client_worker_instance_is_keyed_by_the_client_key_form", () => {
    const id = idOf(store.add(CHART, addInput({ entry: bb, params: { mult: 2.5, n: 30 } })));
    expect(store.keyOf(CHART, id)).toBe(
      fakeClientKey("bollinger", { n: 30, mult: 2.5 }, "series-1"),
    );
    expect(engine.served).toEqual([]);
  });

  it("test_add_refuses_invalid_params_and_unparsed_schema_without_port_calls", () => {
    const bad = store.add(CHART, addInput({ params: { n: 0 } }));
    expect(bad).toMatchObject({
      ok: false,
      reason: "invalid_params",
      errors: [{ name: "n", rule: "minimum" }],
    });
    const refused = { ...ema, schema: { ok: false } } as CatalogueEntry;
    expect(store.add(CHART, addInput({ entry: refused }))).toEqual({
      ok: false,
      reason: "no_path",
    });
    expect(engine.calls).toEqual([]);
    expect(events).toEqual([]);
  });

  it("test_second_instance_gets_its_own_id_key_and_tier", () => {
    const a = idOf(store.add(CHART, addInput()));
    const b = idOf(store.add(CHART, addInput({ params: { n: 50 }, source: "second_instance" })));
    expect(a).not.toBe(b);
    const [x, y] = store.selectInstances(CHART);
    expect([x?.tier, y?.tier]).toEqual([0, 1]);
    expect(engine.order("price")).toEqual([key(a), key(b)]);
  });

  it("test_subpane_target_opens_a_new_pane", () => {
    idOf(store.add(CHART, addInput({ entry: rsi, params: {}, target: "subpane" })));
    const call = engine.calls[0];
    expect(
      call?.op === "add" && call.spec.indicator === "rsi" && call.spec.pane.startsWith("sub:"),
    ).toBe(true);
  });

  it("test_configure_retunes_through_the_old_key_and_takes_the_new_one", () => {
    const id = idOf(store.add(CHART, addInput()));
    events.length = 0;
    expect(store.configure(CHART, id, ema, { n: 30 })).toEqual({ ok: true, id });
    expect(engine.calls.at(-1)).toEqual({
      op: "setParams",
      key: "served:1",
      params: { n: 30 },
      outcome: { ok: true, key: "served:2" },
    });
    expect(store.keyOf(CHART, id)).toBe("served:2");
    const b = idOf(store.add(CHART, addInput({ entry: bb, params: {} })));
    expect(store.configure(CHART, b, bb, { n: 30, mult: 2.5 })).toEqual({ ok: true, id: b });
    expect(store.keyOf(CHART, b)).toBe(
      fakeClientKey("bollinger", { n: 30, mult: 2.5 }, "series-1"),
    );
    expect(
      events.filter((e) => e.name === "indicator.settings_changed").map((e) => "key" in e && e.key),
    ).toEqual(["n", "n", "mult"]);
  });

  it("test_configure_refusals_record_nothing", () => {
    const id = idOf(store.add(CHART, addInput()));
    idOf(store.add(CHART, addInput({ params: { n: 9 } })));
    const before = engine.calls.length;
    expect(store.configure(CHART, id, ema, { n: 21 })).toEqual({ ok: false, reason: "unchanged" });
    expect(store.configure(CHART, id, ema, { n: 1.5 })).toMatchObject({ reason: "invalid_params" });
    expect(store.configure(CHART, id, bb, { n: 3 })).toEqual({
      ok: false,
      reason: "unknown_instance",
    });
    const refused = { ...ema, schema: { ok: false } } as CatalogueEntry;
    expect(store.configure(CHART, id, refused, { n: 3 })).toMatchObject({ reason: "no_path" });
    expect(engine.calls.length).toBe(before);
    // The server refuses a second instance with one key (`23:779`): nothing changes.
    expect(store.configure(CHART, id, ema, { n: 9 })).toEqual({
      ok: false,
      reason: "invalid_options",
    });
    expect(store.selectInstances(CHART)[0]?.params).toEqual({ n: 21 });
    expect(store.keyOf(CHART, id)).toBe("served:1");
    expect(store.getChart(CHART).undo).toHaveLength(2);
  });

  it("test_remove_calls_port_remove_and_emits_no_removed_event", () => {
    const id = idOf(store.add(CHART, addInput()));
    events.length = 0;
    expect(store.remove(CHART, id)).toEqual({ ok: true, id });
    expect(engine.calls.at(-1)).toEqual({ op: "remove", key: "served:1" });
    expect(store.selectInstances(CHART)).toEqual([]);
    expect(store.keyOf(CHART, id)).toBeNull();
    expect(engine.live.size).toBe(0);
    // `indicator.removed` is the toast's, when its undo window closes (D02 :322).
    expect(events).toEqual([]);
    expect(store.remove(CHART, id)).toEqual({ ok: false, reason: "unknown_instance" });
  });

  it("test_reorder_sends_set_order_by_key_and_reports_the_move", () => {
    const a = idOf(store.add(CHART, addInput()));
    const b = idOf(store.add(CHART, addInput({ entry: bb, params: {} })));
    const c = idOf(store.add(CHART, addInput({ params: { n: 50 } })));
    events.length = 0;
    expect(store.reorder(CHART, c, 0)).toEqual({ ok: true, id: c });
    expect(engine.calls.at(-1)).toEqual({
      op: "setOrder",
      pane: "price",
      keys: [key(c), key(a), key(b)],
    });
    expect(engine.order("price")).toEqual([key(c), key(a), key(b)]);
    expect(store.selectPane(CHART, "price").map((i) => i.id)).toEqual([c, a, b]);
    expect(events).toEqual([
      { name: "indicator.reordered", type: "ema", group: "overlays", from: 2, to: 0 },
    ]);
    for (const to of [0, -1, 3])
      expect(store.reorder(CHART, c, to)).toEqual({ ok: false, reason: "unchanged" });
    expect(store.reorder(CHART, asInstanceId("nope"), 0)).toMatchObject({
      reason: "unknown_instance",
    });
  });

  it("test_reorder_in_a_single_member_subpane_changes_nothing", () => {
    const id = idOf(store.add(CHART, addInput({ entry: rsi, params: {}, target: "subpane" })));
    expect(store.reorder(CHART, id, 0)).toEqual({ ok: false, reason: "unchanged" });
  });

  it("test_locked_instances_cannot_be_removed_or_moved_until_unlocked", () => {
    const a = idOf(store.add(CHART, addInput()));
    idOf(store.add(CHART, addInput({ params: { n: 50 } })));
    store.setLocked(CHART, a, true);
    const calls = engine.calls.length;
    expect(store.remove(CHART, a)).toEqual({ ok: false, reason: "indicator.locked" });
    expect(store.reorder(CHART, a, 1)).toEqual({ ok: false, reason: "indicator.locked" });
    expect(engine.calls.length).toBe(calls);
    const doc = store.getChart(CHART);
    store.setLocked(CHART, a, true);
    store.setLocked(CHART, asInstanceId("nope"), true);
    expect(store.getChart(CHART)).toBe(doc);
    expect(doc.undo).toHaveLength(2);
    store.setLocked(CHART, a, false);
    expect(store.remove(CHART, a).ok).toBe(true);
  });
});

describe("the port's opaque key (BQ-03 AMEND)", () => {
  it.each(SEEDS)(
    "seed %i: server keys are only ever the served ones, client keys their form",
    (seed) =>
      withSeed(seed, (next) => {
        const s = createIndicatorStore({ report: () => undefined });
        const e = createFakeEngine({ series: `s${seed}` });
        s.bind(CHART, e);
        for (let step = 0; step < 120; step += 1) {
          const ids = s.selectInstances(CHART).map((i) => i.id);
          const roll = next();
          const n = int(next, 1, 400);
          // T01's PROPOSED key names two equal client instances alike (an open G-row on #425), so the
          // loop never asks for a second `bollinger` with one `n`; equal `server` specs are refused.
          const clash = s
            .selectInstances(CHART)
            .some((i) => i.indicator === "bollinger" && i.params["n"] === n);
          if (roll < 0.5 || ids.length === 0) {
            const pick = next() < 0.5 || clash ? ema : bb;
            s.add(CHART, addInput({ entry: pick, params: pick === bb ? { mult: 2, n } : { n } }));
          } else {
            const id = ids[int(next, 0, ids.length - 1)] as InstanceId;
            const found = s.selectInstances(CHART).find((i) => i.id === id);
            if (roll < 0.8 && found !== undefined && !(clash && found.indicator === "bollinger")) {
              s.configure(CHART, id, found.indicator === "ema" ? ema : bb, { ...found.params, n });
            } else {
              s.remove(CHART, id);
            }
          }
          for (const i of s.selectInstances(CHART)) {
            const k = s.keyOf(CHART, i.id);
            if (i.compute === "server") {
              expect(e.served).toContain(k);
            } else {
              const reversed = Object.fromEntries(Object.entries(i.params).reverse());
              expect(k).toBe(fakeClientKey(i.indicator, reversed, `s${seed}`));
            }
            expect(e.live.get(k as EngineKey)?.spec.params).toEqual(i.params);
          }
        }
      }),
  );
});

describe("indicator store caps", () => {
  it("test_the_21st_instance_is_refused_naming_the_instance_cap", () => {
    for (let k = 0; k < CAP_INSTANCES; k += 1) {
      idOf(store.add(CHART, addInput({ entry: bb, params: { n: k + 1 } })));
    }
    const calls = engine.calls.length;
    expect(store.add(CHART, addInput({ entry: bb, params: { n: 99 } }))).toEqual({
      ok: false,
      reason: "indicator.cap_instances",
    });
    expect(engine.calls.length).toBe(calls);
    expect(store.selectInstances(CHART)).toHaveLength(CAP_INSTANCES);
  });

  it("test_the_7th_subpane_is_refused_but_an_overlay_still_adds", () => {
    for (let k = 0; k < CAP_SUBPANES; k += 1) {
      idOf(store.add(CHART, addInput({ entry: rsi, params: { n: k + 2 }, target: "subpane" })));
    }
    expect(
      store.add(CHART, addInput({ entry: rsi, params: { n: 40 }, target: "subpane" })),
    ).toEqual({
      ok: false,
      reason: "indicator.cap_subpanes",
    });
    expect(store.add(CHART, addInput()).ok).toBe(true);
  });

  it("test_the_9th_server_instance_is_the_servers_refusal_never_the_clients", () => {
    for (let k = 0; k < SERVER_INSTANCES; k += 1)
      idOf(store.add(CHART, addInput({ params: { n: k + 2 } })));
    const doc = store.getChart(CHART);
    events.length = 0;
    expect(store.add(CHART, addInput({ params: { n: 99 } }))).toEqual({
      ok: false,
      reason: "invalid_options",
    });
    expect(engine.calls.at(-1)).toMatchObject({
      op: "add",
      outcome: { ok: false, refusal: "invalid_options" },
    });
    expect(store.getChart(CHART)).toBe(doc);
    expect(events).toEqual([]);
    // A client_worker instance is not on the subscription: it still adds.
    expect(store.add(CHART, addInput({ entry: bb, params: {} })).ok).toBe(true);
  });
});

describe("indicator store undo and redo", () => {
  it("test_add_undo_redo_round_trips_through_the_port", () => {
    const id = idOf(store.add(CHART, addInput()));
    expect(store.undo(CHART)).toBe("done");
    expect(engine.calls.at(-1)).toEqual({ op: "remove", key: "served:1" });
    expect(store.selectHistory(CHART)).toEqual({ canUndo: false, canRedo: true });
    expect(store.redo(CHART)).toBe("done");
    expect(engine.calls.at(-1)).toMatchObject({
      op: "add",
      outcome: { ok: true, key: "served:2" },
    });
    expect(store.selectInstances(CHART).map((i) => i.id)).toEqual([id]);
    expect(store.redo(CHART)).toBe("empty");
  });

  it("test_undo_of_a_remove_readds_same_params_at_the_end_of_its_pane", () => {
    const a = idOf(store.add(CHART, addInput()));
    const b = idOf(store.add(CHART, addInput({ params: { n: 50 } })));
    const c = idOf(store.add(CHART, addInput({ params: { n: 100 } })));
    store.remove(CHART, b);
    events.length = 0;
    const calls = engine.calls.length;
    expect(store.undo(CHART)).toBe("done");
    expect(engine.calls.slice(calls)).toEqual([
      {
        op: "add",
        spec: { indicator: "ema", compute: "server", pane: "price", params: { n: 50 } },
        outcome: { ok: true, key: "served:4" },
      },
    ]);
    expect(store.selectInstances(CHART).map((i) => i.id)).toEqual([a, c, b]);
    expect(engine.order("price")).toEqual([key(a), key(c), key(b)]);
    expect(events).toEqual([
      {
        name: "indicator.added",
        type: "ema",
        pane_target: "overlay",
        entry: "undo",
        compute: "server",
      },
    ]);
  });

  it("test_undo_never_resurrects_a_server_instance_the_server_refuses", () => {
    for (let k = 0; k < SERVER_INSTANCES; k += 1)
      idOf(store.add(CHART, addInput({ params: { n: k + 2 } })));
    const gone = store.selectInstances(CHART)[0]?.id as InstanceId;
    store.remove(CHART, gone);
    engine.capacity = SERVER_INSTANCES - 1;
    const doc = store.getChart(CHART);
    events.length = 0;
    expect(store.undo(CHART)).toBe("refused");
    expect(store.getChart(CHART)).toBe(doc);
    expect(store.selectInstances(CHART)).toHaveLength(SERVER_INSTANCES - 1);
    expect(events).toEqual([]);
    engine.capacity = SERVER_INSTANCES;
    expect(store.undo(CHART)).toBe("done");
    expect(ops().at(-1)).toBe("add");
  });

  it("test_configure_and_reorder_undo_restore_the_previous_state", () => {
    const a = idOf(store.add(CHART, addInput()));
    const b = idOf(store.add(CHART, addInput({ params: { n: 50 } })));
    store.configure(CHART, a, ema, { n: 9 });
    store.reorder(CHART, b, 0);
    events.length = 0;
    expect(store.undo(CHART)).toBe("done");
    expect(engine.order("price")).toEqual([key(a), key(b)]);
    expect(store.undo(CHART)).toBe("done");
    expect(engine.calls.at(-1)).toMatchObject({ op: "setParams", params: { n: 21 } });
    expect(store.redo(CHART)).toBe("done");
    expect(store.redo(CHART)).toBe("done");
    expect(engine.order("price")).toEqual([key(b), key(a)]);
    expect(engine.live.get(key(a))?.spec.params).toEqual({ n: 9 });
    expect(events).toEqual([]);
  });

  it("test_history_ops_on_an_unbound_or_empty_chart", () => {
    expect(store.undo(CHART)).toBe("empty");
    expect(store.undo("other")).toBe("unbound");
    expect(store.redo("other")).toBe("unbound");
  });
});

describe("indicator store binding and teardown", () => {
  it("test_ops_on_an_unbound_chart_are_refused_with_no_port_call", () => {
    const id = idOf(store.add(CHART, addInput()));
    unbind();
    const calls = engine.calls.length;
    expect(store.add(CHART, addInput())).toEqual({ ok: false, reason: "unbound" });
    expect(store.configure(CHART, id, ema, { n: 9 })).toEqual({ ok: false, reason: "unbound" });
    expect(store.remove(CHART, id)).toEqual({ ok: false, reason: "unbound" });
    expect(store.reorder(CHART, id, 0)).toEqual({ ok: false, reason: "unbound" });
    expect(store.undo(CHART)).toBe("unbound");
    expect(store.keyOf(CHART, id)).toBeNull();
    expect(engine.calls.length).toBe(calls);
    // State survives the unmount (session state, BQ-3).
    expect(store.selectInstances(CHART).map((i) => i.id)).toEqual([id]);
  });

  it("test_rebind_replays_instances_in_order_and_takes_the_new_keys", () => {
    const a = idOf(store.add(CHART, addInput()));
    idOf(store.add(CHART, addInput({ entry: rsi, params: {}, target: "subpane" })));
    const b = idOf(store.add(CHART, addInput({ params: { n: 50 } })));
    store.reorder(CHART, b, 0);
    unbind();
    const next = createFakeEngine();
    next.capacity = 2;
    store.bind(CHART, next);
    expect(next.calls.map((c) => c.op === "add" && c.spec.indicator)).toEqual([
      "ema",
      "rsi",
      "ema",
    ]);
    expect(next.order("price")).toEqual(["served:1"]);
    expect([store.keyOf(CHART, b), store.keyOf(CHART, a)]).toEqual(["served:1", null]);
  });

  it("test_a_stale_unbind_does_not_drop_the_newer_binding", () => {
    const next = createFakeEngine();
    store.bind(CHART, next);
    unbind();
    idOf(store.add(CHART, addInput()));
    expect(next.calls).toHaveLength(1);
    expect(engine.calls).toHaveLength(0);
  });

  it("test_dispose_drops_state_and_binding_and_notifies", () => {
    idOf(store.add(CHART, addInput()));
    store.selectPane(CHART, "price");
    store.selectHistory(CHART);
    const listener = vi.fn();
    store.subscribe(listener);
    store.dispose(CHART);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.selectInstances(CHART)).toEqual([]);
    expect(store.selectPane(CHART, "price")).toEqual([]);
    expect(store.selectHistory(CHART)).toEqual({ canUndo: false, canRedo: false });
    expect(store.add(CHART, addInput())).toEqual({ ok: false, reason: "unbound" });
    store.dispose("never-bound");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("test_unsubscribe_stops_notifications", () => {
    const listener = vi.fn();
    const off = store.subscribe(listener);
    idOf(store.add(CHART, addInput()));
    expect(listener).toHaveBeenCalledTimes(1);
    off();
    idOf(store.add(CHART, addInput({ params: { n: 50 } })));
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("test_an_engine_throw_leaves_state_unchanged", () => {
    const id = idOf(store.add(CHART, addInput()));
    const doc = store.getChart(CHART);
    const throwing = {
      ...createFakeEngine(),
      setParams: () => {
        throw new Error("cap");
      },
    };
    store.bind(CHART, throwing);
    expect(() => store.configure(CHART, id, ema, { n: 9 })).toThrow("cap");
    expect(store.getChart(CHART)).toBe(doc);
  });

  it("test_zero_store_updates_across_a_thousand_values_reaching_the_engine", () => {
    const a = idOf(store.add(CHART, addInput()));
    const b = idOf(store.add(CHART, addInput({ entry: bb, params: {} })));
    const listener = vi.fn();
    store.subscribe(listener);
    const before = store.selectInstances(CHART);
    for (let k = 0; k < 1000; k += 1) engine.feed(key(k % 2 === 0 ? a : b), k % 7 === 0 ? null : k);
    expect(engine.values.size).toBe(2);
    expect(listener).not.toHaveBeenCalled();
    expect(store.selectInstances(CHART)).toBe(before);
  });

  it("test_selectors_keep_references_until_their_slice_changes", () => {
    const a = idOf(store.add(CHART, addInput()));
    const price = store.selectPane(CHART, "price");
    const hist = store.selectHistory(CHART);
    expect(store.selectPane(CHART, "price")).toBe(price);
    idOf(store.add(CHART, addInput({ entry: rsi, params: {}, target: "subpane" })));
    expect(store.selectPane(CHART, "price")).toBe(price);
    expect(store.selectHistory(CHART)).toBe(hist);
    store.configure(CHART, a, ema, { n: 9 });
    expect(store.selectPane(CHART, "price")).not.toBe(price);
    expect(store.selectPane(CHART, "nowhere")).toBe(store.selectPane(CHART, "nowhere"));
    store.undo(CHART);
    expect(store.selectHistory(CHART)).toEqual({ canUndo: true, canRedo: true });
  });

  it("test_store_holds_config_only_never_series_or_values", () => {
    idOf(store.add(CHART, addInput()));
    const keys = Object.keys(store.selectInstances(CHART)[0] ?? {}).sort();
    expect(keys).toEqual([
      "compute",
      "id",
      "indicator",
      "locked",
      "params",
      "placement",
      "slot",
      "tier",
      "visible",
    ]);
  });
});

describe("fake engine and analytics seam", () => {
  let seen: unknown[];
  const onEvent = (e: Event): void => {
    seen.push((e as CustomEvent).detail);
  };
  beforeEach(() => {
    seen = [];
    window.addEventListener("cv:analytics", onEvent);
  });
  afterEach(() => window.removeEventListener("cv:analytics", onEvent));

  it("test_only_indicator_added_is_named_and_the_other_four_are_proposed", () => {
    expect(NAMED_EVENT_NAMES).toEqual(["indicator.added"]);
    expect(PROPOSED_EVENT_NAMES).toHaveLength(4);
    expect(PROPOSED_EVENT_NAMES).not.toContain("indicator.added");
  });

  it("test_report_indicator_dispatches_on_cv_analytics", () => {
    reportIndicator({ name: "indicator.removed", type: "ema", source: "tree" });
    expect(seen).toEqual([{ name: "indicator.removed", type: "ema", source: "tree" }]);
  });

  it("test_default_store_reporter_uses_the_seam_and_default_mint", () => {
    const s = createIndicatorStore();
    s.bind("c", createFakeEngine());
    const r = s.add("c", addInput());
    expect(r.ok && typeof r.id === "string" && r.id.length > 0).toBe(true);
    expect(seen).toHaveLength(1);
  });

  it("test_fake_engine_refuses_calls_no_engine_could_honour", () => {
    const e = createFakeEngine();
    const nope = "nope" as EngineKey;
    const spec = {
      indicator: "bollinger",
      compute: "client_worker",
      pane: "price",
      params: {},
    } as const;
    expect(() => e.setParams(nope, {})).toThrow("unknown instance");
    expect(() => e.remove(nope)).toThrow("unknown instance");
    expect(() => e.feed(nope, 1)).toThrow("unknown instance");
    e.add(spec);
    expect(() => e.add(spec)).toThrow("duplicate key");
    expect(() => e.setOrder("price", [nope])).toThrow("other instances");
    expect(e.order("sub:x")).toEqual([]);
  });

  it("test_fake_server_refuses_a_duplicate_spec_and_past_its_capacity", () => {
    const e = createFakeEngine();
    const spec = { indicator: "ema", compute: "server", pane: "price", params: { n: 5 } } as const;
    expect(e.add(spec)).toEqual({ ok: true, key: "served:1" });
    expect(e.add(spec)).toEqual({ ok: false, refusal: "invalid_options" });
    e.capacity = 1;
    expect(e.add({ ...spec, params: { n: 6 } })).toEqual({
      ok: false,
      refusal: "subscription_limit",
    });
    expect(e.setParams("served:1" as EngineKey, { n: 7 })).toEqual({ ok: true, key: "served:2" });
  });
});
