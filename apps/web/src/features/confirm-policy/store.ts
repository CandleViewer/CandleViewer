import type { ConfirmAction, ActionPolicy, UserPolicy } from "./resolve";
import { CONFIRM_ACTIONS, clampHoldMs } from "./resolve";
import { getShellState, subscribeShellState } from "../../shell/bootstrap/store";

/**
 * The client-side policy store (BQ-7): SCR-114 (E30-S07) is unbuilt, so the user's per-action choice lives
 * here, in memory with a validated localStorage copy. It never holds an accessibility flag.
 */
export const CONFIRM_POLICY_STORAGE_PREFIX = "cv.confirmPolicy.v1.";
export const confirmPolicyStorageKey = (userId: string): string =>
  `${CONFIRM_POLICY_STORAGE_PREFIX}${userId}`;

type Listener = () => void;

export interface ConfirmPolicyStore {
  readonly get: () => UserPolicy;
  readonly set: (action: ConfirmAction, policy: ActionPolicy | undefined) => void;
  readonly subscribe: (listener: Listener) => () => void;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Keeps only known actions with a well-formed entry; the resolver still fails closed on odd values. */
export function parsePolicy(raw: unknown): UserPolicy {
  if (!isRecord(raw)) return {};
  const out: Partial<Record<ConfirmAction, ActionPolicy>> = {};
  for (const action of CONFIRM_ACTIONS) {
    const entry: unknown = Object.hasOwn(raw, action) ? raw[action] : undefined;
    if (!isRecord(entry)) continue;
    const { mode, holdMs } = entry;
    // `immediate` is refused at persistence (BQ-2): fail closed, the entry is dropped.
    if (mode !== "dialog" && mode !== "hold") continue;
    out[action] = typeof holdMs === "number" ? { mode, holdMs } : { mode };
  }
  return out;
}

export function createConfirmPolicyStore(
  storage?: Pick<Storage, "getItem" | "setItem">,
  userId = "",
): ConfirmPolicyStore {
  // L2: one copy per user; no user id means in-memory only.
  const key = userId === "" ? undefined : confirmPolicyStorageKey(userId);
  let current: UserPolicy = {};
  try {
    const text = key === undefined ? null : storage?.getItem(key);
    if (typeof text === "string") current = parsePolicy(JSON.parse(text));
  } catch {
    current = {};
  }
  const listeners = new Set<Listener>();
  // Cross-tab `storage` events are deliberately not subscribed: another tab's write is picked up at the
  // next load, and it is safe because the resolver re-applies every floor to whatever the store holds.
  return {
    get: () => current,
    set: (action, policy) => {
      if (policy !== undefined && policy.mode !== "dialog" && policy.mode !== "hold") return;
      const next: Partial<Record<ConfirmAction, ActionPolicy>> = { ...current };
      if (policy === undefined) delete next[action];
      else
        next[action] =
          policy.mode === "hold" && policy.holdMs !== undefined
            ? { mode: "hold", holdMs: clampHoldMs(policy.holdMs) }
            : policy;
      current = next;
      try {
        if (key !== undefined) storage?.setItem(key, JSON.stringify(current));
      } catch {
        // Storage full or blocked: the in-memory choice still applies this session.
      }
      for (const listener of [...listeners]) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

const browserStorage = (): Storage | undefined => {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
};

const shared = new Map<string, ConfirmPolicyStore>();
let sessionKey: string | undefined;
let watching = false;
const sessionKeyOf = (): string | undefined => {
  const me = getShellState().me;
  return me === null ? undefined : `${me.user.id}|${me.session?.session_id ?? ""}`;
};
/** A logout or a different session drops every memoised store, so no user's policy outlives its session. */
function watchSession(): void {
  if (watching) return;
  watching = true;
  sessionKey = sessionKeyOf();
  subscribeShellState(() => {
    const next = sessionKeyOf();
    if (next !== sessionKey) {
      sessionKey = next;
      shared.clear();
    }
  });
}

/**
 * The store for one user (L2): switching user switches the copy, never the previous user's policy. A blank
 * or whitespace-only id is never memoised: each call gets a fresh in-memory store, so no two callers share.
 */
export function getConfirmPolicyStore(userId: string): ConfirmPolicyStore {
  if (userId.trim() === "") return createConfirmPolicyStore(browserStorage(), "");
  watchSession();
  let store = shared.get(userId);
  if (store === undefined) {
    store = createConfirmPolicyStore(browserStorage(), userId);
    shared.set(userId, store);
  }
  return store;
}
