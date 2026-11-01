// The worker-side sync groups (E11-S09 PR 2, #446 BQ-7, BQ-12, BQ-13; 26 §3.5): charts in a group
// share their time range and/or crosshair time, propagated once per frame after every chart's
// input and layout (`flush`, the middle phase of the runtime's tick), never re-entrantly. Pure:
// no DOM, no I/O; the runtime is reached through `SyncTarget`. Echo-free by construction: only a
// chart's own local change is published, an applied value is never published back, the winner of
// a frame (the later input) is never applied to, and a publication made while a propagation is
// being applied is an echo: counted and dropped.

/** E11-S09 (BQ-9, BQ-17): what a member shares. `levels` is the flag only (BQ-18). */
export interface SyncModes {
  readonly time: boolean;
  readonly crosshair: boolean;
  readonly levels: boolean;
}

/** E11-D01 D1 (Q1-h(4)): time and crosshair on, levels off. */
export const DEFAULT_SYNC_MODES: SyncModes = Object.freeze({
  time: true,
  crosshair: true,
  levels: false,
});

/**
 * BQ-7: who propagated: the worker (`init.config.workerId`), its chart and the worker's relay
 * seq, which rises across every group and never restarts while the worker lives (a group that
 * empties and is re-made keeps counting up, so peers never drop it as stale).
 */
export interface SyncOrigin {
  readonly worker: string;
  readonly chart: number;
  readonly seq: number;
}

/** `engine.sync.*` (BQ-13), internal: read through `RenderRuntime.syncCounters`. */
export interface SyncCounters {
  /** The most propagations any one group made in the last flush (≤ 1 by construction). */
  propagationsPerFrame: number;
  /** The most ever seen in one flush. */
  maxPropagationsPerFrame: number;
  /** Group propagations in total (one per group per frame with a publication). */
  propagations: number;
  /** Charts in a group, all groups together. */
  groupMembers: number;
  /**
   * A hub-level guard: publications made while a propagation was being applied, refused. The
   * runtime absorbs changes made in the apply phase before publishing (`publish`), so it never
   * reaches this; it counts a future caller that publishes from inside an application.
   */
  echoes: number;
  /** Remote propagations dropped: this worker's own origin, or a stale seq. */
  dropped: number;
}

/** The runtime side: applies a propagation to one member, never marking it a local change. */
export interface SyncTarget {
  applyTime(chart: number, timeStart: number, timeEnd: number): void;
  applyCrosshair(chart: number, time: number | null): void;
  /** A relay group propagated (BQ-8): post it for the main-thread registry. */
  relay(groupId: string, payload: SyncPayload): void;
}

/** One propagation, as relayed (BQ-8) or received (BQ-7). */
export interface SyncPayload {
  readonly timeRange?: readonly [number, number];
  readonly crosshair?: number | null;
  readonly origin: SyncOrigin;
}

interface Member {
  readonly chart: number;
  modes: SyncModes;
  relay: boolean;
}

/** One group: its members and this frame's pending publication, one slot per field. */
class Group {
  /** In join order; a plain array, so the per-frame walks allocate nothing. */
  readonly members: Member[] = [];
  /** The time publisher this frame (-1: none), its input time and range. */
  timeFrom = -1;
  timeAt = Number.NEGATIVE_INFINITY;
  t0 = 0;
  t1 = 0;
  /** The crosshair publisher this frame (-1: none), its input time and value. */
  crossFrom = -1;
  crossAt = Number.NEGATIVE_INFINITY;
  cross: number | null = null;
  /** The last range propagated or received: a member joining with time on adopts it. */
  hasLast = false;
  lastT0 = 0;
  lastT1 = 0;
  /** Propagations since the tick began (`beginFrame`): ≤ 1 by construction. */
  inFrame = 0;
  /** The last relay seq applied from each origin worker for this group (BQ-7). */
  readonly seen = new Map<string, number>();

  constructor(readonly id: string) {}

  member(chart: number): Member | undefined {
    for (let i = 0; i < this.members.length; i += 1) {
      if ((this.members[i] as Member).chart === chart) return this.members[i];
    }
    return undefined;
  }

