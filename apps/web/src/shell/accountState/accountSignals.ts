/**
 * The account-level signals (E29-S01 #911, BQ-14), lifted to the shell by E29-S07 (#1028; BQ-5 of
 * the ruling of record 6575172489, and BQ-2 ruled (6610918411): lifted on `main`'s file) so the
 * `recovered` region, the reassurance and every new-exposure control read one store. The mapping,
 * the episode counter and the kill-switch lock moved unchanged; `features/positions/accountSignals`
 * re-exports this module. E17's reducer is not touched.
 *
 * - **`account_notice` on `system`** (`23` §15.9, D06 §9 "Signals"): the latest reason of the
 *   `oms.` family per account is its state; `oms.account_synced` clears it; any other family is an
 *   event and kept for nothing. Mapped by E29-D03 §4.1 (D03:212–219) to the deck's `acct.*` line,
 *   header marker and announcement (RT-11 polite and RT-07 assertive, once per episode).
 * - **The stale lock's cause** is the Owner's alone, and only through B19 (D03 §4.1), which no
 *   client reads: the feed subscribes to no `machines.` topic, and the notice carries no cause
 *   (G17), so "2 minutes of failure" may be false for a fault lock. Every role, the Owner included,
 *   reads `acct.stale.line.nocause` and hears D03:329's cause-not-shown sentence (`D03_TEXT`); a
 *   stale notice that arrives while the kill switch covers the account is the kill-switch lock for
 *   every role, said with D03:329's kill-switch sentence (RT-07).
 * - **Late mount:** the shell keeps one `account_notice`, its last (`store.ts`), and no frame `ts`
 *   reaches a feature, so a panel that mounts (a first visit, a route re-entry) knows only the
 *   accounts that frame names, each "since" the mount; an earlier account's state is unknown until
 *   its next notice (D03 G15 asks the server to re-send each account's latest reason). The panel
 *   owns this store for the route's life, so a tab switch keeps every state and its "since".
 * - **The kill switch** comes from `WsState` (`unknown` is never "not killed", WS-E06), its engage
 *   time from the shell's last `system` frame that carries one.
 * - **The risk lockout waits for B20** (the orchestrator's carry on #911): B20 has no runtime
 *   machine (`23` §6.4), so the feed subscribes to no `machines.risk_lockout` topic, and the locks
 *   an account shows are the two this client is told of: the stale lock and the kill-switch lock,
 *   both from `account_notice` (D03 §4.1). S-21's chip (`blotter.ui.lockout_chip`, E39-D01 §8.2,
 *   with its reason and its "until" time) and RT-20 come with B20's runtime machine.
 */
import { useSyncExternalStore } from "react";
import type { Politeness } from "../../features/app-shell/announcer";
import type { SystemUpdate } from "../../lib/ws/protocol/frames";
import type { KillSwitchView } from "../../lib/ws/state/types";
import {
  D03_TEXT,
  DECK,
  type BoundText,
  type DeckEntry,
  type DeckKey,
} from "../../features/positions/copy";
import { isUuid } from "../../features/positions/model/rowMapping";

export type OmsState = "reconciling" | "desync" | "stale";
export type Role = "owner" | "manager" | "viewer";

export interface AccountSignal {
  readonly oms: {
    readonly state: OmsState;
    /**
     * When the account entered the state: the frame's `changed_at_ms` (`23` §15.9, the server's
     * clock) when it carries one, else when this client first heard it (the frame's `ts` does not
     * reach a feature). BQ-1 ruled (6610918411).
     */
    readonly sinceMs: number;
    /**
     * Present only when the wire carried `changed_at_ms`: `sinceMs` is then the server's time, never
     * the client's. Absent, `sinceMs` is "since this client heard it" (a replayed lock after a
     * restart carries none, `23` §15.9; a line never claims it as the lock's time).
     */
    readonly changedAtMs?: number;
    /** A sequence number per episode, never reused (a clear included): announce once per value. */
    readonly episode: number;
    /** A stale lock that began under the kill switch (D03 §4.1 "Locked — kill switch"). */
    readonly killLock: boolean;
  } | null;
}

