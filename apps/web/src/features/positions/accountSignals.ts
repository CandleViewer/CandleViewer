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
 * - **The risk lockout** comes from the B20 topic `machines.risk_lockout:{id}.state` (`23` §6.4):
 *   `clear`, `warning` or `locked`; a refused or ended subscription reads unknown, never clear.
 */
import { useSyncExternalStore } from "react";
import type { TopicFrame } from "../../lib/ws/api";
import type { SystemUpdate } from "../../lib/ws/protocol/frames";
import type { KillSwitchView } from "../../lib/ws/state/types";
import type { DeckKey } from "./copy";
import { isUuid } from "./model/rowMapping";

export type OmsState = "reconciling" | "desync" | "stale";
export type Lockout = "clear" | "warning" | "locked";
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
  /** B20's published state; `null` until one is read, and after the subscription ends. */
  readonly lockout: Lockout | null;
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
const LOCKOUTS: readonly Lockout[] = ["clear", "warning", "locked"];
/** Bounded (C-2.18): a client names at most a few dozen accounts. */
const MAX_ACCOUNTS = 256;

const NO_SIGNAL: AccountSignal = Object.freeze({ oms: null, lockout: null });
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
  /** What the account's B20 handle read. */
  applyLockout(accountId: string, frames: readonly TopicFrame[]): void;
  /** SR-E29-11: a withdrawn account's signals leave too. */
  forget(accountIds: Iterable<string>): void;
  clear(): void;
}

const isRecord = (v: unknown): v is Readonly<Record<string, unknown>> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The B20 state of a structured `machines` payload (`23` §15.10), or `undefined` for another. */
function lockoutOf(body: { readonly e: string; readonly p?: unknown }): Lockout | undefined {
  if (body.e !== "j" || !isRecord(body.p) || body.p["machine_kind"] !== "risk_lockout")
    return undefined;
  return LOCKOUTS.find((state) => state === (body.p as Record<string, unknown>)["state"]);
}

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
    if (before.oms === next.oms && before.lockout === next.lockout) return false;
    const copy = new Map(accounts);
    if (next.oms === null && next.lockout === null) copy.delete(accountId);
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
    applyLockout(accountId, frames) {
      const id = accountId.toLowerCase();
      let state = (accounts.get(id) ?? NO_SIGNAL).lockout;
      for (const frame of frames) {
        if (frame.kind === "reset") {
          state = null; // refused (no B20 machine runs yet, 23 §6.4), removed, or void: unknown
          continue;
        }
        const bodies = frame.kind === "snap" ? frame.bodies : [frame.body];
        for (const body of bodies) {
          const next = lockoutOf(body);
          if (next !== undefined) state = next;
        }
      }
      const before = accounts.get(id) ?? NO_SIGNAL;
      if (put(id, { ...before, lockout: state })) publish();
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
