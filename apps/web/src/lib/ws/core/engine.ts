// E17-T04 S4 (23 5, 7.5, 9.3; C2): the engine. It composes the connection, the stream core (S2)
// and the reducer's events (S1b): the registry's `subscribe`/`unsubscribe`/`resync` become `sub`,
// `unsub` and `resync` frames, the data of each stream goes to its registry record, and after a
// reconnect every stream subscribes again in the 9.3 order. Worker-agnostic: everything
// platform-shaped is injected.
import type { ConsumerSpec, TokenSource, TopicFrame } from "../api";
import type { Timers } from "../policy/timers";
import { platformTimers } from "../policy/timers";
import { chunkTopics, type NonEmpty } from "../policy/outboundPacer";
import type { Inbound } from "../protocol/codec";
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
import { createSubscriptionRegistry, type RegistryHost, type StreamHandle } from "./subscriptions";

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
}

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
  const own = { resyncsSent: 0 };
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

  const host: RegistryHost = {
    subscribe(spec, rs) {
      if (spec.ch === SYSTEM) return; // implicit: the server attaches it at `auth_ok` (6.2)
      const key = topicKey(spec.ch, rs);
      // A subscription the server still holds (its last consumer left a moment ago) is not subscribed
      // again: the new stream takes it over.
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
      });
      scheduleSync();
    },
    unsubscribe: () => scheduleSync(),
    resync(ch, rs, payload) {
      if (!connection.ready) return;
      own.resyncsSent += 1;
      connection.send(F.resync(connection.nextId(), ch, payload, rs));
    },
    deliver(ch, rs, frame) {
      sink.deliver(ch, rs, frame);
    },
  };
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
    for (const group of byCh.values()) {
      if (!group.some(wanted)) {
        const held = group.filter((s) => s.held);
        if (held[0] !== undefined) drops.push(held[0]);
        for (const s of held) {
          s.held = false;
        }
      }
      for (const s of group.filter(wanted)) {
        if (!s.held) adds.push(s);
      }
    }
    const perFrame = connection.topicsPerRequest;
    for (const chunk of chunkTopics(drops, perFrame)) {
      const topics = mapNonEmpty(chunk, (s) => s.ch);
      connection.send(F.unsub(connection.nextId(), topics));
    }
    for (const run of runsOf(restoreOrder(adds))) {
      for (const chunk of chunkTopics(run.items, perFrame)) {
        for (const s of chunk) s.held = true;
        const topics = mapNonEmpty(chunk, topicEntry);
        const replay = run.rs === undefined ? {} : { replay_session_id: run.rs };
        connection.send(F.sub(connection.nextId(), { topics, snapshot: true, ...replay }));
      }
    }
  }

  function onFrame(frame: Inbound, decodeMs: number): void {
    switch (frame.t) {
      case "snap":
      case "d":
        registry.onData(frame, decodeMs);
        return;
    }
  }

  /** The connection is gone: every stream is pending again (9.3: no session resumption) and subscribes afresh on the next one. */
  function down(): void {
    registry.onDisconnect();
    for (const s of streams.values()) {
      s.held = false;
      if (s.consumers.size === 0) streams.delete(s.key);
    }
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
        streams: streams.size,
      };
    },
  };
}
