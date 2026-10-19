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
  /** What a refused `auth` is answered with, when it is not `auth_failed`: an error that does not blame the token. */
  readonly authRefusal?: string;
  /** `auth_ok` echoes this id instead of the `auth` frame's: an answer that is not for it. */
  readonly authOkId?: string;
  /** This many server `ping`s arrive before `welcome`: a server that pings in a flood. */
  readonly pingsBeforeWelcome?: number;
  /** `welcome` leaves out `clock_skew_ms` (it is optional, 4.2). */
  readonly omitSkew?: boolean;
  /** Every `sub_ok` result says `snapshot_forced` (7.6). */
  readonly forceSnapshots?: boolean;
  /**
   * Replies of these types are held back until `releaseHeld()`, in the order they were made: what the
   * client sent meanwhile overtakes them. A held `sub_ok` takes the initial snapshots with it, and a
   * `sub` refused (whole, or `client_rate_limited`) its `err`.
   */
  readonly hold?: readonly ("sub_ok" | "unsub_ok" | "ctl_ok")[];
  /** A second refusal does not close the connection (`deny`): a gateway that does not follow 8.5. */
  readonly keepsDenying?: boolean;
  /** Every `effective` carries more values than options can hold (the registry's limit): a broken or hostile server. */
  readonly bloatEffective?: boolean;
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
  /** The subscriptions the server holds for this client, `system` included. */
  subs(): { ch: string; rs: string | undefined; id: string; seq: number; effective: Json }[];
  /** One `d` with the next number of a subscription; `extra` overrides envelope fields (`e: "b64"` for a binary body). */
  delta(ch: string, p?: Json | string, rs?: string, extra?: Json): void;
  /** A number the client never sees: the next `d` shows a gap. */
  skip(ch: string, rs?: string): void;
  /** A `snap` the server sends unasked (7.4). */
  snap(ch: string, reason: string, rs?: string, extra?: Json): void;
  /** The held replies go out, in the order they were made: the first `n`, else all of them. */
  releaseHeld(n?: number): void;
  /** `revoked`, and the subscription ends with it (a narrowing that keeps accounts does not end it, 9.5). */
  revoke(ch: string, reason: string, extra?: Json): void;
  /** `revoked` of one stream alone, as 9.5 names it (`sub_id`, and `rs` on a replay one): it ends the subscription as `revoke` does. */
  revokeStream(ch: string, rs: string | undefined, reason: string, extra?: Json): void;
}

interface Sub {
  readonly ch: string;
  readonly rs: string | undefined;
  readonly id: string;
  seq: number;
  /** What the client asked for, explicitly: the effective options are derived from it (a heatmap's throttle follows its bucket until one is asked for). */
  opts: Json;
  effective: Json;
  readonly resyncs: number[];
}

