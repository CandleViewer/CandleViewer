/**
 * `GET /instruments/{symbol}` for SCR-103 (E08-D06 §6, §11.1, D-12): one try mapped to an outcome by status, and
 * the bounded ladder over it. A 503 is the server still loading the list (wait 2, 4, 8, 16, 30 s or the
 * `Retry-After`, for 60 s at most, then a failure); a network error or any other status is a failure at once; 404
 * is "not in the instrument list" (retry no sooner than 60 s later, the server's refresh cooldown); 403 is T4.
 * No React: it returns plain values, so the host decides what to paint.
 */
import { SYSTEM_CLOCK, type Clock } from "../symbol-search/instrumentIndex";
import { SENDABLE, field, getAnswer } from "./http";
import type { InstrumentDetail } from "./rules";

const LADDER_MAX_S = 30;
/** 503s for this long is "failed". */
export const LADDER_BUDGET_MS = 60_000;
/** A 404 is asked again no sooner than this (C-8, the server's refresh cooldown). */
export const NOT_LISTED_RETRY_MS = 60_000;

/** D-12's causes: no answer, 503s for 60 s, or another status. */
export type DetailFailure =
  | { readonly cause: "network" }
  /** A 200 whose body is not an `InstrumentDetail` for the symbol asked: read as unreachable, never "answered 200". */
  | { readonly cause: "malformed" }
  | { readonly cause: "unavailable"; readonly instance: string | null }
  | { readonly cause: "http"; readonly status: number; readonly instance: string | null };

export type DetailAttempt =
  | { readonly kind: "ok"; readonly detail: InstrumentDetail }
  /** 503: the server is loading the list; `retryAfterS` is what it asked, or `null`. */
  | {
      readonly kind: "loading";
      readonly retryAfterS: number | null;
      readonly instance: string | null;
    }
  | { readonly kind: "not_listed"; readonly retryAtMs: number }
  | { readonly kind: "forbidden" }
  | { readonly kind: "failed"; readonly failure: DetailFailure };

export type DetailOutcome = Exclude<DetailAttempt, { kind: "loading" }>;

/** A 200 body this feature can use: the symbol asked for, a tick and a step (`22`'s required fields). */
export function isDetail(body: unknown, symbol: string): body is InstrumentDetail {
  return (
    field(body, "symbol") === symbol &&
    typeof field(body, "tick_size") === "string" &&
    typeof field(body, "qty_step") === "string"
  );
}

export async function attemptDetail(
  symbol: string,
  signal: AbortSignal,
  clock: Clock = SYSTEM_CLOCK,
): Promise<DetailAttempt | null> {
  if (!SENDABLE.test(symbol)) return { kind: "failed", failure: { cause: "network" } };
  const answer = await getAnswer(
    `/api/v1/instruments/${encodeURIComponent(symbol)}`,
    signal,
    clock,
  );
  if (signal.aborted) return null;
  if (answer === null) return { kind: "failed", failure: { cause: "network" } };
  if (answer.ok) {
    return isDetail(answer.body, symbol)
      ? { kind: "ok", detail: answer.body }
      : { kind: "failed", failure: { cause: "malformed" } };
  }
  if (answer.status === 403) return { kind: "forbidden" };
  if (answer.status === 404)
    return { kind: "not_listed", retryAtMs: clock.now() + NOT_LISTED_RETRY_MS };
  if (answer.status === 503) {
    return { kind: "loading", retryAfterS: answer.retryAfterS, instance: answer.instance };
  }
  return {
    kind: "failed",
    failure: { cause: "http", status: answer.status, instance: answer.instance },
  };
}

/** The wait before the n-th retry (n from 0): 2, 4, 8, 16, 30 s, then 30 s, or the server's ask. */
export function ladderWaitS(retry: number, askedS: number | null): number {
  return askedS ?? Math.min(2 ** (retry + 1), LADDER_MAX_S);
}

export interface LoadHooks {
  readonly clock?: Clock;
  /** Called with each wait of the ladder, for "next try in 4 s." (`retryAtMs` on the clock's ms). */
  readonly onLoading?: (wait: { readonly waitS: number; readonly retryAtMs: number }) => void;
}

/** Resolves with the outcome, or `null` when `signal` aborted first (the answer is dropped). */
export async function loadInstrumentDetail(
  symbol: string,
  signal: AbortSignal,
  hooks: LoadHooks = {},
): Promise<DetailOutcome | null> {
  const clock = hooks.clock ?? SYSTEM_CLOCK;
  const start = clock.now();
  for (let retry = 0; ; retry += 1) {
    const attempt = await attemptDetail(symbol, signal, clock);
    if (attempt === null || signal.aborted) return null;
    if (attempt.kind !== "loading") return attempt;
    const waitS = ladderWaitS(retry, attempt.retryAfterS);
    // A try due past the 60 s mark is "failed" now: 503s for a minute are not "loading" any more.
    if (clock.now() - start + waitS * 1000 > LADDER_BUDGET_MS) {
      return { kind: "failed", failure: { cause: "unavailable", instance: attempt.instance } };
    }
    hooks.onLoading?.({ waitS, retryAtMs: clock.now() + waitS * 1000 });
    const waited = await new Promise<boolean>((resolve) => {
      const done = (value: boolean): void => {
        clock.clearTimeout(timer);
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      };
      const onAbort = (): void => done(false);
      const timer = clock.setTimeout(() => done(true), waitS * 1000);
      signal.addEventListener("abort", onAbort);
    });
    if (!waited) return null;
  }
}
