// E11-S09 PR 2a (#446 AC2): "Sync propagates once per frame with no echo" on the worker runtime.
// BQ-12's three-phase tick, BQ-13's echo-free publication, BQ-7's origin and stale-seq drops.
import { beforeEach, describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_NO_WEBGL2,
  type FromWorker,
  INPUT,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { ENGINE_SYNC_REFUSED, MAX_GROUP_MEMBERS } from "../../src/sync/SyncGroup.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";

let out: FromWorker[];
let rafs: (() => void)[];
let now: number;
let rt: RenderRuntime;

/** One worker frame: every callback requested before it runs once (a rAF). */
function tick(): void {
  now += 16;
  const due = rafs;
  rafs = [];
  for (const cb of due) cb();
}

const canvas = () => {
  const ctx = new FakeCtx2D();
  return { width: 264, height: 100, ctx, getContext: () => ctx };
};

function make(id: number, syncGroup: string | null = "A", workerId = "w1"): void {
  rt.handle({
    t: "init",
    id,
    canvas: canvas(),
    dpr: 1,
    theme: { [BACKGROUND_TOKEN]: "#000000" },
    config: { bench: false, syncGroup, workerId },
  } satisfies ToWorker);
}

const send = (m: ToWorker): void => rt.handle(m);
const row = (type: number, x: number, buttons = 0): Float32Array =>
  new Float32Array([type, x, 0, buttons, 0, 0]);
const pointer = (id: number, type: number, x: number, buttons = 0): void =>
  send({ t: "input", id, kind: "pointer", events: row(type, x, buttons) });
const viewports = (id: number) =>
  out.filter((m): m is Extract<FromWorker, { t: "viewport" }> => m.t === "viewport" && m.id === id);
const errors = () =>
  out.filter(
    (m): m is Extract<FromWorker, { t: "error" }> => m.t === "error" && m.code !== ENGINE_NO_WEBGL2,
  );
const counters = (id: number) => rt.syncCounters(id);

beforeEach(() => {
  out = [];
  rafs = [];
  now = 1000;
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void rafs.push(cb),
    now: () => now,
    setTimer: () => undefined,
    probe: () => FULL,
  });
});

