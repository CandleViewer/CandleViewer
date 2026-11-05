/**
 * E13-S01 (#423) S1b: the pure per-chart command reducer (BQ-4), shaped on the drawings history:
 * 100 entries, redo cleared by a new command, a stale entry dropped, caps re-checked on undo, and
 * a re-add on the next free pair at the end of its pane (BQ-04 rider, ruling 6652282467).
 */
import { describe, expect, it } from "vitest";
import {
  EMPTY_DOC,
  HISTORY_LIMIT,
  invert,
  reduce,
  type ChartDoc,
  type Command,
} from "../../../src/features/indicators/store/history";
import {
  asInstanceId,
  CAP_INSTANCES,
  CAP_SUBPANES,
  type Instance,
} from "../../../src/features/indicators/model/instances";
import type { Params } from "../../../src/features/indicators/model/types";

const params = (n: number): Params => Object.freeze({ n });
const inst = (id: string, over: Partial<Instance> = {}): Instance => ({
  id: asInstanceId(id),
  indicator: "ema",
  compute: "server",
  params: params(21),
  placement: { kind: "price" },
  slot: 1,
  tier: 0,
  visible: true,
  locked: false,
  ...over,
});
const doc = (instances: Instance[]): ChartDoc => ({ instances, undo: [], redo: [] });
const add = (instance: Instance): Command => ({ kind: "add", instance });

