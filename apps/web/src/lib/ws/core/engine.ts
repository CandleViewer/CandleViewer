// E17-T04 S4 (23 5, 7.5, 9.3, 11; C2, C5): the engine. It composes the connection, the stream
// core (S2) and the reducer's events (S1b): the registry's `subscribe`/`unsubscribe`/`resync` become
// `sub`, `unsub` and `resync` frames, every reply is correlated to the stream its request was for
// (`to`), what a stream's `system` says drives the reducer, and after a reconnect every stream
// subscribes again in the 9.3 order. Worker-agnostic: everything platform-shaped is injected.
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
import { createFlowControl, type PaneState } from "./flowControl";
import { createResyncGuard } from "./resyncGuard";
import { splitKey, topicKey } from "./sequencer";
import {
  createSubscriptionRegistry,
  type RegistryHost,
  type RequestScope,
  type StreamHandle,
} from "./subscriptions";

export type { EngineSocket, SocketEvents, SocketFactory } from "./connection";
export type { PaneState } from "./flowControl";

export interface EngineSink {
  /** The reducer's input, in order: `reduce(state, event)`. */
  event(event: EngineEvent): void;
  /** One validated frame of a stream, in order (`RegistryHost.deliver`). Queueing and fan-out to tabs are the sink's. */
  deliver(ch: string, rs: string | undefined, frame: TopicFrame): void;
  /**
   * What a handle reads (`status`, `effective`, `source`) may have changed with no frame to say so:
   * after every reply of the server and when a snapshot is overdue. The sink reads the handles it holds.
   */
  changed?(): void;
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
  /** Frames the gateway refused with `client_rate_limited`. */
  deniedFrames: number;
  /** Requests whose reply is still due (bounded: the oldest is forgotten past `LEDGER_MAX`). */
  pendingRequests: number;
  /** Subscriptions kept: wanted ones, and ones the server still holds after their last consumer left. */
  streams: number;
  /** Entries flow control keeps: bounded by the streams wanted or held, none once there are none (C-2.18). */
  flowEntries: number;
}

export interface WsEngine {
  /** Opens the first connection. Idempotent. */
  start(): void;
  /** A client stop: closes the socket, never reconnects, and forgets every stream. */
  stop(): void;
  /** `rs` selects a replay stream of the `ch` (23 11). `system` is implicit and shared. */
  consume(spec: ConsumerSpec, rs?: string | undefined): StreamHandle;
  /**
   * What a pane shows decides how fast its topics run: a hidden tab or an off-screen pane is slowed
   * to 1 000 ms, a collapsed one is let go (C8), a heatmap's bucket follows its size (6.1.1).
   * `paneId` is the one of the consumers' specs.
   */
  setPane(paneId: string, state: PaneState): void;
  removePane(paneId: string): void;
  /** The focused pane's topics come back first after a reconnect (9.3); `null` leaves it to each spec's `priority`. */
  focusPane(paneId: string | null): void;
  /**
   * The sink dropped frames of a stream it could not keep up with: a fresh snapshot is asked for,
   * within the resync budget (7.5), and reaches every consumer of the stream. Nothing for a stream
   * the engine does not hold, or while there is no connection to ask on (the next one subscribes afresh).
   */
  rebaseline(ch: string, rs?: string | undefined): void;
  /** `bye.hint.most_expensive_topics` of the last close (8.4): kept, never acted on. */
  readonly slowConsumerHint: readonly string[];
  /** The server's clock minus ours, from `welcome` (4.2); `undefined` until the current socket has had one. */
  readonly clockSkewMs: number | undefined;
  /** A fresh snapshot of the counters. */
  readonly counters: EngineCounters;
}

