// The main-thread sync registry (E11-S09 PR 2b, BQ-21, CMP-196; 26 §3.5, §6). Pure: no DOM, no
// clock, no wire of its own. It relays a worker's `sync` publication to the other workers that
// hold members of the same group, one message per worker with the origin kept (the target drops
// its own and a stale `seq`, BQ-7), and announces a group's state once per change (BQ-22): the
// member's `announce` goes out on `candleviewer:announce` under `chart:pane`. Its maps are keyed
// by app-named groups, so they are capped with the worker's caps and emptied on detach.
import type { FromWorker, ToWorker, WireSyncModes } from "../worker/protocol.js";
import { MAX_GROUP_MEMBERS, MAX_SYNC_GROUPS, SyncRefused } from "./SyncGroup.js";

/** A worker's publication, posted when its chart's `setSync` has `relay: true` (BQ-8). */
export type SyncPost = Extract<FromWorker, { t: "sync" }>;
/** What a target worker applies to its local members of the group (BQ-7). */
export type SyncRelay = Extract<ToWorker, { t: "sync" }>;

/** BQ-22 copy (C-row in the README): the modes on, in this order; "unlinked" below two members. */
export const PANES_LINKED = "Panes linked: ";
export const PANES_UNLINKED = "Panes unlinked";
const MODE_ORDER = ["time", "crosshair", "levels"] as const;

/** The announcement for a group whose members share `modes`: the modes every member has on. */
export function syncAnnouncement(modes: readonly WireSyncModes[]): string {
  if (modes.length < 2) return PANES_UNLINKED;
  const on = MODE_ORDER.filter((k) => modes.every((m) => m[k]));
  return on.length === 0 ? PANES_UNLINKED : `${PANES_LINKED}${on.join(", ")}`;
}

/** One chart as the registry sees it (the facade's host and announcer). */
export interface RegistryMember {
  /** The chart's worker id now: a restarted worker has a new one (BQ-7). */
  workerId(): string;
  /** Hands a relayed publication to the chart's host, coalesced there to one per frame. */
  post(msg: SyncRelay): void;
  /** One polite announcement (`candleviewer:announce`, key `chart:pane`). */
  announce(text: string): void;
}

export interface SyncRegistration {
  /** The chart's group (null: none) and modes. Throws `SyncRefused` past a cap. */
  set(groupId: string | null, modes: WireSyncModes): void;
  /** Relays the chart's publication to every other worker in its group. */
  relay(msg: SyncPost): void;
  /** Leaves the group (announced if that changes its state) and stops relaying. */
  detach(): void;
}

export interface SyncRegistryOptions {
  /** When the pending announcements go out; default a microtask (one per batch of changes). */
  readonly schedule?: (cb: () => void) => void;
  readonly maxGroups?: number; // default 32 (MAX_SYNC_GROUPS)
  readonly maxMembers?: number; // default 16 per group (MAX_GROUP_MEMBERS)
}

export interface SyncRegistry {
  attach(member: RegistryMember): SyncRegistration;
  /** Groups held, at most `maxGroups`. */
  readonly groupCount: number;
  /** Relays posted, and targets skipped because they run the origin's worker. */
  readonly counters: { readonly relayed: number; readonly sameWorker: number };
  dispose(): void;
}

interface Entry {
  readonly m: RegistryMember;
  group: Group | null;
  modes: WireSyncModes;
  live: boolean;
}

interface Group {
  readonly id: string;
  readonly members: Entry[];
  /** The state last announced; a group starts unlinked, so a repeat says nothing. */
  said: string;
  dirty: boolean;
  /** Who speaks when the group emptied (its last member). */
  last: Entry | null;
}

