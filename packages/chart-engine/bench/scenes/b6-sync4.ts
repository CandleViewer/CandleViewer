// `b6-sync4` scene (E11-S09 PR 2b, #446 B6): four synchronised charts, two per render runtime
// (two "workers"), one sync group, relayed through the main-thread registry as the host does
// (one `sync` per group per frame per runtime). Each frame a seeded chart pans or moves its
// crosshair. The unit test counts: at most one propagation per group per frame on each runtime,
// no echo, four members. The 16.7 ms aggregate p95 and the 70 % shared-worker CPU leg run on the
// owner's reference hardware with B5's content at half density (G-row in the README), not in CI.
import { mulberry32 } from "../fixtures/rng.mjs";
import {
  createSyncRegistry,
  type SyncRegistration,
  type SyncRelay,
} from "../../src/sync/registry.js";
import type { CapabilityReport, FromWorker, ToWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";

export const B6_CHARTS = 4;
export const B6_FRAMES = 240;
const MIN = 60e6; // µs
const T0 = 1_700_000_000e6;

interface Worker {
  readonly id: string;
  readonly runtime: RenderRuntime;
  readonly pending: Map<string, SyncRelay>;
  frames: (() => void)[];
}

export class SyncFourBench {
  readonly workers: Worker[] = [];
  readonly registry = createSyncRegistry({ schedule: (cb) => void this.announced.push(cb) });
  readonly said: string[] = [];
  /** Relayed `sync` messages each runtime received per frame, the most seen. */
  maxRelayedPerFrame = 0;
  /** Relayed `sync` messages the runtimes received, all frames. */
  delivered = 0;
  private readonly announced: (() => void)[] = [];
  private readonly regs = new Map<number, SyncRegistration>();
  private readonly rng: () => number;

  constructor(canvas: () => unknown, probe: () => CapabilityReport, seed = 0xb6) {
    this.rng = mulberry32(seed);
    for (const id of ["w1", "w2"]) {
      const pending = new Map<string, SyncRelay>();
      const w: Worker = { id, pending, frames: [], runtime: this.runtime(id, probe) };
      this.workers.push(w);
    }
    for (let c = 1; c <= B6_CHARTS; c += 1) {
      const w = this.workerOf(c);
      const config = { bench: false, syncGroup: "B6", workerId: w.id };
      w.runtime.handle({ t: "init", id: c, canvas: canvas(), dpr: 1, theme: {}, config });
      const reg = this.registry.attach({
        workerId: () => w.id,
        post: (m) => void (w.pending.delete(m.groupId), w.pending.set(m.groupId, m)),
        announce: (text) => void this.said.push(text),
      });
      const modes = { time: true, crosshair: true, levels: false };
      reg.set("B6", modes);
      this.regs.set(c, reg);
      this.cmd(c, { k: "setSync", groupId: "B6", modes, relay: true });
    }
    for (const cb of this.announced.splice(0)) cb();
    this.frame();
  }

  /** Chart `c`'s runtime: charts 1–2 on w1, 3–4 on w2. */
  workerOf(c: number): Worker {
    return this.workers[c <= B6_CHARTS / 2 ? 0 : 1] as Worker;
  }

  /** One frame: a seeded chart pans (or moves its crosshair), then each runtime ticks once. */
  step(f: number): void {
    const c = 1 + Math.floor(this.rng() * B6_CHARTS);
    if (this.rng() < 0.5) {
      this.cmd(c, { k: "setViewport", timeStart: T0 + f * MIN, timeEnd: T0 + (f + 120) * MIN });
    } else {
      const x = Math.floor(this.rng() * 200);
      const events = new Float32Array([0, x, 40, 0, 0, 0]); // INPUT.move
      this.workerOf(c).runtime.handle({ t: "input", id: c, kind: "pointer", events });
    }
    this.frame();
  }

  run(): this {
    for (let f = 0; f < B6_FRAMES; f += 1) this.step(f);
    return this;
  }

  dispose(): void {
    for (const reg of this.regs.values()) reg.detach();
    for (const cb of this.announced.splice(0)) cb();
    this.registry.dispose();
  }

  private runtime(id: string, probe: () => CapabilityReport): RenderRuntime {
    return createRenderRuntime({
      runMode: "inline",
      post: (m) => this.onPost(m),
      requestFrame: (cb) => void this.workers.find((w) => w.id === id)?.frames.push(cb),
      now: () => 0,
      setTimer: () => undefined,
      probe,
    });
  }

  private cmd(c: number, cmd: Extract<ToWorker, { t: "command" }>["cmd"]): void {
    this.workerOf(c).runtime.handle({ t: "command", id: c, cmd });
  }

  private onPost(m: FromWorker): void {
    if (m.t === "sync") this.regs.get(m.id)?.relay(m);
  }

  /** The host's frame: each runtime gets its coalesced relays, then ticks once. */
  private frame(): void {
    for (const w of this.workers) {
      this.maxRelayedPerFrame = Math.max(this.maxRelayedPerFrame, w.pending.size);
      this.delivered += w.pending.size;
      for (const m of w.pending.values()) w.runtime.handle(m);
      w.pending.clear();
    }
    for (const w of this.workers) {
      const due = w.frames;
      w.frames = [];
      for (const cb of due) cb();
    }
  }
}
