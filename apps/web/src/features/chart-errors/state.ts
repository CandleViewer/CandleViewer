/**
 * SCR-048's state model (E11-S02 PR4): driven only by an engine error's `code` and `details` and
 * the frame's `renderProfile`; `message` is never read (it may carry driver text, E11-D04 §12.3).
 */
import type { ChartEvents, FrameStats } from "@candleviewer/chart-engine";

/** The shipped engine codes (README C-8: they win over E11-D04 §12.2's proposed names). */
export const ENGINE_CODES = {
  lost: "ENGINE_CONTEXT_LOST",
  restored: "ENGINE_CONTEXT_RESTORED",
  restoreFailed: "ENGINE_CONTEXT_RESTORE_FAILED",
  noWebgl2: "ENGINE_NO_WEBGL2",
  shaderFailed: "ENGINE_SHADER_COMPILE_FAILED",
  /** Final only (`recoverable: false`): the render worker could not be restarted (README C-8). */
  workerLost: "ENGINE_WORKER_LOST",
} as const;

/** A manual retry's progress on a card: `failed` swaps the retry line (E11-D04 §12.2). */
export type RetryStatus = "idle" | "pending" | "failed";

type CardKind = "failed" | "shader-failed" | "worker-lost" | "no-webgl2";
type Card = {
  readonly code: string;
  readonly ref: string;
  readonly retry: RetryStatus;
  /** The opening event's flag, for `chart.error_shown` (E11-D04 D14). */
  readonly recoverable: boolean;
};

export type ChartErrorState =
  | { readonly kind: "ok" }
  | {
      readonly kind: "restoring";
      readonly attempt: number;
      readonly maxAttempts: number;
      /** Epoch ms of the next attempt; null when the event carried no `details`. */
      readonly nextAt: number | null;
      /** The event's wait: the countdown never shows more than this (a clock step back). */
      readonly nextTryMs: number | null;
    }
  | { readonly kind: "restored" }
  | ({ readonly kind: CardKind } & Card)
  /** The no-WebGL2 card was dismissed: basic rendering stays on, nothing is shown. */
  | { readonly kind: "basic" };

export type ChartErrorAction =
  | {
      readonly type: "error";
      readonly error: ChartEvents["error"];
      readonly now: number;
      /** A fresh `urn:cv:ui:{uuid4}`, used if this event opens a card. */
      readonly ref: string;
    }
  | { readonly type: "frame"; readonly profile: FrameStats["renderProfile"] }
  | { readonly type: "retry" }
  | { readonly type: "continue" }
  /** A `RECREATE_KEYS` recreate (a symbol change): a card never sits over a healthy chart. */
  | { readonly type: "reset" };

export const INITIAL: ChartErrorState = { kind: "ok" };

const CARD_OF: Readonly<Record<string, CardKind>> = {
  [ENGINE_CODES.restoreFailed]: "failed",
  [ENGINE_CODES.shaderFailed]: "shader-failed",
  [ENGINE_CODES.workerLost]: "worker-lost",
  [ENGINE_CODES.noWebgl2]: "no-webgl2",
};

export const isCard = (s: ChartErrorState): s is Extract<ChartErrorState, Card> =>
  s.kind === "failed" ||
  s.kind === "shader-failed" ||
  s.kind === "worker-lost" ||
  s.kind === "no-webgl2";

function onError(
  state: ChartErrorState,
  { error, now, ref }: Extract<ChartErrorAction, { type: "error" }>,
): ChartErrorState {
  const { code, details, recoverable } = error;
  if (code === ENGINE_CODES.workerLost && recoverable) return state; // the worker is respawning
  if (code === ENGINE_CODES.lost) {
    if (isCard(state)) return state; // a remount's loss is the retry's, the card holds
    return details === undefined
      ? { kind: "restoring", attempt: 1, maxAttempts: 3, nextAt: null, nextTryMs: null }
      : {
          kind: "restoring",
          attempt: details.attempt,
          maxAttempts: details.maxAttempts,
          nextAt: now + details.nextTryMs,
          nextTryMs: details.nextTryMs,
        };
  }
  if (code === ENGINE_CODES.restored)
    return state.kind === "restoring" ? { kind: "restored" } : state;
  const kind = Object.hasOwn(CARD_OF, code) ? CARD_OF[code] : undefined; // no prototype keys
  if (kind === undefined) return state;
  // A manual retry that ends in any failure keeps the card and its reference; the line changes.
  if (isCard(state)) return state.retry === "pending" ? { ...state, retry: "failed" } : state;
  if (state.kind === "basic" && kind === "no-webgl2") return state;
  return { kind, code, ref, retry: "idle", recoverable };
}

export function chartErrorReducer(
  state: ChartErrorState,
  action: ChartErrorAction,
): ChartErrorState {
  switch (action.type) {
    case "error":
      return onError(state, action);
    case "frame":
      // A pending retry ends on the remounted chart's first frame: WebGL2 again restores it,
      // `degraded-2d` without an error is still a failed retry (the card never waits forever).
      if (!isCard(state) || state.retry !== "pending") return state;
      return action.profile === "degraded-2d"
        ? { ...state, retry: "failed" }
        : { kind: "restored" };
    case "retry":
      return isCard(state) ? { ...state, retry: "pending" } : state;
    case "continue":
      return state.kind === "no-webgl2" ? { kind: "basic" } : state;
    case "reset":
      return state.kind === "ok" ? state : INITIAL;
  }
}
