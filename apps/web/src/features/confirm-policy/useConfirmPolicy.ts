import { useMemo, useSyncExternalStore } from "react";
import { resolveConfirm } from "./resolve";
import type { ConfirmAction, ConfirmEnv, Resolution } from "./resolve";
import { getConfirmPolicyStore } from "./store";
import type { ConfirmPolicyStore } from "./store";

/**
 * How `action` is confirmed in `env`. The owning screens (SCR-029, 072, 076, 129) call this; `env` is their
 * input because no environment source is wired yet (BQ-8). `store` is for tests.
 */
export function useConfirmPolicy(
  action: ConfirmAction,
  env: ConfirmEnv,
  store: ConfirmPolicyStore = getConfirmPolicyStore(),
): Resolution {
  const policy = useSyncExternalStore(store.subscribe, store.get, store.get);
  return useMemo(() => resolveConfirm(action, env, policy), [action, env, policy]);
}
