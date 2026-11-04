/**
 * The workspace SyncBus (E15-T03): one per workspace, keyed by group letter. A pane's handler calls
 * `publish`, which writes a per-frame slot (one per group and axis; the last write wins) and asks
 * for a frame; the flush runs once in that frame, after input integration, never inside a pointer
 * handler. That one choice gives coalescing (N writes, one dispatch per member), ordering and
 * loop-freedom: the origin token is the pane id, so only the echo is suppressed, never a third
 * member's genuine update (a boolean "applying" flag would suppress both).
 *
 * The bus holds no axis defaults (BQ-04): a group propagates nothing until `setAxes` gives it the
 * stored flags (slice 2 maps the layout). It holds members by weak reference, so it holds up no
 * unmount, and it never touches React state: nothing on the crosshair path can cause a render.
 */
import { linkedAnnouncement, unlinkedAnnouncement } from "./events";
import {
  PAYLOAD_FIELD,
  RECEIVING_KINDS,
  SYNC_AXES,
  SYNC_GROUPS,
  type MemberState,
  type SyncAxes,
  type SyncAxis,
  type SyncGroupId,
  type SyncMember,
  type SyncPayload,
} from "./types";

/** Dev counters (A-7): what a regression shows while developing, not only in CI. */
export interface SyncCounters {
  flushes: number;
  /** `apply` calls, all frames, and in the last flushed frame. */
  dispatches: number;
  lastFrameDispatches: number;
  /** Slot writes replaced before their frame flushed. */
  coalesced: number;
  suppressedEchoes: number;
  reentrancyHits: number;
  rejectedPayloads: number;
  held: number;
  /** `apply` calls that threw; the frame still reaches every other member, then rethrows. */
  applyErrors: number;
}

export type SyncAssertion = "reentrancy" | "payload_rejected";

/** Thrown in dev builds only; production counts the hit and drops the write. */
export class SyncBusAssertionError extends Error {
  constructor(readonly assertion: SyncAssertion) {
    super(`SyncBus assertion: ${assertion}`);
    this.name = "SyncBusAssertionError";
  }
}

export interface SyncBusOptions {
  /** Schedules the flush; `requestAnimationFrame` by default. */
  readonly requestFrame?: (flush: () => void) => void;
  /** Throw on an assertion; `import.meta.env.DEV` by default. */
  readonly dev?: boolean;
  /** CMP-196's one polite announcement per frame with a sync-state change (`events.ts`). */
  readonly announce?: (text: string) => void;
}

export interface MemberSnapshot extends MemberState {
  readonly paneId: string;
  readonly kind: string;
}

export interface GroupSnapshot {
  readonly group: SyncGroupId;
  readonly axes: SyncAxes;
  readonly members: readonly MemberSnapshot[];
}

export interface SyncBus {
  /** Joins `member` to `group` (leaving any other first); returns its leave. */
  join(member: SyncMember, group: SyncGroupId): () => void;
  leave(paneId: string): void;
  groupOf(paneId: string): SyncGroupId | null;
  /** The stored flags for `group` (BQ-04: no defaults here). */
  setAxes(group: SyncGroupId, axes: SyncAxes): void;
  /** Queues `payload` from `origin` for the next frame; false when refused, echoed or unjoined. */
  publish(origin: string, payload: unknown): boolean;
  snapshot(group: SyncGroupId): GroupSnapshot;
  /** Membership, axes and symbol/interval changes; never crosshair, time range or levels. */
  subscribe(listener: () => void): () => void;
  getVersion(): number;
  devCounters(): Readonly<SyncCounters>;
}

const NO_AXES: SyncAxes = {
  symbol: false,
  interval: false,
  crosshair: false,
  timeRange: false,
  drawings: false,
};
/** A sanity bound on `symbol` strings, far above any real one. */
const MAX_TEXT = 64;
/** `22` `PaneIntervalCode`'s pattern (maxLength 36); the generated type is a bare string. */
export const INTERVAL_PATTERN =
  /^(time|heikin_ashi):(1|3|5|15|30|60|120|240|360|720|D|W|M)$|^(tick|range):[1-9][0-9]{0,8}$|^(volume|delta):(0|[1-9][0-9]{0,10})(\.[0-9]{0,11}[1-9])?$|^renko:([1-9][0-9]{0,8}|atr:[1-9][0-9]{0,2})$|^pnf:[1-9][0-9]{0,8}:[1-9][0-9]{0,2}$/;

