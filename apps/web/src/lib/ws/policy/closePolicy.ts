// E17-T04 S3 (23 4.4, 9.2, C7): what to do when the socket ends. A pure decision: the attempt number
// and the random source are arguments, and the delay table stays in `shell/bootstrap/backoff.ts`,
// the one place 9.2 lives (D4).
import { backoffDelayWithJitter, backoffStepFor } from "../../../shell/bootstrap/backoff";
import type { ControlPayloads } from "../protocol/frames";

/** 9.2 names 1002, 4400 and 4403; 1009 joins them (D10: 4.4 says "fix client"). Retrying any of them is pure load. */
export const FATAL_CLOSE_CODES: ReadonlySet<number> = new Set([1002, 1009, 4400, 4403]);
/** 4.4: the token was refused or expired. */
export const TOKEN_REJECTED_CLOSE_CODE = 4401;
/** `bye.retry_after_ms` is untrusted: a longer hint is a bug (a timer past 2^31 ms fires at once, a hot loop). */
export const MAX_RETRY_AFTER_MS = 300_000;

export interface CloseInfo {
  /** The close frame's code; 1006 when the transport dropped without one. */
  readonly code: number;
  /** The `bye` that came before the close, if one did (4.4). */
  readonly bye?: ControlPayloads["bye"] | undefined;
  /** The 1-based reconnect this decision would start: its row of the 9.2 table. */
  readonly attempt: number;
  /** We asked for this close (stop, logout), so there is nothing to reconnect to. */
  readonly stoppedByClient?: boolean | undefined;
}

export interface CloseDecision {
  readonly reconnect: boolean;
  /** 4401: drop the rejected token and get a fresh one over REST before the next `auth`. */
  readonly refreshFirst: boolean;
  /** Wait this long, counted from the close, before the next open (a refresh runs inside it). */
  readonly delayMs: number;
  /** The connection is over for a reason the user should see; a client stop is not one. */
  readonly fatal: boolean;
}

const OVER = { reconnect: false, refreshFirst: false, delayMs: 0 } as const;

/**
 * Either the close code or the `bye` code can be the fatal one: a transport that drops after a
 * `bye 4403` still must not hot-loop. `bye.reconnect: false` is honoured. `bye.retry_after_ms` is a
 * floor under the 9.2 delay, and since a planned shutdown sends the same hint to every client it gets
 * the row's jitter on top as well, so they do not all come back in the same millisecond. A hint that
 * is not a finite number is ignored; a finite one is clamped to [0, 5 min].
 */
export function decideClose(info: CloseInfo, random: () => number = Math.random): CloseDecision {
  if (info.stoppedByClient === true) return { ...OVER, fatal: false };
  const codes = info.bye === undefined ? [info.code] : [info.code, info.bye.code];
  if (info.bye?.reconnect === false || codes.some((code) => FATAL_CLOSE_CODES.has(code))) {
    return { ...OVER, fatal: true };
  }
  const raw = info.bye?.retry_after_ms;
  const hint =
    typeof raw === "number" && Number.isFinite(raw)
      ? Math.min(Math.max(raw, 0), MAX_RETRY_AFTER_MS)
      : 0;
  const backoff = backoffDelayWithJitter(info.attempt, random);
  const spread = hint > 0 ? Math.round(random() * backoffStepFor(info.attempt).jitterMs) : 0;
  return {
    reconnect: true,
    refreshFirst: codes.includes(TOKEN_REJECTED_CLOSE_CODE),
    delayMs: Math.max(hint, backoff) + spread,
    fatal: false,
  };
}
