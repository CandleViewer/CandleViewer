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
  readonly opts?: SubOptions;
  readonly paneId: string;
  /** Restore order after a reconnect (9.3): private, then the focused pane, then the rest. */
  readonly priority: SubscriptionPriority;
}

/** One validated data frame. A `b64` body is the raw CVWB bytes (D13): transferred, not decoded. */
export interface TopicFrame {
  readonly kind: "snap" | "d";
  readonly seq: number;
  readonly ts: number;
  readonly meta: SnapMeta | undefined;
  readonly body: DataBody;
  readonly decodeMs: number;
}

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
  getToken(): Promise<TokenResult>;
  /** The server rejected the token (4401): the next `getToken` must not hand out the same one. */
  invalidate(): void;
}

export interface WsClient {
  consume(spec: ConsumerSpec): TopicHandle;
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