describe("indicator history", () => {
  it("test_invert_each_command_kind_round_trips", () => {
    const a = inst("a");
    const commands: Command[] = [
      add(a),
      { kind: "remove", instance: a },
      { kind: "configure", id: a.id, before: params(1), after: params(2) },
      { kind: "reorder", id: a.id, from: 0, to: 2 },
    ];
    for (const c of commands) expect(invert(invert(c))).toEqual(c);
    expect(invert(commands[2] as Command)).toMatchObject({ before: { n: 2 }, after: { n: 1 } });
  });

  it("test_do_add_appends_and_emits_one_add_effect", () => {
    const step = reduce(EMPTY_DOC, { type: "do", command: add(inst("a")) });
    expect(step.doc.instances.map((i) => i.id)).toEqual(["a"]);
    expect(step.effects).toEqual([{ op: "add", id: "a" }]);
    expect(step.doc.undo).toHaveLength(1);
  });

  it("test_undo_of_a_removal_readds_at_the_end_on_the_next_free_pair", () => {
    const [a, b, c] = [inst("a"), inst("b", { slot: 2 }), inst("c", { slot: 3 })];
    // While b was away, d took its pair (2, 0): the re-add never takes the old pair or position.
    const d = inst("d", { indicator: "bb", slot: 2 });
    const start: ChartDoc = {
      instances: [a, c, d],
      undo: [{ kind: "remove", instance: b }],
      redo: [],
    };
    const step = reduce(start, { type: "undo" });
    expect(step.doc.instances.map((i) => i.id)).toEqual(["a", "c", "d", "b"]);
    expect(step.effects).toEqual([{ op: "add", id: "b" }]);
    const back = step.doc.instances[3] as Instance;
    expect([back.slot, back.tier]).toEqual([4, 1]);
    expect(back.params).toBe(b.params);
  });

  it("test_do_unavailable_when_id_taken_or_target_gone", () => {
    const a = inst("a");
    const start = doc([a]);
    expect(reduce(start, { type: "do", command: add(a) }).unavailable).toBe(true);
    const gone = inst("z");
    for (const command of [
      { kind: "remove", instance: gone },
      { kind: "configure", id: gone.id, before: params(1), after: params(2) },
      { kind: "reorder", id: gone.id, from: 0, to: 0 },
    ] as Command[]) {
      const step = reduce(start, { type: "do", command });
      expect(step).toMatchObject({ unavailable: true, effects: [], ran: null });
      expect(step.doc).toBe(start);
    }
  });

  it("test_reorder_with_a_stale_from_or_bad_to_is_unavailable", () => {
    const start = doc([inst("a"), inst("b", { slot: 2 })]);
    const stale = { kind: "reorder", id: asInstanceId("a"), from: 1, to: 0 } as const;
    expect(reduce(start, { type: "do", command: stale }).unavailable).toBe(true);
    const bad = { kind: "reorder", id: asInstanceId("a"), from: 0, to: 5 } as const;
    expect(reduce(start, { type: "do", command: bad }).unavailable).toBe(true);
  });

  it("test_reorder_moves_within_the_pane_and_leaves_other_panes", () => {
    const sub = inst("s", { placement: { kind: "sub", pane: "p1" }, indicator: "rsi" });
    const start = doc([inst("a"), sub, inst("b", { slot: 2 }), inst("c", { slot: 3 })]);
    const step = reduce(start, {
      type: "do",
      command: { kind: "reorder", id: asInstanceId("c"), from: 2, to: 0 },
    });
    expect(step.doc.instances.map((i) => i.id)).toEqual(["c", "s", "a", "b"]);
    expect(step.effects).toEqual([{ op: "setOrder", pane: "price", ids: ["c", "a", "b"] }]);
  });

  it("test_undo_then_redo_round_trips_and_new_command_clears_redo", () => {
    const one = reduce(EMPTY_DOC, { type: "do", command: add(inst("a")) }).doc;
    const undone = reduce(one, { type: "undo" });
    expect(undone.doc.instances).toEqual([]);
    expect(undone.effects).toEqual([{ op: "remove", id: "a" }]);
    expect(undone.ran?.kind).toBe("remove");
    const redone = reduce(undone.doc, { type: "redo" });
    expect(redone.doc.instances.map((i) => i.id)).toEqual(["a"]);
    expect(redone.doc.redo).toEqual([]);
    const again = reduce(undone.doc, { type: "do", command: add(inst("b")) });
    expect(again.doc.redo).toEqual([]);
  });

  it("test_undo_and_redo_on_empty_stacks_do_nothing", () => {
    for (const type of ["undo", "redo"] as const) {
      const step = reduce(EMPTY_DOC, { type });
      expect(step).toEqual({ doc: EMPTY_DOC, effects: [], ran: null, unavailable: false });
    }
  });

  it("test_history_keeps_the_last_100_entries", () => {
    let d: ChartDoc = doc([inst("a")]);
    for (let k = 0; k < HISTORY_LIMIT + 5; k += 1) {
      const command: Command = {
        kind: "configure",
        id: asInstanceId("a"),
        before: params(k),
        after: params(k + 1),
      };
      d = reduce(d, { type: "do", command }).doc;
    }
    expect(d.undo).toHaveLength(HISTORY_LIMIT);
    expect(d.undo[0]).toMatchObject({ before: { n: 5 } });
    // Redo re-pushes onto a full undo stack and stays bounded.
    const back = reduce(reduce(d, { type: "undo" }).doc, { type: "redo" }).doc;
    expect(back.undo).toHaveLength(HISTORY_LIMIT);
  });

  it("test_undo_of_a_removal_past_the_instance_cap_is_dropped", () => {
    const full = Array.from({ length: CAP_INSTANCES }, (_, k) => inst(`i${k}`));
    const removed = inst("gone");
    const d: ChartDoc = {
      instances: full,
      undo: [{ kind: "remove", instance: removed }],
      redo: [],
    };
    const step = reduce(d, { type: "undo" });
    expect(step.unavailable).toBe(true);
    expect(step.doc.undo).toEqual([]);
    expect(step.doc.instances).toBe(full);
  });

  it("test_redo_of_an_add_past_the_subpane_cap_is_dropped", () => {
    const subs = Array.from({ length: CAP_SUBPANES }, (_, k) =>
      inst(`s${k}`, { placement: { kind: "sub", pane: `p${k}` } }),
    );
    const extra = inst("x", { placement: { kind: "sub", pane: "new" } });
    const d: ChartDoc = { instances: subs, undo: [], redo: [add(extra)] };
    const step = reduce(d, { type: "redo" });
    expect(step.unavailable).toBe(true);
    expect(step.doc.redo).toEqual([]);
    // An instance joining an already-open sub-pane is within the cap.
    const join = inst("y", { placement: { kind: "sub", pane: "p0" } });
    expect(reduce(doc(subs), { type: "do", command: add(join) }).unavailable).toBe(false);
  });
});
