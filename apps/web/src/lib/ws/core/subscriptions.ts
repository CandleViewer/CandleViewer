// E17-T04 S2 (23 5.2, 7.1-7.2, 11; C2, C10, C11): the subscription registry's data plane. It counts
// consumers per stream and turns validated data frames into what the engine delivers: a frame
// applies only to a baseline it continues, and anything else voids the stream and asks for a fresh
// `snap`, through the guard that keeps resyncs under the gateway's limit. Frames leave through
// `host.deliver`, in order: queueing and fan-out to tabs belong to the layer that owns the consumers.
// What the server says about a subscription (`sub_ok`, `ctl_ok`, `unsub_ok`, `revoked`) is the
// control plane, which is S2d. No sockets, timers or wall clock of its own: the host, the guard and
// the clock are injected.
import type { ConsumerSpec, ResetReason, TopicFrame, TopicHandle } from "../api";
import { validateCvwb, type DataBody, type DataFrame } from "../protocol/codec";
import type { ResyncPayload } from "../protocol/frames";
import type { TopicStatus } from "../state/types";
import { createResyncGuard, type ResyncGuard } from "./resyncGuard";
import { createSequencer, topicKey } from "./sequencer";
import { createSnapshotAssembler } from "./snapshotAssembler";

const NO_OPTIONS: Readonly<Record<string, unknown>> = Object.freeze({});
const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isStale = (body: DataBody): boolean =>
  body.e === "j" && isRecord(body.p) && body.p["stale"] === true;

/** What a consumer can ask of its stream. The frames themselves go to `RegistryHost.deliver`. */
export type StreamHandle = Omit<TopicHandle, "read">;

/** What the registry asks of the engine. */
export interface RegistryHost {
  /** The first consumer of a stream arrived: send its `sub` (`spec` is that consumer's). */
  subscribe(spec: ConsumerSpec, rs: string | undefined): void;
  /** The last consumer left the stream: send its `unsub`. */
  unsubscribe(ch: string, rs: string | undefined): void;
  /**
   * A resync the guard admitted: frame it and pace it. `rs` is the replay stream it is for, and the
   * engine puts it on the envelope (13.1): the gateway resolves a bare `ch` to the live stream, so
   * a replay stream's loss would re-snapshot its live twin and stay void (#572).
   */
  resync(ch: string, rs: string | undefined, payload: ResyncPayload): void;
  /**
   * One validated frame of a stream, in order: a `snap` replaces all before it, a `reset` voids
   * them, a `d` extends them. The host owns what happens next: a bounded queue (C-2.18), a copy per
   * tab, holding a newcomer back until its `snap`, and voiding the stream with a resync when it
   * cannot keep up. None of that is here.
   */
  deliver(ch: string, rs: string | undefined, frame: TopicFrame): void;
}

