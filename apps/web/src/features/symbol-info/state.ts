/**
 * The state derivation SCR-103's data layer owns (E08-D06 §6, §11; D13 §5): which sentences a contract result, a
 * coverage result and the live band's inputs give, one state at a time (not trading over live-unavailable over
 * disconnected over stale over live). Pure: the host reads the clock and the stores and passes values in.
 */
import * as copy from "./copy";
import type { CoverageOutcome } from "./coverage";
import type { DetailFailure, DetailOutcome } from "./instrumentDetail";
import { statusOf, type InstrumentDetail } from "./rules";

/** E17-D01's thresholds (D-4): stale at 5 s, escalated at 15 s. */
export const STALE_T1_MS = 5_000;
export const STALE_T2_MS = 15_000;

/** The contract band's phase (`loading`: no result yet, the ladder may be waiting). */
export type ContractPhase =
  | { readonly kind: "loading"; readonly text: string; readonly waitS: number | null }
  | { readonly kind: "ready" }
  | { readonly kind: "not_listed"; readonly text: string; readonly retryAtMs: number }
  | { readonly kind: "forbidden"; readonly text: string }
  | {
      readonly kind: "failed";
      readonly heading: string;
      readonly cause: string;
      readonly orderLine: string;
      /** "Ref urn:cv:req:…", only when the problem carries it. */
      readonly reference: string | null;
    };

/** The words of a failure's cause (D-12): by status only, never `Problem.detail`. */
export function causeText(failure: DetailFailure): string {
  if (failure.cause === "network") return copy.CAUSE_NETWORK;
  if (failure.cause === "unavailable") return copy.CAUSE_UNAVAILABLE;
  return copy.causeAnswered(failure.status);
}

/** Loading before a result (cold open), then the result's phase. `waitS` is the ladder's current wait. */
export function contractPhase(
  symbol: string,
  outcome: DetailOutcome | null,
  waitS: number | null = null,
): ContractPhase {
  if (outcome === null) {
    return {
      kind: "loading",
      text: waitS === null ? copy.checkingBybit(symbol) : copy.loadingList(waitS),
      waitS,
    };
  }
  switch (outcome.kind) {
    case "ok":
      return { kind: "ready" };
    case "not_listed":
      return { kind: "not_listed", text: copy.notInList(symbol), retryAtMs: outcome.retryAtMs };
    case "forbidden":
      return { kind: "forbidden", text: copy.FORBIDDEN };
    case "failed": {
      const instance = outcome.failure.cause === "network" ? null : outcome.failure.instance;
      return {
        kind: "failed",
        heading: copy.loadFailed(symbol),
        cause: causeText(outcome.failure),
        orderLine: copy.orderLine(symbol),
        reference: instance === null ? null : copy.reference(instance),
      };
    }
  }
}

export interface NotTradingView {
  /** Under the title: "BTCUSDT is not trading on Bybit." (PreLaunch: not open for trading in CandleViewer). */
  readonly heading: string;
  /** `status_reason` verbatim, else E11-D04's fallback; `null` for a status with no fallback in the deck. */
  readonly reason: string | null;
  /** CMP-239 `delisted`, only for Delivering and Closed (PreLaunch is an info notice). */
  readonly delisted: boolean;
  readonly liveReplacement: string;
  readonly coverageSentence: string;
  /** The funding row's suppression sentence (§7). */
  readonly noFunding: string;
}

/** D-5: `null` when the symbol is trading; unknown values read as not trading. */
export function notTradingView(detail: InstrumentDetail): NotTradingView | null {
  const status = statusOf(detail.status);
  if (status.trading) return null;
  const symbol = detail.symbol;
  const reasonSent = detail.status_reason;
  const fallback =
    detail.status !== undefined && Object.hasOwn(copy.STATUS_FALLBACK, detail.status)
      ? copy.STATUS_FALLBACK[detail.status as keyof typeof copy.STATUS_FALLBACK]
      : null;
  return {
    heading: detail.status === "PreLaunch" ? copy.preLaunch(symbol) : copy.notTrading(symbol),
    reason: typeof reasonSent === "string" && reasonSent.trim() !== "" ? reasonSent : fallback,
    delisted: detail.status === "Delivering" || detail.status === "Closed",
    liveReplacement: copy.noLiveTradingData(symbol),
    coverageSentence: copy.NO_COVERAGE_NOT_TRADING,
    noFunding: copy.noFunding(symbol),
  };
}

/**
 * §11.3: when to ask for coverage, and how to read its answer by the contract band. `ask` is true for a Trading
 * status; a non-Trading status or a 404 gives the not-trading line without a request; no status yet gives
 * "waits for the instrument list", and coverage is asked once more when the contract band loads.
 */
export type CoverageGate =
  | { readonly kind: "ask" }
  | { readonly kind: "not_trading"; readonly text: string }
  | { readonly kind: "waits"; readonly text: string };

export function coverageGate(contract: DetailOutcome | null): CoverageGate {
  if (contract?.kind === "ok") {
    return statusOf(contract.detail.status).trading
      ? { kind: "ask" }
      : { kind: "not_trading", text: copy.NO_COVERAGE_NOT_TRADING };
  }
  if (contract?.kind === "not_listed") {
    return { kind: "not_trading", text: copy.NO_COVERAGE_NOT_TRADING };
  }
  return { kind: "waits", text: copy.COVERAGE_WAITS };
}