const SERVER_PING = "s-hb-";
/** The reply a request of each type is answered with: a denial is held back with them (`hold`). */
const REPLY_OF: Readonly<Record<string, "sub_ok" | "unsub_ok" | "ctl_ok" | undefined>> = {
  sub: "sub_ok",
  unsub: "unsub_ok",
  ctl: "ctl_ok",
};
const FAMILY_THROTTLE: Readonly<Record<string, number>> = { book: 50, trades: 100 };
const MAX_WINDOW_SECONDS = 300;
const UUID = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const familyOf = (ch: string): string => ch.split(".", 1)[0] ?? ch;
const keyOf = (ch: string, rs?: string): string => `${ch}#${rs ?? "live"}`;
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
  let denials = 0;
  let rebuildsToRefuse = 0;
  let ctlsToRefuse = 0;
  let subsToFail = 0;
  let snapsWithheld = false;
  let unsubsToFail = 0;
  const refusedTopics = new Set<string>();
  const now = () => Date.now() + skewMs;

  /** What `sub_ok.effective` says: the options after the clamps (5.2), a heatmap's throttle following its bucket (6.1). */
  function effectiveOf(ch: string, opts: Json): Json {
    const bucket = familyOf(ch) === "heatmap" ? Number(opts["time_bucket_ms"] ?? 500) : undefined;
    const asked = Number(opts["throttle_ms"] ?? bucket ?? FAMILY_THROTTLE[familyOf(ch)] ?? 250);
    return {
      ...opts,
      ...(bucket !== undefined && { time_bucket_ms: bucket }),
      // this server keeps at most 5 minutes of a heatmap
      ...(opts["window_seconds"] !== undefined && {
        window_seconds: Math.min(Number(opts["window_seconds"]), MAX_WINDOW_SECONDS),
      }),
      ...(options.bloatEffective === true && { junk: Array.from({ length: 2_000 }, (_, i) => i) }),
      throttle_ms: Math.max(asked, limits.min_throttle_ms),
    };
  }

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

    const subs = new Map<string, Sub>();
    const held: (() => void)[] = [];
    /** A reply, now, or when the test lets the held ones go. */
    const later = (t: "sub_ok" | "unsub_ok" | "ctl_ok", go: () => void) => {
      if (options.hold?.includes(t) === true) held.push(go);
      else go();
    };
    const answer = (t: "unsub_ok" | "ctl_ok", frame: Json, id: unknown) =>
      later(t, () => reply(t, frame, id));
    let subIds = 0;
    const payloadOf = (ch: string): Json =>
      ch === "system"
        ? { kind: "health", health: "healthy", kill_switch: { engaged: false, scope: "global" } }
        : { price_scale: 1, qty_scale: 1, stale: false };
    const emitSnap = (sub: Sub, reason: string, extra: Json = {}, unasked = false) =>
      snapsWithheld && !unasked
        ? undefined
        : send({
            t: "snap",
            ch: sub.ch,
            s: (sub.seq += 1),
            e: "j",
            p: payloadOf(sub.ch),
            meta: { reason, source: sub.rs === undefined ? "live" : "replay" },
            ...(sub.rs !== undefined && { rs: sub.rs }),
            ...extra,
          });
    /** The replay session a request names, as 7.5 reads it: none (or `null`) is the live stream, a uuid is that session, anything else is refused. */
    const sessionOf = (frame: Json): { rs: string | undefined } | undefined => {
      const rs = frame["rs"];
      if (rs === undefined || rs === null) return { rs: undefined };
      return typeof rs === "string" && UUID.test(rs) ? { rs: rs.toLowerCase() } : undefined;
    };
    /** What names the stream in a reply (5.2 to 5.4): its `sub_id`, and `rs` on a replay one. */
    const namedBy = (sub: Sub): Json => ({ ...(sub.rs !== undefined && { rs: sub.rs }) });
    /**
     * `ctl` and `resync` reach the subscription of their `ch` in the session they name, or the live one (since #3218 the
     * gateway never falls back to a replay one): a bad `rs` is `invalid_options`, a stream that is not there
     * `not_subscribed`, and a `resync` pinned to another stream's `sub_id` too; the error carries the `ch` and a uuid `rs`.
     */
    const resolve = (frame: Json): Sub | undefined => {
      const session = sessionOf(frame);
      const ch = frame["ch"];
      if (session === undefined) {
        reply(
          "err",
          { ch, p: { code: "invalid_options", message: "rs", field: "rs" } },
          frame["id"],
        );
        return undefined;
      }
      const sub = subs.get(keyOf(String(ch), session.rs));
      const pin = asJson(frame["p"])["sub_id"];
      if (sub === undefined || (pin !== undefined && pin !== null && pin !== sub.id)) {
        const echo = session.rs === undefined ? {} : { rs: session.rs };
        reply("err", { ch, ...echo, p: { code: "not_subscribed", message: "no" } }, frame["id"]);
        return undefined;
      }
      return sub;
    };
    const open1 = (ch: string, rs: string | undefined, opts: Json): Sub => {
      const sub: Sub = {
        ch,
        rs,
        id: `s_${(subIds += 1)}`,
        seq: 0,
        opts,
        effective: effectiveOf(ch, opts),
        resyncs: [],
      };
      subs.set(keyOf(ch, rs), sub);
      return sub;
    };

    const onSub = (frame: Json) => {
      if (subsToFail > 0) {
        subsToFail -= 1; // a malformed or over-long sub is answered by an err, not a sub_ok (5.2)
        return later("sub_ok", () =>
          reply(
            "err",
            { p: { code: "invalid_options", message: "refused", field: "topics" } },
            frame["id"],
          ),
        );
      }
      const p = asJson(frame["p"]);
      const topics = (p["topics"] as Json[]) ?? [];
      if (topics.length > limits.max_topics_per_request) {
        problems.push(`a sub of ${topics.length} topics, over max_topics_per_request`);
        return reply("err", { p: { code: "too_many_topics", message: "too many" } }, frame["id"]);
      }
      const rs = typeof p["replay_session_id"] === "string" ? p["replay_session_id"] : undefined;
      const made: Sub[] = [];
      const results = topics.map((entry) => {
        const ch = String(entry["ch"]);
        if (refusedTopics.has(ch))
          return { ch, ok: false, error: { code: "forbidden", message: "refused" } };
        if (subs.has(keyOf(ch, rs))) {
          problems.push(`${ch} subscribed twice`);
          return { ch, ok: false, error: { code: "duplicate_subscription", message: "twice" } };
        }
        const sub = open1(ch, rs, asJson(entry["opts"]));
        made.push(sub);
        return {
          ch,
          ok: true,
          sub_id: sub.id,
          ...namedBy(sub),
          snapshot_pending: true,
          effective: sub.effective,
          ...(options.forceSnapshots === true && { snapshot_forced: true }),
        };
      });
      later("sub_ok", () => {
        reply("sub_ok", { p: { results } }, frame["id"]);
        for (const sub of made) emitSnap(sub, "initial");
      });
    };
    /** 5.3 (#3218): an `unsub` ends the stream of each entry's `ch` in the session it names, or the live one; `system` stays. */
    const onUnsub = (frame: Json) => {
      if (unsubsToFail > 0) {
        unsubsToFail -= 1; // a malformed unsub is refused whole, and nothing is unsubscribed (5.3)
        return reply(
          "err",
          { p: { code: "invalid_options", message: "refused", field: "topics" } },
          frame["id"],
        );
      }
      const session = sessionOf(frame);
      if (session === undefined) {
        return reply(
          "err",
          { p: { code: "invalid_options", message: "rs", field: "rs" } },
          frame["id"],
        );
      }
      const chs = asJson(frame["p"])["topics"] as string[];
      const results = chs.map((ch) => {
        if (ch === "system") return { ch, ok: false };
        const sub = subs.get(keyOf(ch, session.rs));
        if (sub === undefined) return { ch, ok: true, noop: true };
        subs.delete(keyOf(ch, session.rs));
        return { ch, ok: true, ended: [{ sub_id: sub.id, ...namedBy(sub) }] };
      });
      answer("unsub_ok", { p: { results } }, frame["id"]);
    };
    const onCtl = (frame: Json) => {
      const sub = resolve(frame);
      if (sub === undefined) return;
      const asked = asJson(frame["p"]);
      const rebucketed =
        asked["time_bucket_ms"] !== undefined &&
        asked["time_bucket_ms"] !== sub.effective["time_bucket_ms"];
      if ((rebucketed && rebuildsToRefuse > 0) || ctlsToRefuse > 0) {
        if (rebucketed && rebuildsToRefuse > 0) rebuildsToRefuse -= 1;
        else ctlsToRefuse -= 1;
        // the rebuild budget (SR-193, 5.4): nothing is applied and no snapshot follows
        return later("ctl_ok", () =>
          reply(
            "err",
            { ch: sub.ch, ...namedBy(sub), p: { code: "resync_rate_limited", message: "budget" } },
            frame["id"],
          ),
        );
      }
      sub.opts = { ...sub.opts, ...asked };
      sub.effective = effectiveOf(sub.ch, sub.opts);
      // as the gateway echoes it (5.4): what this `ctl` changed, and the throttle, not every option
      const echoed = Object.entries(sub.effective).filter(
        ([k]) => k in asked || k === "throttle_ms",
      );
      answer(
        "ctl_ok",
        {
          ch: sub.ch,
          ...namedBy(sub),
          p: {
            sub_id: sub.id,
            effective: Object.fromEntries(echoed),
            ...(rebucketed && { resnapshot: true }),
          },
        },
        frame["id"],
      );
      if (rebucketed) emitSnap(sub, "reconfigure");
    };
    const onResync = (frame: Json) => {
      const sub = resolve(frame);
      if (sub === undefined) return;
      const at = performance.now();
      sub.resyncs.push(at);
      if (sub.resyncs.filter((stamp) => at - stamp < 60_000).length > 5)
        problems.push(`more than 5 resyncs of ${sub.ch} in a minute`);
      emitSnap(sub, "client_resync");
    };

    /** The gateway's own `dispatch`: size, rate limit, order, then the handler. */
    const dispatch = (frame: Json) => {
      const t = String(frame["t"]);
      const exempt = t === "pong" && authenticated;
      const at = performance.now();
      if (!exempt && denials > 0) {
        denials -= 1; // refused as the gateway refuses, though the client was within its limits
        strikes += 1;
        if (strikes > 1 && options.keepsDenying !== true) {
          return bye("client_rate_limited", 4429, { retry_after_ms: 1000 });
        }
        const refuse = () =>
          reply("err", { p: { code: "client_rate_limited", message: "rate" } }, frame["id"]);
        const replyType = REPLY_OF[t];
        return replyType === undefined ? refuse() : later(replyType, refuse);
      }
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
        for (let i = 0; i < (options.pingsBeforeWelcome ?? 0); i += 1) {
          send({ t: "ping", id: `${SERVER_PING}pre-${i}`, p: { server_ms: now() } });
        }
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
        const code = options.authRefusal ?? "auth_failed";
        reply("err", { p: { code, message: "refused" } }, frame["id"]);
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
          options.authOkId ?? frame["id"],
        );
        if (!subs.has("system#live")) emitSnap(open1("system", undefined, {}), "initial"); // attached at `auth_ok` (6.2)
      } else if (t === "ping") {
        reply("pong", { p: { server_ms: now() } }, frame["id"]);
      } else if (!authenticated && t !== "pong") {
        problems.push(`${t} before auth_ok`);
      } else if (t === "sub") {
        onSub(frame);
      } else if (t === "unsub") {
        onUnsub(frame);
      } else if (t === "ctl") {
        onCtl(frame);
      } else if (t === "resync") {
        onResync(frame);
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
      releaseHeld: (n) => held.splice(0, n ?? held.length).forEach((send) => send()),
      subs: () =>
        [...subs.values()].map(({ ch, rs, id, seq, effective }) => ({
          ch,
          rs,
          id,
          seq,
          effective,
        })),
      delta(ch, p = {}, rs, extra = {}) {
        const sub = subs.get(keyOf(ch, rs));
        if (sub !== undefined) {
          const rsField = rs === undefined ? {} : { rs };
          send({ t: "d", ch, s: (sub.seq += 1), e: "j", p, ...rsField, ...extra });
        }
      },
      skip(ch, rs) {
        const sub = subs.get(keyOf(ch, rs));
        if (sub !== undefined) sub.seq += 1;
      },
      snap(ch, reason, rs, extra) {
        const sub = subs.get(keyOf(ch, rs));
        if (sub !== undefined) emitSnap(sub, reason, extra, true);
      },
      revoke(ch, reason, extra = {}) {
        const narrowed =
          reason === "account_scope_changed" && extra["resubscribe_allowed"] === true;
        const hit = [...subs.values()].filter(
          (sub) => sub.ch === ch && (reason !== "replay_session_ended" || sub.rs !== undefined),
        );
        // one frame for each stream it reaches, naming it (5.2); one with no name for a `ch` nobody holds
        if (hit.length === 0) send({ t: "revoked", ch, p: { reason, message: reason, ...extra } });
        for (const sub of hit) {
          const p = { reason, message: reason, sub_id: sub.id, ...extra };
          send({ t: "revoked", ch, ...namedBy(sub), p });
          if (!narrowed) subs.delete(keyOf(sub.ch, sub.rs));
        }
      },
      revokeStream(ch, rs, reason, extra = {}) {
        const sub = subs.get(keyOf(ch, rs));
        if (sub === undefined) return;
        const narrowed =
          reason === "account_scope_changed" && extra["resubscribe_allowed"] === true;
        const p = { reason, message: reason, sub_id: sub.id, ...extra };
        send({ t: "revoked", ch, ...namedBy(sub), p });
        if (!narrowed) subs.delete(keyOf(ch, rs));
      },
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
    /** The next `n` frames the client sends are refused `client_rate_limited`, as if it were over its limit. */
    deny(n: number) {
      denials = n;
    },
    /** The next `n` `ctl`s that would re-snapshot are refused `resync_rate_limited` (SR-193): nothing is applied. */
    refuseRebuilds(n: number) {
      rebuildsToRefuse = n;
    },
    /** The next `n` `ctl`s of any kind are refused `resync_rate_limited`: a server that does so to a throttle too. */
    refuseCtls(n: number) {
      ctlsToRefuse = n;
    },
    /** The snapshots a `sub`, a `resync` or a retune would bring are not sent; `conn.snap(ch, reason)` still sends one. */
    withholdSnaps(on: boolean) {
      snapsWithheld = on;
    },
    /** The next `n` `unsub` frames are refused whole, with an `err` and no `unsub_ok`. */
    failUnsubs(n: number) {
      unsubsToFail = n;
    },
    /** The next `n` `sub` frames are refused whole, with an `err` and no `sub_ok`. */
    failSubs(n: number) {
      subsToFail = n;
    },
    /** A `sub` of `ch` is answered `forbidden`. */
    refuseTopic(ch: string) {
      refusedTopics.add(ch);
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
