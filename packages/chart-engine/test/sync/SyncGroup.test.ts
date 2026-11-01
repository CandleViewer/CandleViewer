// E11-S09 PR 2 (#446 BQ-7, BQ-12, BQ-13): the worker-side sync groups as a pure unit. A fake
// target records every application; seeded runs check "once per group per frame" and "no echo".
import { describe, expect, it } from "vitest";
import {
  DEFAULT_SYNC_MODES,
  SyncHub,
  type SyncModes,
  type SyncPayload,
  type SyncTarget,
} from "../../src/sync/SyncGroup.js";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";

type Applied = ["time", number, number, number] | ["cross", number, number | null];

function hub(worker = "w1"): {
  hub: SyncHub;
  applied: Applied[];
  relayed: [string, SyncPayload][];
  target: SyncTarget;
} {
  const applied: Applied[] = [];
  const relayed: [string, SyncPayload][] = [];
  const target: SyncTarget = {
    applyTime: (chart, t0, t1) => void applied.push(["time", chart, t0, t1]),
    applyCrosshair: (chart, t) => void applied.push(["cross", chart, t]),
    relay: (g, p) => void relayed.push([g, p]),
  };
  return { hub: new SyncHub(target, worker), applied, relayed, target };
}

const TIME_ONLY: SyncModes = { time: true, crosshair: false, levels: false };
const CROSS_ONLY: SyncModes = { time: false, crosshair: true, levels: false };

describe("BQ-13: publish once, apply to every other member, never back", () => {
  it("test_flush_onePublisher_appliesToPeersOnly_onePropagation", () => {
    const { hub: h, applied } = hub();
    for (const c of [1, 2, 3]) h.join(c, "g", DEFAULT_SYNC_MODES);
    h.join(4, "other", DEFAULT_SYNC_MODES);
    h.beginFrame();
    expect(h.publishTime(2, 10, 100, 200)).toBe(true);
    expect(h.publishCrosshair(2, 10, 150)).toBe(true);
    expect(h.flush()).toBe(1);
    expect(applied).toEqual([
      ["time", 1, 100, 200],
      ["cross", 1, 150],
      ["time", 3, 100, 200],
      ["cross", 3, 150],
    ]);
    expect(h.counters).toMatchObject({
      propagationsPerFrame: 1,
      propagations: 1,
      groupMembers: 4,
      echoes: 0,
    });
    applied.length = 0;
    h.beginFrame();
    expect(h.flush()).toBe(0); // nothing published: nothing applied
    expect(applied).toEqual([]);
    expect(h.counters.propagationsPerFrame).toBe(0);
  });

  it("test_publish_twoInOneFrame_laterInputWins_loserBecomesAMember", () => {
    const { hub: h, applied } = hub();
    h.join(1, "g", DEFAULT_SYNC_MODES);
    h.join(2, "g", DEFAULT_SYNC_MODES);
    h.beginFrame();
    h.publishTime(1, 20, 100, 200); // the later input
    expect(h.publishTime(2, 10, 300, 400)).toBe(false); // an earlier input loses
    h.flush();
    expect(applied).toEqual([["time", 2, 100, 200]]);
    applied.length = 0;
    h.beginFrame();
    h.publishTime(1, 30, 1, 2);
    h.publishTime(2, 30, 3, 4); // a tie: the later call wins
    h.flush();
    expect(applied).toEqual([["time", 1, 3, 4]]);
  });

  it("test_modes_filterPublishersAndMembers_perField", () => {
    const { hub: h, applied } = hub();
    h.join(1, "g", TIME_ONLY);
    h.join(2, "g", CROSS_ONLY);
    h.join(3, "g", DEFAULT_SYNC_MODES);
    h.beginFrame();
    expect(h.publishCrosshair(1, 1, 5)).toBe(false); // crosshair mode off: not published
    expect(h.publishTime(2, 1, 1, 2)).toBe(false); // time mode off: not published
    h.publishTime(3, 1, 10, 20);
    h.publishCrosshair(3, 1, 15);
    h.flush();
    expect(applied).toEqual([
      ["time", 1, 10, 20],
      ["cross", 2, 15],
    ]);
    expect(h.modesOf(2)).toEqual(CROSS_ONLY);
    expect(h.modesOf(9)).toBeNull();
    expect(h.groupOf(3)).toBe("g");
  });

  it("test_publish_insideAnApplication_isAnEcho_countedAndDropped", () => {
    // A target that (wrongly) publishes back while applying: the hub refuses and counts it.
    const applied: number[] = [];
    const ref: { hub: SyncHub | null } = { hub: null };
    const target: SyncTarget = {
      applyTime: (chart, t0, t1) => {
        applied.push(chart);
        expect(ref.hub?.publishTime(chart, 99, t0, t1)).toBe(false);
        expect(ref.hub?.publishCrosshair(chart, 99, t0)).toBe(false);
      },
      applyCrosshair: () => undefined,
      relay: () => undefined,
    };
    const h = new SyncHub(target, "w");
    ref.hub = h;
    h.join(1, "g", DEFAULT_SYNC_MODES);
    h.join(2, "g", DEFAULT_SYNC_MODES);
    h.beginFrame();
    h.publishTime(1, 1, 10, 20);
    h.flush();
    expect(applied).toEqual([2]);
    expect(h.counters.echoes).toBe(2);
    h.beginFrame();
    expect(h.flush()).toBe(0); // the echoes left nothing pending
  });

  it("test_join_withTimeOn_adoptsTheGroupsLastRange_leaveDropsPending", () => {
    const { hub: h, applied } = hub();
    h.join(1, "g", DEFAULT_SYNC_MODES);
    h.join(2, "g", DEFAULT_SYNC_MODES);
    h.join(3, "g", CROSS_ONLY); // no range yet: nothing to adopt
    expect(applied).toEqual([]);
    h.beginFrame();
    h.publishTime(1, 1, 10, 20);
    h.flush();
    applied.length = 0;
    h.join(4, "g", DEFAULT_SYNC_MODES);
    h.join(5, "g", CROSS_ONLY); // time off: adopts nothing
    expect(applied).toEqual([["time", 4, 10, 20]]);
    expect(h.join(4, "g", TIME_ONLY)).toBe(false); // same group: re-moded, not re-joined
    expect(h.modesOf(4)).toEqual(TIME_ONLY);
    h.beginFrame();
    h.publishTime(2, 2, 30, 40);
    h.leave(2); // its publication goes with it
    expect(h.flush()).toBe(0);
    expect(h.join(1, null, DEFAULT_SYNC_MODES)).toBe(true);
    expect(h.join(1, null, DEFAULT_SYNC_MODES)).toBe(false);
    h.leave(42); // unknown: nothing
    expect(h.counters.groupMembers).toBe(3);
    for (const c of [3, 4, 5]) h.leave(c);
    expect(h.counters.groupMembers).toBe(0);
    expect(h.groupOf(3)).toBeNull();
  });
});