export interface KillSwitchSignal {
  readonly view: KillSwitchView;
  readonly engagedAtMs: number | null;
}

export interface SignalsSnapshot {
  readonly accounts: ReadonlyMap<string, AccountSignal>;
  readonly killSwitch: KillSwitchSignal;
  readonly version: number;
  /**
   * An account's state was refused past `MAX_ACCOUNTS` (C-2.18): an account the store does not
   * hold may then be locked, so new exposure for it reads closed (review fold m3, fail closed).
   * Cleared with the store.
   */
  readonly overflowed: boolean;
}

/**
 * `23` §15.9's `oms.` reasons that report a state, and what each sets. A `Map`, so a wire string
 * never indexes an object (the shell's security lint, SR-127); the mapping is unchanged.
 */
const OMS_REASONS: ReadonlyMap<string, OmsState | "synced"> = new Map<string, OmsState | "synced">([
  ["oms.account_resyncing", "reconciling"],
  ["oms.account_desync", "desync"],
  ["oms.account_stale", "stale"],
  ["oms.account_synced", "synced"],
]);

/** Bounded (C-2.18): a client names at most a few dozen accounts. */
const MAX_ACCOUNTS = 256;

const NO_SIGNAL: AccountSignal = Object.freeze({ oms: null });
const UNKNOWN: KillSwitchSignal = Object.freeze<KillSwitchSignal>({
  view: { state: "unknown" },
  engagedAtMs: null,
});

/** Whether an engaged kill switch covers `accountId` (`23` §15.9, C12). */
export function killSwitchCovers(view: KillSwitchView, accountId: string): boolean {
  if (view.state !== "engaged") return false;
  return (
    view.scope === "global" || view.exchangeAccountIds.some((id) => id.toLowerCase() === accountId)
  );
}

/** An account state's announcement: its words, and the region D03 §8.3 gives it. */
export interface AccountAnnounce {
  readonly text: BoundText;
  /** Its owner's name for the words, for a binding error. */
  readonly name: string;
  readonly politeness: Politeness;
}

export interface AccountLine {
  readonly line: DeckKey;
  /** The header marker: a deck key, or `kill_lock` for D02:422's "Locked — kill switch". */
  readonly marker: DeckKey | "kill_lock";
  readonly announce: AccountAnnounce;
}

const DECK_MAP: ReadonlyMap<DeckKey, DeckEntry> = new Map(
  Object.entries(DECK) as [DeckKey, DeckEntry][],
);
const D03_TEXT_MAP: ReadonlyMap<keyof typeof D03_TEXT, BoundText> = new Map(
  Object.entries(D03_TEXT) as [keyof typeof D03_TEXT, BoundText][],
);

const deckAnnounce = (key: DeckKey): AccountAnnounce => {
  const entry = DECK_MAP.get(key) ?? DECK["acct.announce.reconciling"];
  return {
    text: entry,
    name: key,
    politeness: entry.announce === "assertive" ? "assertive" : "polite",
  };
};
/** RT-07 (D05 §8.1): a lock, either variant, is assertive, once per episode (D03 §8.3). */
const lockAnnounce = (key: keyof typeof D03_TEXT): AccountAnnounce => ({
  text: D03_TEXT_MAP.get(key) ?? D03_TEXT.staleAnnounce,
  name: `D03_TEXT.${key}`,
  politeness: "assertive",
});

/**
 * E29-D03 §4.1's line, marker and announcement for an account's state. The same for every role
 * while no client reads B19: the cause is withheld from all (the "cause not shown" row).
 */
