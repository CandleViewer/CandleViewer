// E17-T04 S3 (23 4.4, 9.2, C7): a close, and the `bye` before it, become reconnect / refresh / delay.
import { describe, expect, it } from "vitest";
import {
  decideClose,
  FATAL_CLOSE_CODES,
  type CloseDecision,
} from "../../../src/lib/ws/policy/closePolicy";
import type { ControlPayloads } from "../../../src/lib/ws/protocol/frames";
import { backoffDelayWithJitter } from "../../../src/shell/bootstrap/backoff";

type Bye = ControlPayloads["bye"];
const bye = (code: Bye["code"], extra: Partial<Bye> = {}): Bye => ({
  code,
  reason: "test",
  message: "test",
  ...extra,
});
const OVER = { reconnect: false, refreshFirst: false, delayMs: 0 } as const;
const MIDPOINT = () => 0.5; // zero jitter: the delay is the table value

/** The 9.2 table written out, so the samples are not judged by the code that makes them: attempt, delay, jitter. */
const TABLE = [
  [1, 500, 250],
  [2, 1000, 500],
  [3, 2000, 1000],
  [4, 5000, 2000],
  [5, 10_000, 5000],
  [6, 30_000, 10_000],
  [7, 30_000, 10_000],
] as const;

/** A seeded LCG (Numerical Recipes constants): the same 1 000 samples on every run. */
const seeded = (seed: number) => () =>
  (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32;

describe("backoff (9.2, D4)", () => {
  it.each(TABLE)("attempt %i: 1 000 samples in bounds and varied", (attempt, delay, jitter) => {
    const random = seeded(attempt);
    const samples = Array.from({ length: 1000 }, () => {
      return decideClose({ code: 1011, attempt }, random).delayMs;
    });
    expect(Math.min(...samples)).toBeGreaterThanOrEqual(delay - jitter);
    expect(Math.max(...samples)).toBeLessThanOrEqual(delay + jitter);
    expect(new Set(samples).size).toBeGreaterThan(100);
  });

  it("takes the delay from the shell's backoffDelayWithJitter, unchanged", () => {
    for (const attempt of [1, 3, 6, 9]) {
      const decision = decideClose({ code: 1011, attempt }, () => 0.3);
      expect(decision.delayMs).toBe(backoffDelayWithJitter(attempt, () => 0.3));
    }
  });
});

describe("what a close means (C7)", () => {
  it.each([1000, 1001, 1006, 1011, 1012, 1013, 4429, 4999])("%i reconnects on backoff", (code) => {
    const decision = decideClose({ code, attempt: 2 }, MIDPOINT);
    expect(decision).toEqual({ ...OVER, reconnect: true, delayMs: 1000, fatal: false });
  });

  it("the fatal set is 1002, 4400 and 4403 from 9.2, plus 1009 (D10)", () => {
    expect([...FATAL_CLOSE_CODES].sort()).toEqual([1002, 1009, 4400, 4403]);
  });

  it.each([1002, 1009, 4400, 4403] as const)("%i never reconnects", (code) => {
    const fatal: CloseDecision = { ...OVER, fatal: true };
    expect(decideClose({ code, attempt: 1 })).toEqual(fatal);
    // the transport may drop after the bye, with a 1006 and no close frame
    expect(decideClose({ code: 1006, bye: bye(code), attempt: 1 })).toEqual(fatal);
    expect(decideClose({ code, bye: bye(1013, { reconnect: true }), attempt: 1 })).toEqual(fatal);
  });

  it("4401 refreshes the token first and reconnects on the climbing backoff", () => {
    const expected = { reconnect: true, refreshFirst: true, delayMs: 2000, fatal: false };
    expect(decideClose({ code: 4401, attempt: 3 }, MIDPOINT)).toEqual(expected);
    expect(decideClose({ code: 1006, bye: bye(4401), attempt: 3 }, MIDPOINT)).toEqual(expected);
  });

  it("bye.retry_after_ms is a floor, and a shared hint still gets the row's jitter on top (9.2)", () => {
    const random = seeded(7);
    const hinted = bye(1013, { retry_after_ms: 20_000 });
    const delays = Array.from({ length: 200 }, () => {
      return decideClose({ code: 1013, bye: hinted, attempt: 1 }, random).delayMs; // 200 clients, one hint
    });
    expect(Math.min(...delays)).toBeGreaterThanOrEqual(20_000);
    expect(Math.max(...delays)).toBeLessThanOrEqual(20_250); // plus up to the first row's 250 ms
    expect(new Set(delays).size).toBeGreaterThan(100); // never all back in the same millisecond
    // a small hint under a large backoff leaves the backoff in charge, plus the row's jitter (10 s x 0.5)
    const small = bye(1013, { retry_after_ms: 3000 });
    expect(decideClose({ code: 1013, bye: small, attempt: 6 }, MIDPOINT).delayMs).toBe(35_000);
  });

  it("ignores a retry_after_ms that is not a finite number and clamps a huge one to 5 minutes", () => {
    const delayFor = (retry_after_ms: number) => {
      const decision = decideClose(
        { code: 1013, bye: bye(1013, { retry_after_ms }), attempt: 1 },
        MIDPOINT,
      );
      return decision.delayMs;
    };
    // no hint: the table's first row, never an instant retry (an unclamped NaN or 2^31 timer fires at once)
    for (const bad of [Number.NaN, Infinity, -Infinity, -5, 0]) expect(delayFor(bad)).toBe(500);
    // clamped to 300 000, then half of the first row's 250 ms of jitter
    for (const huge of [2 ** 31, 1e12, Number.MAX_SAFE_INTEGER])
      expect(delayFor(huge)).toBe(300_125);
  });

  it.each([1000, 1011, 1013, 4429] as const)("bye.reconnect:false on %i is honoured", (code) => {
    const decision = decideClose({ code, bye: bye(code, { reconnect: false }), attempt: 1 });
    expect(decision).toEqual({ ...OVER, fatal: true });
  });

  it.each([1000, 1011, 4401])("a client stop on %i never reconnects and is not a fault", (code) => {
    const decision = decideClose({ code, attempt: 1, stoppedByClient: true });
    expect(decision).toEqual({ ...OVER, fatal: false });
  });
});
