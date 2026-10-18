// E17-T04 S4 (23 4, 8.5, 9; C1, C6, C7): the connection. It owns one socket at a time and the
// whole life of it: `hello`, `auth` through the `TokenSource`, an in-place re-`auth` before the token
// expires, heartbeats, the pacing of everything the client sends, and the reconnect schedule after a
// close. It knows nothing of streams: the frames that are not its own go to the engine through
// `hooks`. Worker-agnostic: the socket, the clock, the timers and the random source are injected.
import type { TokenResult, TokenSource } from "../api";
import { handleWsError } from "../errorHandler";
import { decideClose } from "../policy/closePolicy";
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
import type { EngineEvent, OfflineCause } from "../state/types";
import { backoffDelayWithJitter } from "../../../shell/bootstrap/backoff";
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
  /** A queued `ctl` was merged into a newer one (8.5): its `id` is never sent, so no reply is due for it. */
  superseded?(id: string): void;
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
  /** The server's clock minus ours (`welcome`, 4.2): `undefined` until `welcome` of this socket. */
  readonly clockSkewMs: number | undefined;
  /** `bye.hint.most_expensive_topics` of the last close (8.4): kept, never acted on. */
  readonly slowConsumerHint: readonly string[];
  readonly counters: { readonly reconnects: number; readonly malformedFrames: number };
}

/** 23 3.6: the largest frame the gateway sends. A longer message is not parsed. */
export const MAX_INBOUND_CHARS = 4 * 1024 * 1024;
/** From the socket's creation to `auth_ok`: the gateway gives up on an unauthenticated one after 10 s (4.3). */
export const HANDSHAKE_TIMEOUT_MS = 15_000;
/** How long `TokenSource.getToken` may take before it counts as `unavailable`. */
export const TOKEN_WAIT_MS = 10_000;
/** 4.3: the access token is renewed at `expires_at - 60 s`. */
export const REAUTH_LEAD_MS = 60_000;
/** A token that expires sooner, or a source that keeps handing out the same one, never makes a hot loop. */
export const REAUTH_MIN_DELAY_MS = 5_000;
export const REAUTH_RETRY_MS = 5_000;
/** 13.4 `auth`: the token is 20 to 4 096 characters. The cap also keeps `auth` under the 8 KiB frame limit before `auth_ok` (3.6), or the gateway closes 1009. */
export const MIN_TOKEN_LENGTH = 20;
export const MAX_TOKEN_LENGTH = 4096;
/** `welcome` is server-controlled: a zero interval would be a hot loop of `ping`s, and a timer past 2^31 ms fires at once. */
const MIN_HEARTBEAT_MS = 1_000;
const MAX_HEARTBEAT_MS = 300_000;
const MAX_TIMER_MS = 2 ** 31 - 1;
/** Pongs sent before `auth_ok`: there a `pong` counts against the rate limit like any frame (8.5), and the gateway drops it. */
const MAX_PRE_AUTH_PONGS = 3;
/** Application close codes (3000-4999) for the connections the client ends itself. */
const CLOSE_STOP = 1000;
const CLOSE_TIMEOUT = 4000;
/** What the client closes with when the server breaks the protocol (4.4). */
const CLOSE_PROTOCOL_ERROR = 1002;
/** What the close policy judges of a connection that was lost without a close frame (RFC 6455): the ordinary backoff follows. */
const CLOSE_LOST = 1006;
/** What a refused `auth` is treated as: the gateway's own code for it (4.4). */
const CLOSE_AUTH_REFUSED = 4401;
/** What an `auth` answered with an error that does not blame the token is treated as: the connection ends and the token stays. */
const CLOSE_AUTH_ERROR = 4001;
/** 10.3: the codes that say the token itself is no good. Any other error that answers an `auth` (a busy gateway, a fault) leaves it alone. */
const TOKEN_REFUSED: ReadonlySet<string> = new Set(["auth_failed", "token_expired"]);
const MAX_HINT_TOPICS = 5;
const MAX_TOPIC_LENGTH = 120;

type Token = { readonly accessToken: string; readonly expiresAtMs: number };
type Bye = F.ControlPayloads["bye"];

