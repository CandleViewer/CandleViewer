// E24-S05 (#780): the backfill read's contract as the feed consumes it, from `22` `getLiquidations`
// (`LiquidationsPageMeta.coverage`). The read itself is `historyRead.ts`; the feed takes it as `loadHistory`.
import type { LiquidationPrint } from "./prints";

export interface LiqCoverage {
  /** The first stored print for the symbol; `null` when none is stored. */
  readonly firstAvailableMs: number | null;
  /** The part of the requested window the store answers for. */
  readonly coveredFromMs: number | null;
  readonly coveredToMs: number | null;
  /** The window ends before `first_available_ts`, or nothing is stored: empty means "not recorded". */
  readonly noCoverage: boolean;
}

/** `older`: prints before `atMs` were not loaded; `newer`: prints after `atMs` were not (the last attempt). */
export interface LiqTruncation {
  readonly side: "older" | "newer";
  readonly atMs: number;
}

export type LiqHistoryResult =
  | {
      readonly kind: "ok";
      /** Ascending, at most `keep`. */
      readonly prints: readonly LiquidationPrint[];
      readonly coverage: LiqCoverage;
      /** The end of the window that was not loaded, or `null` when the whole window was. */
      readonly truncated: LiqTruncation | null;
      readonly malformed: number;
    }
  | {
      readonly kind: "failed";
      /** `null`: no answer (network, deadline, unreadable body). */
      readonly status: number | null;
      readonly code: string | null;
    };

export interface LiqHistoryClock {
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
}

export interface LiqHistoryRequest {
  readonly symbol: string;
  readonly fromMs: number;
  readonly toMs: number;
  readonly minNotionalUsd: string | null;
  readonly signal: AbortSignal;
  /** The prints kept: the ring's capacity. */
  readonly keep: number;
  readonly clock?: LiqHistoryClock | undefined;
  readonly maxPages?: number | undefined;
  readonly maxAttempts?: number | undefined;
}