describe("Scenario: Sync propagates once per frame with no echo (BQ-12, BQ-13)", () => {
  for (const order of [
    [1, 2],
    [2, 1],
  ]) {
    it(`test_crosshair_move_in_chart_1_lands_on_chart_2_same_tick_created_${order.join("_then_")}`, () => {
      for (const id of order) make(id);
      tick(); // first frames
      send({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 0, timeEnd: 2e9 } });
      tick();
      out = [];
      pointer(1, INPUT.move, 120); // a hover: chart 1's local crosshair
      tick(); // exactly one frame
      const own = counters(1)?.crosshair;
      expect(own).not.toBeNull();
      expect(counters(2)?.remoteCrosshair).toBe(own);
      expect(counters(2)?.applied).toBe(2); // the setViewport frame and this one
      expect(counters(1)?.applied).toBe(0); // no inbound sync from its own broadcast
      expect(counters(1)?.echoes).toBe(0);
      expect(counters(1)?.propagationsPerFrame).toBe(1);
      expect(counters(1)?.groupMembers).toBe(2);
    });

    it(`test_time_drag_in_chart_1_renders_chart_2_on_the_same_tick_created_${order.join("_then_")}`, () => {
      for (const id of order) make(id);
      tick();
      send({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 0, timeEnd: 2e9 } });
      tick();
      const v2 = viewports(2).at(-1);
      expect(v2?.timeStart).toBe(0); // the same tick as chart 1's
      expect(v2?.timeEnd).toBeCloseTo(2e9, -1);
      expect(v2?.origin).toEqual({ worker: "w1", chart: 1, seq: 1 }); // BQ-26's syncId source
      expect(viewports(1).at(-1)?.origin).toBeUndefined();
      out = [];
      pointer(1, INPUT.down, 100, 1);
      pointer(1, INPUT.move, 150, 1);
      pointer(1, INPUT.up, 150);
      tick();
      const [a, b] = [viewports(1).at(-1), viewports(2).at(-1)];
      expect(b?.timeStart).toBe(a?.timeStart);
      expect(b?.timeEnd).toBe(a?.timeEnd);
      expect(b?.frameId).toBeTypeOf("number");
      expect(counters(1)?.applied).toBe(0);
      for (let i = 0; i < 5; i += 1) tick(); // a synced chart never publishes back
      expect(counters(1)?.applied).toBe(0);
      expect(counters(2)?.echoes).toBe(0);
    });
  }

  it("test_three_charts_a_member_prepared_before_the_middle_publisher_renders_the_same_tick", () => {
    for (const id of [1, 2, 3]) make(id);
    tick();
    while (rafs.length > 0) tick(); // settle the first frames
    out = [];
    // Chart 1 is due for its own reason (a theme), so pass 1 prepares it before chart 2 publishes.
    send({ t: "command", id: 1, cmd: { k: "setTheme", theme: { [BACKGROUND_TOKEN]: "#111111" } } });
    send({ t: "command", id: 2, cmd: { k: "setViewport", timeStart: 0, timeEnd: 3e9 } });
    tick();
    for (const id of [1, 3]) {
      expect(viewports(id).at(-1)?.timeEnd).toBeCloseTo(3e9, -1);
      expect(viewports(id).at(-1)?.origin).toEqual({ worker: "w1", chart: 2, seq: 1 });
    }
    expect(rafs).toHaveLength(0); // re-prepared in this tick: no extra frame for chart 1
    // 2a nit: chart 1 is prepared twice but finished once, so one `viewport` (one
    // `viewportChanged`) whose frameId matches the peers' that each rendered once.
    for (const id of [1, 2, 3]) expect(viewports(id)).toHaveLength(1);
    expect(viewports(1)[0]?.frameId).toBe(viewports(3)[0]?.frameId);
    expect(viewports(1)[0]?.frameId).toBe(viewports(2)[0]?.frameId);
    out = []; // and the next frame's id is one on, in step with the peers
    send({ t: "command", id: 2, cmd: { k: "setViewport", timeStart: 0, timeEnd: 4e9 } });
    tick();
    const ids = [1, 2, 3].map((id) => viewports(id).map((v) => v.frameId));
    expect(ids).toEqual([ids[1], ids[1], ids[1]]);
    expect(counters(2)?.applied).toBe(0);
  });

  it("test_600_random_frames_on_2_to_4_charts_propagate_at_most_once_per_group_frame", () => {
    const rng = mulberry32(0x446a);
    const n = 2 + Math.floor(rng() * 3);
    for (let id = 1; id <= n; id += 1) make(id);
    tick();
    let seq = 0;
    for (let f = 0; f < 600; f += 1) {
      for (let id = 1; id <= n; id += 1) {
        const r = rng();
        if (r < 0.25) pointer(id, INPUT.move, rng() * 200);
        else if (r < 0.35) {
          const start = Math.floor(rng() * 1e9);
          send({
            t: "command",
            id,
            cmd: { k: "setViewport", timeStart: start, timeEnd: start + 1e9 },
          });
        } else if (r < 0.4) {
          seq += rng() < 0.2 ? -1 : 1; // some stale
          const origin = { worker: rng() < 0.5 ? "w1" : "w2", chart: 9, seq: Math.max(0, seq) };
          send({ t: "sync", groupId: "A", crosshair: rng() * 1e9, origin });
        }
      }
      tick();
      for (let id = 1; id <= n; id += 1) {
        expect(counters(id)?.propagationsPerFrame).toBeLessThanOrEqual(1);
      }
    }
    expect(counters(1)?.propagationsPerFrameMax).toBe(1);
    expect(counters(1)?.echoes).toBe(0);
    expect(errors()).toEqual([]);
  });
});

describe("BQ-7: the inbound sync's origin token", () => {
  it("test_inbound_sync_from_this_worker_is_dropped", () => {
    make(1);
    make(2);
    tick();
    send({ t: "sync", groupId: "A", crosshair: 5, origin: { worker: "w1", chart: 7, seq: 1 } });
    tick();
    expect(counters(1)?.applied).toBe(0);
    expect(counters(2)?.remoteCrosshair).toBeNull();
  });

  it("test_inbound_sync_with_a_stale_seq_is_dropped", () => {
    make(1);
    tick();
    const origin = (seq: number) => ({ worker: "w2", chart: 3, seq });
    send({ t: "sync", groupId: "A", crosshair: 5, origin: origin(4) });
    send({ t: "sync", groupId: "A", crosshair: 6, origin: origin(3) }); // older: dropped
    send({ t: "sync", groupId: "A", crosshair: 7, origin: origin(4) }); // same: dropped
    expect(counters(1)?.remoteCrosshair).toBe(5);
    expect(counters(1)?.applied).toBe(1);
    send({ t: "sync", groupId: "A", timeRange: [10, 20], origin: origin(5) });
    tick();
    expect(viewports(1).at(-1)?.origin).toEqual(origin(5));
    expect(counters(1)?.remoteCrosshair).toBe(5); // a time-only sync keeps the crosshair
  });

  it("test_inbound_sync_interleaved_origins_drop_a_replay_from_either", () => {
    make(1);
    tick();
    const from = (worker: string, seq: number) => ({ worker, chart: 3, seq });
    send({ t: "sync", groupId: "A", crosshair: 5, origin: from("wA", 5) });
    send({ t: "sync", groupId: "A", crosshair: 6, origin: from("wB", 3) });
    send({ t: "sync", groupId: "A", crosshair: 7, origin: from("wA", 4) }); // A's replay: dropped
    expect(counters(1)?.remoteCrosshair).toBe(6);
    expect(counters(1)?.applied).toBe(2);
  });

  it("test_init_with_a_malformed_syncGroup_is_rejected_and_joins_nothing", () => {
    for (const syncGroup of [7, "", "g".repeat(129), "a b"]) {
      rt.handle({
        t: "init",
        id: 9,
        canvas: canvas(),
        dpr: 1,
        theme: { [BACKGROUND_TOKEN]: "#000000" },
        config: { bench: false, syncGroup, workerId: "w1" },
      } as unknown as ToWorker);
      expect(errors().at(-1)?.message).toBe("malformed init");
      expect(counters(9)).toBeUndefined();
    }
  });
});