/** The socket being built or lived on; at most one. Its callbacks check they still own `current`. */
interface Conn {
  socket: EngineSocket;
  /** `connecting`: not open. `hello`: `welcome` due. `auth`: `auth_ok` due. */
  phase: "connecting" | "hello" | "auth" | "ready";
  opened: boolean;
  /** Fetched before the socket opened, held until the `auth` frame is built: the only place it goes. */
  token: Token | undefined;
  /** The server's clock minus ours, from `welcome`. */
  skewMs: number;
  heartbeatMs: number;
  timeoutMs: number;
  /** `token_expires_at_ms` of the last `auth_ok`: the server's clock. */
  expiresAtMs: number;
  bye: Bye | undefined;
  lastInboundAt: number;
  /** The `auth` whose `auth_ok` (or error) is due. */
  authId: string | undefined;
  /** Pongs sent before `auth_ok` (`MAX_PRE_AUTH_PONGS`). */
  prePongs: number;
  handshakeTimer: unknown;
  heartbeatTimer: unknown;
  watchdogTimer: unknown;
  reauthTimer: unknown;
}

/**
 * What `Conn.socket` holds until the factory returns: the factory's callbacks need the `Conn`, and
 * a socket calls them from a later task, so nothing touches this before it is replaced.
 */
const UNOPENED = {} as EngineSocket;

const clampMs = (ms: number): number => Math.min(Math.max(ms, MIN_HEARTBEAT_MS), MAX_HEARTBEAT_MS);
const bounded = (v: unknown): v is string => typeof v === "string" && v.length <= MAX_TOPIC_LENGTH;

/** The hint is the server's and the codec does not look inside it: only a list of short names is kept. */
function hintOf(bye: Bye): readonly string[] {
  const hint: unknown = bye.hint?.most_expensive_topics;
  return Array.isArray(hint) ? hint.filter(bounded).slice(0, MAX_HINT_TOPICS) : [];
}

