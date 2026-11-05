/**
 * E13-S01 (#423) S1: instances as client state with opaque ids (BQ-3), D03 §3.4's slot and tier
 * assignment (seeded properties: a pair is never shared on a pane), and the add availability rule
 * (BQ-2, BQ-15; D06 §8.1; SR-E13-11).
 */
import { describe, expect, it } from "vitest";
import {
  availability,
  computePath,
  defaultTarget,
  targetsOf,
} from "../../../src/features/indicators/model/availability";
import {
  normaliseDescriptor,
  type CatalogueEntry,
} from "../../../src/features/indicators/model/catalogue";
import {
  assignSlot,
  CAP_INSTANCES,
  CAP_SUBPANES,
  createInstance,
  onChartCount,
  paneKey,
  readdInstance,
  subpaneCount,
  type Instance,
} from "../../../src/features/indicators/model/instances";
import { defaultParams } from "../../../src/features/indicators/model/params";
import { BOLLINGER, CVD, EMA, RSI, VOLUME } from "./fixtures";
import { int, rng, SEEDS } from "./rng";

const entry = (raw: unknown): CatalogueEntry => {
  const e = normaliseDescriptor(raw);
  if (e === null) throw new Error("bad fixture");
  return e;
};
const ENTRIES = [EMA, BOLLINGER, RSI, VOLUME, CVD].map(entry);
const [ema, bb, rsi, volume] = ENTRIES as [
  CatalogueEntry,
  CatalogueEntry,
  CatalogueEntry,
  CatalogueEntry,
];
const paramsOf = (e: CatalogueEntry) => (e.schema.ok ? defaultParams(e.schema.fields) : {});

function minter(): () => string {
  let n = 0;
  return () => `id-${(n += 1)}`;
}

const add = (
  list: readonly Instance[],
  e: CatalogueEntry,
  target: "overlay" | "subpane",
  mint: () => string,
) => [...list, createInstance(list, { entry: e, params: paramsOf(e), target }, mint)];

const pairsUnique = (list: readonly Instance[]): boolean => {
  const seen = new Set<string>();
  for (const i of list) {
    const k = `${paneKey(i.placement)}|${i.slot}|${i.tier}`;
    if (seen.has(k)) return false;
    seen.add(k);
  }
  return true;
};

describe("createInstance", () => {
  it("mints an opaque id, places the instance and starts visible and unlocked", () => {
    const mint = minter();
    const [first] = add([], ema, "overlay", mint);
    expect(first).toMatchObject({
      id: "id-1",
      indicator: "ema",
      compute: "server",
      params: { n: 21 },
      placement: { kind: "price" },
      slot: 1,
      tier: 0,
      visible: true,
      locked: false,
    });
    const [sub] = add([], rsi, "subpane", mint);
    expect(sub?.placement).toEqual({ kind: "sub", pane: "id-2" });
    expect(sub?.id).toBe("id-3");
  });

  it("gives a second instance of one indicator the next hue and the next tier (D02 D4)", () => {
    const mint = minter();
    const list = add(add([], ema, "overlay", mint), ema, "overlay", mint);
    expect(list.map((i) => [i.slot, i.tier])).toEqual([
      [1, 0],
      [2, 1],
    ]);
    expect(onChartCount(list, "ema")).toBe(2);
    expect(new Set(list.map((i) => i.id)).size).toBe(2);
  });

  it("counts sub-panes, one per sub-pane add", () => {
    const mint = minter();
    let list: Instance[] = [];
    for (let i = 0; i < 3; i += 1) list = add(list, rsi, "subpane", mint);
    list = add(list, ema, "overlay", mint);
    expect(subpaneCount(list)).toBe(3);
  });
});