export function accountLine(signal: AccountSignal): AccountLine | null {
  const oms = signal.oms;
  if (oms === null) return null;
  switch (oms.state) {
    case "reconciling":
      return {
        line: "acct.reconciling.line",
        marker: "acct.marker.checking",
        announce: deckAnnounce("acct.announce.reconciling"),
      };
    case "desync":
      return {
        line: "acct.desync.line",
        marker: "acct.marker.verifying",
        announce: deckAnnounce("acct.announce.desync"),
      };
    case "stale":
      if (oms.killLock) {
        return {
          line: "acct.killlock.line",
          marker: "kill_lock",
          announce: lockAnnounce("killLockAnnounce"),
        };
      }
      return {
        line: "acct.stale.line.nocause",
        marker: "acct.marker.stale",
        announce: lockAnnounce("staleAnnounce"),
      };
  }
}

/** The kill-switch banner keys (D02 §10.3; S-19 the Owner, S-20 every other role). */
export function killSwitchBanner(role: Role): readonly DeckKey[] {
  return role === "owner"
    ? ["blotter.ui.ks_owner"]
    : ["blotter.ui.ks_manager", "blotter.ui.ks_ask"];
}

export interface AccountSignalsStore {
  getSnapshot(): SignalsSnapshot;
  subscribe(listener: () => void): () => void;
  applyNotice(update: SystemUpdate, atMs: number): void;
  setKillSwitch(view: KillSwitchView, engagedAtMs: number | null): void;
  /** SR-E29-11: a withdrawn account's signals leave too. */
  forget(accountIds: Iterable<string>): void;
  clear(): void;
}

const isRecord = (v: unknown): v is Readonly<Record<string, unknown>> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export function createAccountSignals(): AccountSignalsStore {
  let accounts = new Map<string, AccountSignal>();
  let killSwitch: KillSwitchSignal = UNKNOWN;
  let episodes = 0;
  let version = 0;
  let overflowed = false;
  let snapshot: SignalsSnapshot = { accounts, killSwitch, overflowed, version };
  const listeners = new Set<() => void>();

  function publish(): void {
    version += 1;
    snapshot = { accounts, killSwitch, overflowed, version };
    for (const listener of [...listeners]) listener();
  }

  function put(accountId: string, next: AccountSignal): boolean {
    const before = accounts.get(accountId) ?? NO_SIGNAL;
    if (before.oms === next.oms) return false;
    const copy = new Map(accounts);
    if (next.oms === null) copy.delete(accountId);
    else if (copy.has(accountId)) copy.set(accountId, next);
    else if (copy.size < MAX_ACCOUNTS) copy.set(accountId, next);
    else {
      if (!overflowed) {
        overflowed = true;
        console.warn(
          `[accountSignals] accounts exceeded ${MAX_ACCOUNTS}; refusing ${accountId} (C-2.18 fail-closed)`,
        );
        publish();
      }
      return false;
    }
    accounts = copy;
    return true;
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    applyNotice(update, atMs) {
      if (!isRecord(update) || update.kind !== "account_notice") return;
      const reason = typeof update.reason === "string" ? update.reason : "";
      const target = OMS_REASONS.get(reason);
      // `23` §15.9: a reason outside the `oms.` family is an event, and an unknown `oms.` reason
      // names no state this client can render: both are kept for nothing
      if (target === undefined) return;
      const ids = Array.isArray(update.exchange_account_ids) ? update.exchange_account_ids : [];
      const at = update.changed_at_ms;
      const changedAtMs = typeof at === "number" && Number.isSafeInteger(at) ? at : undefined;
      let changed = false;
      for (const raw of ids) {
        if (!isUuid(raw)) continue;
        const id = raw.toLowerCase();
        const before = accounts.get(id) ?? NO_SIGNAL;
        if (target === "synced") {
          changed = put(id, { ...before, oms: null }) || changed;
          continue;
        }
        const held = before.oms;
        if (held?.state === target) {
          // `23` §15.9 keys the state on (account, reason, `changed_at_ms` or its absence), BQ-1
          // ruled (6610918411): the same triple is that state again (a replay at reconnect), and a
          // frame that adds a time to an untimed state is that state with its time — neither is a
          // new episode, so two reconnects show and announce one state.
          if (changedAtMs === undefined || held.changedAtMs === changedAtMs) continue;
          if (held.changedAtMs === undefined) {
            const timed = { ...held, sinceMs: changedAtMs, changedAtMs };
            changed = put(id, { ...before, oms: timed }) || changed;
            continue;
          }
          // Both timed and different: the server says the account entered the state again.
        }
        const killLock = target === "stale" && killSwitchCovers(killSwitch.view, id);
        episodes += 1;
        const oms =
          changedAtMs === undefined
            ? { state: target, sinceMs: atMs, episode: episodes, killLock }
            : { state: target, sinceMs: changedAtMs, changedAtMs, episode: episodes, killLock };
        changed = put(id, { ...before, oms }) || changed;
      }
      if (changed) publish();
    },
    setKillSwitch(view, engagedAtMs) {
      const same =
        view.state === killSwitch.view.state &&
        engagedAtMs === killSwitch.engagedAtMs &&
        (view.state === "unknown" ||
          (killSwitch.view.state !== "unknown" &&
            view.scope === killSwitch.view.scope &&
            view.exchangeAccountIds.join() === killSwitch.view.exchangeAccountIds.join()));
      if (same) return;
      killSwitch = { view, engagedAtMs };
      publish();
    },
    forget(accountIds) {
      let changed = false;
      for (const id of accountIds) changed = put(id.toLowerCase(), NO_SIGNAL) || changed;
      if (changed) publish();
    },
    clear() {
      if (accounts.size === 0 && killSwitch === UNKNOWN && !overflowed) return;
      accounts = new Map();
      overflowed = false;
      killSwitch = UNKNOWN;
      publish();
    },
  };
}

