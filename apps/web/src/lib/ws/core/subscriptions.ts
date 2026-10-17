// E17-T04 S2 (23 5.2, 5.4, 7.1-7.2, 9.5, 11; C2-C5, C10, C11): the subscription registry. It counts
// consumers per stream, records what the server says about each subscription (`sub_ok`, `ctl_ok`,
// `unsub_ok`, `revoked`: the control plane, which names a `ch` and never its stream) and turns
// validated data frames into what the engine delivers: a frame applies only to a baseline it
// continues, and anything else voids the stream and asks for a fresh `snap`, through the guard that
// keeps resyncs under the gateway's limit. Frames leave through `host.deliver`, in order: queueing
// and fan-out to tabs belong to the layer that owns the consumers. No sockets, timers or wall clock
// of its own: the host, the guard and the clock are injected.
import type { ConsumerSpec, ResetReason, TopicFrame, TopicHandle } from "../api";
import { validateCvwb, type ControlOf, type DataBody, type DataFrame } from "../protocol/codec";
import type { ResyncPayload } from "../protocol/frames";
import type { TopicStatus } from "../state/types";
import { createResyncGuard, type ResyncGuard } from "./resyncGuard";
import { createSequencer, topicKey } from "./sequencer";
import { createSnapshotAssembler } from "./snapshotAssembler";

const MAX_SUB_ID_LENGTH = 64;
/** A `sub_id` is 1 to 64 characters (23 7.5, `subId`): any other string is no id, and no pin the server accepts. */
const isSubId = (v: unknown): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= MAX_SUB_ID_LENGTH;
/** `effective` is a few small options, lists and maps of them: more levels or more values than these is not options. */
const MAX_OPTIONS_DEPTH = 8;
const MAX_OPTIONS_NODES = 1024;
const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
/**
 * True when `value` is not options: its containers nest deeper than `MAX_OPTIONS_DEPTH`, or it holds
 * more than `MAX_OPTIONS_NODES` values (the root, every key's value and every element count). Walked
 * level by level, without recursion, and stopped at either limit before a level is read: a 4 MiB
 * frame can nest a million levels or hold a million elements, and `frozen` below copies what this
 * lets through, so neither its stack nor its heap sees more than the limits.
 */
function beyondOptions(value: unknown): boolean {
  let level: unknown[] = [value];
  let nodes = 1; // the root
  for (let depth = 1; ; depth += 1) {
    const containers = level.filter((v): v is object => typeof v === "object" && v !== null);
    if (containers.length === 0) return false;
    if (depth > MAX_OPTIONS_DEPTH) return true;
    // A list's length and an object's keys: counted without reading what they hold.
    nodes += containers.reduce(
      (n, c) => n + (Array.isArray(c) ? c.length : Object.keys(c).length),
      0,
    );
    if (nodes > MAX_OPTIONS_NODES) return true;
    level = containers.flatMap((c) => Object.values(c));
  }
}
/** A deep, read-only copy: `effective` is read by every consumer of the stream, and the frame it came from stays untouched. */
function frozen<T>(value: T): T {
  if (typeof value !== "object" || value === null) return value;
  const entries = Object.entries(value).map(([key, v]) => [key, frozen(v)] as const);
  // Cast: the copy has the shape of `value` (an array stays an array).
  return Object.freeze(
    Array.isArray(value) ? entries.map(([, v]) => v) : Object.fromEntries(entries),
  ) as T;
}
const NO_OPTIONS: Readonly<Record<string, unknown>> = frozen({});
const isStale = (body: DataBody): boolean =>
  body.e === "j" && isRecord(body.p) && body.p["stale"] === true;

/** What a consumer can ask of its stream. The frames themselves go to `RegistryHost.deliver`. */
export type StreamHandle = Omit<TopicHandle, "read"> & {
  /** From `sub_ok`; the gateway tells a live and a replay subscription of one `ch` apart by it (23 11). */
  readonly subId: string | undefined;
};

/** The stream a request was for (`rs: undefined` is live): the engine has it from the request `id` its reply echoes. */
export interface RequestScope {
  readonly rs: string | undefined;
}

