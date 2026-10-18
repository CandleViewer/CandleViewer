// E17-T04 S4 (23 5, 7.5, 9.3, 11; C2, C5): the engine. It composes the connection, the stream
// core (S2) and the reducer's events (S1b): the registry's `subscribe`/`unsubscribe`/`resync` become
// `sub`, `unsub` and `resync` frames, every reply is correlated to the stream its request was for
// (`to`), and after a reconnect every stream subscribes again in the 9.3 order. Worker-agnostic:
// everything platform-shaped is injected.
import type { ConsumerSpec, TokenSource, TopicFrame } from "../api";
import type { Timers } from "../policy/timers";
import { platformTimers } from "../policy/timers";
import { chunkTopics, type NonEmpty } from "../policy/outboundPacer";
import type { ControlOf, Inbound } from "../protocol/codec";
import * as F from "../protocol/frames";
import type { EngineEvent } from "../state/types";
import { ReachabilityTracker } from "../../../shell/bootstrap/reachability";
import {
  orderSubscriptionsForRestore,
  type SubscriptionPriority,
} from "../../../shell/bootstrap/subscriptionOrder";
import { createConnection, type Connection, type SocketFactory } from "./connection";
import { createResyncGuard } from "./resyncGuard";
import { topicKey } from "./sequencer";
import {
  createSubscriptionRegistry,
  type RegistryHost,
  type RequestScope,
  type StreamHandle,
} from "./subscriptions";

export type { EngineSocket, SocketEvents, SocketFactory } from "./connection";

export interface EngineSink {
  /** The reducer's input, in order: `reduce(state, event)`. */
  event(event: EngineEvent): void;
  /** One validated frame of a stream, in order (`RegistryHost.deliver`). Queueing and fan-out to tabs are the sink's. */
  deliver(ch: string, rs: string | undefined, frame: TopicFrame): void;
}

export interface EngineOptions {
  /** 2.1: `wss://host/api/v1/ws`. Never carries a token (4.3). */
  readonly url: string;
  readonly createSocket: SocketFactory;
  readonly tokens: TokenSource;
  readonly sink: EngineSink;
  readonly client: {
    readonly version: string;
    readonly shell: NonNullable<F.HelloPayload["shell"]>;
    readonly locale: string;
  };
  /** The clock and timers every policy runs on; defaults to the platform's. */
  readonly timers?: Partial<Timers> | undefined;
  /** Epoch milliseconds: `hello.clock_ms`, the clock skew and the token's expiry. Defaults to `Date.now`. */
  readonly wallClock?: (() => number) | undefined;
  readonly random?: (() => number) | undefined;
  /** Where the offline cause comes from (SCR-159); defaults to a new tracker. */
  readonly reachability?:
    Pick<ReachabilityTracker, "recordSuccess" | "recordFailure" | "current"> | undefined;
}

/** Events of the connection, for the diagnostics bundle (E04-S02). */
export interface EngineCounters {
  gaps: number;
  resyncsSent: number;
  resyncsDeferred: number;
  /** Reconnects scheduled (a refused token counts: it is a failed attempt too). */
  reconnects: number;
  forcedSnapshots: number;
  /** Inbound frames that could not be trusted: undecodable, or over the 4 MiB cap. */
  malformedFrames: number;
  /** Requests whose reply is still due (bounded: the oldest is forgotten past `LEDGER_MAX`). */
  pendingRequests: number;
  /** Subscriptions kept: wanted ones, and ones the server still holds after their last consumer left. */
  streams: number;
}

export interface WsEngine {
  /** Opens the first connection. Idempotent. */
  start(): void;
  /** A client stop: closes the socket, never reconnects, and forgets every stream. */
  stop(): void;
  /** `rs` selects a replay stream of the `ch` (23 11). `system` is implicit and shared. */
  consume(spec: ConsumerSpec, rs?: string | undefined): StreamHandle;
  /** `bye.hint.most_expensive_topics` of the last close (8.4): kept, never acted on. */
  readonly slowConsumerHint: readonly string[];
  /** A fresh snapshot of the counters. */
  readonly counters: EngineCounters;
}

