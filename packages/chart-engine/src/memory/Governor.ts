// The memory governor (26 §7 "State" / "Response", §3.6 memory tier; E11-S15 BQ-S15-02, the
// S15-03 override, BQ-S15-14). A plain enum driven by samples, never a statechart (C-2.20): the
// runtime feeds it one `MemorySampler` reading per sample (every memory.sampleIntervalMs on the 1 s
// tick, and on resize) and one `oom()` per GPU out-of-memory; it publishes its state, its
// `memoryTier` and, per call, whether that call was a worsening edge (one ENGINE_MEMORY_PRESSURE)
// and whether it moved the tier. Pure and allocation-free: no clock, no I/O, no events of its own.
//
// Rung semantics (the S15-03 override): one memoryTier rung per pressure episode. An episode opens
// when the state leaves `ok` (to `pressure`, or straight to `over`) and closes only when a sample
// falls below the recovery threshold (the state returns to `ok`), which resets the tier to 0 and
// re-arms the rung. `ok` -> `pressure` -> `over` is two edges and one rung; oscillating around the
// pressure threshold without dropping below recovery raises neither again.
//
// Masked rung (BQ-P2-03): the governor's tier is per driver. When the frame-time driver's loadTier
// (or the maxLod clamp) already hides it, the governor still reports `rung === 1` and the episode
// still counts as its one rung; whether the effective tier moved, and so whether
// ENGINE_LOD_STEPDOWN is raised, is the frame scheduler's call (PR-2b), as is suspending this input
// while `setLod` pins the tiers. Eviction is not suspended by a pin.
//
// OOM cycle: `oom()` moves to `over`, but the next sample re-derives the state from the counted
// usage, so a driver-level OOM under a low count can cycle OOM -> ok -> OOM with one code and one
// rung each cycle (S15-03: an `ok` sample closes the episode). Damping that cycle is for the
// runtime's GPU-OOM wiring (PR-2b) and its chaos note, not this enum.

/** The governor's state, `frame.memory.state` and `FrameStats.memoryState` (26 §6, §8). */
export type MemoryState = "ok" | "pressure" | "over";

/** `ok` -> `pressure` at or above this share of the budget (26 :455, the ticket's 70 %). */
export const PRESSURE_PCT = 70;
/** `pressure` / `over` -> `ok` only strictly below this share (26 §7 internal constants). */
export const RECOVERY_PCT = 60;
/** `over` at or above this share, from `ok` or `pressure`; back to `pressure` below it. */
export const OVER_PCT = 100;

const MIB = 2 ** 20;

export class MemoryGovernor {
  /** The state after the last sample or `oom()`. */
  state: MemoryState = "ok";
  /** `memoryTier` (§3.6): 1 while a pressure episode is open, else 0. */
  tier = 0;
  /** True when the last call was a worsening edge: post one ENGINE_MEMORY_PRESSURE for it. */
  edge = false;
  /** The last call's tier move: 1 opened an episode (one rung), -1 closed it, 0 neither. */
  rung: -1 | 0 | 1 = 0;
  /** Worsening edges so far (diagnostics; ticket metric engine.memory pressure count). */
  edges = 0;
  /** Episodes opened so far (each is exactly one rung). */
  episodes = 0;
  private readonly budgetBytes: number;

  /** Throws `RangeError` unless `budgetMb` is a positive finite number (createChart bounds it). */
  constructor(readonly budgetMb: number) {
    if (!Number.isFinite(budgetMb) || budgetMb <= 0) {
      throw new RangeError("chart-engine: memoryBudgetMb must be a positive number");
    }
    this.budgetBytes = budgetMb * MIB;
  }

  /**
   * One sample of the bytes the chart holds. Returns the new state. A non-finite or negative
   * reading is ignored (state kept, no edge), as `MemoryAccount` counts such a source as 0.
   */
  update(usedBytes: number): MemoryState {
    this.edge = false;
    this.rung = 0;
    if (!Number.isFinite(usedBytes) || usedBytes < 0) return this.state;
    // Integer-exact percentages: used * 100 against budget * pct, no division.
    const used = usedBytes * 100;
    const b = this.budgetBytes;
    let next: MemoryState;
    if (used >= b * OVER_PCT) next = "over";
    else if (this.state === "ok") next = used >= b * PRESSURE_PCT ? "pressure" : "ok";
    else next = used < b * RECOVERY_PCT ? "ok" : "pressure";
    this.move(next);
    return next;
  }

  /**
   * A GPU `OUT_OF_MEMORY` after a buffer or texture allocation (26 §7, §11): moves to `over`, a
   * worsening edge unless already `over`. The next sample re-derives the state from usage.
   */
  oom(): MemoryState {
    this.edge = false;
    this.rung = 0;
    this.move("over");
    return "over";
  }

  private move(next: MemoryState): void {
    const prev = this.state;
    if (next === prev) return;
    this.state = next;
    if (next === "over" || (next === "pressure" && prev === "ok")) {
      this.edge = true;
      this.edges += 1;
    }
    if (prev === "ok") {
      this.tier = 1;
      this.rung = 1;
      this.episodes += 1;
    } else if (next === "ok") {
      this.tier = 0;
      this.rung = -1;
    }
  }
}
