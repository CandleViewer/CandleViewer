// `memory-sample` scene (E11-S15, BQ-S15-12): one chart's `MemoryAccount` at the bench scale, the
// runtime's GL and framebuffer sources plus the three stores (a 200k-bar BarStore, a footprint and
// a heatmap ring) as their owners will join them; each step one `MemorySampler.sample`. It reads no
// clock: memory-sampler.test.ts asserts through `probeAllocations` that it allocates nothing, the
// .perf.test.ts times it (≤ 0.2 ms) and counts the scavenges a long run of samples triggers.
import { MemoryAccount, MemorySampler } from "../../src/memory/index.js";
import { BarStore, FootprintStore, HeatmapRing } from "../../src/model/index.js";

const STEP_US = 60_000_000;
const BARS = 200_000;

export class MemorySampleBench {
  readonly account = new MemoryAccount();
  readonly sampler = new MemorySampler(this.account);
  readonly bars = new BarStore();
  steps = 0;

  constructor() {
    const open = Int32Array.from({ length: BARS }, (_, i) => 1_000 + (i % 50));
    const time = Float64Array.from({ length: BARS }, (_, i) => i * STEP_US);
    const volume = new Float32Array(BARS).fill(1);
    this.bars.replace({
      time,
      open,
      high: open,
      low: open,
      close: open,
      volume,
      priceOrigin: 0,
      tickSize: 1,
    });
    const footprint = new FootprintStore();
    const heatmap = new HeatmapRing();
    const backend = { gpuMemoryMbEstimate: 42.5 };
    const canvas = { width: 2560, height: 1440 };
    this.account.register({ id: "gl", bytes: () => backend.gpuMemoryMbEstimate * 2 ** 20 });
    this.account.register({ id: "framebuffer", bytes: () => canvas.width * canvas.height * 4 });
    this.account.register({ id: "bars", bytes: () => this.bars.bytes });
    this.account.register({ id: "footprint", bytes: () => footprint.bytes });
    this.account.register({ id: "heatmap", bytes: () => heatmap.bytes });
  }

  step(now: number): number {
    this.steps += 1;
    return this.sampler.sample(now);
  }
}

/** The allocating built-ins a sample path could reach for: array and iterator helpers, `bind`. */
const ARRAY_METHODS = [
  "map",
  "filter",
  "reduce",
  "reduceRight",
  "slice",
  "concat",
  "flat",
  "flatMap",
  "forEach",
  "entries",
  "keys",
  "values",
  "toSorted",
  "toReversed",
  "toSpliced",
  "with",
] as const;
const ARRAY_STATICS = ["from", "of"] as const;
const OBJECT_STATICS = ["assign", "keys", "values", "entries", "fromEntries"] as const;

type Patch = readonly [target: object, name: string];

/**
 * Test-only allocation probe (BQ-S15-12, rule 31 "no per-frame allocations"): runs `run` with
 * every allocating built-in above wrapped in a call counter and returns how many calls `run` made,
 * restoring each built-in afterwards, even on a throw. A sample that sums with `.map`/`.reduce`,
 * copies with `.slice`, binds a callback or spreads through `Object.assign` makes it non-zero. A
 * bare object or closure literal never calls a built-in: the scavenge count in the perf test
 * (`v8.GCProfiler`) is the probe for those.
 */
export function probeAllocations(run: () => void): number {
  let calls = 0;
  const patches: Patch[] = [
    ...ARRAY_METHODS.map((m): Patch => [Array.prototype, m]),
    ...ARRAY_STATICS.map((m): Patch => [Array, m]),
    ...OBJECT_STATICS.map((m): Patch => [Object, m]),
    [Function.prototype, "bind"],
  ];
  const saved = patches.map(([target, name]) => Object.getOwnPropertyDescriptor(target, name));
  patches.forEach(([target, name], i) => {
    const original = saved[i]?.value as ((...a: unknown[]) => unknown) | undefined;
    if (typeof original !== "function") return;
    Object.defineProperty(target, name, {
      ...saved[i],
      value: function counted(this: unknown, ...args: unknown[]): unknown {
        calls += 1;
        return original.apply(this, args);
      },
    });
  });
  try {
    run();
  } finally {
    for (let i = 0; i < patches.length; i += 1) {
      const d = saved[i];
      const p = patches[i];
      if (d !== undefined && p !== undefined) Object.defineProperty(p[0], p[1], d);
    }
  }
  return calls;
}
