/**
 * The account-level signals of the Positions tab (E29-S01 #911, BQ-14): a feature-level consumer
 * (E17's reducer is not touched) that renders the state E29-S07 defines.
 *
 * - **`account_notice` on `system`** (`23` §15.9, D06 §9 "Signals"): the latest reason of the
 *   `oms.` family per account is its state; `oms.account_synced` clears it; any other family is an
 *   event and kept for nothing. Mapped by E29-D03 §4.1 (D03:212–219) to the deck's `acct.*` line,
 *   header marker and announcement (RT-11 polite and RT-07 assertive, once per episode).
 * - **The stale lock's cause** is the Owner's alone, and only through B19, which no client reads
 *   yet: an Owner reads `acct.stale.line` (the notice's own meaning, 2 minutes of failure), a
 *   Manager or Viewer `acct.stale.line.nocause`; a stale notice that arrives while the kill switch
 *   covers the account is the kill-switch lock for every role (D03 §4.1).
 * - **The kill switch** comes from `WsState` (`unknown` is never "not killed", WS-E06), its engage
 *   time from the shell's last `system` frame that carries one.
 * - **The risk lockout waits for B20** (the orchestrator's carry on #911): B20 has no runtime
 *   machine (`23` §6.4), so the feed subscribes to no `machines.risk_lockout` topic, and the locks
 *   an account shows are the two this client is told of: the stale lock and the kill-switch lock,
 *   both from `account_notice` (D03 §4.1). S-21's chip (`blotter.ui.lockout_chip`, E39-D01 §8.2,
 *   with its reason and its "until" time) and RT-20 come with B20's runtime machine.
 */
import { useSyncExternalStore } from "react";
import type { SystemUpdate } from "../../lib/ws/protocol/frames";
import type { KillSwitchView } from "../../lib/ws/state/types";
import type { DeckKey } from "./copy";
import { isUuid } from "./model/rowMapping";

export type OmsState = "reconciling" | "desync" | "stale";
export type Role = "owner" | "manager" | "viewer";

export interface AccountSignal {
  readonly oms: {
    readonly state: OmsState;
    /** When this client heard it begin (the frame's `ts` does not reach a feature). */
    readonly sinceMs: number;
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
}

/** `23` §15.9's `oms.` reasons that report a state, and what each sets. */
const OMS_REASONS: Readonly<Record<string, OmsState | "synced">> = {
  "oms.account_resyncing": "reconciling",
  "oms.account_desync": "desync",
  "oms.account_stale": "stale",
  "oms.account_synced": "synced",
};
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

export interface AccountLine {
  readonly line: DeckKey;
  /** The header marker: a deck key, or `kill_lock` for D02:422's "Locked — kill switch". */
  readonly marker: DeckKey | "kill_lock";
  readonly announce: DeckKey | null;
}

/** E29-D03 §4.1's line, marker and announcement for an account's state, per role. */
export function accountLine(signal: AccountSignal, role: Role): AccountLine | null {
  const oms = signal.oms;
  if (oms === null) return null;
  switch (oms.state) {
    case "reconciling":
      return {
        line: "acct.reconciling.line",
        marker: "acct.marker.checking",
        announce: "acct.announce.reconciling",
      };
    case "desync":
      return {
        line: "acct.desync.line",
        marker: "acct.marker.verifying",
        announce: "acct.announce.desync",
      };
    case "stale":
      if (oms.killLock) return { line: "acct.killlock.line", marker: "kill_lock", announce: null };
      return {
        line: role === "owner" ? "acct.stale.line" : "acct.stale.line.nocause",
        marker: "acct.marker.stale",
        announce: "acct.announce.stale",
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
  let version = 0;
  let episodes = 0;
  let snapshot: SignalsSnapshot = { accounts, killSwitch, version };
  const listeners = new Set<() => void>();

  function publish(): void {
    version += 1;
    snapshot = Object.freeze({ accounts, killSwitch, version });
    for (const listener of [...listeners]) listener();
  }

  function put(accountId: string, next: AccountSignal): boolean {
    const before = accounts.get(accountId) ?? NO_SIGNAL;
    if (before.oms === next.oms) return false;
    const copy = new Map(accounts);
    if (next.oms === null) copy.delete(accountId);
    else if (copy.has(accountId) || copy.size < MAX_ACCOUNTS) copy.set(accountId, next);
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
      const target = Object.hasOwn(OMS_REASONS, reason) ? OMS_REASONS[reason] : undefined;
      // `23` §15.9: a reason outside the `oms.` family is an event, and an unknown `oms.` reason
      // names no state this client can render: both are kept for nothing
      if (target === undefined) return;
      const ids = Array.isArray(update.exchange_account_ids) ? update.exchange_account_ids : [];
      let changed = false;
      for (const raw of ids) {
        if (!isUuid(raw)) continue;
        const id = raw.toLowerCase();
        const before = accounts.get(id) ?? NO_SIGNAL;
        if (target === "synced") {
          changed = put(id, { ...before, oms: null }) || changed;
          continue;
        }
        if (before.oms?.state === target) continue; // the same episode: said once
        const killLock = target === "stale" && killSwitchCovers(killSwitch.view, id);
        episodes += 1;
        changed =
          put(id, {
            ...before,
            oms: { state: target, sinceMs: atMs, episode: episodes, killLock },
          }) || changed;
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
      if (accounts.size === 0 && killSwitch === UNKNOWN) return;
      accounts = new Map();
      killSwitch = UNKNOWN;
      publish();
    },
  };
}

/** The engage time the shell's last `system` frames carry (`kill_switch`, else `health`). */
export function engagedAtOf(
  systemByKind: Readonly<Partial<Record<SystemUpdate["kind"], SystemUpdate>>>,
): number | null {
  for (const kind of ["kill_switch", "health"] as const) {
    const at = systemByKind[kind]?.kill_switch?.engaged_at_ms;
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
 * (`23` §15.9: notices are not replayed; any other account's state is unknown until its next one).
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
