// E11-S09 PR 2b (#446): "Sync state is announced once" and the main-thread relay (BQ-21, BQ-22)
// on the pure registry, with fake members standing in for chart hosts on several workers.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { MAX_GROUP_MEMBERS, MAX_SYNC_GROUPS, SyncRefused } from "../../src/sync/SyncGroup.js";
import {
  createSyncRegistry,
  PANES_UNLINKED,
  type SyncPost,
  type SyncRelay,
  syncAnnouncement,
} from "../../src/sync/registry.js";

const ON = { time: true, crosshair: true, levels: false };
const LEVELS = { time: false, crosshair: true, levels: true };

function setup(maxGroups?: number) {
  const pending: (() => void)[] = [];
  const said: string[] = [];
  const reg = createSyncRegistry({
    schedule: (cb) => void pending.push(cb),
    ...(maxGroups !== undefined && { maxGroups }),
  });
  const apply = (): void => {
    for (const cb of pending.splice(0)) cb();
  };
  const member = (worker: string) => {
    const inbox: SyncRelay[] = [];
    let id = worker;
    const r = reg.attach({
      workerId: () => id,
      post: (m) => void inbox.push(m),
      announce: (t) => void said.push(t),
    });
    return { r, inbox, worker: () => id, restart: (w: string) => void (id = w) };
  };
  return { reg, said, apply, member };
}

const pub = (worker: string, chart: number, seq: number): SyncPost => ({
  t: "sync",
  id: chart,
  groupId: "G",
  timeRange: [1, 2],
  origin: { worker, chart, seq },
});

describe("Scenario: Sync state is announced once (BQ-22)", () => {
  it("test_enabling_levels_on_three_members_announces_once_and_a_repeat_says_nothing", () => {
    const { said, apply, member } = setup();
    const ms = [member("w1"), member("w1"), member("w2")];
    for (const m of ms) m.r.set("G", { ...LEVELS, levels: false });
    apply();
    said.length = 0; // the group forming: "Panes linked: crosshair"
    for (const m of ms) m.r.set("G", LEVELS); // the user enables level sync
    apply();
    expect(said).toEqual(["Panes linked: crosshair, levels"]);
    for (const m of ms) m.r.set("G", LEVELS); // unchanged
    apply();
    apply();
    expect(said).toHaveLength(1);
  });

  it("test_unlinking_the_group_announces_panes_unlinked_once", () => {
    const { said, apply, member, reg } = setup();
    const [a, b] = [member("w1"), member("w2")];
    a.r.set("G", ON);
    b.r.set("G", ON);
    apply();
    expect(said).toEqual(["Panes linked: time, crosshair"]);
    b.r.set(null, ON);
    apply();
    a.r.detach();
    apply();
    expect(said).toEqual(["Panes linked: time, crosshair", PANES_UNLINKED]);
    expect(reg.groupCount).toBe(0); // cleaned up once empty
  });

  it("test_announcement_lists_only_modes_every_member_has_on_in_order", () => {
    expect(syncAnnouncement([ON, LEVELS])).toBe("Panes linked: crosshair");
    expect(syncAnnouncement([ON, ON])).toBe("Panes linked: time, crosshair");
    expect(syncAnnouncement([ON])).toBe(PANES_UNLINKED);
    const off = { time: false, crosshair: false, levels: false };
    expect(syncAnnouncement([off, off])).toBe(PANES_UNLINKED);
  });
});

