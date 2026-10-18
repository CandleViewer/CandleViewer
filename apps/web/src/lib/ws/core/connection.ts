// E17-T04 S4 (23 4, 8.5; C1, C6): the connection's session. It owns one socket at a time: `hello`,
// `auth` through the `TokenSource`, and the pacing of everything the client sends. It knows nothing
// of streams: the frames that are not its own go to the engine through `hooks`. Heartbeats, the
// reconnect schedule and the in-place re-`auth` are the next slice's. Worker-agnostic: the socket,
// the clock, the timers and the random source are injected.
import type { TokenResult, TokenSource } from "../api";
import { createOutboundPacer } from "../policy/outboundPacer";
import type { Timers } from "../policy/timers";
import {
  decodeFrame,
  encodeFrame,
  type ControlOf,
  type Inbound,
  type WsDecodeError,
} from "../protocol/codec";
import * as F from "../protocol/frames";
import type { EngineEvent } from "../state/types";
import type { ReachabilityTracker } from "../../../shell/bootstrap/reachability";

/** What a socket tells the connection; the platform adapter maps `WebSocket` events onto it. */
export interface SocketEvents {
  open(): void;
  message(data: unknown): void;
  /** A connect that failed and a connection that was lost both end here: a `WebSocket` closes after its error. */
  close(code: number): void;
}

export interface EngineSocket {
  send(data: string): void;
  close(code: number, reason: string): void;
}

export type SocketFactory = (
  url: string,
  protocols: readonly string[],
  events: SocketEvents,
) => EngineSocket;

export interface ConnectionHooks {
  /** The first `auth_ok` of a socket: subscribe now. */
  ready(): void;
  /** The socket is gone and everything it taught is void. Runs before the reconnect is announced. */
  down(): void;
  /** Every frame the session does not settle itself: data, replies, `revoked`, and each `err`. */
  frame(frame: Inbound, decodeMs: number): void;
  /** A message that could not be trusted (undecodable). */
  malformed(error: WsDecodeError): void;
}

export interface ConnectionOptions {
  /** 2.1: `wss://host/api/v1/ws`. Never carries a token (4.3). */
  readonly url: string;
  readonly createSocket: SocketFactory;
  readonly tokens: TokenSource;
  readonly client: {
    readonly version: string;
    readonly shell: NonNullable<F.HelloPayload["shell"]>;
    readonly locale: string;
  };
  readonly timers: Timers;
  /** Epoch milliseconds: `hello.clock_ms`, the clock skew and the token's expiry. */
  readonly wall: () => number;
  readonly random: () => number;
  readonly reachability: Pick<ReachabilityTracker, "recordSuccess" | "recordFailure" | "current">;
  readonly emit: (event: EngineEvent) => void;
  readonly hooks: ConnectionHooks;
}

export interface Connection {
  /** Opens the first connection. Idempotent. */
  start(): void;
  /** A client stop: closes the socket and never reconnects. */
  stop(): void;
  /** Paces `frame` out (8.5); dropped unless the connection is `ready`. */
  send(frame: F.ClientFrame): void;
  /** An id for a request: unique among everything this connection sends (`hello`, `auth` and pings take theirs from the same source). */
  nextId(): string;
  /** Authenticated: `sub` and the rest may go. */
  readonly ready: boolean;
  /** `welcome.limits.max_topics_per_request`. */
  readonly topicsPerRequest: number;
  /** `welcome.limits.min_throttle_ms`: `undefined` until `welcome`. */
  readonly minThrottleMs: number | undefined;
  readonly counters: { readonly reconnects: number; readonly malformedFrames: number };
}

/** Application close codes (3000-4999) for the connections the client ends itself. */
const CLOSE_STOP = 1000;
/** What a refused `auth` is treated as: the gateway's own code for it (4.4). */
const CLOSE_AUTH_REFUSED = 4401;

type Token = { readonly accessToken: string; readonly expiresAtMs: number };

/** The socket being built or lived on; at most one. Its callbacks check they still own `current`. */
interface Conn {
  socket: EngineSocket;
  /** `connecting`: not open. `hello`: `welcome` due. `auth`: `auth_ok` due. */
  phase: "connecting" | "hello" | "auth" | "ready";
  opened: boolean;
  /** Fetched before the socket opened, held until the `auth` frame is built: the only place it goes. */
  token: Token | undefined;
  /** The `auth` whose `auth_ok` (or error) is due. */
  authId: string | undefined;
}

/**
 * What `Conn.socket` holds until the factory returns: the factory's callbacks need the `Conn`, and
 * a socket calls them from a later task, so nothing touches this before it is replaced.
 */
const UNOPENED = {} as EngineSocket;