describe("assignSlot (D03 §3.4)", () => {
  it("takes the lowest hue not on the pane, then the lowest free pair from the sibling tier on", () => {
    const eight = Array.from({ length: 8 }, (_, k) => ({
      indicator: `x${k}`,
      slot: k + 1,
      tier: 0,
    }));
    expect(assignSlot(eight, "new")).toEqual({ slot: 1, tier: 1 });
    expect(
      assignSlot(
        [
          { indicator: "a", slot: 1, tier: 0 },
          { indicator: "a", slot: 2, tier: 1 },
        ],
        "a",
      ),
    ).toEqual({ slot: 3, tier: 2 });
  });

  it("wraps the tier after six siblings and still finds a free pair", () => {
    const six = Array.from({ length: 6 }, (_, k) => ({ indicator: "a", slot: k + 1, tier: k }));
    expect(assignSlot(six, "a")).toEqual({ slot: 7, tier: 0 });
  });

  it.each(SEEDS)(
    "seed %i: add, remove and undo up to the cap never share a pair on a pane",
    (seed) => {
      const next = rng(seed);
      const mint = minter();
      let list: Instance[] = [];
      const removed: Instance[] = [];
      for (let step = 0; step < 400; step += 1) {
        const roll = next();
        if (roll < 0.55 && list.length < CAP_INSTANCES) {
          const e = ENTRIES[int(next, 0, ENTRIES.length - 1)] as CatalogueEntry;
          // Mostly the price pane: every sub-pane add opens its own pane, so the price pane is the shared one.
          const target = e.pane === "sub" && next() < 0.3 ? "subpane" : "overlay";
          const huesBefore = new Set(
            list.filter((i) => i.placement.kind === "price").map((i) => i.slot),
          );
          list = add(list, e, target, mint);
          const added = list[list.length - 1] as Instance;
          // AC 3: a new instance takes a hue not on its pane while one is free (D03 §3.4).
          if (added.placement.kind === "price" && huesBefore.size < 8) {
            expect(huesBefore.has(added.slot)).toBe(false);
          }
        } else if (roll < 0.85 && list.length > 0) {
          const at = int(next, 0, list.length - 1);
          removed.push(list[at] as Instance);
          list = list.filter((_, k) => k !== at);
        } else if (removed.length > 0 && list.length < CAP_INSTANCES) {
          const back = removed.pop() as Instance;
          list = [...list, readdInstance(list, back)];
        }
        expect(pairsUnique(list)).toBe(true);
      }
    },
  );

  it("an undo re-adds with the same params on the next free pair, never the old one (BQ-04)", () => {
    const mint = minter();
    const first = add(add([], ema, "overlay", mint), bb, "overlay", mint);
    const gone = first[0] as Instance;
    expect([gone.slot, gone.tier]).toEqual([1, 0]);
    // While it was away another instance took (1, 0): the re-add takes the next free pair.
    const rest = add(first.slice(1), volume, "overlay", mint);
    expect(rest.map((i) => i.slot)).toEqual([2, 1]);
    const back = readdInstance(rest, gone);
    expect(back).toMatchObject({ id: gone.id, params: gone.params, slot: 3, tier: 0 });
    expect(back.params).toBe(gone.params);
  });
});

describe("availability (BQ-2, BQ-15)", () => {
  const none = () => false;
  const all = () => true;

  it("routes a server entry to the WS stream, never to a worker plugin (SR-E13-11)", () => {
    expect(computePath(ema, all)).toBe("server-stream");
    expect(computePath(ema, none)).toBe("server-stream");
    expect(availability(ema, "overlay", { hasPlugin: all, instances: [] })).toEqual({
      kind: "available",
      path: "server-stream",
    });
  });

  it("disables a client_worker entry with no plugin, with a reason, never hiding it", () => {
    expect(availability(bb, "overlay", { hasPlugin: none, instances: [] })).toEqual({
      kind: "disabled",
      reason: "no_path",
    });
    expect(
      availability(bb, "overlay", { hasPlugin: (id) => id === "bollinger", instances: [] }),
    ).toEqual({ kind: "available", path: "worker" });
  });

  it("disables an entry whose schema the renderer refused", () => {
    const hostile = entry({ ...EMA, params_schema: { $ref: "#" } });
    expect(availability(hostile, "overlay", { hasPlugin: all, instances: [] })).toMatchObject({
      reason: "no_path",
    });
  });

  it("gates the 21st instance, hidden ones counted, and the 7th sub-pane only for a sub-pane target", () => {
    const mint = minter();
    let list: Instance[] = [];
    for (let i = 0; i < CAP_SUBPANES; i += 1) list = add(list, rsi, "subpane", mint);
    expect(availability(rsi, "subpane", { hasPlugin: none, instances: list })).toEqual({
      kind: "disabled",
      reason: "indicator.cap_subpanes",
    });
    expect(availability(volume, "overlay", { hasPlugin: none, instances: list }).kind).toBe(
      "available",
    );
    while (list.length < CAP_INSTANCES) list = add(list, ema, "overlay", mint);
    list = list.map((i) => ({ ...i, visible: false }));
    expect(availability(ema, "overlay", { hasPlugin: none, instances: list })).toEqual({
      kind: "disabled",
      reason: "indicator.cap_instances",
    });
  });

  it("maps the descriptor pane to the targets it offers (D06 §3.3)", () => {
    expect(targetsOf(ema)).toEqual(["overlay"]);
    expect(targetsOf(rsi)).toEqual(["subpane"]);
    expect(targetsOf(volume)).toEqual(["overlay", "subpane"]);
    expect([ema, rsi, volume].map(defaultTarget)).toEqual(["overlay", "subpane", "overlay"]);
  });
});