describe("BQ-7, BQ-8: relay out, receive in, own origin and stale seq dropped", () => {
  it("test_flush_relayGroup_postsOnePayloadPerFrame_withARisingSeq", () => {
    const { hub: h, relayed } = hub("A");
    h.join(1, "g", DEFAULT_SYNC_MODES, true);
    h.join(2, "h", DEFAULT_SYNC_MODES); // not a relay group
    h.beginFrame();
    h.publishTime(1, 1, 10, 20);
    h.publishCrosshair(1, 1, 15);
    h.publishCrosshair(2, 1, 15);
    h.flush();
    h.beginFrame();
    h.publishCrosshair(1, 2, null);
    h.flush();
    expect(relayed).toEqual([
      ["g", { timeRange: [10, 20], crosshair: 15, origin: { worker: "A", chart: 1, seq: 1 } }],
      ["g", { crosshair: null, origin: { worker: "A", chart: 1, seq: 2 } }],
    ]);
  });

  it("test_receive_ownOriginOrStaleSeq_isDropped_otherwiseAppliedByMode", () => {
    const { hub: h, applied } = hub("B");
    h.join(7, "g", DEFAULT_SYNC_MODES);
    h.join(8, "g", CROSS_ONLY);
    const from = (worker: string, seq: number) => ({ worker, chart: 1, seq });
    expect(h.receive("g", { timeRange: [1, 2], origin: from("B", 1) })).toBe(false); // own
    expect(h.receive("g", { timeRange: [1, 2], crosshair: 1.5, origin: from("A", 5) })).toBe(true);
    expect(h.receive("g", { timeRange: [3, 4], origin: from("A", 5) })).toBe(false); // not newer
    expect(h.receive("g", { timeRange: [3, 4], origin: from("A", 3) })).toBe(false); // older
    expect(h.receive("g", { crosshair: null, origin: from("C", 1) })).toBe(true); // its own seq
    expect(h.receive("nope", { timeRange: [3, 4], origin: from("A", 9) })).toBe(false);
    expect(h.receive("g", { timeRange: [5, 6] })).toBe(true); // no origin: the pre-S09 form
    expect(applied).toEqual([
      ["time", 7, 1, 2],
      ["cross", 7, 1.5],
      ["cross", 8, 1.5],
      ["cross", 7, null],
      ["cross", 8, null],
      ["time", 7, 5, 6],
    ]);
    expect(h.counters.dropped).toBe(3);
    applied.length = 0;
    h.join(9, "g", DEFAULT_SYNC_MODES); // a received range is the group's last range too
    expect(applied).toEqual([["time", 9, 5, 6]]);
  });
});