export interface RegistryOptions {
  readonly host: RegistryHost;
  /** Defaults to a new guard. */
  readonly guard?: ResyncGuard | undefined;
  /** Monotonic milliseconds; adds the CVWB validation time to `decodeMs`. Defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  readonly maxHeldBytes?: number | undefined;
}

/** Events of every stream, for the engine's metrics. */
export interface StreamCounters {
  gaps: number;
  malformed: number;
  /** Chunk sets dropped for passing a cap. */
  overflows: number;
  resyncsSent: number;
  resyncsDeferred: number;
}

export interface SubscriptionRegistry {
  /**
   * `rs` selects a replay stream of the `ch` (23 11); live otherwise. A consumer that joins a stream
   * which already has a baseline needs its own: a resync is asked for, and the `snap` it brings is
   * delivered like any other, so the engine holds the newcomer back until it arrives.
   */
  consume(spec: ConsumerSpec, rs?: string | undefined): StreamHandle;
  /** A `snap` or `d` that decoded. `decodeMs` is the caller's decode time; the CVWB check here is added. */
  onData(frame: DataFrame, decodeMs: number): void;
  readonly counters: Readonly<StreamCounters>;
  /** Bytes held for incomplete chunk sets across every stream (bounded by `maxHeldBytes`). */
  readonly heldBytes: number;
  /** Forgets every stream and what waits for it. The registry keeps no spec to subscribe again from. */
  dispose(): void;
}

interface Rec {
  readonly key: string;
  readonly ch: string;
  readonly rs: string | undefined;
  /** Consumers holding the stream. */
  refs: number;
  stale: boolean;
  /** Chunk sets dropped for size since the last complete `snap`: it comes back the same, so a second in a row ends the asking. */
  overflows: number;
  /** A `reset` was delivered and no `snap` since: consumers already hold nothing, so none repeats it. */
  voided: boolean;
  /** Sticky until the next baseline: a frame that says replay makes the stream replay (C11). */
  replay: boolean;
}

export function createSubscriptionRegistry(options: RegistryOptions): SubscriptionRegistry {
  const { host } = options;
  const now = options.now ?? (() => performance.now());
  const guard = options.guard ?? createResyncGuard();
  const seq = createSequencer();
  const assembler = createSnapshotAssembler({ maxHeldBytes: options.maxHeldBytes });
  // Keyed by `(ch, rs)` in a Map: server strings never become property names (no `__proto__` games).
  const records = new Map<string, Rec>();
  const counters: StreamCounters = {
    gaps: 0,
    malformed: 0,
    overflows: 0,
    resyncsSent: 0,
    resyncsDeferred: 0,
  };

  const named = (ch: string): Rec[] => [...records.values()].filter((rec) => rec.ch === ch);
  const send = (rec: Rec, frame: TopicFrame): void => host.deliver(rec.ch, rec.rs, frame);
  const reset = (rec: Rec, reason: ResetReason): void => send(rec, { kind: "reset", reason });
  /** A resync is owed while a stream of this `ch` has lost its baseline. */
  const owed = (ch: string): boolean => named(ch).some((rec) => seq.state(rec.key) === "resyncing");

  function statusOf(rec: Rec): TopicStatus {
    const state = seq.state(rec.key);
    if (state !== "live") return state;
    return rec.stale ? "stale" : "live";
  }

  function requestResync(rec: Rec, reason: ResyncPayload["reason"]): void {
    if (rec.overflows > 1) return; // see applySnap: asking again would get the same snapshot
    const go = () => {
      counters.resyncsSent += 1;
      host.resync(rec.ch, rec.rs, { last_seq: seq.lastSeq(rec.key), reason });
    };
    if (guard.request(rec.ch, go) === "deferred") counters.resyncsDeferred += 1;
  }

  /** The stream's state is void: nothing applies until the next complete `snap`, which is asked for unless the server sends it anyway. */
  function lose(rec: Rec, why: ResetReason, resync?: ResyncPayload["reason"]): void {
    seq.discard(rec.key);
    if (!rec.voided) reset(rec, why);
    rec.voided = true;
    if (resync !== undefined) requestResync(rec, resync);
  }

  function malformed(rec: Rec, id?: string | undefined): void {
    counters.malformed += 1;
    assembler.discard(rec.key, id);
    lose(rec, "malformed", "decode_error");
  }

  /** The stream is gone: its state, and with the last stream of the `ch` the gateway's resync window, which is per subscription. */
  function forget(rec: Rec): void {
    seq.forget(rec.key);
    assembler.forget(rec.key);
    if (named(rec.ch).length === 0) guard.forget(rec.ch);
    else if (!owed(rec.ch)) guard.cancel(rec.ch);
  }

  /**
   * A delta of a stream with no baseline is dropped unread: there is nothing to extend, and a bad
   * body must not void a stream that is already void. If a chunk set is held, the server went on
   * without it (3.6) and nothing will complete it: it is dropped and a snapshot asked for.
   */
  function orphaned(rec: Rec): void {
    if (!assembler.holds(rec.key)) return;
    assembler.discard(rec.key);
    lose(rec, "gap", "state_corrupt");
  }

  function applyDelta(rec: Rec, frame: DataFrame, decodeMs: number, replay: boolean): void {
    if (frame.s === null) return malformed(rec); // the codec refuses it; a caller may not have
    // The stream is live (`onData` checked), so the verdict is a gap or an apply.
    if (seq.accept(rec.key, frame.s).kind === "gap") {
      counters.gaps += 1;
      return lose(rec, "gap", "sequence_gap"); // discarded at once, never patched around (7.1)
    }
    if (replay) rec.replay = true;
    const { ts, sp, meta, body } = frame;
    send(rec, { kind: "d", seq: frame.s, ts, sp, decodeMs, meta, body });
  }

  function applySnap(
    rec: Rec,
    frame: DataFrame,
    decodeMs: number,
    replay: boolean,
    partial: boolean | undefined,
  ): void {
    const { id, s, body, size } = frame;
    const result = assembler.push(rec.key, { id, s, partial, body, size, decodeMs });
    if (result.kind === "ignored") return;
    if (result.kind === "malformed") return malformed(rec, id);
    if (result.kind === "overflow") {
      counters.overflows += 1;
      // The server answers a resync with the same snapshot, which passes the cap again: the second
      // overflow in a row ends the asking (`requestResync`) until a snapshot fits or the stream is
      // subscribed again; the engine's baseline deadline surfaces a stream left void.
      rec.overflows += 1;
      return lose(rec, "overflow", "state_corrupt");
    }
    if (result.kind === "pending") {
      // The old baseline is void once a new snapshot starts: no `d` applies until it completes.
      if (seq.state(rec.key) === "live") seq.discard(rec.key);
      return;
    }
    seq.baseline(rec.key, result.seq);
    rec.stale = result.bodies.some(isStale);
    rec.replay = replay;
    rec.voided = false;
    rec.overflows = 0;
    const { ts, sp, meta } = frame;
    const { seq: snapSeq, bodies, decodeMs: total } = result;
    send(rec, { kind: "snap", seq: snapSeq, ts, sp, decodeMs: total, meta, bodies });
    if (!owed(rec.ch)) guard.cancel(rec.ch);
  }

  function handleFor(rec: Rec): StreamHandle {
    let released = false;
    return {
      ch: rec.ch,
      rs: rec.rs,
      effective: NO_OPTIONS,
      get status() {
        return statusOf(rec);
      },
      get source() {
        return rec.rs !== undefined || rec.replay ? "replay" : "live";
      },
      release() {
        if (released) return;
        released = true;
        rec.refs -= 1;
        if (rec.refs > 0 || records.get(rec.key) !== rec) return;
        records.delete(rec.key);
        forget(rec);
        host.unsubscribe(rec.ch, rec.rs);
      },
    };
  }

  return {
    consume(spec, rs) {
      const key = topicKey(spec.ch, rs);
      let rec = records.get(key);
      if (rec === undefined) {
        rec = {
          key,
          ch: spec.ch,
          rs,
          refs: 1,
          stale: false,
          overflows: 0,
          voided: false,
          replay: false,
        };
        records.set(key, rec);
        host.subscribe(spec, rs);
      } else {
        rec.refs += 1;
        if (seq.state(key) === "live") requestResync(rec, "client_restart");
      }
      return handleFor(rec);
    },

    onData(frame, decodeMs) {
      const rec = records.get(topicKey(frame.ch, frame.rs));
      if (rec === undefined) return; // in flight after an `unsub`, say
      if (frame.t === "d" && seq.state(rec.key) !== "live") return orphaned(rec);
      let ms = decodeMs;
      let replay = frame.meta?.source === "replay";
      let partial: boolean | undefined;
      if (frame.body.e === "b64") {
        // C10: magic, version, kind and length, before anything reads the body.
        const start = now();
        const checked = validateCvwb(frame.body.bytes);
        ms += now() - start;
        if (!("ok" in checked)) return malformed(rec, frame.id);
        replay ||= checked.header.flags.replay;
        partial = checked.header.flags.partial;
      }
      if (frame.t === "d") applyDelta(rec, frame, ms, replay);
      else applySnap(rec, frame, ms, replay, partial);
    },

    counters,
    get heldBytes() {
      return assembler.heldBytes;
    },
    dispose() {
      for (const rec of records.values()) {
        seq.forget(rec.key);
        assembler.forget(rec.key);
      }
      records.clear();
      guard.reset();
    },
  };
}
