// E11-S09 PR 2 (#446 BQ-7 to BQ-9, BQ-12, BQ-13) through the render runtime: the three-phase
// tick delivers a publication to every member in the same tick whatever the charts' creation
// order (#388's bug 1), nothing is applied back to its publisher (bug 2), the leader coasts and
// the members follow, and a group spanning two workers is relayed by the registry with its
// origin kept. Frames are driven by hand: one `tick()` is one runtime frame callback.
import { beforeEach, describe, expect, it } from "vitest";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { SyncRegistry, type SyncMember } from "../../src/sync/registry.js";
import { DEFAULT_SYNC_MODES } from "../../src/sync/SyncGroup.js";
import {
  BACKGROUND_TOKEN,
  INPUT,
  KEY,
  type Command,
  type FromWorker,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";
import { AT_14, MIN, minuteMap, rows } from "../interaction/fixtures.js";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";

type Of<T extends FromWorker["t"]> = Extract<FromWorker, { t: T }>;
const THEME = { [BACKGROUND_TOKEN]: "#000000", "color.crosshair": "#ff0000" };
const MUTED = `rgba(255, 0, 0, ${Math.round(Math.fround(0.7) * 255) / 255})`;
const W = 1064;
const H = 624;

/** One runtime with its own frame queue, clock and outbox. */
class Rig {
  readonly out: FromWorker[] = [];
  readonly ctx = new Map<number, FakeCtx2D>();
  readonly rt: RenderRuntime;
  private pending: (() => void)[] = [];
  now = 1000;

  constructor() {
    this.rt = createRenderRuntime({
      runMode: "inline",
      post: (m) => void this.out.push(m),
      requestFrame: (cb) => void this.pending.push(cb),
      now: () => this.now,
      setTimer: () => undefined,
      probe: () => FULL,
      timeMap: minuteMap(),
    });
  }

  /** One frame callback: every pending request runs in one tick. */
  tick(n = 1): void {
    for (let i = 0; i < n; i += 1) {
      this.now += 16;
      for (const cb of this.pending.splice(0)) cb();
    }
  }

  make(id: number, group: string | null, workerId?: string): void {
    const ctx = new FakeCtx2D();
    this.ctx.set(id, ctx);
    this.rt.handle({
      t: "init",
      id,
      canvas: { width: W, height: H, getContext: () => ctx },
      dpr: 1,
      theme: THEME,
      config: { bench: true, syncGroup: group, ...(workerId !== undefined && { workerId }) },
    } satisfies ToWorker);
    this.cmd(id, { k: "setViewport", timeStart: AT_14 - 100 * MIN, timeEnd: AT_14 + 25 * MIN });
    this.tick(2);
  }

  cmd(id: number, cmd: Command): void {
    this.rt.handle({ t: "command", id, cmd });
  }

  input(id: number, kind: "pointer" | "wheel" | "key", ...r: number[][]): void {
    this.rt.handle({ t: "input", id, kind, events: rows(...r) });
  }

  of<T extends FromWorker["t"]>(t: T, id?: number): Of<T>[] {
    return this.out.filter((m): m is Of<T> => m.t === t && (id === undefined || m.id === id));
  }

  range(id: number): [number, number] | undefined {
    const v = this.of("viewport", id).at(-1);
    return v && [v.timeStart, v.timeEnd];
  }

  /** Dashed (remote) segments chart `id` stroked since `from`. */
  remote(id: number, from = 0): number {
    const ctx = this.ctx.get(id) as FakeCtx2D;
    return ctx.paths
      .slice(from)
      .filter((p) => p.op === "stroke" && p.style === MUTED)
      .reduce((n, p) => n + p.parts.filter((s) => s.startsWith("moveTo")).length, 0);
  }

  mark(id: number): number {
    return (this.ctx.get(id) as FakeCtx2D).paths.length;
  }
}

let rig: Rig;

beforeEach(() => {
  rig = new Rig();
});

describe("Scenario: Sync propagates once with no echo: same tick, both creation orders", () => {
  it.each([
    ["the publisher created first", [1, 2]],
    ["the publisher created last (#388 bug 1)", [2, 1]],
  ])("%s: the peer draws the remote crosshair and follows a zoom in that tick", (_, order) => {
    for (const id of order as number[]) rig.make(id, "g");
    rig.tick(3);
    rig.out.length = 0;
    const from = rig.mark(2);
    rig.input(1, "pointer", [INPUT.move, 300, 200, 0, 0, 0]);
    rig.tick(); // ONE tick
    expect(rig.of("crosshair", 1).at(-1)?.visible).toBe(true);
    expect(rig.remote(2, from)).toBeGreaterThan(0); // drawn in the same tick
    expect(rig.of("frame", 1)).toHaveLength(1);
    expect(rig.of("frame", 2)).toHaveLength(1); // one frame each: no echo frame
    expect(rig.of("crosshair", 2)).toEqual([]); // remote-only (BQ-5)
    rig.out.length = 0;
    rig.input(1, "wheel", [INPUT.wheel, 300, 200, -120, 0, 0]);
    rig.tick();
    const leader = rig.range(1);
    expect(leader).toBeDefined();
    expect(rig.range(2)).toEqual(leader); // the same tick, the same range
    expect(rig.rt.syncCounters).toMatchObject({ propagationsPerFrame: 1 });
    rig.tick(3);
    expect(rig.of("frame", 1)).toHaveLength(1); // nothing came back to the publisher
  });

  it("test_peerChanges_neverAppliedBackToTheOriginator_bug2", () => {
    rig.make(1, "g");
    rig.make(2, "g");
    rig.tick(3);
    rig.input(1, "key", [INPUT.key, KEY.left, 0, 0, 0, 0]);
    rig.tick();
    const leader = rig.range(1);
    rig.out.length = 0;
    rig.tick(5);
    expect(rig.of("viewport", 1)).toEqual([]); // #388 applied the range to its originator too
    expect(rig.range(1) ?? leader).toEqual(rig.range(2) ?? leader);
  });
});

describe("Scenario: 600 seeded frames on 2 to 4 charts", () => {
  it.each([2, 3, 4])("%i charts: propagations <= 1 per frame, echoes 0, ranges equal", (n) => {
    const r = mulberry32(0x446 + n);
    for (let id = 1; id <= n; id += 1) rig.make(id, "g");
    rig.tick(3);
    const last = new Map<number, [number, number]>();
    for (let id = 1; id <= n; id += 1) last.set(id, rig.range(id) ?? [0, 0]);
    for (let f = 0; f < 600; f += 1) {
      const id = 1 + Math.floor(r() * n);
      const roll = r();
      const x = 10 + Math.floor(r() * 900);
      const y = 10 + Math.floor(r() * 500);
      if (roll < 0.45) rig.input(id, "pointer", [INPUT.move, x, y, 0, 0, 0]);
      else if (roll < 0.55) rig.input(id, "pointer", [INPUT.leave, x, y, 0, 0, 0]);
      else if (roll < 0.7) rig.input(id, "wheel", [INPUT.wheel, x, y, r() < 0.5 ? -60 : 60, 0, 0]);
      else if (roll < 0.8) rig.input(id, "key", [INPUT.key, r() < 0.5 ? KEY.left : KEY.right, 0]);
      else if (roll < 0.85) {
        // Two charts move in one frame: the later input wins and the other follows it.
        const other = (id % n) + 1;
        rig.input(id, "key", [INPUT.key, KEY.left, 0, 0, 0, 0]);
        rig.now += 1;
        rig.input(other, "key", [INPUT.key, KEY.right, 0, 0, 0, 0]);
      }
      const mark = rig.out.length;
      rig.tick();
      const c = rig.rt.syncCounters;
      expect(c.propagationsPerFrame).toBeLessThanOrEqual(1);
      const frames = rig.out.slice(mark).filter((m) => m.t === "frame");
      expect(new Set(frames.map((m) => m.id)).size).toBe(frames.length); // one frame per chart
      for (const m of rig.out.slice(mark)) {
        if (m.t === "viewport" && m.pane === 0) last.set(m.id, [m.timeStart, m.timeEnd]);
      }
      const ranges = [...last.values()].map((v) => v.join(":"));
      expect(new Set(ranges).size).toBe(1); // every member shows the same range after the tick
    }
    expect(rig.rt.syncCounters.maxPropagationsPerFrame).toBe(1);
    expect(rig.rt.syncCounters.groupMembers).toBe(n);
  });
});

describe("BQ-13: the leader coasts, the members follow (G-10)", () => {
  it("test_flick_leaderGlides_memberTakesEachFrame_andNeverGlidesItself", () => {
    rig.make(1, "g");
    rig.make(2, "g");
    rig.tick(3);
    rig.input(1, "pointer", [INPUT.down, 308, 300, 1, 0, 0]);
    for (let x = 324; x <= 500; x += 16) rig.input(1, "pointer", [INPUT.move, x, 300, 1, 0, 8]);
    rig.input(1, "pointer", [INPUT.up, 500, 300, 0, 0, 8]);
    rig.tick();
    rig.out.length = 0;
    let glided = 0;
    for (let f = 0; f < 200; f += 1) {
      const mark = rig.out.length;
      rig.tick();
      const step = rig.out.slice(mark).filter((m): m is Of<"viewport"> => m.t === "viewport");
      const lead = step.filter((m) => m.id === 1);
      const member = step.filter((m) => m.id === 2);
      if (lead.length > 0) glided += 1;
      // Every leader frame reaches the member in the same tick, never the other way round.
      expect(member.map((m) => [m.timeStart, m.timeEnd])).toEqual(
        lead.map((m) => [m.timeStart, m.timeEnd]),
      );
    }
    expect(glided).toBeGreaterThan(5); // it coasted for several frames, then parked
  });

  it("test_memberTouched_midGlide_winsAndStopsTheLeadersGlide", () => {
    rig.make(1, "g");
    rig.make(2, "g");
    rig.tick(3);
    rig.input(1, "pointer", [INPUT.down, 308, 300, 1, 0, 0]);
    for (let x = 324; x <= 500; x += 16) rig.input(1, "pointer", [INPUT.move, x, 300, 1, 0, 8]);
    rig.input(1, "pointer", [INPUT.up, 500, 300, 0, 0, 8]);
    rig.tick(3);
    rig.now += 1;
    rig.input(2, "key", [INPUT.key, KEY.left, 0, 0, 0, 0]); // a later input in the member
    rig.tick();
    expect(rig.range(1)).toEqual(rig.range(2));
    rig.out.length = 0;
    rig.tick(10);
    expect(rig.of("viewport")).toEqual([]); // the leader's glide was stopped by the sync
  });
});

describe("BQ-9: setSync joins, re-modes and leaves", () => {
  it("test_setSync_modes_crosshairOff_noRemoteLine_leave_dropsIt", () => {
    rig.make(1, null);
    rig.make(2, null);
    rig.cmd(1, { k: "setSync", groupId: "g", modes: DEFAULT_SYNC_MODES, relay: false });
    const timeOnly = { time: true, crosshair: false, levels: false };
    rig.cmd(2, { k: "setSync", groupId: "g", modes: timeOnly, relay: false });
    rig.tick(3);
    const from = rig.mark(2);
    rig.input(1, "pointer", [INPUT.move, 300, 200, 0, 0, 0]);
    rig.tick();
    expect(rig.remote(2, from)).toBe(0); // its crosshair mode is off
    rig.cmd(2, { k: "setSync", groupId: "g", modes: DEFAULT_SYNC_MODES, relay: false });
    rig.input(1, "pointer", [INPUT.move, 400, 200, 0, 0, 0]);
    rig.tick();
    expect(rig.remote(2, from)).toBeGreaterThan(0);
    rig.cmd(2, { k: "setSync", groupId: null, modes: DEFAULT_SYNC_MODES, relay: false });
    rig.tick();
    const after = rig.mark(2);
    rig.input(1, "pointer", [INPUT.move, 500, 200, 0, 0, 0]);
    rig.tick(2);
    expect(rig.remote(2, after)).toBe(0); // left: no remote line, none drawn
    expect(rig.rt.syncCounters.groupMembers).toBe(1);
    rig.cmd(1, { k: "release" });
    expect(rig.rt.syncCounters.groupMembers).toBe(0);
  });

  it("test_join_withTimeOn_adoptsTheGroupsLastRange", () => {
    rig.make(1, "g");
    rig.make(2, null);
    rig.input(1, "wheel", [INPUT.wheel, 300, 200, -120, 0, 0]);
    rig.tick();
    rig.cmd(2, { k: "setSync", groupId: "g", modes: DEFAULT_SYNC_MODES, relay: false });
    rig.tick();
    expect(rig.range(2)).toEqual(rig.range(1));
  });
});

describe("BQ-7, BQ-8, BQ-21: two workers and the registry (fake links)", () => {
  function bridge(): { a: Rig; b: Rig; reg: SyncRegistry; members: [SyncMember, SyncMember] } {
    const a = new Rig();
    const b = new Rig();
    a.make(1, null, "A");
    b.make(1, null, "B");
    const reg = new SyncRegistry();
    const memberOf = (r: Rig): SyncMember => ({
      link: r,
      command: (cmd) => r.cmd(1, cmd),
      sync: (groupId, p) => r.rt.handle({ t: "sync", groupId, ...p }),
      say: () => undefined,
    });
    const members: [SyncMember, SyncMember] = [memberOf(a), memberOf(b)];
    for (const m of members) reg.set(m, "g", DEFAULT_SYNC_MODES);
    return { a, b, reg, members };
  }

  it("test_relay_crossWorker_originKept_followerMatches_ownOriginAndStaleSeqDropped", () => {
    const { a, b, reg, members } = bridge();
    a.tick(3);
    b.tick(3);
    a.out.length = 0;
    a.input(1, "wheel", [INPUT.wheel, 300, 200, -120, 0, 0]);
    a.tick();
    const relays = a.of("sync");
    expect(relays).toHaveLength(1); // relay is on: the group spans two links
    const [msg] = relays;
    expect(msg?.origin).toEqual({ worker: "A", chart: 1, seq: 1 });
    for (const m of relays) reg.relay(members[0], m);
    b.tick();
    expect(b.range(1)).toEqual(a.range(1));
    expect(b.of("sync")).toEqual([]); // a received range is never relayed back
    // The relay handed back to A (its own origin) is dropped; so is a stale seq at B.
    if (msg === undefined) throw new Error("no relay");
    a.rt.handle({ t: "sync", groupId: "g", timeRange: [1, 2], origin: msg.origin });
    b.rt.handle({ t: "sync", groupId: "g", timeRange: [1, 2], origin: msg.origin });
    a.tick();
    b.tick();
    expect(a.rt.syncCounters.dropped).toBe(1);
    expect(b.rt.syncCounters.dropped).toBe(1);
    expect(b.range(1)).toEqual(a.range(1)); // neither moved
  });

  it("test_registryFlip_groupRemovedAndReAdded_onA_peerStillAppliesTheNextRelay_M1", () => {
    const { a, b, reg, members } = bridge();
    a.tick(3);
    b.tick(3);
    const pan = (): void => {
      a.out.length = 0;
      a.input(1, "wheel", [INPUT.wheel, 300, 200, -120, 0, 0]);
      a.tick();
      for (const m of a.of("sync")) reg.relay(members[0], m);
      b.tick();
    };
    pan();
    expect(b.range(1)).toEqual(a.range(1));
    reg.set(members[0], null, DEFAULT_SYNC_MODES); // the group empties on worker A
    reg.set(members[0], "g", DEFAULT_SYNC_MODES); // and is made again, relay back on
    a.tick();
    b.tick();
    pan();
    expect(a.of("sync").map((m) => m.origin.seq)).toEqual([2]); // the worker's counter rose
    expect(b.range(1)).toEqual(a.range(1)); // not dropped as stale
    expect(b.rt.syncCounters.dropped).toBe(0);
  });

  it("test_oneWorker_noRelay_postsNoSyncMessage", () => {
    rig.make(1, "g");
    rig.make(2, "g");
    rig.input(1, "wheel", [INPUT.wheel, 300, 200, -120, 0, 0]);
    rig.tick();
    expect(rig.of("sync")).toEqual([]);
  });
});
