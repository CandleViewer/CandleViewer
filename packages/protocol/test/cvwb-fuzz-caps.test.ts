// The caps of a decode (#415, E17-X02), checked in process with a planted decoder and a gauge it
// moves, so no time passes and the result is the same on every machine. The time cap reads the wall
// clock, so a trip is run once more on the same input and fails only if it trips again (a stall of
// the machine does not repeat, a slow decode does); an allocation trip is final.
import { expect, it } from "vitest";
import { breach } from "./support/fuzzReport.js";

const CAPS = { ms: 50, bytes: 16 * 1024 * 1024 };
const DATA = Uint8Array.from([1, 2, 3]);

/** What a run of the planted decoder costs: milliseconds on its clock, bytes it holds. */
interface Cost {
  readonly ms?: number;
  readonly bytes?: number;
}
const SLOW: Cost = { ms: CAPS.ms + 1 };
const FAST: Cost = { ms: 1 };
const BIG: Cost = { bytes: CAPS.bytes + 1 };

/** A decoder whose i-th run costs `plan[i]` (the last after that); the inputs it saw; its gauge. */
function plant(plan: Cost[]) {
  let clock = 0;
  let held = 0;
  const seen: ArrayBufferView[] = [];
  const decode = (view: ArrayBufferView): void => {
    const cost = plan[Math.min(seen.length, plan.length - 1)] ?? {};
    seen.push(view);
    clock += cost.ms ?? 0;
    held += cost.bytes ?? 0;
  };
  return { decode, seen, gauge: { now: () => clock, used: () => held } };
}

it("a decode that is slow once and fast on the retry passes, on the same input", () => {
  const { decode, seen, gauge } = plant([SLOW, FAST]);
  expect(breach(decode, DATA, CAPS, gauge)).toBe("");
  expect(seen).toHaveLength(2);
  expect(seen.every((view) => view === DATA)).toBe(true);
});

it("a decode that is slow twice fails with the time cap, after two runs and no more", () => {
  const { decode, seen, gauge } = plant([SLOW]);
  expect(breach(decode, DATA, CAPS, gauge)).toBe("decode exceeded time cap");
  expect(seen).toHaveLength(2);
});

it("a decode inside the cap is run once", () => {
  const { decode, seen, gauge } = plant([FAST]);
  expect(breach(decode, DATA, CAPS, gauge)).toBe("");
  expect(seen).toHaveLength(1);
});

it("an allocation over the cap fails at once, without a retry", () => {
  const { decode, seen, gauge } = plant([BIG, FAST]);
  expect(breach(decode, DATA, CAPS, gauge)).toBe("decode exceeded allocation cap");
  expect(seen).toHaveLength(1);
});

it("a decode that is slow and over the allocation cap fails with the allocation, at once", () => {
  const { decode, seen, gauge } = plant([{ ...SLOW, ...BIG }, FAST]);
  expect(breach(decode, DATA, CAPS, gauge)).toBe("decode exceeded allocation cap");
  expect(seen).toHaveLength(1);
});