interface Entry {
  readonly ref: WeakRef<SyncMember>;
  readonly kind: string;
}
interface Write {
  readonly origin: string;
  readonly payload: SyncPayload;
}

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isText = (v: unknown): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= MAX_TEXT;

/** A plain object's own string keys, or null for anything else (no inherited or symbol keys). */
function ownPlainKeys(value: unknown): string[] | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const proto: unknown = Object.getPrototypeOf(value);
  if (proto !== Object.prototype && proto !== null) return null;
  const keys = Reflect.ownKeys(value);
  return keys.every((k) => typeof k === "string") ? (keys as string[]) : null;
}

/**
 * The allow-list (A-4): `axis` plus exactly its one field, of the right shape; nothing else. Each
 * property is read once and the result is a frozen copy built from those reads, so what members
 * get is exactly what was checked.
 */
export function toSyncPayload(value: unknown): SyncPayload | null {
  const keys = ownPlainKeys(value);
  if (keys === null || keys.length !== 2 || !keys.includes("axis")) return null;
  const record = value as Record<string, unknown>;
  const axis = record["axis"];
  if (typeof axis !== "string" || !(SYNC_AXES as readonly string[]).includes(axis)) return null;
  const field = PAYLOAD_FIELD[axis as SyncAxis];
  if (!keys.includes(field)) return null;
  const v = record[field];
  const make = (x: unknown): SyncPayload => Object.freeze({ axis, [field]: x }) as SyncPayload;
  switch (axis as SyncAxis) {
    case "symbol":
      return isText(v) ? make(v) : null;
    case "interval":
      return typeof v === "string" && v.length <= 36 && INTERVAL_PATTERN.test(v) ? make(v) : null;
    case "crosshair":
      return v === null || isFiniteNumber(v) ? make(v) : null;
    case "drawings":
      return isFiniteNumber(v) ? make(v) : null;
    case "timeRange": {
      const wk = ownPlainKeys(v);
      if (wk === null || wk.length !== 2 || !wk.includes("from") || !wk.includes("to")) return null;
      const w = v as Record<string, unknown>;
      const from = w["from"];
      const to = w["to"];
      return isFiniteNumber(from) && isFiniteNumber(to) && from < to
        ? make(Object.freeze({ from, to }))
        : null;
    }
  }
}

export const isSyncPayload = (value: unknown): value is SyncPayload =>
  toSyncPayload(value) !== null;

/** The value an echo is compared by. */
function valueKey(p: SyncPayload): string | number | null {
  switch (p.axis) {
    case "symbol":
      return p.symbol;
    case "interval":
      return p.interval;
    case "crosshair":
      return p.crosshair;
    case "drawings":
      return p.priceLevel;
    case "timeRange":
      return `${p.timeRange.from}:${p.timeRange.to}`;
  }
}

function defaultFrame(flush: () => void): void {
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => flush());
  else setTimeout(flush, 0);
}

