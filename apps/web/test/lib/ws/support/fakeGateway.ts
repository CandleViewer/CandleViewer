// A fake WebSocket and a stub of the gateway's behaviour (23 4-9, as built in `ws/gateway.py`) for the
// engine tests. Every client frame is checked against the schemas through the S1 harness, the
// gateway's own inbound limits are replayed on what arrives (30 in any second, 300 in any minute,
// `pong` exempt after `auth_ok`), and anything the client does that the gateway would punish is
// recorded in `problems`: a test ends with `expect(gateway.problems).toEqual([])`.
import { expect, onTestFinished } from "vitest";
import type { SocketFactory } from "../../../../src/lib/ws/core/connection";
import { validateClientFrame } from "./schemaHarness";

export type Json = Record<string, unknown>;

export interface FakeGatewayOptions {
  /** The server's clock minus the client's (`welcome.clock_skew_ms`). */
  readonly skewMs?: number;
  readonly heartbeat?: { readonly interval_ms: number; readonly timeout_ms: number };
  readonly limits?: Partial<Record<"max_topics_per_request" | "min_throttle_ms", number>>;
  /** How long the access token it accepts lives, from `auth_ok`. */
  readonly tokenTtlMs?: number;
  /** Nothing it says reaches the client: a network that is up but dead. */
  readonly silent?: boolean;
  /** The first `n` `auth` frames are refused with `auth_failed` (4.3). */
  readonly refuseAuths?: number;
  /** `welcome` leaves out `clock_skew_ms` (it is optional, 4.2). */
  readonly omitSkew?: boolean;
}

export interface FakeConn {
  readonly url: string;
  readonly protocols: readonly string[];
  /** When the client created it (`Date.now()`). */
  readonly at: number;
  /** Every frame the client sent, parsed, in order. */
  readonly received: Json[];
  readonly closedByClient: { readonly code: number; readonly reason: string } | undefined;
  readonly authenticated: boolean;
  /** The upgrade succeeds: the client's `open` fires. */
  accept(): void;
  /** One server frame. */
  send(frame: Json): void;
  /** One server message, as it stands (a frame that is not JSON, or too long). */
  raw(text: string): void;
  /** From now on nothing the server says reaches the client: a dead network. */
  mute(): void;
  /** `bye`, then the close frame (4.4). */
  bye(reason: string, code: number, extra?: Json): void;
  /** The transport ends: the client's `close` fires. */
  close(code: number): void;
  /** A `close` event of a socket the client already gave up on. */
  lateClose(code: number): void;
  /** A message of a socket the client already gave up on. */
  lateMessage(frame: Json): void;
  /** The client's frames of one type. */
  of(t: string): Json[];
}

const SERVER_PING = "s-hb-";
const asJson = (v: unknown): Json => (typeof v === "object" && v !== null ? (v as Json) : {});