export function createConnection(options: ConnectionOptions): Connection {
  const { url, createSocket, tokens, client, timers, wall, reachability, emit, hooks } = options;
  const nextId = F.createIdSource();
  const counters = { reconnects: 0, malformedFrames: 0 };
  let topicsPerRequest = 1;
  let minThrottleMs: number | undefined;
  let current: Conn | undefined;
  let started = false;
  let stopped = false;

  const pacer = createOutboundPacer({
    // Cast: the pacer is reset whenever `current` goes (`drop`), so no frame outlives its socket.
    send: (frame) => (current as Conn).socket.send(encodeFrame(frame)),
    timers,
  });

  /** Reads a token; `undefined` when it is locked or unavailable. */
  async function acquireToken(): Promise<Token | undefined> {
    const result: TokenResult = await tokens.getToken();
    return result.kind === "ok"
      ? { accessToken: result.accessToken, expiresAtMs: result.expiresAtMs }
      : undefined;
  }

  async function connect(): Promise<void> {
    if (stopped) return;
    // Before the socket: a locked or unavailable token opens nothing, and `auth` has its token the
    // moment `welcome` arrives, well inside the 10 s the gateway allows.
    const token = await acquireToken();
    if (stopped) return; // a stop overtook the wait
    if (token === undefined) {
      emit({ type: "offline", cause: reachability.current.cause ?? "offline" });
    } else {
      open(token);
    }
  }

  function open(token: Token): void {
    emit({ type: "connecting" });
    const c: Conn = {
      socket: UNOPENED,
      phase: "connecting",
      opened: false,
      token,
      authId: undefined,
    };
    current = c;
    topicsPerRequest = 1;
    minThrottleMs = undefined;
    try {
      c.socket = createSocket(url, F.SUBPROTOCOLS, {
        open: () => onOpen(c),
        message: (data) => onMessage(c, data),
        close: () => drop(c),
      });
    } catch {
      drop(c);
    }
  }

  function onOpen(c: Conn): void {
    if (c !== current) return;
    c.opened = true;
    c.phase = "hello";
    reachability.recordSuccess();
    const { version, shell, locale } = client;
    pacer.enqueue(F.hello(nextId(), { client_version: version, shell, locale, clock_ms: wall() }));
  }

  function onMessage(c: Conn, data: unknown): void {
    if (c !== current) return;
    const started = timers.now();
    const frame = decodeFrame(data);
    const decodeMs = timers.now() - started;
    if (frame.t === "decode_error") {
      counters.malformedFrames += 1;
      hooks.malformed(frame);
      return;
    }
    switch (frame.t) {
      case "welcome":
        return onWelcome(c, frame);
      case "auth_ok":
        return onAuthOk(c, frame);
      case "bye":
        return;
      case "ping":
        // C6: answered at once, so well inside the 10 s; exempt from the rate limit after `auth_ok`
        pacer.enqueue(F.pong(frame.id ?? nextId(), wall()));
        return;
      case "pong":
      case "permission_change": // liveness only; no state the client keeps (S5's concern)
        return;
      case "err":
        onErr(c, frame);
        hooks.frame(frame, decodeMs);
        return;
      default:
        hooks.frame(frame, decodeMs);
    }
  }

  function onWelcome(c: Conn, frame: ControlOf<"welcome">): void {
    if (c.phase !== "hello") return;
    const { connection_id: connectionId, limits } = frame.p;
    topicsPerRequest = limits.max_topics_per_request;
    minThrottleMs = limits.min_throttle_ms;
    emit({ type: "welcome", connectionId });
    const { token } = c;
    c.token = undefined; // from here on it lives in the `auth` frame alone
    if (token === undefined) return abandon(c, CLOSE_AUTH_REFUSED, "no_token");
    c.phase = "auth";
    sendAuth(c, token.accessToken);
  }

  function sendAuth(c: Conn, accessToken: string): void {
    c.authId = nextId();
    pacer.enqueue(F.auth(c.authId, accessToken));
  }

  function onAuthOk(c: Conn, frame: ControlOf<"auth_ok">): void {
    if (c.authId === undefined) return; // nobody asked
    const first = c.phase === "auth";
    c.authId = undefined;
    if (first) {
      c.phase = "ready";
      reachability.recordSuccess();
      pacer.markAuthenticated();
    }
    emit({ type: "auth_ok", killSwitch: frame.p.kill_switch });
    if (first) hooks.ready();
  }

  /** The gateway refused an `auth` of ours: the connection is over (4.3). */
  function onErr(c: Conn, frame: ControlOf<"err">): void {
    if (frame.id === undefined || frame.id !== c.authId) return;
    c.authId = undefined;
    if (c.phase === "auth") abandon(c, CLOSE_AUTH_REFUSED, "auth_refused");
  }

  /** The client ends the connection (a silent server, a refused `auth`, a stop): the socket's own close can take as long as a dead network lets it, so the connection is over now. */
  function abandon(c: Conn, code: number, reason: string): void {
    try {
      c.socket.close(code, reason);
    } catch {
      // already closing: the connection is over either way
    }
    drop(c);
  }

  /**
   * The connection is over, whoever ended it. Everything it taught is void (9.3: there is no
   * session resumption), and the close policy says what comes next (4.4, 9.2).
   */
  function drop(c: Conn): void {
    if (c !== current) return;
    current = undefined;
    c.token = undefined;
    pacer.reset();
    hooks.down();
    if (stopped) return;
    if (!c.opened) reachability.recordFailure();
    emit({ type: "offline", cause: reachability.current.cause ?? "offline" });
  }

  return {
    start() {
      if (started) return;
      started = true;
      void connect();
    },
    stop() {
      if (stopped) return;
      stopped = true;
      if (current !== undefined) abandon(current, CLOSE_STOP, "client_stop");
    },
    send(frame) {
      if (current?.phase === "ready") pacer.enqueue(frame);
    },
    nextId,
    get ready() {
      return current?.phase === "ready";
    },
    get topicsPerRequest() {
      return topicsPerRequest;
    },
    get minThrottleMs() {
      return minThrottleMs;
    },
    counters,
  };
}