const SYSTEM = "system";
/** A `snap` is due this long after `sub_ok`, a resync or a `resnapshot`: else one resync, then the stream reads stale. */
export const BASELINE_DEADLINE_MS = 10_000;
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
  /** A consumer arrived for a subscription the server still holds: no `sub`, but a baseline is asked for. */
  attach: boolean;
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
  /** The gateway refused it once (8.5) and it went again: a second refusal of it is final. */
  readonly resent: boolean;
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

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
/** The reducer vets every field it reads (S1b); this only says the payload is shaped like an update at all. */
const isSystemUpdate = (v: unknown): v is F.SystemUpdate =>
  isRecord(v) && typeof v["kind"] === "string";

export function createWsEngine(options: EngineOptions): WsEngine {
  const { sink } = options;
  const timers: Timers = { ...platformTimers, ...options.timers };
  const streams = new Map<string, Stream>();
  const ledger = new Map<string, Request>();
  /** `(ch, rs)` -> `unsub` requests whose `unsub_ok` is due (9.3: a new `sub` of the stream waits, and its old frames are dropped). */
  const unsubbing = new Set<string>();
  /** `(ch, rs)` -> the wait for a baseline, and whether it already got its one retry. */
  const deadlines = new Map<string, { timer: unknown; retried: boolean }>();
  const own = { resyncsSent: 0, deniedFrames: 0 };
  let generation = 0;
  const nextGeneration = (): number => (generation += 1);
  let focusedPane: string | null = null;
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
        arm(SYSTEM, undefined); // attached by the server at `auth_ok`: its snapshot is due
        sync();
      },
      down,
      frame: onFrame,
      malformed: (error) => registry.onDecodeError(error),
      superseded: (id) => void ledger.delete(id),
    },
  });

  /** Sends a request whose reply is due: `rs` is the stream the reply is for (`to`), `gens` the subscriptions it is about, and the frame is kept in case the gateway refuses it (`resent`: it already went again once). */
  function submit(
    frame: F.ClientFrame,
    rs: string | undefined,
    gens: ReadonlyMap<string, number> = NO_GENS,
    resent = false,
  ): void {
    if (ledger.size >= LEDGER_MAX) {
      const oldest = ledger.keys().next();
      if (!oldest.done) ledger.delete(oldest.value);
    }
    ledger.set(frame.id, { rs, frame, gens, resent });
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

  function* allConsumers() {
    for (const s of streams.values()) for (const { spec } of s.consumers) yield { spec, rs: s.rs };
  }

  /** `ctl` names its stream by `ch` and `rs` (5.4, C20; the gateway resolves it so since #3398): the live one's carries none. Flow control keeps one intent for each stream, so a `ch` with a live and a replay stream is retuned in a `ctl` each (#3439). */
  function sendCtl(ch: string, rs: string | undefined, payload: F.CtlPayload): void {
    const target = streams.get(topicKey(ch, rs));
    const gens = target?.held === true ? gensOf([target]) : NO_GENS;
    submit(F.ctl(connection.nextId(), ch, payload, rs), rs, gens);
  }
  const flow = createFlowControl(
    {
      consumers: allConsumers,
      ctl: sendCtl,
      changed: scheduleSync,
      minThrottleMs: () => connection.minThrottleMs,
    },
    timers,
  );

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
        attach: kept !== undefined,
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
      arm(ch, rs);
    },
    deliver(ch, rs, frame) {
      if (frame.kind === "snap") forgetResyncs(ch, rs);
      // A snapshot ends the wait for one, and so does the server ending the stream (a stream the engine lets go of is disarmed where it is dropped, a lost connection by `down`); a `resnapshot` brings one by itself.
      if (frame.kind === "snap" || (frame.kind === "reset" && frame.reason === "revoked")) {
        disarm(topicKey(ch, rs));
      } else if (frame.kind === "reset" && frame.reason === "resnapshot") {
        arm(ch, rs);
      }
      if (ch === SYSTEM && rs === undefined) bridgeSystem(frame);
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
  /** The engine's own consumer of `system`: it drives the reducer (WS-E06, C12). Never released, never subscribed. */
  const system = registry.consume({ ch: SYSTEM, paneId: "engine", priority: "private" });

  /**
   * The status goes first, so a resynced `system` stream is `live` before the update of the
   * snapshot that ended the resync (the ordering `EngineEvent` promises): a kill-switch fact that
   * arrives sooner is dropped by the reducer, never trusted. The reconnect is the reducer's own
   * business (`connecting` resets the stream).
   */
  function bridgeSystem(frame: TopicFrame): void {
    if (frame.kind === "reset") {
      if (frame.reason !== "reconnect")
        sink.event({ type: "system_stream", status: system.status });
      return;
    }
    if (frame.kind === "snap") sink.event({ type: "system_stream", status: system.status });
    const body = frame.kind === "snap" ? frame.bodies[0] : frame.body;
    if (body.e === "j" && isSystemUpdate(body.p)) sink.event({ type: "system", update: body.p });
  }

  function scheduleSync(): void {
    if (syncQueued) return;
    syncQueued = true;
    timers.queueMicrotask(sync);
  }

  function priorityOf(stream: Stream): SubscriptionPriority {
    let best: SubscriptionPriority = "other";
    for (const { spec } of stream.consumers) {
      // The focused pane is whichever the app says; without one, each spec says its own.
      const asked =
        spec.priority === "private" || focusedPane === null
          ? spec.priority
          : spec.paneId === focusedPane
            ? "focused"
            : "other";
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
  const wanted = (s: Stream): boolean =>
    s.consumers.size > 0 && s.handle?.status !== "revoked" && !flow.isReleased(s.ch, s.rs);

  function topicEntry(s: Stream): F.SubPayload["topics"][number] {
    const opts = flow.optionsOf(s.spec, s.rs);
    return opts === undefined ? { ch: s.ch } : { ch: s.ch, opts };
  }

  /**
   * Brings the server in line with what is wanted: subscribes what is new (in the 9.3 order, in
   * frames of at most `max_topics_per_request`), unsubscribes what nobody wants, and asks for a
   * baseline of a subscription a new consumer found still held. An `unsub` ends the stream its `rs`
   * names (5.3, #3398), so each held stream that nobody wants is let go, whatever its twin does, in a
   * frame for each replay session (#3439).
   */
  function sync(): void {
    syncQueued = false;
    if (!connection.ready) return;
    for (const s of streams.values()) if (!s.held && s.consumers.size === 0) streams.delete(s.key);
    const drops: Stream[] = [];
    const adds: Stream[] = [];
    for (const s of streams.values()) {
      if (!wanted(s)) {
        if (!s.held) continue;
        drops.push(s);
        s.held = false;
        s.gen = nextGeneration(); // what the server held goes with the `unsub`
        disarm(s.key); // no snapshot is due of a subscription that is going
        continue;
      }
      if (s.attach && s.held) askBaseline(s.ch, s.rs);
      s.attach = false;
      if (!s.held && !unsubbing.has(s.key)) adds.push(s);
    }
    const perFrame = connection.topicsPerRequest;
    // A frame lists the topics of one `rs`, which it carries (5.3): the session whose streams it ends, or the live ones.
    const dropsBySession = new Map<string | undefined, Stream[]>();
    for (const s of drops) dropsBySession.set(s.rs, [...(dropsBySession.get(s.rs) ?? []), s]);
    for (const [rs, items] of dropsBySession) {
      for (const chunk of chunkTopics(items, perFrame)) {
        const topics = mapNonEmpty(chunk, (s) => s.ch);
        for (const ch of topics) {
          unsubbing.add(topicKey(ch, rs));
          flow.unsubscribed(ch, rs); // the server holds nothing of it from here: what it was told is void
        }
        submit(F.unsub(connection.nextId(), topics, rs), rs, gensOf(chunk));
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

  /** The server holds the subscription, but this consumer has no baseline: ask for one, within the resync budget (7.5). */
  function askBaseline(ch: string, rs: string | undefined): void {
    guard.request(ch, topicKey(ch, rs), () => {
      const subId = streams.get(topicKey(ch, rs))?.handle?.subId;
      host.resync(ch, rs, { last_seq: null, reason: "client_restart" }, subId);
    });
  }

  function arm(ch: string, rs: string | undefined): void {
    const key = topicKey(ch, rs);
    const prior = deadlines.get(key);
    if (prior !== undefined) timers.clearTimeout(prior.timer);
    deadlines.set(key, {
      retried: prior?.retried ?? false,
      timer: timers.setTimeout(() => overdue(ch, rs), BASELINE_DEADLINE_MS),
    });
  }

  function disarm(key: string): void {
    const wait = deadlines.get(key);
    if (wait === undefined) return;
    timers.clearTimeout(wait.timer);
    deadlines.delete(key);
  }

  /** No snapshot in time: ask once more, within the resync budget; if that fails too the stream reads stale until one comes, so a `system` fact the stream missed is never trusted (WS-E06). */
  function overdue(ch: string, rs: string | undefined): void {
    const wait = deadlines.get(topicKey(ch, rs));
    if (wait === undefined) return;
    if (!wait.retried) {
      wait.retried = true;
      askBaseline(ch, rs);
      return;
    }
    deadlines.delete(topicKey(ch, rs));
    registry.markOverdue(ch, rs);
    if (ch === SYSTEM && rs === undefined) {
      sink.event({ type: "system_stream", status: system.status });
    }
    sink.changed?.(); // the stream reads `stale` now
  }

  function onFrame(frame: Inbound, decodeMs: number): void {
    switch (frame.t) {
      case "snap":
      case "d":
        // The frames of a subscription whose `unsub_ok` is still due belong to the old one.
        if (!unsubbing.has(topicKey(frame.ch, frame.rs))) registry.onData(frame, decodeMs);
        return; // a frame is its own news: it goes through `deliver`
      case "sub_ok":
        onSubOk(frame);
        break;
      case "ctl_ok":
        onCtlOk(frame);
        break;
      case "unsub_ok":
        onUnsubOk(frame);
        break;
      case "revoked":
        onRevoked(frame);
        break;
      case "err":
        onErr(frame);
        break;
    }
    sink.changed?.(); // a reply moves what a handle reads, with no frame to say so
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
      if (!result.ok) {
        stream.held = false;
        continue;
      }
      // Flow control keeps the registry's copy of the options, which is bounded: never the frame's own.
      flow.confirmed(result.ch, request.rs, stream.handle?.effective ?? {});
      arm(result.ch, request.rs);
    }
  }

  function onCtlOk(frame: ControlOf<"ctl_ok">): void {
    const request = take(frame.id);
    if (request === undefined || frame.ch === undefined) return;
    const stream = streamOf(request, frame.ch);
    if (stream === undefined) return;
    registry.onCtlOk(frame, scopeOf(request));
    flow.confirmed(frame.ch, request.rs, stream.handle?.effective ?? {});
  }

  function onUnsubOk(frame: ControlOf<"unsub_ok">): void {
    const request = take(frame.id);
    if (request !== undefined) {
      const results = frame.p.results.filter(({ ch }) => streamOf(request, ch) !== undefined);
      registry.onUnsubOk({ ...frame, p: { ...frame.p, results } }, scopeOf(request));
    }
    // whatever it answers, nothing waits for it any more: the stream of its request, or each of the `ch` when the request is unknown
    for (const { ch } of frame.p.results) {
      if (request !== undefined) unsubbing.delete(topicKey(ch, request.rs));
      else for (const key of unsubbing) if (splitKey(key).ch === ch) unsubbing.delete(key);
    }
    scheduleSync(); // what waited behind it can go
  }

  function onRevoked(frame: ControlOf<"revoked">): void {
    if (frame.ch !== undefined && unsubbing.has(topicKey(frame.ch, frame.rs))) return; // of a subscription we let go of: a stream here now is a newer one's
    registry.onRevoked(frame);
    for (const s of streams.values()) {
      if (s.ch !== frame.ch || !s.held || s.handle?.status !== "revoked") continue;
      s.held = false; // the server dropped it
      flow.unsubscribed(s.ch, s.rs);
    }
    scheduleSync();
  }

  /** The `err` that answers a request settles it (the connection has mapped it already, and settled any `auth`). */
  function onErr(frame: ControlOf<"err">): void {
    const request = take(frame.id);
    if (request === undefined) return;
    if (frame.p.code === "client_rate_limited") {
      // 8.5: the gateway dropped the frame unhandled and answered with its id. Send it again, once: a second refusal of it is final (the gateway closes 4429 at the second, and one that does not must not be fed for ever).
      // A `ctl` is asked for again from what is wanted now, not replayed: a newer one may have overtaken it.
      own.deniedFrames += 1;
      if (request.frame.t === "ctl") return flow.denied(request.frame.ch, request.rs);
      if (!request.resent) return resubmit(request);
    }
    // SR-193 (5.4, 8.5): the rebuild budget refused a `ctl` that would have re-snapshotted. It changed nothing, so what the engine took for applied is undone, and it is asked for again after a back-off, never at once and never in a loop.
    if (frame.p.code === "resync_rate_limited" && request.frame.t === "ctl") {
      return flow.refused(request.frame.ch, request.rs);
    }
    if (request.frame.t === "sub") {
      refuseSub(request, request.frame, frame.p);
    } else if (request.frame.t === "unsub") {
      // An `unsub` the gateway refused (a client bug) has no `unsub_ok` to wait for: what waited behind it goes.
      for (const ch of request.frame.p.topics) unsubbing.delete(topicKey(ch, request.rs));
      scheduleSync();
    }
  }

  /**
   * The gateway dropped a frame unhandled: it goes again with its id. A `sub` goes only for the
   * streams it is still about: one let go meanwhile has its `unsub` ahead of this frame at the
   * gateway, and subscribing it again would leave the server holding what nobody reads.
   */
  function resubmit(request: Request): void {
    const { frame } = request;
    if (frame.t !== "sub") return submit(frame, request.rs, request.gens, true);
    const [first, ...rest] = frame.p.topics.filter(({ ch }) => streamOf(request, ch) !== undefined);
    if (first === undefined) return;
    submit(
      F.sub(frame.id, { ...frame.p, topics: [first, ...rest] }),
      request.rs,
      request.gens,
      true,
    );
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
    flow.reset();
    for (const key of [...deadlines.keys()]) disarm(key);
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

    setPane: (paneId, state) => flow.setPane(paneId, state),
    removePane: (paneId) => flow.removePane(paneId),
    focusPane(paneId) {
      focusedPane = paneId;
    },

    rebaseline(ch, rs) {
      if (!connection.ready) return; // nothing leaves, so the guard's budget is not spent on it
      const session = ch === SYSTEM ? undefined : rs; // `system` has no replay twin
      const stream = streams.get(topicKey(ch, rs));
      // a stream the server does not hold (let go by its pane, ended, not subscribed yet) has nothing to re-snapshot
      if (ch === SYSTEM || stream?.held === true) askBaseline(ch, session);
    },

    consume(spec, rs) {
      const handle = registry.consume(spec, rs);
      if (spec.ch === SYSTEM) return handle;
      const stream = streams.get(topicKey(spec.ch, rs));
      const consumer: Consumer = { spec };
      stream?.consumers.add(consumer);
      if (stream !== undefined) stream.handle ??= handle;
      flow.evaluate();
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
          if (![...allConsumers()].some((c) => c.spec.ch === spec.ch && c.rs === rs)) {
            flow.forget(spec.ch, rs);
          }
          flow.evaluate();
          scheduleSync();
        },
      };
    },

    get slowConsumerHint() {
      return connection.slowConsumerHint;
    },

    get clockSkewMs() {
      return connection.clockSkewMs;
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
        flowEntries: flow.retained,
      };
    },
  };
}
