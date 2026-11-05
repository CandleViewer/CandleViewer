// E11-S09 PR 2a: the worker-side sync group core (CMP-196, BQ-7, BQ-13, BQ-17, BQ-24).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  checkSyncModes,
  DEFAULT_SYNC_MODES,
  ENGINE_SYNC_REFUSED,
  MAX_SYNC_ORIGINS,
  SyncGroups,
  type SyncMember,
  type SyncModes,
  type SyncPublication,
  SyncRefused,
} from "../../src/sync/SyncGroup.js";

class Member implements SyncMember {
  received: { from: number; time: boolean; cross: boolean }[] = [];
  constructor(
    readonly id: number,
    public modes: SyncModes = DEFAULT_SYNC_MODES,
  ) {}
  applySync(p: SyncPublication): void {
    this.received.push({ from: p.chart, time: p.hasTime, cross: p.hasCrosshair });
  }
}

describe("SyncGroup (BQ-13): propagates once per frame with no echo", () => {
  it("test_flush_publication_reaches_every_other_member_never_the_publisher", () => {
    const groups = new SyncGroups<Member>();
    const [a, b, c] = [new Member(1), new Member(2), new Member(3)];
    for (const m of [a, b, c]) groups.join(m, "A");
    groups.get("A")?.publish(a, true, 10, 20, true, 15);
    expect(groups.flush()).toBe(2);
    expect(a.received).toEqual([]);
    expect(b.received).toEqual([{ from: 1, time: true, cross: true }]);
    expect(groups.get("A")?.propagations).toBe(1);
    expect(groups.flush()).toBe(0); // nothing pending: no second propagation
    expect(groups.get("A")?.propagations).toBe(0);
  });

  it("test_publish_last_writer_wins_so_a_frame_propagates_at_most_once", () => {
    const rng = mulberry32(0x5eed09);
    const groups = new SyncGroups<Member>();
    const ms = [1, 2, 3, 4].map((id) => new Member(id));
    for (const m of ms) groups.join(m, "A");
    for (let frame = 0; frame < 600; frame += 1) {
      let last = -1;
      for (const m of ms) {
        if (rng() < 0.5) continue;
        if (groups.get("A")?.publish(m, true, frame, frame + 1, rng() < 0.5, frame)) last = m.id;
      }
      for (const m of ms) m.received.length = 0;
      groups.flush();
      expect(groups.get("A")?.propagations).toBeLessThanOrEqual(1);
      for (const m of ms) {
        expect(m.received.every((r) => r.from !== m.id)).toBe(true); // no echo
        expect(m.received.length).toBe(last === -1 || last === m.id ? 0 : 1);
      }
    }
    expect(groups.get("A")?.propagationsMax).toBe(1);
  });

  it("test_modes_per_mode_propagation_skips_a_member_that_takes_neither_part", () => {
    const groups = new SyncGroups<Member>();
    const timeOnly = { ...DEFAULT_SYNC_MODES, crosshair: false };
    const crossOnly = { ...DEFAULT_SYNC_MODES, time: false };
    const [a, b, c] = [new Member(1), new Member(2, timeOnly), new Member(3, crossOnly)];
    for (const m of [a, b, c]) groups.join(m, "A");
    groups.get("A")?.publish(a, false, 0, 1, true, 5); // a crosshair only
    groups.flush();
    expect(b.received).toEqual([]);
    expect(c.received).toEqual([{ from: 1, time: false, cross: true }]);
    // The publisher's own modes gate what it shares: a time-only member shares no crosshair.
    expect(groups.get("A")?.publish(b, false, 0, 1, true, 5)).toBe(false);
  });

  it("test_accept_drops_a_stale_seq_from_the_same_origin_only", () => {
    const g = new SyncGroups<Member>().join(new Member(1), "A");
    expect(g?.accept("w1", 3, 5)).toBe(true);
    expect(g?.accept("w1", 3, 5)).toBe(false);
    expect(g?.accept("w1", 3, 4)).toBe(false);
    expect(g?.accept("w2", 3, 1)).toBe(true); // another origin's counter is its own
    expect(g?.accept("w1", 3, 6)).toBe(true);
  });

  it("test_accept_interleaved_origins_keep_their_own_floor", () => {
    const g = new SyncGroups<Member>().join(new Member(1), "A");
    expect(g?.accept("wA", 1, 5)).toBe(true);
    expect(g?.accept("wB", 1, 3)).toBe(true);
    expect(g?.accept("wA", 1, 4)).toBe(false); // A's replay, though B came in between
    expect(g?.accept("wB", 2, 9)).toBe(true);
    expect(g?.accept("wB", 1, 2)).toBe(false); // the same worker, another chart's counter
  });

  it("test_accept_remembers_at_most_MAX_SYNC_ORIGINS_least_recent_first", () => {
    const g = new SyncGroups<Member>().join(new Member(1), "A");
    for (let i = 0; i <= MAX_SYNC_ORIGINS; i += 1) g?.accept(`w${i}`, 0, 5);
    expect(g?.originCount).toBe(MAX_SYNC_ORIGINS);
    expect(g?.accept("w0", 0, 1)).toBe(true); // evicted: its floor is forgotten
    expect(g?.accept(`w${MAX_SYNC_ORIGINS}`, 0, 5)).toBe(false); // still remembered
  });
});

describe("SyncGroups: membership and bounds (C-2.18)", () => {
  it("test_join_moves_a_member_and_drops_an_emptied_group", () => {
    const groups = new SyncGroups<Member>();
    const a = new Member(1);
    groups.join(a, "A");
    groups.join(a, "B");
    expect(groups.get("A")).toBeUndefined();
    expect(groups.get("B")?.members).toEqual([a]);
    expect(groups.join(a, null)).toBeUndefined();
    expect(groups.groups.size).toBe(0);
  });

  it("test_join_past_the_caps_is_refused_recoverably_and_keeps_membership", () => {
    const groups = new SyncGroups<Member>(1, 2);
    const [a, b, c] = [new Member(1), new Member(2), new Member(3)];
    groups.join(a, "A");
    groups.join(b, "A");
    expect(() => groups.join(c, "A")).toThrow(SyncRefused);
    expect(() => groups.join(c, "B")).toThrow(/at most 1 sync groups/);
    try {
      groups.join(a, "B");
    } catch (e) {
      expect((e as SyncRefused).code).toBe(ENGINE_SYNC_REFUSED);
      expect((e as SyncRefused).recoverable).toBe(true);
    }
    expect(groups.of(a)?.id).toBe("A");
  });

  it("test_leave_clears_a_pending_publication_of_the_leaver", () => {
    const groups = new SyncGroups<Member>();
    const [a, b] = [new Member(1), new Member(2)];
    groups.join(a, "A");
    groups.join(b, "A");
    groups.get("A")?.publish(a, true, 0, 1, false, null);
    groups.leave(a);
    expect(groups.flush()).toBe(0);
    expect(b.received).toEqual([]);
  });
});

describe("SyncModes (BQ-17, BQ-24 AMEND)", () => {
  it("test_checkSyncModes_defaults_time_and_crosshair_on", () => {
    expect(checkSyncModes({})).toEqual({
      time: true,
      crosshair: true,
      levels: false,
      scale: false,
    });
    expect(checkSyncModes({ levels: true }).levels).toBe(true);
  });

  it("test_checkSyncModes_scale_true_is_refused_never_ignored", () => {
    expect(() => checkSyncModes({ scale: true })).toThrow(SyncRefused);
  });
});