export function createSyncBus(options: SyncBusOptions = {}): SyncBus {
  const requestFrame = options.requestFrame ?? defaultFrame;
  const dev = options.dev ?? import.meta.env.DEV;
  const rosters = new Map<SyncGroupId, Map<string, Entry>>(SYNC_GROUPS.map((g) => [g, new Map()]));
  const axesOf = new Map<SyncGroupId, SyncAxes>();
  const groupIndex = new Map<string, SyncGroupId>();
  /**
   * The origin token's memory: the value each member was given, per axis, in this flush (`given`)
   * and the one before (`aging`). It expires at the end of the flush after the one that wrote it,
   * which covers the engine's one-frame echo and nothing more.
   */
  type Memory = Map<string, Map<SyncAxis, string | number | null>>;
  let given: Memory = new Map();
  let aging: Memory = new Map();
  let slots = new Map<SyncGroupId, Map<SyncAxis, Write>>();
  let spare = new Map<SyncGroupId, Map<SyncAxis, Write>>();
  const listeners = new Set<() => void>();
  const announced = new Map<SyncGroupId, string | null>();
  const counters: SyncCounters = {
    flushes: 0,
    dispatches: 0,
    lastFrameDispatches: 0,
    coalesced: 0,
    suppressedEchoes: 0,
    reentrancyHits: 0,
    rejectedPayloads: 0,
    held: 0,
    applyErrors: 0,
  };
  let version = 0;
  let scheduled = false;
  let flushing = false;
  let structural = false;
  let membershipChanged = false;
  const deferred: SyncAssertion[] = [];
  const thrown: unknown[] = [];

  const fail = (assertion: SyncAssertion): void => {
    if (!dev) return;
    if (flushing) deferred.push(assertion);
    else throw new SyncBusAssertionError(assertion);
  };
  const notify = (): void => {
    version += 1;
    // Each listener is guarded on its own: one throwing does not skip the others. The first error
    // is rethrown after the loop (the flush defers it with the others); nothing is allocated unless
    // a listener throws.
    let first: { error: unknown } | undefined;
    for (const listener of [...listeners]) {
      try {
        listener();
      } catch (error) {
        first ??= { error };
      }
    }
    if (first !== undefined) throw first.error;
  };
  const guarded = (run: () => void): void => {
    try {
      run();
    } catch (error) {
      thrown.push(error);
    }
  };
  const schedule = (): void => {
    if (scheduled) return;
    scheduled = true;
    requestFrame(flush);
  };
  const changed = (): void => {
    membershipChanged = true;
    notify();
    schedule();
  };

  /** Removes a pane without notifying: `leave`'s body, and the sweep of collected members. */
  function drop(paneId: string): void {
    const group = groupIndex.get(paneId);
    if (group === undefined) return;
    groupIndex.delete(paneId);
    rosters.get(group)?.delete(paneId);
    given.delete(paneId);
    aging.delete(paneId);
    const writes = slots.get(group);
    if (writes === undefined) return;
    for (const [axis, write] of writes) if (write.origin === paneId) writes.delete(axis);
  }

  /** The group's roster without members collected unleft, so they never read as linked. */
  function prune(group: SyncGroupId): Map<string, Entry> {
    const roster = rosters.get(group) ?? new Map<string, Entry>();
    for (const [paneId, entry] of roster) {
      if (entry.ref.deref() !== undefined) continue;
      drop(paneId);
      membershipChanged = true;
      schedule();
    }
    return roster;
  }

  /** Every group whose linked state changed this frame, in one message (none dropped). */
  function announceLinks(): void {
    const texts: string[] = [];
    for (const group of SYNC_GROUPS) {
      const on = axesOf.get(group) ?? NO_AXES;
      const linked = prune(group).size >= 2 ? linkedAnnouncement(group, on) : null;
      if (linked === (announced.get(group) ?? null)) continue;
      announced.set(group, linked);
      texts.push(linked ?? unlinkedAnnouncement(group));
    }
    if (texts.length > 0) options.announce?.(texts.join(" "));
  }

  function dispatch(roster: Map<string, Entry>, write: Write): number {
    const { axis } = write.payload;
    const origin = roster.get(write.origin)?.ref.deref();
    if (origin === undefined) return 0;
    const levelSymbol = axis === "drawings" ? origin.current().symbol : null;
    if (axis === "drawings" && levelSymbol === null) return 0;
    const key = valueKey(write.payload);
    const receivers = RECEIVING_KINDS[axis];
    let count = 0;
    for (const [paneId, entry] of roster) {
      if (paneId === write.origin || !receivers.has(entry.kind)) continue;
      const member = entry.ref.deref();
      if (member === undefined) {
        bus.leave(paneId);
        continue;
      }
      let memory = given.get(paneId);
      if (memory === undefined) given.set(paneId, (memory = new Map()));
      try {
        // Drawings reach members on the origin's symbol only (D-8, AD-4).
        if (levelSymbol !== null && member.current().symbol !== levelSymbol) continue;
        memory.set(axis, key);
        count += 1;
        if (member.apply(write.payload) === "held") {
          counters.held += 1;
          memory.delete(axis);
        }
      } catch (error) {
        // One failing member never costs the others their frame (rethrown after it).
        counters.applyErrors += 1;
        memory.delete(axis);
        thrown.push(error);
      }
    }
    return count;
  }

  function flush(): void {
    scheduled = false;
    flushing = true;
    const pending = slots;
    slots = spare;
    spare = pending;
    let count = 0;
    try {
      for (const [group, writes] of pending) {
        const roster = rosters.get(group);
        const on = axesOf.get(group) ?? NO_AXES;
        if (roster === undefined) continue;
        for (const write of writes.values()) {
          if (on[write.payload.axis]) count += dispatch(roster, write);
        }
      }
    } finally {
      pending.clear();
      flushing = false;
      counters.flushes += 1;
      counters.dispatches += count;
      counters.lastFrameDispatches = count;
    }
    // Expire the previous flush's memory; one more frame expires this one's. Rotating comes first
    // so a throwing listener or announcer cannot skip it; emptied inner maps are pruned so they
    // do not schedule a no-op frame.
    [aging, given] = [given, aging];
    given.clear();
    for (const [paneId, memory] of aging) if (memory.size === 0) aging.delete(paneId);
    if (aging.size > 0) schedule();
    if (structural) {
      structural = false;
      guarded(notify);
    }
    if (membershipChanged) {
      membershipChanged = false;
      guarded(announceLinks);
    }
    const failed = thrown.length > 0;
    const error = thrown[0];
    thrown.length = 0;
    const first = deferred[0];
    deferred.length = 0;
    if (failed) throw error;
    if (first !== undefined) throw new SyncBusAssertionError(first);
  }

  const bus: SyncBus = {
    join(member, group) {
      const { paneId } = member;
      if (
        groupIndex.get(paneId) !== group ||
        rosters.get(group)?.get(paneId)?.ref.deref() !== member
      ) {
        bus.leave(paneId);
        rosters.get(group)?.set(paneId, { ref: new WeakRef(member), kind: member.kind });
        groupIndex.set(paneId, group);
        changed();
      }
      let done = false;
      return () => {
        if (done) return;
        done = true;
        if (rosters.get(group)?.get(paneId)?.ref.deref() === member) bus.leave(paneId);
      };
    },
    leave(paneId) {
      if (!groupIndex.has(paneId)) return;
      drop(paneId);
      changed();
    },
    groupOf: (paneId) => groupIndex.get(paneId) ?? null,
    setAxes(group, axes) {
      const prior = axesOf.get(group);
      if (prior !== undefined && SYNC_AXES.every((a) => prior[a] === axes[a])) return;
      axesOf.set(group, { ...axes });
      changed();
    },
    publish(origin, payload) {
      const stored = toSyncPayload(payload); // members get the checked frozen copy
      if (stored === null) {
        counters.rejectedPayloads += 1;
        fail("payload_rejected");
        return false;
      }
      const group = groupIndex.get(origin);
      if (group === undefined) return false;
      const { axis } = stored;
      const memory = given.get(origin)?.has(axis) ? given.get(origin) : aging.get(origin);
      if (memory?.has(axis) === true) {
        const echoed = memory.get(axis) === valueKey(stored);
        memory.delete(axis);
        if (echoed) {
          counters.suppressedEchoes += 1;
          return false;
        }
      }
      if (flushing) {
        counters.reentrancyHits += 1;
        fail("reentrancy");
        return false;
      }
      let writes = slots.get(group);
      if (writes === undefined) slots.set(group, (writes = new Map()));
      if (writes.has(axis)) counters.coalesced += 1;
      writes.set(axis, { origin, payload: stored });
      if (axis === "symbol" || axis === "interval") structural = true;
      schedule();
      return true;
    },
    snapshot(group) {
      const members: MemberSnapshot[] = [];
      for (const [paneId, entry] of prune(group)) {
        const member = entry.ref.deref();
        if (member !== undefined) members.push({ paneId, kind: entry.kind, ...member.current() });
      }
      return { group, axes: axesOf.get(group) ?? NO_AXES, members };
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    getVersion: () => version,
    devCounters: () => ({ ...counters }),
  };
  return bus;
}
