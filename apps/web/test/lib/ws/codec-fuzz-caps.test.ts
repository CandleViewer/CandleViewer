// @vitest-environment node
// The caps of a codec call in the fuzz (#415, E17-X02), checked in process with a planted call and
// a gauge it moves, so no time passes and the result is the same on every machine. The time cap
// reads the wall clock, so a trip is run once more on the same input and fails only if it trips
// again (a stall of the machine does not repeat, a slow call does); an allocation trip is final.
import { expect, it } from "vitest";
import { checked } from "./support/fuzzCaps";

const CAPS = { ms: 500, bytes: 64 * 1024 * 1024 };

/** What a run of the planted call costs: milliseconds on its clock, bytes it holds. */
interface Cost {
  readonly ms?: number;
  readonly bytes?: number;
}
const SLOW: Cost = { ms: CAPS.ms + 1 };
const FAST: Cost = { ms: 1 };
const BIG: Cost = { bytes: CAPS.bytes + 1 };

/** A call whose i-th run costs `plan[i]` (the last after that) and returns i + 1; and its gauge. */
function plant(plan: Cost[]) {
  let clock = 0;
  let held = 0;
  let runs = 0;
  const call = (): number => {
    const cost = plan[Math.min(runs, plan.length - 1)] ?? {};
    clock += cost.ms ?? 0;
    held += cost.bytes ?? 0;
    return ++runs;
  };
  return { call, runs: () => runs, gauge: { now: () => clock, used: () => held } };
}

it("a call that is slow once and fast on the retry passes, with the result of the retry", () => {
  const { call, runs, gauge } = plant([SLOW, FAST]);
  expect(checked(call, CAPS, gauge)).toEqual({ ok: true, out: 2 });
  expect(runs()).toBe(2);
});

it("a call that is slow twice fails with the time cap, after two runs and no more", () => {
  const { call, runs, gauge } = plant([SLOW]);
  expect(checked(call, CAPS, gauge)).toEqual({ ok: false, why: "decode exceeded time cap" });
  expect(runs()).toBe(2);
});

it("a call inside the cap is run once", () => {
  const { call, runs, gauge } = plant([FAST]);
  expect(checked(call, CAPS, gauge)).toEqual({ ok: true, out: 1 });
  expect(runs()).toBe(1);
});

it("an allocation over the cap fails at once, without a retry", () => {
  const { call, runs, gauge } = plant([BIG, FAST]);
  expect(checked(call, CAPS, gauge)).toEqual({ ok: false, why: "decode exceeded allocation cap" });
  expect(runs()).toBe(1);
});

it("a call that is slow and over the allocation cap fails with the allocation, at once", () => {
  const { call, runs, gauge } = plant([{ ...SLOW, ...BIG }, FAST]);
  expect(checked(call, CAPS, gauge)).toEqual({ ok: false, why: "decode exceeded allocation cap" });
  expect(runs()).toBe(1);
});