export function createSyncRegistry(o: SyncRegistryOptions = {}): SyncRegistry {
  const schedule = o.schedule ?? ((cb: () => void) => queueMicrotask(cb));
  const maxGroups = o.maxGroups ?? MAX_SYNC_GROUPS;
  const maxMembers = o.maxMembers ?? MAX_GROUP_MEMBERS;
  const groups = new Map<string, Group>();
  const dirty: Group[] = [];
  const targets: string[] = []; // reused per relay: the workers already posted to
  const counters = { relayed: 0, sameWorker: 0 };
  let queued = false;
  let disposed = false;

  function mark(g: Group, by: Entry): void {
    g.last = by;
    if (!g.dirty) {
      g.dirty = true;
      dirty.push(g);
    }
    if (queued) return;
    queued = true;
    schedule(flush);
  }

  /** Announces each changed group once; never per frame (only `set` and `detach` mark one). */
  function flush(): void {
    queued = false;
    if (disposed) return;
    const due = dirty.splice(0);
    for (const g of due) {
      g.dirty = false;
      const text = syncAnnouncement(g.members.map((e) => e.modes));
      // An emptied group speaks through its last member only while that chart is live: a
      // disposed chart's announcer is cancelled, and nobody is left to hear "Panes unlinked".
      const by = g.members[0] ?? (g.last?.live === true ? g.last : null);
      g.last = null;
      if (text !== g.said) {
        g.said = text;
        by?.m.announce(text);
      }
      if (g.members.length === 0 && groups.get(g.id) === g) groups.delete(g.id);
    }
  }

  /** Drops emptied groups now rather than at the flush, so a join in the same tick is not refused. */
  function prune(): void {
    for (const [id, g] of groups) if (g.members.length === 0) groups.delete(id);
  }

  function leave(e: Entry): void {
    const g = e.group;
    if (g === null) return;
    g.members.splice(g.members.indexOf(e), 1);
    e.group = null;
    mark(g, e);
  }

  return {
    attach(m): SyncRegistration {
      const e: Entry = {
        m,
        group: null,
        modes: { time: false, crosshair: false, levels: false },
        live: true,
      };
      return {
        set(id, modes): void {
          if (!e.live || disposed) return;
          const next = id === null ? undefined : groups.get(id);
          if (id !== null && e.group?.id !== id) {
            if (next === undefined && groups.size >= maxGroups) prune();
            if (next === undefined && groups.size >= maxGroups) {
              throw new SyncRefused(`chart-engine: at most ${maxGroups} sync groups`);
            }
            if (next !== undefined && next.members.length >= maxMembers) {
              throw new SyncRefused(`chart-engine: sync group is full (${maxMembers} charts)`);
            }
          }
          e.modes = { time: modes.time, crosshair: modes.crosshair, levels: modes.levels };
          if (e.group !== null && e.group.id !== id) leave(e);
          if (id === null) return;
          let g = next;
          if (g === undefined) {
            g = { id, members: [], said: PANES_UNLINKED, dirty: false, last: null };
            groups.set(id, g);
          }
          if (!g.members.includes(e)) g.members.push(e);
          e.group = g;
          mark(g, e);
        },
        relay(msg): void {
          const g = e.group;
          if (!e.live || g === null || g.id !== msg.groupId) return;
          const from = msg.origin.worker;
          const out: SyncRelay = {
            t: "sync",
            groupId: msg.groupId,
            ...(msg.timeRange !== undefined && { timeRange: msg.timeRange }),
            ...(msg.crosshair !== undefined && { crosshair: msg.crosshair }),
            origin: { worker: from, chart: msg.origin.chart, seq: msg.origin.seq },
          };
          targets.length = 0;
          for (const t of g.members) {
            const w = t.m.workerId();
            if (t === e || targets.includes(w)) continue;
            targets.push(w);
            if (w === from) {
              counters.sameWorker += 1; // its worker applied it already: never echoed back
              continue;
            }
            counters.relayed += 1;
            t.m.post(out);
          }
        },
        detach(): void {
          if (!e.live) return;
          leave(e);
          e.live = false;
        },
      };
    },
    get groupCount(): number {
      return groups.size;
    },
    counters,
    dispose(): void {
      disposed = true;
      groups.clear();
      dirty.length = 0;
    },
  };
}
