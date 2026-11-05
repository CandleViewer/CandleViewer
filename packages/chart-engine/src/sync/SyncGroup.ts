// The worker-side sync group core (E11-S09 PR 2a, CMP-196; 26 §3.5). Pure: no DOM, no clock,
// no wire. A member publishes at most once per frame; `flush()` hands the last publication of
// each group to every other member, so a group propagates at most once per frame and a member
// never receives its own publication (echo-free by construction, BQ-13). The engine never
// invents or persists a group id: the app names them (BQ-9).

/** BQ-17: what a member shares. `scale` is reserved (BQ-24 AMEND): typed, off, refused if set. */
export interface SyncModes {
  readonly time: boolean;
  readonly crosshair: boolean;
  /** BQ-18: the flag ships; the price-level payload is E14's (no drawing exists yet). */
  readonly levels: boolean;
  readonly scale: boolean;
}

export const DEFAULT_SYNC_MODES: SyncModes = Object.freeze({
  time: true,
  crosshair: true,
  levels: false,
  scale: false,
});

/** Bounds (C-2.18): groups per worker and members per group; past them a join is refused. */
export const MAX_SYNC_GROUPS = 32;
export const MAX_GROUP_MEMBERS = 16;
/**
 * BQ-7s: remote origins `(worker, chart)` whose last `seq` a group remembers. Past the bound the
 * least recently seen origin is forgotten, so its next publication is accepted whatever its
 * `seq` (a replay from an origin idle across 64 newer ones is not detected).
 */
export const MAX_SYNC_ORIGINS = 64;
export const ENGINE_SYNC_REFUSED = "ENGINE_SYNC_REFUSED";

/** A recoverable refusal: a full group, too many groups, or a reserved mode set. */
export class SyncRefused extends Error {
  readonly code = ENGINE_SYNC_REFUSED;
  readonly recoverable = true;
}

/** BQ-24: `scale: true` is refused with an error, never silently ignored. */
export function checkSyncModes(modes: Partial<SyncModes>): SyncModes {
  if (modes.scale === true) {
    throw new SyncRefused("chart-engine: sync mode `scale` is reserved and cannot be enabled");
  }
  return { ...DEFAULT_SYNC_MODES, ...modes, scale: false };
}

/** One publication, reused per group (no per-frame allocation). Times are µs. */
export class SyncPublication {
  hasTime = false;
  timeStart = 0;
  timeEnd = 0;
  hasCrosshair = false;
  crosshair: number | null = null;
  /** BQ-7's origin token: the worker id, the chart and that chart's publication counter. */
  worker = "";
  chart = -1;
  seq = 0;
}

export interface SyncMember {
  readonly id: number;
  modes: SyncModes;
  /** Applies a peer's publication: never sets the member's own "moved" state (BQ-13). */
  applySync(p: SyncPublication): void;
}

export class SyncGroup<M extends SyncMember> {
  readonly members: M[] = [];
  readonly pub = new SyncPublication();
  /** The publisher of `pub`, or null when nothing is pending. */
  from: M | null = null;
  /** `engine.sync.propagations_per_frame`: the last flushed frame's count, and the most seen. */
  propagations = 0;
  propagationsMax = 0;
  /** BQ-7s: the last `seq` applied per inbound origin, least recently seen first (bounded). */
  private readonly seqs = new Map<string, number>();

  constructor(readonly id: string) {}

  /**
   * Stages `from`'s state for this frame: the last publisher in a frame wins. Returns false when
   * the member's modes share nothing that moved.
   */
  publish(
    from: M,
    moved: boolean,
    timeStart: number,
    timeEnd: number,
    crosshairMoved: boolean,
    crosshair: number | null,
  ): boolean {
    const time = moved && from.modes.time;
    const cross = crosshairMoved && from.modes.crosshair;
    if (!time && !cross) return false;
    const p = this.pub;
    p.hasTime = time;
    p.timeStart = timeStart;
    p.timeEnd = timeEnd;
    p.hasCrosshair = cross;
    p.crosshair = crosshair;
    p.chart = from.id;
    this.from = from;
    return true;
  }

