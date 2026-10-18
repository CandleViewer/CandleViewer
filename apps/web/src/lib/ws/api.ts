// E17-T04 S1: the public surface of the web WS client (C-6.1: typed first, built in S2-S5).
// Consumers never see the socket: they register interest (`consume`), read the latest frames from
// rAF (`read`, C9) and bind to `WsState`. Chart data never flows through React state.
import type { SubscriptionPriority } from "../../shell/bootstrap/subscriptionOrder";
import type { DataBody } from "./protocol/codec";
import type { SnapMeta, SubOptions } from "./protocol/frames";
import type { TopicStatus, WsState } from "./state/types";

/** C8: what a pane tells the client about itself; `collapsed` releases its subscriptions. */
export type PaneVisibility = "visible" | "offscreen" | "collapsed";

export interface ConsumerSpec {
  readonly ch: string;
  readonly opts?: SubOptions | undefined;
  readonly paneId: string;
  /** Restore order after a reconnect (9.3): private, then the focused pane, then the rest. */
  readonly priority: SubscriptionPriority;
}

/** Why the state a consumer holds for a topic is void: it clears it, and a `snap` follows unless the subscription ended. */
export type ResetReason =
  | "gap"
  | "malformed"
  | "overflow"
  | "resnapshot"
  | "narrowed"
  | "revoked"
  | "unsubscribed"
  | "reconnect";

interface Stamped {
  readonly seq: number;
  readonly ts: number;
  /** 13.1: span id of a sampled frame. */
  readonly sp: string | undefined;
  readonly decodeMs: number;
  /** The frame as it arrived, in encoded bytes (a chunked set: all its chunks): what a queue in front of a consumer charges a structured body for. */
  readonly size: number;
}

/**
 * A complete snapshot. A chunked set (3.6) is handed over whole, never piecemeal: `bodies` holds
 * its chunks in order (one for a single-frame `snap`) and `seq` is the final chunk's. A `b64`
 * body is the raw CVWB bytes (D13): transferred, not decoded.
 */
export interface SnapFrame extends Stamped {
  readonly kind: "snap";
  readonly meta: SnapMeta | undefined;
  readonly bodies: readonly [DataBody, ...DataBody[]];
}

export interface DeltaFrame extends Stamped {
  readonly kind: "d";
  /** A `bars` delta carries `include_delta`, which says whether a kind-4 `delta` of 0 is real (6.1, C13). */
  readonly meta: SnapMeta | undefined;
  readonly body: DataBody;
}

/** In-band, so a consumer that reads late still clears its state before it applies what follows. */
export interface ResetFrame {
  readonly kind: "reset";
  readonly reason: ResetReason;
}

/** One entry of `read()`: validated and sequenced, never state assembled across a gap (7.1). */
export type TopicFrame = SnapFrame | DeltaFrame | ResetFrame;

export interface TopicHandle {
  readonly ch: string;
  /** Drains the frames applied since the last call, in order. Call it from rAF, never per arrival (C9). */
  read(): readonly TopicFrame[];
  /** C4: the server's effective options, never the requested ones. */
  readonly effective: Readonly<Record<string, unknown>>;
  readonly status: TopicStatus;
  /** C11: replay data is rendered in distinct chrome; `rs` is the replay session id. */
  readonly source: "live" | "replay";
  readonly rs: string | undefined;
  /** Drops this consumer; the topic is unsubscribed when the last consumer lets go. */
  release(): void;
}

export type TokenResult =
  | { readonly kind: "ok"; readonly accessToken: string; readonly expiresAtMs: number }
  | { readonly kind: "locked" | "unavailable" };

/**
 * The seam to #2712's in-memory access-token client. The WS client never refreshes: it asks, uses
 * the token only to send `auth`, and never stores or logs it or puts it in a URL (4.3).
 */
export interface TokenSource {
  /**
   * The holder coalesces concurrent calls: the WS client keeps one in flight at a time, but a call it stopped waiting for
   * (10 s) may still be pending when the next connection asks, and a refresh token is single-use.
   */
  getToken(): Promise<TokenResult>;
  /** The server rejected the token (4401): the next `getToken` must not hand out the same one. */
  invalidate(): void;
}

export interface WsClient {
  /** `rs`: the replay session this consumer reads (C11); without one it reads the live stream. */
  consume(spec: ConsumerSpec, rs?: string): TopicHandle;
  /** Visibility drives throttling (C8); the size drives the heatmap `time_bucket_ms` (6.1.1). */
  setPane(
    paneId: string,
    visibility: PaneVisibility,
    size?: { cssWidth: number; dpr: number },
  ): void;
  focusPane(paneId: string | null): void;
  /** A `useSyncExternalStore` pair: the snapshot is referentially stable between transitions. */
  getState(): WsState;
  subscribe(listener: () => void): () => void;
  stop(): void;
}
