// `context-restore` scene (E11-S02 PR3, README BQ-49): the 3-pane `draw-submit` chart with a
// 100 000-bar candles ring on an injected GL that has `WEBGL_lose_context`, driven through
// `ContextLoss`. `cycle()` loses the context, restores it and draws the first frame; the
// .perf.test.ts times it against the 2 s R1 budget (CPU side: the fake's GPU work is free).
import { ContextLoss, type LossHooks } from "../../src/gl/context-loss.js";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { RESTART_BACKOFF_MS } from "../../src/worker/protocol.js";
import { DrawSubmitBench } from "./draw-submit.js";

export const RESTORE_BARS = 100_000;

export type RestoreClock = Pick<LossHooks, "now" | "setTimer">;

interface LoseContextExt {
  loseContext(): void;
  restoreContext(): void;
}

export class ContextRestoreBench {
  readonly scene: DrawSubmitBench;
  readonly loss: ContextLoss;
  /** The codes `ContextLoss` emitted, in order. */
  readonly events: string[] = [];
  readonly ext: LoseContextExt;

  constructor(gl: GL2Like, clock: RestoreClock, bars = RESTORE_BARS) {
    this.ext = gl.getExtension("WEBGL_lose_context") as LoseContextExt; // GL call 1
    this.scene = new DrawSubmitBench(gl, 3, bars);
    const { backend, graph } = this.scene;
    this.loss = new ContextLoss({
      backoffMs: RESTART_BACKOFF_MS,
      ...clock,
      park: () => backend.invalidate(),
      rebuild: () => backend.restore(),
      resume: () => graph.markAllData(),
      giveUp: () => undefined,
      emit: (code) => this.events.push(code),
    });
  }

  /** Loses the context, `wait`s, restores it and draws the first frame: the restore ms. */
  cycle(wait: () => void = () => undefined): number {
    this.ext.loseContext();
    this.loss.lost();
    wait();
    this.ext.restoreContext();
    this.loss.restored();
    this.scene.step();
    this.loss.framed();
    return this.loss.stats.restoreMs;
  }
}