const SYSTEM = "system";
/** Requests whose reply or error is still due, bounded (C-2.18): the oldest is forgotten first. */
export const LEDGER_MAX = 512;
/** 9.3: after the implicit `system`, these private families come first, in this order. */
const PRIVATE_FIRST: readonly string[] = ["orders", "positions", "executions", "wallet"];
const PRIORITY_RANK: Readonly<Record<SubscriptionPriority, number>> = {
  private: 0,
  focused: 1,
  other: 2,
};

interface Consumer {
  readonly spec: ConsumerSpec;
}

/** A subscription the engine keeps: `(ch, rs)`, whether the server holds it, and who wants it. */
interface Stream {
  readonly key: string;
  readonly ch: string;
  readonly rs: string | undefined;
  /** The first consumer's: its options go on the `sub`. */
  readonly spec: ConsumerSpec;
  readonly consumers: Set<Consumer>;
  handle: StreamHandle | undefined;
  /** A `sub` went out on this connection and no `unsub` since: the server has it. */
  held: boolean;
  /**
   * Which server subscription this is: it advances at every `sub` and `unsub` the engine sends for it
   * (0 before the first), and a new stream that takes over a held subscription keeps it. A reply is
   * for the subscription its request was sent for (`Request.gens`), and a reply for one that has
   * been let go or sent again since is an old one's: the reply scope (`rs`) alone cannot tell.
   */
  gen: number;
}

/**
 * A request whose reply or error is due: the stream its reply is for (`to`), the generation of
 * each stream it is about (`ch` to `Stream.gen`, when it was sent), and the frame, to send it
 * again if the gateway refused it.
 */
interface Request {
  readonly rs: string | undefined;
  readonly frame: F.ClientFrame;
  readonly gens: ReadonlyMap<string, number>;
}

const NO_GENS: ReadonlyMap<string, number> = new Map();
const gensOf = (list: readonly Stream[]): ReadonlyMap<string, number> =>
  new Map(list.map((s) => [s.ch, s.gen]));

const familyOf = (ch: string): string => ch.split(".", 1)[0] ?? ch;
const privateRank = (ch: string): number => {
  const rank = PRIVATE_FIRST.indexOf(familyOf(ch));
  return rank === -1 ? PRIVATE_FIRST.length : rank;
};

/** Consecutive items of one `rs`: a `sub` frame has one `replay_session_id`. */
function runsOf<T extends { readonly rs: string | undefined }>(list: readonly T[]) {
  const runs: { readonly rs: string | undefined; readonly items: T[] }[] = [];
  for (const item of list) {
    const last = runs.at(-1);
    if (last !== undefined && last.rs === item.rs) last.items.push(item);
    else runs.push({ rs: item.rs, items: [item] });
  }
  return runs;
}

const mapNonEmpty = <T, U>([first, ...rest]: NonEmpty<T>, map: (item: T) => U): NonEmpty<U> => [
  map(first),
  ...rest.map(map),
];

