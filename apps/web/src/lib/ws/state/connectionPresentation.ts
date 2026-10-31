// E10-S01 (#304) S10, BQ-02 / BQ-03 (E04-D02-F08, F09, F18, F23): one connection vocabulary for the
// shell chrome, pure over `WsState`. The CMP-076 chip and the CMP-208 / 210 status-bar word read it,
// the CMP-077 region reads `connectionRegion` beside it, and all three split the link the same way:
// live, a first connect, a running retry (a shell cause included), and a stopped one (a fatal close,
// 4403 included). Delayed and Stale stay unfed: `WsState` carries no throttle multiplier or topic
// ages, and no mapping is guessed from `quality` (a C-row on #325 asks for the shell-level source).
import type { WsState } from "./types";

/** The CMP-076 chip's five values (E17-D02 §3); this mapper feeds `live`, `reconnecting` and `offline`. */
export type ChipStatus = "live" | "delayed" | "stale" | "reconnecting" | "offline";
export type StatusTone = "ok" | "warn" | "error";

export interface ConnectionPresentation {
  readonly chip: {
    readonly status: ChipStatus;
    /** The running retry's number (`reconnecting` links only). */
    readonly attempt?: number;
    /** No session has been up yet: "Connecting…", no counter (E17-D02 §5, Q1). */
    readonly firstConnect?: boolean;
  };
  /**
   * The status bar's word, lower case, after "Connection: ". PROPOSED for #325: `live`,
   * `connecting` (a first connect only), `reconnecting` (any running retry, a shell cause
   * included), `offline` (the retry stopped: a fatal close or a session end).
   */
  readonly word: "live" | "connecting" | "reconnecting" | "offline";
  readonly tone: StatusTone;
  /** Epoch ms of the last topic frame before the outage (`outage.lastDataMs`); `null` while live or with none. */
  readonly lastGoodTs: number | null;
}

/**
 * A first connect is a `connecting` link with no outage: `outage` is stamped when an `up` link goes
 * down and cleared only by the next `auth_ok`, so a link that has been up never reads as one.
 */
export function connectionPresentation(ws: WsState): ConnectionPresentation {
  const { link, outage } = ws;
  const lastGoodTs = outage?.lastDataMs ?? null;
  if (link.kind === "up") {
    return { chip: { status: "live" }, word: "live", tone: "ok", lastGoodTs: null };
  }
  if (link.kind === "offline" && link.cause === "fatal") {
    return { chip: { status: "offline" }, word: "offline", tone: "error", lastGoodTs };
  }
  if (link.kind === "connecting" && outage === null) {
    const chip = { status: "reconnecting", firstConnect: true } as const;
    return { chip, word: "connecting", tone: "warn", lastGoodTs };
  }
  const chip =
    link.kind === "reconnecting"
      ? ({ status: "reconnecting", attempt: link.attempt } as const)
      : ({ status: "reconnecting" } as const);
  return { chip, word: "reconnecting", tone: "error", lastGoodTs };
}