export function createFakeGateway(options: FakeGatewayOptions = {}) {
  const { skewMs = 0, tokenTtlMs = 600_000 } = options;
  const heartbeat = options.heartbeat ?? { interval_ms: 15_000, timeout_ms: 45_000 };
  const limits = {
    max_subscriptions: 200,
    max_topics_per_request: 50,
    max_inbound_frame_bytes: 262_144,
    max_outbound_frame_bytes: 4_194_304,
    min_throttle_ms: 50,
    ...options.limits,
  };
  const conns: FakeConn[] = [];
  const problems: string[] = [];
  // every test that opens a gateway ends by asserting that nothing the client sent was invalid or punished
  onTestFinished(() => expect(problems).toEqual([]));
  let refusals = 0;
  let authsToRefuse = options.refuseAuths ?? 0;
  let serverPings = 0;
  const now = () => Date.now() + skewMs;

  const createSocket: SocketFactory = (url, protocols, events) => {
    const refused = refusals > 0;
    if (refused) refusals -= 1;
    const received: Json[] = [];
    const stamps: number[] = [];
    let strikes = 0;
    let authenticated = false;
    let open = false;
    let ended = false;
    let muted = options.silent === true;
    let closedByClient: { code: number; reason: string } | undefined;

    const raw = (text: string) => {
      if (!ended && !muted) events.message(text);
    };
    const send = (frame: Json) => raw(JSON.stringify({ ts: now(), ...frame }));
    const close = (code: number) => {
      if (ended) return;
      ended = true;
      events.close(code);
    };
    const reply = (t: string, frame: Json, id: unknown) =>
      send({ t, ...(typeof id === "string" && { id }), ...frame });
    const bye = (reason: string, code: number, extra: Json = {}) => {
      send({ t: "bye", p: { code, reason, message: reason, reconnect: true, ...extra } });
      close(code);
    };

    /** The gateway's own `dispatch`: size, rate limit, order, then the handler. */
    const dispatch = (frame: Json) => {
      const t = String(frame["t"]);
      const exempt = t === "pong" && authenticated;
      const at = performance.now();
      if (!exempt) {
        while (stamps[0] !== undefined && at - stamps[0] >= 60_000) stamps.shift();
        const lastSecond = stamps.filter((stamp) => at - stamp < 1000).length;
        if (lastSecond >= 30 || stamps.length >= 300) {
          problems.push(
            `rate: ${t} #${received.length} refused (${lastSecond}/s, ${stamps.length}/min)`,
          );
          strikes += 1;
          if (strikes > 1) return bye("client_rate_limited", 4429, { retry_after_ms: 1000 });
          return reply("err", { p: { code: "client_rate_limited", message: "rate" } }, frame["id"]);
        }
        stamps.push(at);
      }
      if (received.length === 1 && t !== "hello") problems.push(`first frame is ${t}, not hello`);
      if (t === "hello") {
        reply(
          "welcome",
          {
            p: {
              protocol: "cv.v1",
              encoding: "json",
              server_version: "test",
              connection_id: `ws_${conns.length}`,
              server_time_ms: now(),
              ...(options.omitSkew !== true && { clock_skew_ms: skewMs }),
              auth_required: true,
              auth_timeout_ms: 10_000,
              heartbeat,
              limits,
            },
          },
          frame["id"],
        );
      } else if (t === "auth" && authsToRefuse > 0) {
        authsToRefuse -= 1;
        reply("err", { p: { code: "auth_failed", message: "refused" } }, frame["id"]);
      } else if (t === "auth") {
        authenticated = true;
        reply(
          "auth_ok",
          {
            p: {
              user_id: "u1",
              roles: ["owner"],
              permissions: [],
              account_scope: [],
              session_id: "s1",
              token_expires_at_ms: now() + tokenTtlMs,
              kill_switch: { engaged: false, scope: "global" },
            },
          },
          frame["id"],
        );
      } else if (t === "ping") {
        reply("pong", { p: { server_ms: now() } }, frame["id"]);
      } else if (!authenticated && t !== "pong") {
        problems.push(`${t} before auth_ok`);
      }
    };

    const conn: FakeConn = {
      url,
      protocols,
      at: Date.now(),
      received,
      get closedByClient() {
        return closedByClient;
      },
      get authenticated() {
        return authenticated;
      },
      accept() {
        if (open || ended) return;
        open = true;
        events.open();
      },
      send,
      raw,
      mute() {
        muted = true;
      },
      bye,
      close,
      lateClose: (code) => events.close(code),
      lateMessage: (frame) => events.message(JSON.stringify({ ts: now(), ...frame })),
      of: (t) => received.filter((f) => f["t"] === t),
    };
    conns.push(conn);

    const socket = {
      send(data: string) {
        if (!open || ended) throw new Error("send on a socket that is not open");
        const frame = asJson(JSON.parse(data));
        const errors = validateClientFrame(frame as { t: string });
        if (errors.length > 0) problems.push(`${String(frame["t"])} invalid: ${errors.join("; ")}`);
        received.push(frame);
        dispatch(frame);
      },
      close(code: number, reason: string) {
        closedByClient = { code, reason };
        ended = true;
      },
    };
    // The upgrade takes one task; a refused connect never opens.
    queueMicrotask(() => (refused ? close(1006) : conn.accept()));
    return socket;
  };

  return {
    createSocket,
    conns,
    problems,
    /** The newest socket. */
    get latest(): FakeConn {
      const conn = conns.at(-1);
      if (conn === undefined) throw new Error("no socket was opened");
      return conn;
    },
    /** The next `n` connects fail before they open (unreachable). */
    refuse(n = 1) {
      refusals += n;
    },
    /** The next `n` `auth` frames, re-auths included, are refused. */
    refuseAuths(n: number) {
      authsToRefuse = n;
    },
    /** An unsolicited server `ping` (9.1). */
    ping(conn: FakeConn) {
      serverPings += 1;
      conn.send({ t: "ping", id: `${SERVER_PING}${serverPings}`, p: { server_ms: now() } });
    },
  };
}

export type FakeGateway = ReturnType<typeof createFakeGateway>;