  /** Applies the pending publication to every other member; at most one propagation. */
  flush(): number {
    const from = this.from;
    this.propagations = 0;
    if (from === null) return 0;
    this.from = null;
    this.propagations = 1;
    if (this.propagationsMax < 1) this.propagationsMax = 1;
    return this.deliver(from.id, this.pub);
  }

  /** Delivers `p` to every member but `skip` whose modes take a part of it; returns the count. */
  deliver(skip: number, p: SyncPublication): number {
    let n = 0;
    const ms = this.members;
    for (let i = 0; i < ms.length; i += 1) {
      const m = ms[i] as M;
      if (m.id === skip) continue;
      if (!((p.hasTime && m.modes.time) || (p.hasCrosshair && m.modes.crosshair))) continue;
      m.applySync(p);
      n += 1;
    }
    return n;
  }

  /**
   * BQ-7s: false for a `seq` at or below the last one applied from the same origin
   * `(worker, chart)`, however origins interleave. Inbound only (one message each), never per frame.
   */
  accept(worker: string, chart: number, seq: number): boolean {
    const key = `${chart}/${worker}`; // a wire worker id never contains "/" (GROUP_ID_PATTERN)
    const last = this.seqs.get(key);
    if (last !== undefined && seq <= last) return false;
    if (last === undefined && this.seqs.size >= MAX_SYNC_ORIGINS) {
      const oldest = this.seqs.keys().next(); // the least recently seen origin
      if (oldest.done !== true) this.seqs.delete(oldest.value);
    }
    this.seqs.delete(key); // re-inserted below: most recently seen
    this.seqs.set(key, seq);
    return true;
  }

  /** The origins remembered (BQ-7s), at most `MAX_SYNC_ORIGINS`. */
  get originCount(): number {
    return this.seqs.size;
  }
}

/** Every group on one worker, bounded; a member is in at most one group. */
export class SyncGroups<M extends SyncMember> {
  readonly groups = new Map<string, SyncGroup<M>>();
  /** The groups as an array, so `flush()` iterates without an iterator. */
  private readonly list: SyncGroup<M>[] = [];

  constructor(
    readonly maxGroups = MAX_SYNC_GROUPS,
    readonly maxMembers = MAX_GROUP_MEMBERS,
  ) {}

  get(id: string): SyncGroup<M> | undefined {
    return this.groups.get(id);
  }

  /** The member's group, or undefined. */
  of(m: M): SyncGroup<M> | undefined {
    for (let i = 0; i < this.list.length; i += 1) {
      const g = this.list[i] as SyncGroup<M>;
      if (g.members.includes(m)) return g;
    }
    return undefined;
  }

  /** Moves `m` into group `id` (null: out of every group). Throws `SyncRefused` past a cap. */
  join(m: M, id: string | null): SyncGroup<M> | undefined {
    const current = this.of(m);
    if (current?.id === id) return current;
    let next: SyncGroup<M> | undefined;
    if (id !== null) {
      next = this.groups.get(id);
      if (next === undefined && this.list.length >= this.maxGroups) {
        throw new SyncRefused(`chart-engine: at most ${this.maxGroups} sync groups`);
      }
      if (next !== undefined && next.members.length >= this.maxMembers) {
        throw new SyncRefused(`chart-engine: sync group is full (${this.maxMembers} charts)`);
      }
    }
    if (current !== undefined) this.leave(m);
    if (id === null) return undefined;
    if (next === undefined) {
      next = new SyncGroup<M>(id);
      this.groups.set(id, next);
      this.list.push(next);
    }
    next.members.push(m);
    return next;
  }

  /** Removes `m` from its group; an emptied group is dropped. */
  leave(m: M): void {
    const g = this.of(m);
    if (g === undefined) return;
    g.members.splice(g.members.indexOf(m), 1);
    if (g.from === m) g.from = null;
    if (g.members.length > 0) return;
    this.groups.delete(g.id);
    this.list.splice(this.list.indexOf(g), 1);
  }

  /** Flushes every group once (26 §3.5 step 4); returns the members it applied to. */
  flush(): number {
    let n = 0;
    for (let i = 0; i < this.list.length; i += 1) n += (this.list[i] as SyncGroup<M>).flush();
    return n;
  }
}