  get relay(): boolean {
    for (let i = 0; i < this.members.length; i += 1)
      if ((this.members[i] as Member).relay) return true;
    return false;
  }
}

/** One worker's groups: membership, the per-frame publications and the flush. */
export class SyncHub {
  readonly counters: SyncCounters = {
    propagationsPerFrame: 0,
    maxPropagationsPerFrame: 0,
    propagations: 0,
    groupMembers: 0,
    echoes: 0,
    dropped: 0,
  };
  private readonly groups = new Map<string, Group>();
  /** The same groups as a plain array, kept on join and leave (m2): no per-frame iterator. */
  private readonly list: Group[] = [];
  /** This worker's relay seq (BQ-7): one counter for every group, never reset (M1). */
  private seq = 0;
  /** Groups made so far (the allocation check: the per-frame path makes none). */
  created = 0;
  private readonly of = new Map<number, Group>();
  /** True while a propagation is being applied: a publication now is an echo. */
  private applying = false;

  constructor(
    private readonly target: SyncTarget,
    /** This worker's id (`init.config.workerId`); "" when the host gave none. */
    public worker = "",
  ) {}

  /** The chart's group id, or null. */
  groupOf(chart: number): string | null {
    return this.of.get(chart)?.id ?? null;
  }

  modesOf(chart: number): SyncModes | null {
    return this.of.get(chart)?.member(chart)?.modes ?? null;
  }

  /**
   * BQ-9: joins `groupId` (null leaves). Joining with time on adopts the group's last range,
   * applied as a sync (never a local change). Returns true when the group changed.
   */
  join(chart: number, groupId: string | null, modes: SyncModes, relay = false): boolean {
    const old = this.of.get(chart);
    if (old !== undefined && old.id === groupId) {
      const m = old.member(chart) as Member;
      m.modes = modes;
      m.relay = relay;
      return false;
    }
    this.leave(chart);
    if (groupId === null) return old !== undefined;
    let g = this.groups.get(groupId);
    if (g === undefined) {
      g = new Group(groupId);
      this.groups.set(groupId, g);
      this.list.push(g);
      this.created += 1;
    }
    g.members.push({ chart, modes, relay });
    this.of.set(chart, g);
    this.counters.groupMembers += 1;
    if (modes.time && g.hasLast) {
      this.applying = true;
      try {
        this.target.applyTime(chart, g.lastT0, g.lastT1);
      } finally {
        this.applying = false;
      }
    }
    return true;
  }

  /** Leaves the chart's group (release, `setSync(null)`); its pending publication goes too. */
  leave(chart: number): void {
    const g = this.of.get(chart);
    if (g === undefined) return;
    g.members.splice(g.members.indexOf(g.member(chart) as Member), 1);
    this.of.delete(chart);
    this.counters.groupMembers -= 1;
    if (g.timeFrom === chart) g.timeFrom = -1;
    if (g.crossFrom === chart) g.crossFrom = -1;
    if (g.members.length === 0) {
      this.groups.delete(g.id);
      this.list.splice(this.list.indexOf(g), 1);
    }
  }

  /**
   * BQ-13: a member's own local move this frame. Of two in one frame the later input (`at`) wins;
   * a tie goes to the later call. False when dropped (no group, mode off, or an echo).
   */
  publishTime(chart: number, at: number, timeStart: number, timeEnd: number): boolean {
    const g = this.of.get(chart);
    if (g === undefined || g.member(chart)?.modes.time !== true) return false;
    if (this.echo()) return false;
    if (g.timeFrom >= 0 && g.timeAt > at) return false;
    g.timeFrom = chart;
    g.timeAt = at;
    g.t0 = timeStart;
    g.t1 = timeEnd;
    return true;
  }

  /** BQ-13: a member's own local crosshair time (null once hidden), as `publishTime`. */
  publishCrosshair(chart: number, at: number, time: number | null): boolean {
    const g = this.of.get(chart);
    if (g === undefined || g.member(chart)?.modes.crosshair !== true) return false;
    if (this.echo()) return false;
    if (g.crossFrom >= 0 && g.crossAt > at) return false;
    g.crossFrom = chart;
    g.crossAt = at;
    g.cross = time;
    return true;
  }