export function createWsEngine(options: EngineOptions): WsEngine {
  const { sink } = options;
  const timers: Timers = { ...platformTimers, ...options.timers };
  const streams = new Map<string, Stream>();
  const ledger = new Map<string, Request>();
  /** `ch` -> `unsub` requests whose `unsub_ok` is due (9.3: a new `sub` of it waits, and its old frames are dropped). */
  const unsubbing = new Set<string>();
  const own = { resyncsSent: 0 };
  let generation = 0;
  const nextGeneration = (): number => (generation += 1);
  let syncQueued = false;

  const connection: Connection = createConnection({
    url: options.url,
    createSocket: options.createSocket,
    tokens: options.tokens,
    client: options.client,
    timers,
    wall: options.wallClock ?? (() => Date.now()),
    random: options.random ?? Math.random,
    reachability: options.reachability ?? new ReachabilityTracker(),
    emit: (event) => sink.event(event),
    hooks: {
      ready: () => {
        sync();
      },
      down,
      frame: onFrame,
      malformed: (error) => registry.onDecodeError(error),
    },
  });

  /** Sends a request whose reply is due: `rs` is the stream the reply is for (`to`), `gens` the subscriptions it is about, and the frame is kept in case the gateway refuses it. */
  function submit(
    frame: F.ClientFrame,
    rs: string | undefined,
    gens: ReadonlyMap<string, number> = NO_GENS,
  ): void {
    if (ledger.size >= LEDGER_MAX) {
      const oldest = ledger.keys().next();
      if (!oldest.done) ledger.delete(oldest.value);
    }
    ledger.set(frame.id, { rs, frame, gens });
    connection.send(frame);
  }

  /** The request a reply or an error answers, forgotten once read. */
  function take(id: string | undefined): Request | undefined {
    const request = id === undefined ? undefined : ledger.get(id);
    if (id !== undefined) ledger.delete(id);
    return request;
  }
  const scopeOf = (request: Request): RequestScope => ({ rs: request.rs });

  /** The stream a request is about, unless a `sub` or an `unsub` went out for it since (`Stream.gen`): then the reply is an old subscription's, and applies to nothing. */
  function streamOf(request: Request, ch: string): Stream | undefined {
    const stream = streams.get(topicKey(ch, request.rs));
    return stream !== undefined && stream.gen === request.gens.get(ch) ? stream : undefined;
  }

  /** A snapshot of a stream is the baseline a `resync` of it asked for (no frame answers one by id), so no denial of that resync can matter any more: its request is forgotten. */
  function forgetResyncs(ch: string, rs: string | undefined): void {
    for (const [id, request] of ledger) {
      if (request.frame.t === "resync" && request.frame.ch === ch && request.rs === rs) {
        ledger.delete(id);
      }
    }
  }

  const host: RegistryHost = {
    subscribe(spec, rs) {
      if (spec.ch === SYSTEM) return; // implicit: the server attaches it at `auth_ok` (6.2)
      const key = topicKey(spec.ch, rs);
      // A subscription the server still holds (its last consumer left a moment ago) is not subscribed
      // again: the new stream takes it over, and with it the replies still due for it and what its `sub_ok` said.
      const prior = streams.get(key);
      const kept = prior?.held === true ? prior : undefined;
      streams.set(key, {
        key,
        ch: spec.ch,
        rs,
        spec,
        consumers: new Set(),
        handle: undefined,
        held: kept !== undefined,
        gen: kept?.gen ?? 0,
      });
      if (kept !== undefined) inherit(kept);
      scheduleSync();
    },
    unsubscribe: () => scheduleSync(),
    // `sub_id` pins the subscription the envelope's `ch` and `rs` name (7.5): a bare `ch` would be the live stream's.
    resync(ch, rs, payload, subId) {
      if (!connection.ready) return;
      own.resyncsSent += 1;
      const pin = subId === undefined ? {} : { sub_id: subId };
      submit(F.resync(connection.nextId(), ch, { ...payload, ...pin }, rs), rs);
    },
    deliver(ch, rs, frame) {
      if (frame.kind === "snap") forgetResyncs(ch, rs);
      sink.deliver(ch, rs, frame);
    },
  };
  /** The registry's record of a stream that takes a held subscription over is a new one: it knows nothing of the `sub_ok` that made the subscription, so it is handed what the old record learned. */
  function inherit(old: Stream): void {
    const subId = old.handle?.subId;
    const effective = old.handle?.effective;
    const result = {
      ch: old.ch,
      ok: true,
      ...(subId !== undefined && { sub_id: subId }),
      ...(effective !== undefined && { effective }),
    };
    registry.onSubOk({ t: "sub_ok", p: { results: [result] } }, { rs: old.rs });
  }

  const guard = createResyncGuard({
    now: timers.now,
    setTimer: timers.setTimeout,
    clearTimer: timers.clearTimeout,
  });
  const registry = createSubscriptionRegistry({ host, guard, now: timers.now });

  function scheduleSync(): void {
    if (syncQueued) return;
    syncQueued = true;
    timers.queueMicrotask(sync);
  }

  function priorityOf(stream: Stream): SubscriptionPriority {
    let best: SubscriptionPriority = "other";
    for (const { spec } of stream.consumers) {
      const asked = spec.priority;
      if (PRIORITY_RANK[asked] < PRIORITY_RANK[best]) best = asked;
    }
    return best;
  }

  /** 9.3: private (orders, positions, executions, wallet first), then the focused pane, then the rest. */
  function restoreOrder(list: readonly Stream[]): Stream[] {
    const rank = (s: Stream) => (priorityOf(s) === "private" ? privateRank(s.ch) : 0);
    const sorted = [...list].sort((a, b) => rank(a) - rank(b)); // stable: ties keep their order
    const byKey = new Map(sorted.map((s) => [s.key, s]));
    const ordered = orderSubscriptionsForRestore(
      sorted.map((s) => ({ topic: s.key, priority: priorityOf(s) })),
    );
    return ordered.flatMap(({ topic }) => byKey.get(topic) ?? []);
  }

  /** Wanted on the server: has a consumer, and was not ended by it (a revoked stream is replaced by a new consume). */
  const wanted = (s: Stream): boolean => s.consumers.size > 0 && s.handle?.status !== "revoked";

  function topicEntry(s: Stream): F.SubPayload["topics"][number] {
    const opts = s.spec.opts;
    return opts === undefined ? { ch: s.ch } : { ch: s.ch, opts };
  }

  /**
   * Brings the server in line with what is wanted: subscribes what is new (in the 9.3 order, in
   * frames of at most `max_topics_per_request`) and unsubscribes what nobody wants. One `unsub` ends
   * every subscription of a `ch`, live and replay alike (5.3), so it is sent only when none is wanted.
   */
  function sync(): void {
    syncQueued = false;
    if (!connection.ready) return;
    for (const s of streams.values()) if (!s.held && s.consumers.size === 0) streams.delete(s.key);
    const byCh = new Map<string, Stream[]>();
    for (const s of streams.values()) byCh.set(s.ch, [...(byCh.get(s.ch) ?? []), s]);
    const drops: Stream[] = [];
    const adds: Stream[] = [];
    for (const [ch, group] of byCh) {
      if (!group.some(wanted)) {
        const held = group.filter((s) => s.held);
        if (held[0] !== undefined) drops.push(held[0]);
        for (const s of held) {
          s.held = false;
          s.gen = nextGeneration(); // what the server held goes with the `unsub`
        }
      }
      for (const s of group.filter(wanted)) {
        if (!s.held && !unsubbing.has(ch)) adds.push(s);
      }
    }
    const perFrame = connection.topicsPerRequest;
    // An `unsub` names no replay session, but its reply is applied to the stream of each `ch` it names (`Request.rs`): a frame lists the topics of one `rs`.
    for (const run of runsOf(drops)) {
      for (const chunk of chunkTopics(run.items, perFrame)) {
        const topics = mapNonEmpty(chunk, (s) => s.ch);
        for (const ch of topics) unsubbing.add(ch);
        submit(F.unsub(connection.nextId(), topics), run.rs, gensOf(chunk));
      }
    }
    for (const run of runsOf(restoreOrder(adds))) {
      for (const chunk of chunkTopics(run.items, perFrame)) {
        for (const s of chunk) {
          s.held = true;
          s.gen = nextGeneration();
        }
        const topics = mapNonEmpty(chunk, topicEntry);
        const replay = run.rs === undefined ? {} : { replay_session_id: run.rs };
        submit(
          F.sub(connection.nextId(), { topics, snapshot: true, ...replay }),
          run.rs,
          gensOf(chunk),
        );
      }
    }
  }

  function onFrame(frame: Inbound, decodeMs: number): void {
    switch (frame.t) {
      case "snap":
      case "d":
        // The frames of a subscription whose `unsub_ok` is still due belong to the old one.
        if (!unsubbing.has(frame.ch)) registry.onData(frame, decodeMs);
        return;
      case "sub_ok":
        return onSubOk(frame);
      case "unsub_ok":
        return onUnsubOk(frame);
      case "err":
        return onErr(frame);
    }
  }

  /**
   * A reply is applied to the stream of its request, and only while that stream is still the
   * subscription the request was sent for (`streamOf`): a reply to no request of ours, one
   * forgotten, or one for a subscription let go or sent again since applies to nothing.
   */
  function onSubOk(frame: ControlOf<"sub_ok">): void {
    const request = take(frame.id);
    if (request === undefined) return;
    const current = frame.p.results.flatMap((result) => {
      const stream = streamOf(request, result.ch);
      return stream === undefined ? [] : [{ result, stream }];
    });
    const results = current.map(({ result }) => result);
    registry.onSubOk({ ...frame, p: { ...frame.p, results } }, scopeOf(request));
    // A refused topic is not held; the registry ended its stream, and an ended stream is not wanted, so it is not asked for again.
    for (const { result, stream } of current) {
      if (!result.ok) stream.held = false;
    }
  }

  function onUnsubOk(frame: ControlOf<"unsub_ok">): void {
    const request = take(frame.id);
    if (request !== undefined) {
      const results = frame.p.results.filter(({ ch }) => streamOf(request, ch) !== undefined);
      registry.onUnsubOk({ ...frame, p: { ...frame.p, results } }, scopeOf(request));
    }
    for (const { ch } of frame.p.results) unsubbing.delete(ch); // whatever it answers, nothing waits for it any more
    scheduleSync(); // what waited behind it can go
  }

  /** The `err` that answers a request settles it (the connection has mapped it already, and settled any `auth`). */
  function onErr(frame: ControlOf<"err">): void {
    const request = take(frame.id);
    if (request === undefined) return;
    if (request.frame.t === "sub") {
      refuseSub(request, request.frame, frame.p);
    } else if (request.frame.t === "unsub") {
      // An `unsub` the gateway refused (a client bug) has no `unsub_ok` to wait for: what waited behind it goes.
      for (const ch of request.frame.p.topics) unsubbing.delete(ch);
      scheduleSync();
    }
  }

  /** A `sub` the gateway answered with an `err` subscribed nothing: each of its topics is refused, as a `sub_ok` would say. */
  function refuseSub(
    request: Request,
    sub: Extract<F.ClientFrame, { t: "sub" }>,
    error: ControlOf<"err">["p"],
  ): void {
    const current = sub.p.topics.flatMap(({ ch }) => {
      const stream = streamOf(request, ch);
      return stream === undefined ? [] : [{ ch, stream }];
    });
    const results = current.map(({ ch }) => ({ ch, ok: false, error }));
    registry.onSubOk({ t: "sub_ok", p: { results } }, { rs: request.rs });
    for (const { stream } of current) stream.held = false;
  }

  /** The connection is gone: every stream is pending again (9.3: no session resumption) and subscribes afresh on the next one. */
  function down(): void {
    registry.onDisconnect();
    for (const s of streams.values()) {
      s.held = false;
      if (s.consumers.size === 0) streams.delete(s.key);
    }
    unsubbing.clear();
    ledger.clear();
  }

  return {
    start: () => connection.start(),

    stop() {
      connection.stop();
      streams.clear();
      registry.dispose(); // what it still held, and the resyncs that wait for their budget, are not coming back
    },

    consume(spec, rs) {
      const handle = registry.consume(spec, rs);
      if (spec.ch === SYSTEM) return handle;
      const stream = streams.get(topicKey(spec.ch, rs));
      const consumer: Consumer = { spec };
      stream?.consumers.add(consumer);
      if (stream !== undefined) stream.handle ??= handle;
      return {
        ch: handle.ch,
        rs: handle.rs,
        get subId() {
          return handle.subId;
        },
        get effective() {
          return handle.effective;
        },
        get status() {
          return handle.status;
        },
        get source() {
          return handle.source;
        },
        release() {
          stream?.consumers.delete(consumer);
          handle.release();
          scheduleSync();
        },
      };
    },

    get slowConsumerHint() {
      return connection.slowConsumerHint;
    },

    get counters() {
      const { gaps, resyncsDeferred, forcedSnapshots } = registry.counters;
      const { reconnects, malformedFrames } = connection.counters;
      return {
        gaps,
        resyncsDeferred,
        forcedSnapshots,
        reconnects,
        malformedFrames,
        ...own,
        pendingRequests: ledger.size,
        streams: streams.size,
      };
    },
  };
}
