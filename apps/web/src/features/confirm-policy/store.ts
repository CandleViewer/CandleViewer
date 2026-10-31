import type { ConfirmAction, ActionPolicy, UserPolicy } from "./resolve";
import { CONFIRM_ACTIONS } from "./resolve";

/**
 * The client-side policy store (BQ-7): SCR-114 (E30-S07) is unbuilt, so the user's per-action choice lives
 * here, in memory with a validated localStorage copy. It never holds an accessibility flag.
 */
export const CONFIRM_POLICY_STORAGE_KEY = "cv.confirmPolicy.v1";

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
    if (mode !== "dialog" && mode !== "hold" && mode !== "immediate") continue;
    out[action] = typeof holdMs === "number" ? { mode, holdMs } : { mode };
  }
  return out;
}

export function createConfirmPolicyStore(
  storage?: Pick<Storage, "getItem" | "setItem">,
): ConfirmPolicyStore {
  let current: UserPolicy = {};
  try {
    const text = storage?.getItem(CONFIRM_POLICY_STORAGE_KEY);
    if (typeof text === "string") current = parsePolicy(JSON.parse(text));
  } catch {
    current = {};
  }
  const listeners = new Set<Listener>();
  return {
    get: () => current,
    set: (action, policy) => {
      const next: Partial<Record<ConfirmAction, ActionPolicy>> = { ...current };
      if (policy === undefined) delete next[action];
      else next[action] = policy;
      current = next;
      try {
        storage?.setItem(CONFIRM_POLICY_STORAGE_KEY, JSON.stringify(current));
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

let shared: ConfirmPolicyStore | undefined;
export function getConfirmPolicyStore(): ConfirmPolicyStore {
  shared ??= createConfirmPolicyStore(browserStorage());
  return shared;
}