/** What the registry asks of the engine. */
export interface RegistryHost {
  /** The first consumer of a stream arrived: send its `sub` (`spec` is that consumer's). */
  subscribe(spec: ConsumerSpec, rs: string | undefined): void;
  /** The last consumer left a stream the server still holds: send its `unsub`. */
  unsubscribe(ch: string, rs: string | undefined): void;
  /**
   * A resync the guard admitted: frame it and pace it. `rs` is the replay stream it is for and
   * `subId` the subscription `sub_ok` named, if it has: the engine puts them on the frame (13.1),
   * since the gateway resolves a bare `ch` to the live stream, so a replay stream's loss would
   * re-snapshot its live twin and stay void (#572).
   */
  resync(
    ch: string,
    rs: string | undefined,
    payload: ResyncPayload,
    subId: string | undefined,
  ): void;
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
  forcedSnapshots: number;
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
  /**
   * `sub_ok`, `ctl_ok` and `unsub_ok` name a `ch`, never its stream, and a live and a replay stream of
   * one `ch` can coexist (23 11): the frames carry no `rs` or `sub_id` (#572). `to` is the stream of
   * the request being answered, which the engine knows from the request `id` the reply echoes, and it
   * is required: the engine drops a reply that answers no request it sent, and a reply for a stream
   * that is gone applies to nothing, never to the twin of the stream it was for.
   */
  onSubOk(frame: ControlOf<"sub_ok">, to: RequestScope): void;
  onCtlOk(frame: ControlOf<"ctl_ok">, to: RequestScope): void;
  /** Concerns only a stream with no baseline yet: what it holds of a chunk set is the old subscription's. */
  onUnsubOk(frame: ControlOf<"unsub_ok">, to: RequestScope): void;
  /**
   * Names a `ch` too. `replay_session_ended` ends replay streams only; every other reason reaches
   * each stream of the `ch`, live and replay. With two replay streams of one `ch` it ends both.
   */
  onRevoked(frame: ControlOf<"revoked">): void;
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
  subId: string | undefined;
  effective: Readonly<Record<string, unknown>>;
  /** Ended by the server: nothing more is delivered to it, and no control frame reaches it. */
  revoked: boolean;
  stale: boolean;
  /** Chunk sets dropped for size since the last complete `snap`: it comes back the same, so a second in a row ends the asking. */
  overflows: number;
  /** The server owes the `snap` that `resnapshot` promised: a `d` first says it went on without one. */
  snapDue: boolean;
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
    forcedSnapshots: 0,
    resyncsSent: 0,
    resyncsDeferred: 0,
  };

  /** The streams of a `ch` that are not ended: an ended one gets no control frame and no resync. */
  const named = (ch: string): Rec[] =>
    [...records.values()].filter((rec) => rec.ch === ch && !rec.revoked);
  /** The streams a reply means: the stream of its request. */
  const targets = (ch: string, to: RequestScope): Rec[] =>
    named(ch).filter((rec) => rec.rs === to.rs);
  const send = (rec: Rec, frame: TopicFrame): void => host.deliver(rec.ch, rec.rs, frame);
  const reset = (rec: Rec, reason: ResetReason): void => send(rec, { kind: "reset", reason });
  /** A resync is owed while a stream of this `ch` has lost its baseline. */
  const owed = (ch: string): boolean => named(ch).some((rec) => seq.state(rec.key) === "resyncing");

  function statusOf(rec: Rec): TopicStatus {
    if (rec.revoked) return "revoked";
    const state = seq.state(rec.key);
    if (state !== "live") return state;
    return rec.stale ? "stale" : "live";
  }

  function requestResync(rec: Rec, reason: ResyncPayload["reason"]): void {
    if (rec.overflows > 1) return; // see applySnap: asking again would get the same snapshot
    const go = () => {
      counters.resyncsSent += 1;
      host.resync(rec.ch, rec.rs, { last_seq: seq.lastSeq(rec.key), reason }, rec.subId);
    };
    if (guard.request(rec.ch, go) === "deferred") counters.resyncsDeferred += 1;
  }

  /** The stream's state is void: nothing applies until the next complete `snap`, which is asked for unless the server sends it anyway. */
  function lose(rec: Rec, why: ResetReason, resync?: ResyncPayload["reason"]): void {
    seq.discard(rec.key);
    if (!rec.voided) reset(rec, why);
    rec.voided = true;
    rec.snapDue = why === "resnapshot"; // the server owes a `snap` for that one alone (C5)
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

  /** The server ended the subscription (or refused it): nothing more comes, and nothing is asked for. */
  function end(rec: Rec): void {
    rec.revoked = true;
    forget(rec);
    reset(rec, "revoked");
  }

  /**
   * A delta of a stream with no baseline is dropped unread: there is nothing to extend, and a bad
   * body must not void a stream that is already void. If a chunk set is held, the server went on
   * without it (3.6) and nothing will complete it: it is dropped and a snapshot asked for. The same
   * when `resnapshot` promised a snap and a delta comes first: the server went on without one.
   */
  function orphaned(rec: Rec): void {
    if (assembler.holds(rec.key)) {
      assembler.discard(rec.key);
      return lose(rec, "gap", "state_corrupt");
    }
    if (!rec.snapDue) return;
    rec.snapDue = false;
    requestResync(rec, "state_corrupt");
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
      get subId() {
        return rec.subId;
      },
      get effective() {
        return rec.effective;
      },
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
        if (!rec.revoked) host.unsubscribe(rec.ch, rec.rs);
      },
    };
  }

  return {
    consume(spec, rs) {
      const key = topicKey(spec.ch, rs);
      let rec = records.get(key);
      if (rec === undefined || rec.revoked) {
        // A dead stream is replaced: its old handles keep the revoked record they hold.
        rec = {
          key,
          ch: spec.ch,
          rs,
          refs: 1,
          subId: undefined,
          effective: NO_OPTIONS,
          revoked: false,
          stale: false,
          overflows: 0,
          snapDue: false,
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

    onSubOk(frame, to) {
      for (const result of frame.p.results) {
        for (const rec of targets(result.ch, to)) {
          if (!result.ok) {
            end(rec); // refused (the error goes to the error handler): nothing will be delivered
            continue;
          }
          if (isSubId(result.sub_id)) rec.subId = result.sub_id;
          // C4: what the server clamped the options to, never what was asked for.
          const options = result.effective;
          if (isRecord(options) && !beyondOptions(options)) {
            rec.effective = frozen(options);
          }
          if (result.snapshot_forced === true) counters.forcedSnapshots += 1;
        }
      }
    },

    onCtlOk(frame, to) {
      if (frame.ch === undefined) return;
      for (const rec of targets(frame.ch, to)) {
        // The keys of every retune add up, so the merge is held to the limits a frame is.
        const merged = { ...rec.effective, ...frame.p.effective };
        if (!beyondOptions(merged)) rec.effective = frozen(merged);
        if (frame.p.resnapshot !== true) continue;
        // C5: the state is void and a `snap` follows by itself (5.4): nothing to ask for, unless a
        // `d` comes first (`orphaned`). A tail of the set held now must not assemble into it.
        assembler.discard(rec.key);
        lose(rec, "resnapshot");
      }
    },

    onUnsubOk(frame, to) {
      for (const result of frame.p.results) {
        if (!result.ok) continue;
        for (const rec of targets(result.ch, to)) {
          if (seq.state(rec.key) !== "pending") continue; // a stream with a baseline is not the one unsubscribed
          assembler.forget(rec.key);
          reset(rec, "unsubscribed");
        }
      }
    },

    onRevoked(frame) {
      if (frame.ch === undefined) return;
      // 9.5: only a narrowing the server says it kept some accounts for continues.
      const narrowed =
        frame.p.reason === "account_scope_changed" && frame.p.resubscribe_allowed === true;
      for (const rec of named(frame.ch)) {
        if (frame.p.reason === "replay_session_ended" && rec.rs === undefined) continue;
        if (!narrowed) {
          end(rec);
          continue;
        }
        // Rows of a removed account must not outlive the narrowing, and with the backpressure flag
        // off the gateway sends no `reconfigure` snap, so one is asked for. A tail of the set held
        // now must not assemble into one.
        assembler.discard(rec.key);
        lose(rec, "narrowed", "state_corrupt");
      }
    },

    onData(frame, decodeMs) {
      const rec = records.get(topicKey(frame.ch, frame.rs));
      if (rec === undefined || rec.revoked) return; // in flight after an `unsub`, say
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
