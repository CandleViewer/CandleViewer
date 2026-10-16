/**
 * WS `system` topic client (`docs/plan/23-ws-protocol.md` §4, §6.2, §9).
 * `system` is auto-subscribed at `auth_ok` — this client never sends an
 * explicit `sub` for it and never unsubscribes. Handles the envelope
 * framing (§3.1), the heartbeat contract (§9.1) and the mandated
 * reconnect-backoff table (§9.2, `backoff.ts`).
 *
 * E17 (the WS gateway) has not landed; until then this connects against
 * whatever `wsUrl` resolves to and degrades to the offline state on
 * failure — the contract test in `test/shell/bootstrap/systemSocket.test.ts`
 * validates frames against the committed schema
 * (`docs/plan/ws-schema.json`) independent of a live server.
 */
import type { generated } from "@candleviewer/protocol";
import { handleWsError } from "../../lib/ws/errorHandler.js";
import { backoffDelayWithJitter } from "./backoff.js";
import { ReachabilityTracker } from "./reachability.js";

export type SystemUpdate = generated.ws.System;

interface Envelope {
  readonly t: string;
  readonly id?: string;
  readonly ch?: string;
  readonly s?: number | null;
  readonly ts?: number;
  readonly e?: "j" | "b" | "b64";
  readonly p?: unknown;
}

const SYSTEM_UPDATE_KINDS: ReadonlySet<SystemUpdate["kind"]> = new Set([
  "health",
  "kill_switch",
  "feature_flags",
  "exchange_state",
  "connection_quality",
  "shutdown_notice",
  "degraded_data",
  "clock_drift",
  "notice",
]);

/** Minimal structural guard — full schema validation is the `contract` CI job's concern. */
export function isSystemUpdate(payload: unknown): payload is SystemUpdate {
  return (
    typeof payload === "object" &&
    payload !== null &&
    "kind" in payload &&
    SYSTEM_UPDATE_KINDS.has((payload as { kind: unknown }).kind as SystemUpdate["kind"])
  );
}

const HEARTBEAT_INTERVAL_MS = 15_000;

export interface SystemSocketCallbacks {
  onSystemUpdate(update: SystemUpdate): void;
  onConnectionChange(
    state:
      | { kind: "connecting" }
      | { kind: "live" }
      | { kind: "reconnecting"; attempt: number; nextAttemptAtMs: number }
      | { kind: "offline"; cause: "offline" | "tailnet_unreachable" | "backend_unreachable" },
  ): void;
}

export interface SystemSocketOptions {
  readonly url: string;
  readonly callbacks: SystemSocketCallbacks;
  /** Test seam: an injectable `WebSocket`-shaped constructor. */
  readonly createSocket?: ((url: string, protocols: string[]) => WebSocket) | undefined;
  readonly now?: (() => number) | undefined;
  readonly random?: (() => number) | undefined;
}

/** Manages one reconnecting WS connection dedicated to the `system` topic. */
export class SystemSocket {
  private socket: WebSocket | null = null;
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;
  private readonly reachability = new ReachabilityTracker();

  constructor(private readonly options: SystemSocketOptions) {
    this.reachability.subscribe((state) => {
      if (!state.reachable && state.cause) {
        this.options.callbacks.onConnectionChange({ kind: "offline", cause: state.cause });
      }
    });
  }

  connect(): void {
    this.stopped = false;
    this.openSocket();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.socket?.close(1000, "client_stop");
    this.socket = null;
  }

  private openSocket(): void {
    this.options.callbacks.onConnectionChange({ kind: "connecting" });
    const factory =
      this.options.createSocket ?? ((url, protocols) => new WebSocket(url, protocols));
    // `cv.v1.msgpack` is offered once this client decodes it (#2886): the server prefers it.
    const socket = factory(this.options.url, ["cv.v1.json"]);
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.attempt = 0;
      this.reachability.recordSuccess();
      this.options.callbacks.onConnectionChange({ kind: "live" });
      this.startHeartbeat();
    });

    socket.addEventListener("message", (event) => {
      this.handleMessage(event.data);
    });

    socket.addEventListener("close", () => {
      this.reachability.recordFailure();
      if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
      if (!this.stopped) this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      this.reachability.recordFailure();
    });
  }

  private handleMessage(data: unknown): void {
    if (typeof data !== "string") return;
    let envelope: Envelope;
    try {
      envelope = JSON.parse(data) as Envelope;
    } catch {
      return;
    }
    if (envelope.t === "err") {
      // E17-T05: every err frame goes through the single 10.3 mapping, whatever the channel.
      const p = envelope.p as { code?: unknown; message?: unknown } | undefined;
      if (p && typeof p.code === "string") {
        handleWsError({
          t: "err",
          p: { code: p.code, ...(typeof p.message === "string" ? { message: p.message } : {}) },
        });
      }
      return;
    }
    if (envelope.ch !== "system") return;
    if (envelope.t !== "d" && envelope.t !== "snap") return;
    if (isSystemUpdate(envelope.p)) {
      this.options.callbacks.onSystemUpdate(envelope.p);
    }
  }

  private startHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = setInterval(() => {
      this.socket?.send(JSON.stringify({ t: "ping", id: `c-hb-${Date.now()}`, ts: Date.now() }));
    }, HEARTBEAT_INTERVAL_MS);
  }

  private scheduleReconnect(): void {
    this.attempt += 1;
    const random = this.options.random ?? Math.random;
    const delayMs = backoffDelayWithJitter(this.attempt, random);
    const now = this.options.now ?? Date.now;
    const nextAttemptAtMs = now() + delayMs;
    this.options.callbacks.onConnectionChange({
      kind: "reconnecting",
      attempt: this.attempt,
      nextAttemptAtMs,
    });
    this.reconnectTimer = setTimeout(() => {
      if (!this.stopped) this.openSocket();
    }, delayMs);
  }
}
