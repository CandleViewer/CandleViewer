// The DataModel's counters and its one rejection type (26 §3.3, E11-T03). A mutation is validated
// in full before its first write, so a rejected one leaves the store byte-identical.
import { ENGINE_DECODE_ERROR } from "../worker/protocol.js";

export const REJECT_REASONS = [
  "length", // columns of unequal length, or a cell count the offsets do not match
  "non_finite", // NaN or ±Infinity in a float column or a scalar parameter
  "order", // time not strictly increasing, or out of order against the bars held
  "range", // an index, bar or price level outside the store's extent
  "ceiling", // a declared count above maxBars, rejected before any allocation
  "origin", // priceOrigin / tickSize differ from the series held
  "offsets", // footprint prefix sums not starting at 0 or not non-decreasing
  "type", // a column that is not the typed array its field declares
] as const;
export type RejectReason = (typeof REJECT_REASONS)[number];

/** `engine.model.*`: `rejected_mutations{reason}`, `evictions`, `reallocations`. */
export class ModelCounters {
  readonly rejectedMutations = Object.fromEntries(REJECT_REASONS.map((r) => [r, 0])) as Record<
    RejectReason,
    number
  >;
  evictions = 0;
  reallocations = 0;

  /** Counts the rejection and throws it: the caller has written nothing yet. */
  reject(reason: RejectReason, message: string): never {
    this.rejectedMutations[reason] += 1;
    throw new ModelRejection(reason, message);
  }
}

/** A mutation refused at the store boundary; the runtime reports it as `ENGINE_DECODE_ERROR`. */
export class ModelRejection extends Error {
  readonly code = ENGINE_DECODE_ERROR;
  constructor(
    readonly reason: RejectReason,
    message: string,
  ) {
    super(`chart-engine: ${message}`);
    this.name = "ModelRejection";
  }
}

/** The range a mutation touched, in logical indices after it (HeatmapRing: the physical column);
 * reused, valid until the next one. */
export interface MutationRange {
  /** Which mutation produced it: the direction stored indices rebase in (see indexShift). */
  readonly op: MutationOp;
  readonly from: number;
  readonly to: number;
  /** How far stored indices move: after `prepend`, i += indexShift; after `append`, i -= it. */
  readonly indexShift: number;
}

export type MutationOp = "append" | "patch" | "prepend" | "replace";

export class RangeSlot implements MutationRange {
  op: MutationOp = "replace";
  from = 0;
  to = 0;
  indexShift = 0;
  set(op: MutationOp, from: number, to: number, indexShift: number): MutationRange {
    this.op = op;
    this.from = from;
    this.to = to;
    this.indexShift = indexShift;
    return this;
  }
}

/** The smallest power of two ≥ n (n ≥ 1). */
export const pow2 = (n: number): number => (n <= 1 ? 1 : 2 ** (32 - Math.clz32(n - 1)));
