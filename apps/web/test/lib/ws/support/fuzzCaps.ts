// The check each codec call of the web fuzz is held to (#415, E17-X02): a result, inside a time cap
// and an allocation cap. The time cap reads the wall clock, so a trip is run once more on the same
// input and fails only if it trips again (a stall does not repeat, a slow call does); an
// allocation trip is final. codec-fuzz-caps.test.ts pins that with a planted call and gauge.
import { performance } from "node:perf_hooks";

/** A time cap in milliseconds, and an allocation cap in bytes. */
export interface Caps {
  readonly ms: number;
  readonly bytes: number;
}

/** What a call is measured by: a clock (ms) and the bytes in use. A test plants its own. */
export interface Gauge {
  readonly now: () => number;
  readonly used: () => number;
}

/** The real one: the clock, and heap plus external memory (a typed array's store is external). */
const REAL: Gauge = {
  now: () => performance.now(),
  used: () => {
    const m = process.memoryUsage();
    return m.heapUsed + m.external;
  },
};

/** What a failure may say about a thrown value: its class, never its message. */
export const kindOf = (e: unknown): string => (e instanceof Error ? e.constructor.name : typeof e);

/** The result of a call that kept to its caps, or why it did not. */
export type Checked<T> =
  { readonly ok: true; readonly out: T } | { readonly ok: false; readonly why: string };

const TIME = "decode exceeded time cap";

/** One run of `call`: a throw, an allocation past the cap or a run past the cap fails. */
function attempt<T>(call: () => T, caps: Caps, gauge: Gauge): Checked<T> {
  const before = gauge.used();
  const t0 = gauge.now();
  let out: T;
  try {
    out = call();
  } catch (e) {
    return { ok: false, why: `non-typed throw (${kindOf(e)})` };
  }
  const ms = gauge.now() - t0;
  if (gauge.used() - before > caps.bytes) {
    return { ok: false, why: "decode exceeded allocation cap" };
  }
  return ms > caps.ms ? { ok: false, why: TIME } : { ok: true, out };
}

/** `call` held to `caps`: a time trip is run once more, and fails only if it trips again. */
export function checked<T>(call: () => T, caps: Caps, gauge: Gauge = REAL): Checked<T> {
  const first = attempt(call, caps, gauge);
  return !first.ok && first.why === TIME ? attempt(call, caps, gauge) : first;
}