describe("BQ-9: setSync", () => {
  it("test_setSync_moves_the_chart_and_relay_posts_a_FromWorker_sync", () => {
    make(1, null);
    make(2, null);
    const modes = { time: true, crosshair: true, levels: false };
    send({ t: "command", id: 1, cmd: { k: "setSync", groupId: "B", modes, relay: true } });
    send({ t: "command", id: 2, cmd: { k: "setSync", groupId: "B", modes, relay: false } });
    tick();
    send({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 0, timeEnd: 1e9 } });
    send({ t: "command", id: 2, cmd: { k: "setViewport", timeStart: 0, timeEnd: 5e8 } });
    tick(); // both publish; the last publisher wins the frame
    const relayed = out.filter((m) => m.t === "sync");
    expect(relayed).toEqual([
      {
        t: "sync",
        id: 1,
        groupId: "B",
        timeRange: [0, expect.closeTo(1e9, -1)],
        origin: { worker: "w1", chart: 1, seq: 1 },
      },
    ]);
    expect(counters(1)?.propagationsPerFrame).toBe(1);
    send({ t: "command", id: 2, cmd: { k: "setSync", groupId: null, modes, relay: false } });
    expect(counters(2)?.groupMembers).toBe(0);
    expect(counters(1)?.groupMembers).toBe(1);
  });

  it("test_setSync_past_the_member_cap_is_a_recoverable_ENGINE_SYNC_REFUSED", () => {
    for (let id = 1; id <= MAX_GROUP_MEMBERS + 1; id += 1) make(id);
    const refused = errors().filter((e) => e.code === ENGINE_SYNC_REFUSED);
    expect(refused.map((e) => [e.id, e.recoverable])).toEqual([[MAX_GROUP_MEMBERS + 1, true]]);
    expect(counters(MAX_GROUP_MEMBERS + 1)?.groupMembers).toBe(0);
  });

  it("test_collapsed_panes_counter", () => {
    make(1, null);
    send({ t: "command", id: 1, cmd: { k: "addPane", pane: 1 } });
    send({ t: "command", id: 1, cmd: { k: "setPaneCollapsed", pane: 1, collapsed: true } });
    tick();
    expect(counters(1)?.panesCollapsed).toBe(1);
  });
});

describe("2a review M1 / m2: the group teardown", () => {
  const release = (id: number): void => send({ t: "command", id, cmd: { k: "release" } });
  const modes = { time: true, crosshair: true, levels: false };

  it("test_release_frees_its_slot_so_strictmode_churn_at_the_member_cap_never_refuses", () => {
    for (let id = 1; id <= MAX_GROUP_MEMBERS; id += 1) make(id);
    for (let id = MAX_GROUP_MEMBERS + 1; id <= 4 * MAX_GROUP_MEMBERS; id += 1) {
      release(id - 1); // a StrictMode unmount, then the re-mount takes a fresh chart id
      make(id); // refused (and in no group) if a released chart kept its slot
    }
    expect(counters(4 * MAX_GROUP_MEMBERS)?.groupMembers).toBe(MAX_GROUP_MEMBERS);
  });

  it("test_degraded_2d_handoff_keeps_the_setSync_group_without_a_leaked_member", () => {
    make(1, null);
    make(2, "B");
    send({ t: "command", id: 1, cmd: { k: "setSync", groupId: "B", modes, relay: false } });
    make(1, "A"); // the handoff's re-init: its config's group is not the one kept
    expect(counters(1)?.groupMembers).toBe(2); // not 3 (a leaked `old`), not 1 (group "A")
  });

  it("test_remote_crosshair_is_cleared_on_leave_and_on_crosshair_mode_off", () => {
    make(1);
    const peer = (seq: number): void =>
      send({ t: "sync", groupId: "A", crosshair: 5, origin: { worker: "w2", chart: 3, seq } });
    peer(1);
    expect(counters(1)?.remoteCrosshair).toBe(5);
    send({ t: "command", id: 1, cmd: { k: "setSync", groupId: null, modes, relay: false } });
    expect(counters(1)?.remoteCrosshair).toBeNull();
    send({ t: "command", id: 1, cmd: { k: "setSync", groupId: "A", modes, relay: false } });
    peer(2);
    expect(counters(1)?.remoteCrosshair).toBe(5);
    const off = { ...modes, crosshair: false };
    send({ t: "command", id: 1, cmd: { k: "setSync", groupId: "A", modes: off, relay: false } });
    expect(counters(1)?.remoteCrosshair).toBeNull();
  });
});
