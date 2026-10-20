// Shared by the CVWB fuzz files (#415, E17-X02, SR-155): the check every decoder call is held to,
// and what a failing input may say. A report is its reason, its target and a sha256 digest of the
// input, never the input itself (the log is public); the input goes to CV_FUZZ_ARTIFACT_DIR, which
// CI uploads only encrypted (fuzz-nightly.yml). cvwb-fuzz-report.test.ts runs the nightly file
// against decoders that fail and quote their input, and reads everything printed: that pins this
// module for the nightly fuzz and for cvwb-exhaustive.test.ts alike. cvwb-fuzz-caps.test.ts pins
// the caps: a time trip is run once more on the same input, an allocation trip is not.
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import { BinaryFrameError } from "../../src/runtime/index.js";

/** What a failure may say about a thrown value: its class, never its message. */
const kindOf = (e: unknown): string => (e instanceof Error ? e.constructor.name : typeof e);

/** The reason for a throw that is not a BinaryFrameError. */
export const untyped = (e: unknown): string => `non-typed throw (${kindOf(e)})`;

/**
 * `why: target sha256=<digest>`, the line a failure may print; the digest takes `salt` and the
 * whole input. With CV_FUZZ_ARTIFACT_DIR set the input is saved there, with `extra` (the seed).
 */
export function report(
  why: string,
  target: string,
  data: Uint8Array,
  salt: string,
  extra: Record<string, string> = {},
): string {
  const digest = createHash("sha256").update(salt).update(data).digest("hex");
  let label = `${why}: ${target} sha256=${digest}`;
  const dir = process.env["CV_FUZZ_ARTIFACT_DIR"];
  if (dir) {
    try {
      mkdirSync(dir, { recursive: true });
      const input = Buffer.from(data).toString("base64");
      const record = JSON.stringify({ ...extra, target, input });
      writeFileSync(join(dir, `${target}-${digest}.json`), record);
    } catch (e) {
      label += ` (not saved: ${kindOf(e)})`;
    }
  }
  return label;
}

/** A time cap in milliseconds, and an allocation cap in bytes. */
export interface Caps {
  readonly ms: number;
  readonly bytes: number;
}

/** What a decode is measured by: a clock (ms) and the bytes in use. A test plants its own. */
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

const TIME = "decode exceeded time cap";

/** One decode of `data`: why it breaks the contract, or "". An allocation breach is read first. */
function attempt(
  decode: (view: ArrayBufferView) => unknown,
  data: Uint8Array,
  caps: Caps,
  gauge: Gauge,
): string {
  const before = gauge.used();
  const t0 = gauge.now();
  try {
    decode(data);
  } catch (e) {
    if (!(e instanceof BinaryFrameError)) return untyped(e);
  }
  const ms = gauge.now() - t0;
  if (gauge.used() - before > caps.bytes) return "decode exceeded allocation cap";
  return ms > caps.ms ? TIME : "";
}

/**
 * Why `decode(data)` breaks the contract, or "": it may return, or throw BinaryFrameError, inside
 * `caps`. The caps are a trip-wire for a future allocation or loop sized from a count in the input,
 * not a measurement (GC is not forced, so a heap delta can only under-report). The time cap reads
 * the wall clock, so a trip is run once more on the same input and fails only if it trips again: a
 * stall of the machine does not repeat, a slow decode does. An allocation trip is final.
 */
export function breach(
  decode: (view: ArrayBufferView) => unknown,
  data: Uint8Array,
  caps: Caps,
  gauge: Gauge = REAL,
): string {
  const why = attempt(decode, data, caps, gauge);
  return why === TIME ? attempt(decode, data, caps, gauge) : why;
}