export type CoverageState =
  | { readonly kind: "view"; readonly view: Extract<CoverageOutcome, { kind: "ok" }>["view"] }
  | { readonly kind: "waits" | "not_trading"; readonly text: string }
  | { readonly kind: "failed"; readonly text: string; readonly retry: boolean }
  | { readonly kind: "forbidden"; readonly text: string };

/** A coverage answer read by the contract band: a 422 is never "failed" for a symbol that is not trading. */
export function coverageState(
  contract: DetailOutcome | null,
  coverage: CoverageOutcome | null,
): CoverageState | null {
  const gate = coverageGate(contract);
  if (gate.kind !== "ask") return { kind: gate.kind, text: gate.text };
  if (coverage === null) return null;
  switch (coverage.kind) {
    case "ok":
      return { kind: "view", view: coverage.view };
    case "forbidden":
      return { kind: "forbidden", text: copy.FORBIDDEN };
    default:
      // 422 for a Trading symbol, and any other status or no answer, is Coverage failed (§11.3).
      return { kind: "failed", text: copy.COVERAGE_FAILED, retry: true };
  }
}

export interface LiveInput {
  readonly symbol: string;
  readonly trading: boolean;
  /** `sub_ok` refused with `subscription_limit`. */
  readonly subscriptionLimit: boolean;
  /** The transport is down (E17-D01); `lastDataMs` is the newest item's `ts`. */
  readonly disconnected: boolean;
  readonly feedDown: boolean;
  readonly hasItem: boolean;
  readonly lastDataMs: number | null;
  readonly nowMs: number;
  /** The server's `meta.stale`, with the instant it began (epoch ms) when sent. */
  readonly serverStale: { readonly sinceMs: number | null } | null;
  /** The per-item `stale` flag (T1 at once, D-4). */
  readonly itemStale: boolean;
  /** Fed only by the one-shot bootstrap: it turns stale at 5 s and stays there, never T2, never live (§11.2). */
  readonly bootstrapOnly: boolean;
}

export type LiveState =
  | { readonly kind: "not_trading"; readonly text: string }
  | { readonly kind: "live_unavailable"; readonly lines: readonly string[] }
  | { readonly kind: "disconnected"; readonly text: string }
  | { readonly kind: "awaiting"; readonly text: string | null }
  | {
      readonly kind: "stale_t1" | "stale_t2" | "feed_down";
      readonly marker: string;
      readonly lastUpdate: string | null;
      /** The polite sentence on entry; `null` for T2, whose assertive sentence is the shell's (E17-D01 §7). */
      readonly announce: string | null;
    }
  | { readonly kind: "live"; readonly announce: string | null };

const utcTime = (ms: number): string => new Date(ms).toISOString().slice(11, 16);
const utcSeconds = (ms: number): string => new Date(ms).toISOString().slice(11, 19);

/** One state at a time: not trading, then live unavailable, disconnected, stale (T2, T1), then live. */
export function liveState(input: LiveInput): LiveState {
  if (!input.trading) return { kind: "not_trading", text: copy.noLiveTradingData(input.symbol) };
  if (input.subscriptionLimit) return { kind: "live_unavailable", lines: copy.LIVE_UNAVAILABLE };
  if (input.disconnected) {
    return {
      kind: "disconnected",
      text: copy.disconnected(input.lastDataMs === null ? "—" : utcTime(input.lastDataMs)),
    };
  }
  const age = input.lastDataMs === null ? null : Math.max(input.nowMs - input.lastDataMs, 0);
  if (!input.hasItem) {
    // `sub_ok` with no `snap` yet: static rows, and "No live values yet" after 5 s.
    return {
      kind: "awaiting",
      text: age !== null && age >= STALE_T1_MS ? copy.NO_LIVE_VALUES : null,
    };
  }
  const last = input.lastDataMs === null ? null : copy.lastUpdate(utcSeconds(input.lastDataMs));
  if (input.feedDown) {
    return {
      kind: "feed_down",
      marker: copy.FEED_DOWN,
      lastUpdate: last,
      announce: copy.LIVE_STALE,
    };
  }
  const seconds = age === null ? null : Math.floor(age / 1000);
  const serverSince = input.serverStale?.sinceMs ?? null;
  if (input.serverStale !== null && serverSince !== null && !input.bootstrapOnly) {
    return {
      kind: "stale_t2",
      marker: copy.staleServer(utcSeconds(serverSince)),
      lastUpdate: last,
      announce: null,
    };
  }
  if (
    !input.bootstrapOnly &&
    seconds !== null &&
    (input.serverStale !== null || (age ?? 0) >= STALE_T2_MS)
  ) {
    return {
      kind: "stale_t2",
      marker: copy.staleT2(input.symbol, `${String(seconds)} s`),
      lastUpdate: last,
      announce: null,
    };
  }
  if (input.itemStale || (age !== null && age >= STALE_T1_MS)) {
    return {
      kind: "stale_t1",
      marker: copy.staleT1(`${String(seconds ?? Math.floor(STALE_T1_MS / 1000))}s`),
      lastUpdate: last,
      announce: copy.LIVE_STALE,
    };
  }
  return { kind: "live", announce: null };
}

/** The polite announcement on a change of kind: stale on entry, "Live values current." on exit (§6). */
export function liveTransition(prev: LiveState["kind"] | null, next: LiveState): string | null {
  const stale = (k: LiveState["kind"] | null): boolean =>
    k === "stale_t1" || k === "stale_t2" || k === "feed_down";
  if (stale(prev) && next.kind === "live") return copy.LIVE_CURRENT;
  if (!stale(prev) && stale(next.kind) && "announce" in next) return next.announce;
  return null;
}
