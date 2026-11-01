// The main-thread sync registry (E11-S09 PR 2, #446 BQ-21): which chart is in which group across
// every host on the page, the `relay` flag each member's worker gets (on when its group spans
// more than one worker link), the relay of a worker's propagation to the group's other links
// (origin kept), and one announcement per group per state change. Propagation inside one worker
// never comes here (ticket Scope); with one worker per page nothing is relayed. DOM-free: each
// member brings its own `say` (the facade's `candleviewer:announce` writer, key `chart:sync`).
import type { Command, FromWorker, SyncMessage } from "../worker/protocol.js";
import { type SyncModes } from "./SyncGroup.js";

/** BQ-21: the shell announcer's key for the group state (never the axes' or the magnet's). */
export const SYNC_ANNOUNCE_KEY = "chart:sync";

/** E11-D02 copy (BQ-21): the modes in the order time, crosshair, levels; none is unlinked. */
export function syncText(modes: SyncModes | null): string {
  if (modes === null) return "Panes unlinked";
  const on: string[] = [];
  if (modes.time) on.push("time");
  if (modes.crosshair) on.push("crosshair");
  if (modes.levels) on.push("levels");
  return on.length === 0 ? "Panes unlinked" : `Panes linked: ${on.join(", ")}`;
}

/** One chart as the registry sees it: its host's link, its commands, relays and announcer. */
export interface SyncMember {
  /** The worker link it runs on: two members on one link share a worker. */
  readonly link: object;
  command(cmd: Command): void;
  sync(groupId: string, payload: Omit<SyncMessage, "t" | "groupId">): void;
  /** Announces politely through this chart (once per call). */
  say(text: string): void;
}

interface Entry {
  readonly groupId: string;
  readonly modes: SyncModes;
  relay: boolean;
}

type SyncRelay = Extract<FromWorker, { t: "sync" }>;

export class SyncRegistry {
  private readonly entries = new Map<SyncMember, Entry>();
  /** The state last announced per group; an unseen group reads as unlinked. */
  private readonly said = new Map<string, string>();

  /** The member's group and modes, or null. */
  groupOf(member: SyncMember): { groupId: string; modes: SyncModes; relay: boolean } | null {
    const e = this.entries.get(member);
    return e === undefined ? null : { groupId: e.groupId, modes: e.modes, relay: e.relay };
  }

  /**
   * BQ-9, BQ-21: joins `groupId` with `modes` (null leaves). The member gets its `setSync`; every
   * member whose `relay` flips gets one too. A group whose state changed is announced once.
   */
  set(member: SyncMember, groupId: string | null, modes: SyncModes): void {
    const prev = this.entries.get(member);
    if (groupId === null) this.entries.delete(member);
    else this.entries.set(member, { groupId, modes, relay: prev?.relay ?? false });
    if (groupId === null) member.command({ k: "setSync", groupId: null, modes, relay: false });
    this.settle(prev?.groupId ?? null, groupId, member, member);
  }

  /** A disposed chart leaves; the group's remaining members carry the announcement. */
  remove(member: SyncMember): void {
    const prev = this.entries.get(member);
    if (prev === undefined) return;
    this.entries.delete(member);
    this.settle(prev.groupId, null, null, null);
  }

  /**
   * BQ-8, BQ-21: a worker's propagation goes to one member on each other link of its group, the
   * origin kept (that worker drops its own; a stale seq is dropped too). Never back to `from`'s.
   */
  relay(from: SyncMember, msg: SyncRelay): void {
    const e = this.entries.get(from);
    if (e === undefined || e.groupId !== msg.groupId) return;
    const sent: object[] = [from.link];
    for (const [m, x] of this.entries) {
      if (x.groupId !== msg.groupId || sent.includes(m.link)) continue;
      sent.push(m.link);
      m.sync(msg.groupId, {
        ...(msg.timeRange !== undefined && { timeRange: msg.timeRange }),
        ...(msg.crosshair !== undefined && { crosshair: msg.crosshair }),
        origin: msg.origin,
      });
    }
  }

  /**
   * Re-flags the groups a change touched (`before` and `after`) and announces at most once per
   * call under `chart:sync` (m4). A switch from group A to B touches two groups; E11-D01/D02 have
   * copy for one state only ("Panes linked: …" / "Panes unlinked"), so the speaker's new state is
   * said: B's when it changed, else A's. The other group's state is recorded without a word.
   */
  private settle(
    before: string | null,
    after: string | null,
    changed: SyncMember | null,
    speaker: SyncMember | null,
  ): void {
    let say: string | null = null;
    let by: SyncMember | null = speaker;
    for (const g of before === after ? [after] : [after, before]) {
      if (g === null) continue;
      const members = [...this.entries].filter(([, e]) => e.groupId === g);
      const relay = new Set(members.map(([m]) => m.link)).size > 1;
      for (const [m, e] of members) {
        if (m !== changed && e.relay === relay) continue;
        e.relay = relay;
        m.command({ k: "setSync", groupId: g, modes: e.modes, relay });
      }
      const text = syncText(members.length < 2 ? null : union(members.map(([, e]) => e.modes)));
      if (text === (this.said.get(g) ?? syncText(null))) continue;
      if (members.length === 0) this.said.delete(g);
      else this.said.set(g, text);
      if (say !== null) continue; // the new group's state was said already
      say = text;
      by = speaker ?? members[0]?.[0] ?? null;
    }
    if (say !== null) by?.say(say);
  }
}

const union = (all: readonly SyncModes[]): SyncModes => ({
  time: all.some((m) => m.time),
  crosshair: all.some((m) => m.crosshair),
  levels: all.some((m) => m.levels),
});

const registries = new WeakMap<object, SyncRegistry>();

/** The one registry per realm (as the host's one link per realm and mode). */
export function syncRegistryFor(realm: object): SyncRegistry {
  let r = registries.get(realm);
  if (r === undefined) {
    r = new SyncRegistry();
    registries.set(realm, r);
  }
  return r;
}
