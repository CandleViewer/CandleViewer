// E17-T04: the connection state the UI binds to (C11, C12, WS-E06). Plain data: only `reduce`
// (reducer.ts) produces it.
import type { KillSwitchPayload, SystemUpdate } from "../protocol/frames";

/** The six E17-D02 rows plus `connecting`. Provisional until #325 is signed off (Q4). */
export type TransportState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "degraded:lagging"
  | "degraded:saturated"
  | "offline"
  | "shutdown_pending";

/** `fatal`: a close that forbids auto-reconnect (1002, 1009, 4400, 4403); the rest mirror the shell's reachability causes. */
export type OfflineCause = "offline" | "tailnet_unreachable" | "backend_unreachable" | "fatal";

/** Where the socket is, before `connection_quality` and `shutdown_notice` are applied. */
export type Link =
  | { readonly kind: "connecting" | "up" }
  | { readonly kind: "reconnecting"; readonly attempt: number; readonly nextAttemptAtMs: number }
  | {
      readonly kind: "offline";
      readonly cause: OfflineCause;
      readonly closeCode?: number | undefined;
    };

/** `overflowing` (queue over 90 %, 8.3) is folded into `saturated`: both are the worst degraded row. */
export type Quality = "healthy" | "lagging" | "saturated";
export type TopicStatus = "pending" | "live" | "resyncing" | "stale" | "revoked";

/** `unknown` is never rendered as "not killed" (WS-E06). */
export type KillSwitchView =
  | { readonly state: "unknown" }
  | {
      readonly state: "engaged" | "disengaged";
      readonly scope: KillSwitchPayload["scope"];
      readonly exchangeAccountIds: readonly string[];
    };

export type OrderEntryReason = "kill_switch_engaged" | "shutdown_pending" | "kill_switch_unknown";
/** C12: whether order entry may be offered, decided without a REST round-trip. */
export type OrderEntry =
  | { readonly enabled: true; readonly reason: null }
  | { readonly enabled: false; readonly reason: OrderEntryReason };

export interface WsState {
  readonly transport: TransportState;
  /** +1 exactly once per change of `transport`: the chrome announces a transition once, not per heartbeat. */
  readonly transitionSeq: number;
  readonly link: Link;
  readonly quality: Quality;
  /** Set by `shutdown_notice`, cleared by the `auth_ok` of the next connection (a re-auth keeps it). */
  readonly shutdown: {
    readonly closingInMs: number | undefined;
    readonly expectedDowntimeMs: number | undefined;
  } | null;
  readonly systemStream: TopicStatus;
  readonly killSwitch: KillSwitchView;
  readonly orderEntry: OrderEntry;
  /** Behind a "copy details" affordance only; never in default copy. Kept across reconnects. */
  readonly diagnostics: { readonly connectionId: string | null; readonly requestId: string | null };
}

/**
 * What the connection engine (S4) tells the reducer. Its promises: (1) every new socket is
 * announced by `connecting` before its `auth_ok`, so an `auth_ok` after `reconnecting` or `offline`
 * is ignored; (2) `connecting` announces only a new socket, so an `auth_ok` on an `up` link is an
 * in-place re-auth (23 4.1) and a re-auth emits no `connecting`, `reconnecting` or `offline`; (3)
 * after a resync of the `system` stream it reports `live` before the update of the snapshot that
 * ended it (a kill-switch fact that arrives sooner is dropped, WS-E06). `assertEngineOrder` (test
 * support) checks (1) and (3); (2) is S4's own test obligation, as events alone cannot tell a
 * re-auth from a new socket. The reducer vets every wire value it reads and keeps only the vetted.
 */
export type EngineEvent =
  | { readonly type: "connecting" }
  | { readonly type: "welcome"; readonly connectionId: string }
  | { readonly type: "auth_ok"; readonly killSwitch: KillSwitchPayload | undefined }
  | { readonly type: "reconnecting"; readonly attempt: number; readonly nextAttemptAtMs: number }
  | {
      readonly type: "offline";
      readonly cause: OfflineCause;
      readonly closeCode?: number | undefined;
    }
  | { readonly type: "system"; readonly update: SystemUpdate }
  | { readonly type: "system_stream"; readonly status: TopicStatus }
  | { readonly type: "request_id"; readonly requestId: string };