describe("M1: the relay seq is the worker's, so a re-made group is never stale", () => {
  it("test_joinRelayLeaveRejoinRelay_seqKeepsRising_peerAppliesTheSecond", () => {
    const { hub: a, relayed } = hub("A");
    const { hub: b, applied } = hub("B");
    b.join(7, "g", DEFAULT_SYNC_MODES);
    const relayOnce = (t0: number): void => {
      a.beginFrame();
      a.publishTime(1, t0, t0, t0 + 10);
      a.flush();
      const [g, p] = relayed.at(-1) as [string, SyncPayload];
      b.receive(g, p);
    };
    a.join(1, "g", DEFAULT_SYNC_MODES, true);
    relayOnce(100);
    a.leave(1); // the group empties and is deleted on A
    a.join(1, "g", DEFAULT_SYNC_MODES, true); // re-made under the same worker id
    relayOnce(200);
    a.join(1, "h", DEFAULT_SYNC_MODES, true); // another group shares the one counter
    a.join(1, "g", DEFAULT_SYNC_MODES, true);
    relayOnce(300);
    expect(relayed.map(([, p]) => p.origin.seq)).toEqual([1, 2, 3]);
    expect(applied).toEqual([
      ["time", 7, 100, 110],
      ["time", 7, 200, 210],
      ["time", 7, 300, 310],
    ]);
    expect(b.counters.dropped).toBe(0);
  });
});

describe("m2: the per-frame path makes no group and walks a plain array", () => {
  it("test_steadyFrames_createNoGroups", () => {
    const { hub: h } = hub();
    for (const c of [1, 2, 3, 4]) h.join(c, c < 3 ? "g" : "k", DEFAULT_SYNC_MODES);
    const warm = h.created;
    for (let f = 0; f < 200; f += 1) {
      h.beginFrame();
      h.publishTime(1 + (f % 4), f, f, f + 10);
      h.publishCrosshair(1 + ((f + 1) % 4), f, f % 3 === 0 ? null : f);
      h.flush();
    }
    expect(h.created - warm).toBe(0);
    h.leave(3);
    h.leave(4); // "k" is deleted; the walks skip it from now on
    h.beginFrame();
    h.publishTime(3, 1, 1, 2); // no longer a member: dropped
    expect(h.flush()).toBe(0);
  });
});

describe("Scenario: Sync propagates once with no echo (600 seeded frames, 2 to 4 charts)", () => {
  it.each([2, 3, 4])("%i charts: at most one propagation per group per frame, no echo", (n) => {
    const r = mulberry32(0x5e9c + n);
    const { hub: h, applied } = hub();
    for (let c = 1; c <= n; c += 1) h.join(c, c % 2 === 0 || n < 4 ? "g" : "k", DEFAULT_SYNC_MODES);
    for (let f = 0; f < 600; f += 1) {
      h.beginFrame();
      applied.length = 0;
      const publishers = new Set<number>();
      const pubs = Math.floor(r() * 3);
      for (let p = 0; p < pubs; p += 1) {
        const c = 1 + Math.floor(r() * n);
        publishers.add(c);
        const t0 = Math.floor(r() * 1000);
        if (r() < 0.5) h.publishTime(c, f * 10 + p, t0, t0 + 100);
        else h.publishCrosshair(c, f * 10 + p, r() < 0.2 ? null : t0);
      }
      h.flush();
      expect(h.counters.propagationsPerFrame).toBeLessThanOrEqual(1);
      // Each (chart, field) is applied at most once a frame.
      const keys = applied.map((a) => `${a[0]}:${a[1]}`);
      expect(new Set(keys).size).toBe(keys.length);
    }
    expect(h.counters.echoes).toBe(0);
    expect(h.counters.maxPropagationsPerFrame).toBe(1);
  });
});