  /** The tick began: every group's per-frame propagation count restarts. */
  beginFrame(): void {
    for (let i = 0; i < this.list.length; i += 1) (this.list[i] as Group).inFrame = 0;
    this.counters.propagationsPerFrame = 0;
  }

  /**
   * BQ-12: the tick's middle phase. Each group with a publication propagates once: the range to
   * every member with time on but its publisher, the crosshair likewise; a relay group is posted.
   * Returns the groups that propagated.
   */
  flush(): number {
    let n = 0;
    const c = this.counters;
    for (let i = 0; i < this.list.length; i += 1) {
      const g = this.list[i] as Group;
      if (g.timeFrom < 0 && g.crossFrom < 0) continue;
      n += 1;
      this.propagate(g, g.timeFrom >= 0, g.crossFrom >= 0);
      g.timeFrom = -1;
      g.crossFrom = -1;
      g.timeAt = g.crossAt = Number.NEGATIVE_INFINITY;
      g.inFrame += 1;
      c.propagationsPerFrame = Math.max(c.propagationsPerFrame, g.inFrame);
    }
    c.maxPropagationsPerFrame = Math.max(c.maxPropagationsPerFrame, c.propagationsPerFrame);
    return n;
  }

  /**
   * BQ-7: a propagation from another worker, applied to every local member (by mode) at once.
   * Dropped (and counted) when its origin is this worker or its seq is not newer than the last
   * applied from that origin worker for the group.
   */
  receive(groupId: string, p: Omit<SyncPayload, "origin"> & { origin?: SyncOrigin }): boolean {
    const o = p.origin;
    const g = this.groups.get(groupId);
    if (o !== undefined) {
      const stale = g !== undefined && o.seq <= (g.seen.get(o.worker) ?? -1);
      if ((this.worker !== "" && o.worker === this.worker) || stale) {
        this.counters.dropped += 1;
        return false;
      }
      g?.seen.set(o.worker, o.seq);
    }
    if (g === undefined) return false;
    const range = p.timeRange;
    this.applying = true;
    try {
      for (let i = 0; i < g.members.length; i += 1) {
        const m = g.members[i] as Member;
        if (m.modes.time && range !== undefined) this.target.applyTime(m.chart, range[0], range[1]);
        if (m.modes.crosshair && p.crosshair !== undefined) {
          this.target.applyCrosshair(m.chart, p.crosshair);
        }
      }
    } finally {
      this.applying = false;
    }
    if (p.timeRange !== undefined) this.remember(g, p.timeRange[0], p.timeRange[1]);
    return true;
  }

  private propagate(g: Group, time: boolean, cross: boolean): void {
    this.applying = true;
    try {
      for (let i = 0; i < g.members.length; i += 1) {
        const m = g.members[i] as Member;
        if (time && m.chart !== g.timeFrom && m.modes.time) {
          this.target.applyTime(m.chart, g.t0, g.t1);
        }
        if (cross && m.chart !== g.crossFrom && m.modes.crosshair) {
          this.target.applyCrosshair(m.chart, g.cross);
        }
      }
    } finally {
      this.applying = false;
    }
    if (time) this.remember(g, g.t0, g.t1);
    this.counters.propagations += 1;
    if (!g.relay) return;
    this.seq += 1;
    const origin = { worker: this.worker, chart: time ? g.timeFrom : g.crossFrom, seq: this.seq };
    this.target.relay(g.id, {
      ...(time && { timeRange: [g.t0, g.t1] as const }),
      ...(cross && { crosshair: g.cross }),
      origin,
    });
  }

  private remember(g: Group, t0: number, t1: number): void {
    g.hasLast = true;
    g.lastT0 = t0;
    g.lastT1 = t1;
  }

  private echo(): boolean {
    if (!this.applying) return false;
    this.counters.echoes += 1;
    return true;
  }
}