export function createConnection(options: ConnectionOptions): Connection {
  const { url, createSocket, tokens, client, timers, wall, random, reachability, emit, hooks } =
    options;
  const nextId = F.createIdSource();
  const counters = { reconnects: 0, malformedFrames: 0 };
  let slowConsumerHint: readonly string[] = [];
  let topicsPerRequest = 1;
  let minThrottleMs: number | undefined;
  let current: Conn | undefined;
  let attempt = 0;
  let started = false;
  let stopped = false;
  let reconnectTimer: unknown;

  const pacer = createOutboundPacer({
    // Cast: the pacer is reset whenever `current` goes (`drop`), so no frame outlives its socket.
    send: (frame) => (current as Conn).socket.send(encodeFrame(frame)),
    onSuperseded: (id) => hooks.superseded?.(id),
    timers,
  });

  const unavailable: TokenResult = { kind: "unavailable" };
  /**
   * The `getToken` call that has not answered yet. A source that hangs is waited for again on each
   * retry and never asked again meanwhile: a refresh token is single-use, so two calls in flight
   * would spend it twice. It is forgotten once it answers, whatever it says, and when its
   * `epoch` is over: a connection ended, so what it answers late is not what the next one needs.
   */
  let tokenCall: { readonly epoch: number; readonly answer: Promise<TokenResult> } | undefined;
  let tokenEpoch = 0;

  function askToken(): Promise<TokenResult> {
    if (tokenCall?.epoch === tokenEpoch) return tokenCall.answer;
    // a source that throws instead of rejecting is unavailable too: the executor's throw rejects the promise
    const answer = new Promise<TokenResult>((resolve) => resolve(tokens.getToken())).catch(
      (): TokenResult => unavailable,
    );
    const call = { epoch: tokenEpoch, answer };
    tokenCall = call;
    void answer.then(() => {
      if (tokenCall === call) tokenCall = undefined;
    });
    return answer;
  }

  /** Reads a token within `TOKEN_WAIT_MS`; `undefined` when it is locked, unavailable or unusable. */
  async function acquireToken(): Promise<Token | undefined> {
    const result = await new Promise<TokenResult>((resolve) => {
      const waiting = timers.setTimeout(() => resolve(unavailable), TOKEN_WAIT_MS);
      void askToken().then((answer) => {
        timers.clearTimeout(waiting);
        resolve(answer);
      });
    });
    if (result.kind !== "ok") return undefined;
    const { accessToken, expiresAtMs } = result;
    const usable =
      typeof accessToken === "string" &&
      accessToken.length >= MIN_TOKEN_LENGTH &&
      accessToken.length <= MAX_TOKEN_LENGTH &&
      Number.isFinite(expiresAtMs) &&
      expiresAtMs > wall();
    return usable ? { accessToken, expiresAtMs } : undefined;
  }

  async function connect(): Promise<void> {
    if (stopped) return;
    // Before the socket: a locked or unavailable token opens nothing, and `auth` has its token the
    // moment `welcome` arrives, well inside the 10 s the gateway allows.
    const token = await acquireToken();
    if (stopped) return; // a stop overtook the wait
    if (token === undefined) {
      attempt += 1;
      scheduleReconnect(
        backoffDelayWithJitter(attempt, random),
        reachability.current.cause ?? "offline",
      );
    } else {
      open(token);
    }
  }

  function scheduleReconnect(delayMs: number, offline?: OfflineCause): void {
    counters.reconnects += 1;
    if (offline === undefined) {
      emit({ type: "reconnecting", attempt, nextAttemptAtMs: wall() + delayMs });
    } else {
      emit({ type: "offline", cause: offline });
    }
    reconnectTimer = timers.setTimeout(() => {
      reconnectTimer = undefined;
      void connect();
    }, delayMs);
  }

  function open(token: Token): void {
    emit({ type: "connecting" });
    const c: Conn = {
      socket: UNOPENED,
      phase: "connecting",
      opened: false,
      token,
      skewMs: 0,
      heartbeatMs: MAX_HEARTBEAT_MS,
      timeoutMs: MAX_HEARTBEAT_MS,
      expiresAtMs: 0,
      bye: undefined,
      lastInboundAt: timers.now(),
      authId: undefined,
      prePongs: 0,
      handshakeTimer: undefined,
      heartbeatTimer: undefined,
      watchdogTimer: undefined,
      reauthTimer: undefined,
    };
    current = c;
    topicsPerRequest = 1;
    minThrottleMs = undefined;
    c.handshakeTimer = timers.setTimeout(
      () => abandon(c, CLOSE_TIMEOUT, "handshake_timeout"),
      HANDSHAKE_TIMEOUT_MS,
    );
    try {
      c.socket = createSocket(url, F.SUBPROTOCOLS, {
        open: () => onOpen(c),
        message: (data) => onMessage(c, data),
        close: (code) => drop(c, code),
      });
    } catch {
      drop(c, CLOSE_LOST);
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
    c.lastInboundAt = timers.now();
    if (typeof data === "string" && data.length > MAX_INBOUND_CHARS) {
      // 3.6: the gateway never sends this much. A frame dropped unread would leave its stream in a state no
      // gap shows, so the peer has broken the protocol: the socket is closed 1002, and the connection is lost like
      // any other (what it taught is void, and the reconnect follows the ordinary backoff).
      counters.malformedFrames += 1;
      return abandon(c, CLOSE_PROTOCOL_ERROR, "frame_too_big", CLOSE_LOST);
    }
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
        c.bye = frame.p; // the close that follows is judged with it (4.4)
        slowConsumerHint = hintOf(frame.p);
        return;
      case "ping":
        return answerPing(c, frame.id);
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

  /**
   * C6: a server `ping` is answered with a `pong` at once, and from `auth_ok` on it is exempt from the
   * rate limit. Before it a `pong` counts like any frame (8.5) and waits its turn behind `hello` and
   * `auth`, so only a few are sent: a server that pings in a flood cannot hold `auth` back.
   */
  function answerPing(c: Conn, id: string | undefined): void {
    if (c.phase !== "ready") {
      if (c.prePongs >= MAX_PRE_AUTH_PONGS) return;
      c.prePongs += 1;
    }
    pacer.enqueue(F.pong(id ?? nextId(), wall()));
  }

  function onWelcome(c: Conn, frame: ControlOf<"welcome">): void {
    if (c.phase !== "hello") return;
    const { connection_id: connectionId, heartbeat, limits, server_time_ms: serverMs } = frame.p;
    const skew = frame.p.clock_skew_ms;
    topicsPerRequest = limits.max_topics_per_request;
    minThrottleMs = limits.min_throttle_ms;
    c.skewMs = typeof skew === "number" && Number.isFinite(skew) ? skew : serverMs - wall();
    c.heartbeatMs = clampMs(heartbeat.interval_ms);
    c.timeoutMs = clampMs(heartbeat.timeout_ms);
    emit({ type: "welcome", connectionId });
    armWatchdog(c, c.timeoutMs);
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
    if (c.authId === undefined || frame.id !== c.authId) return; // nobody asked, or it answers another frame
    const first = c.phase === "auth";
    c.authId = undefined;
    c.expiresAtMs = frame.p.token_expires_at_ms;
    if (first) {
      c.phase = "ready";
      attempt = 0; // the backoff resets here, not when the socket opens: an open socket that fails auth is no success
      reachability.recordSuccess();
      pacer.markAuthenticated();
      timers.clearTimeout(c.handshakeTimer);
      c.handshakeTimer = undefined;
      armHeartbeat(c);
    }
    emit({ type: "auth_ok", killSwitch: frame.p.kill_switch });
    armReauth(c);
    if (first) hooks.ready();
  }

  /** The gateway refused an `auth` of ours, or a request: every `err` goes through the one mapping (10.3). */
  function onErr(c: Conn, frame: ControlOf<"err">): void {
    const { code, message, request_id: requestId } = frame.p;
    handleWsError({ t: "err", p: { code, message } });
    if (bounded(requestId)) emit({ type: "request_id", requestId });
    if (frame.id === undefined || frame.id !== c.authId) return;
    c.authId = undefined;
    // Only an error that blames the token spends a refresh (10.3); the rest of them leave a good one alone.
    const blamed = TOKEN_REFUSED.has(code);
    if (c.phase === "auth") {
      // 4401: the close policy refreshes the token before the reconnect.
      if (blamed) return abandon(c, CLOSE_AUTH_REFUSED, "auth_refused");
      return abandon(c, CLOSE_AUTH_ERROR, "auth_error");
    }
    if (blamed) tokens.invalidate(); // this token is bad, whatever else is true of it
    retryReauth(c);
  }

  /** 4.1: the token is renewed in place, on the same socket, `REAUTH_LEAD_MS` before the server's expiry (its clock, corrected by the skew). */
  function armReauth(c: Conn, minDelayMs = REAUTH_MIN_DELAY_MS): void {
    const due = c.expiresAtMs - c.skewMs - wall() - REAUTH_LEAD_MS;
    const delay = Math.min(Math.max(due, minDelayMs), MAX_TIMER_MS);
    c.reauthTimer = timers.setTimeout(() => void reauth(c), delay);
  }

  async function reauth(c: Conn): Promise<void> {
    c.reauthTimer = undefined;
    const token = await acquireToken();
    if (c !== current) return; // the connection ended while the token was fetched: never send it on another
    if (token === undefined) retryReauth(c);
    else sendAuth(c, token.accessToken);
  }

  /** The identity lasts until its token expires (4.3): keep asking until then; after it the gateway closes 4401 and the reconnect refreshes. */
  function retryReauth(c: Conn): void {
    if (wall() + c.skewMs < c.expiresAtMs) armReauth(c, REAUTH_RETRY_MS);
  }

  function armHeartbeat(c: Conn): void {
    c.heartbeatTimer = timers.setTimeout(() => {
      pacer.enqueue(F.ping(nextId(), wall()));
      armHeartbeat(c);
    }, c.heartbeatMs);
  }

  /** 9.1: no traffic at all for `timeout_ms` ends the connection. Checked lazily, so a message costs a timestamp, not a timer. */
  function armWatchdog(c: Conn, delayMs: number): void {
    c.watchdogTimer = timers.setTimeout(() => {
      const idle = timers.now() - c.lastInboundAt;
      if (idle >= c.timeoutMs) abandon(c, CLOSE_TIMEOUT, "heartbeat_timeout");
      else armWatchdog(c, c.timeoutMs - idle);
    }, delayMs);
  }

  /** The client ends the connection (a silent server, a refused `auth`, a stop): the socket's own close can take as long as a dead network lets it, so the connection is over now. */
  function abandon(c: Conn, code: number, reason: string, judgedAs = code): void {
    try {
      c.socket.close(code, reason);
    } catch {
      // already closing: the connection is over either way
    }
    drop(c, judgedAs); // what the peer is told is not always what the close policy judges
  }

  /**
   * The connection is over, whoever ended it. Everything it taught is void (9.3: there is no
   * session resumption), and the close policy says what comes next (4.4, 9.2).
   */
  function drop(c: Conn, code: number): void {
    if (c !== current) return;
    current = undefined;
    for (const timer of [c.handshakeTimer, c.heartbeatTimer, c.watchdogTimer, c.reauthTimer]) {
      if (timer !== undefined) timers.clearTimeout(timer);
    }
    tokenEpoch += 1; // a token still being fetched was for this connection
    c.token = undefined;
    pacer.reset();
    hooks.down();
    if (stopped) return;
    if (!c.opened) reachability.recordFailure();
    attempt += 1;
    const decision = decideClose({ code, bye: c.bye, attempt }, random);
    if (decision.fatal) {
      emit({ type: "offline", cause: "fatal", closeCode: code });
      return;
    }
    if (decision.refreshFirst) tokens.invalidate();
    // A socket that never opened found the backend unreachable; one that did was lost.
    const cause = c.opened ? undefined : (reachability.current.cause ?? "offline");
    scheduleReconnect(decision.delayMs, cause);
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
      if (reconnectTimer !== undefined) timers.clearTimeout(reconnectTimer);
      reconnectTimer = undefined;
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
    get clockSkewMs() {
      // `welcome` is what says it: before that the connection holds a placeholder of 0
      return current?.phase === "auth" || current?.phase === "ready" ? current.skewMs : undefined;
    },
    get slowConsumerHint() {
      return slowConsumerHint;
    },
    counters,
  };
}