/** The engage time the shell's last `system` frames carry (`kill_switch`, else `health`). */
export function engagedAtOf(
  systemByKind: Readonly<Partial<Record<SystemUpdate["kind"], SystemUpdate>>>,
): number | null {
  for (const update of [systemByKind.kill_switch, systemByKind.health]) {
    const at = update?.kill_switch?.engaged_at_ms;
    if (typeof at === "number" && Number.isSafeInteger(at)) return at;
  }
  return null;
}

export interface SignalSources {
  /** The shell store (`shell/bootstrap/store.ts`): its `system` frames by kind. */
  readonly shell: {
    getState(): {
      readonly systemByKind: Readonly<Partial<Record<SystemUpdate["kind"], SystemUpdate>>>;
    };
    subscribe(listener: () => void): () => void;
  };
  /** The WS client's state (`WsClient.getState` / `subscribe`). */
  readonly ws: {
    getState(): { readonly killSwitch: KillSwitchView };
    subscribe(listener: () => void): () => void;
  };
  readonly wall?: (() => number) | undefined;
}

/**
 * Feeds `store` from the shell's `system` frames and the client's kill switch until the returned
 * stop. The shell keeps one `account_notice` (its last), so it seeds the accounts that frame names
 * (`23` §15.9: the server replays each account's latest state at first auth, so a reconnect brings
 * it back as a frame the dedupe keys on; an account with no state yet is unknown until its first
 * notice).
 */
export function startAccountSignals(
  store: AccountSignalsStore,
  sources: SignalSources,
): () => void {
  const wall = sources.wall ?? ((): number => Date.now());
  let lastNotice: SystemUpdate | undefined;
  const fromShell = (): void => {
    const { systemByKind } = sources.shell.getState();
    const notice = systemByKind.account_notice;
    if (notice !== undefined && notice !== lastNotice) {
      lastNotice = notice;
      store.applyNotice(notice, wall());
    }
    store.setKillSwitch(sources.ws.getState().killSwitch, engagedAtOf(systemByKind));
  };
  const stops = [sources.shell.subscribe(fromShell), sources.ws.subscribe(fromShell)];
  fromShell();
  return () => stops.forEach((stop) => stop());
}

export function useAccountSignals<T>(
  store: AccountSignalsStore,
  select: (s: SignalsSnapshot) => T,
): T {
  const read = (): T => select(store.getSnapshot());
  return useSyncExternalStore(store.subscribe, read, read);
}