describe("BQ-21: the cross-worker relay", () => {
  it("test_relay_posts_once_per_other_worker_and_never_back_to_the_origin_worker", () => {
    const { reg, member } = setup();
    const [a, b, c, d] = [member("w1"), member("w1"), member("w2"), member("w2")];
    for (const m of [a, b, c, d]) m.r.set("G", ON);
    a.r.relay(pub("w1", 1, 1));
    expect([a.inbox, b.inbox, d.inbox]).toEqual([[], [], []]); // w1 applied it; w2 hears once
    expect(c.inbox).toEqual([
      { t: "sync", groupId: "G", timeRange: [1, 2], origin: { worker: "w1", chart: 1, seq: 1 } },
    ]);
    expect(reg.counters).toEqual({ relayed: 1, sameWorker: 1 });
    c.restart("w1"); // a peer now on the origin's worker is not echoed back
    d.restart("w1");
    a.r.relay(pub("w1", 1, 2));
    expect(c.inbox).toHaveLength(1);
    a.r.relay({ ...pub("w1", 1, 3), groupId: "other" }); // not its group: dropped
    expect(reg.counters.relayed).toBe(1);
  });

  it("test_relay_with_seeded_worker_layouts_reaches_each_other_worker_exactly_once", () => {
    const rng = mulberry32(0x5eed);
    for (let run = 0; run < 50; run += 1) {
      const { member } = setup();
      const ms = Array.from({ length: 2 + Math.floor(rng() * 8) }, () =>
        member(`w${Math.floor(rng() * 4)}`),
      );
      for (const m of ms) m.r.set("G", ON);
      const from = ms[Math.floor(rng() * ms.length)] as (typeof ms)[number];
      from.r.relay(pub(from.worker(), 1, 1));
      const hit = new Map<string, number>();
      for (const m of ms) if (m.inbox.length > 0) hit.set(m.worker(), m.inbox.length);
      const expected = new Set(ms.map((m) => m.worker()));
      expected.delete(from.worker());
      expect(new Set(hit.keys())).toEqual(expected);
      expect([...hit.values()].every((n) => n === 1)).toBe(true);
    }
  });

  it("test_detach_stops_relaying_and_set_after_detach_does_nothing", () => {
    const { reg, member } = setup();
    const [a, b] = [member("w1"), member("w2")];
    a.r.set("G", ON);
    b.r.set("G", ON);
    b.r.detach();
    a.r.relay(pub("w1", 1, 1));
    b.r.set("G", ON);
    expect(b.inbox).toEqual([]);
    expect(reg.counters.relayed).toBe(0);
  });
});

describe("bounds: the registry's group maps are capped and emptied", () => {
  it("test_registry_refuses_a_group_past_the_cap_and_a_member_past_a_full_group", () => {
    const { reg, member, apply } = setup();
    const ms = Array.from({ length: MAX_SYNC_GROUPS }, () => member("w1"));
    ms.forEach((m, i) => m.r.set(`g${i}`, ON));
    expect(() => member("w1").r.set("one-more", ON)).toThrow(SyncRefused);
    for (let i = 1; i < MAX_GROUP_MEMBERS; i += 1) member("w2").r.set("g0", ON);
    expect(() => member("w3").r.set("g0", ON)).toThrow(SyncRefused);
    for (const m of ms) m.r.detach();
    apply();
    expect(reg.groupCount).toBe(1); // g0 still holds the w2 members
    reg.dispose();
    expect(reg.groupCount).toBe(0);
  });
  it("test_join_in_the_tick_a_group_emptied_is_not_refused_at_the_group_cap", () => {
    const { reg, member, apply } = setup(1);
    const [a, b] = [member("w1"), member("w2")];
    a.r.set("g1", ON);
    a.r.set(null, ON); // g1 is empty; the flush has not run yet
    expect(() => b.r.set("g2", ON)).not.toThrow();
    expect(reg.groupCount).toBe(1);
    apply();
    expect(reg.groupCount).toBe(1);
  });

  it("test_a_group_emptied_by_disposed_charts_announces_nothing", () => {
    const { said, member, apply } = setup();
    const [a, b] = [member("w1"), member("w2")];
    a.r.set("G", ON);
    b.r.set("G", ON);
    apply();
    expect(said).toEqual(["Panes linked: time, crosshair"]);
    a.r.detach(); // a layout teardown: both leave in one tick
    b.r.detach();
    apply();
    expect(said).toHaveLength(1); // nobody is left to hear "Panes unlinked"
  });
});
