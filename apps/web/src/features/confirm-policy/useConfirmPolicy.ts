import { useMemo, useSyncExternalStore } from "react";
import { resolveConfirm } from "./resolve";
import type { ConfirmAction, ConfirmEnv, Resolution, ServerFloor } from "./resolve";
import { getConfirmPolicyStore } from "./store";
import type { ConfirmPolicyStore } from "./store";

export interface ConfirmPolicyOptions {
  readonly serverFloor?: ServerFloor;
  /** For tests. */
  readonly store?: ConfirmPolicyStore;
}

/**
 * How `action` is confirmed in `env` for `userId` (UX only, C-2.12). The owning screens (SCR-029, 072,
 * 076, 129) call this; `env` is their input (from `shell/bootstrap/store`, BQ-8).
 */
export function useConfirmPolicy(
  action: ConfirmAction,
  env: ConfirmEnv,
  userId: string,
  options: ConfirmPolicyOptions = {},
): Resolution {
  const store = options.store ?? getConfirmPolicyStore(userId);
  const policy = useSyncExternalStore(store.subscribe, store.get, store.get);
  const confirmFlatten = options.serverFloor?.confirmFlatten;
  return useMemo(
    () =>
      resolveConfirm(action, env, policy, confirmFlatten === undefined ? {} : { confirmFlatten }),
    [action, env, policy, confirmFlatten],
  );
}
