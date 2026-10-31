import { useMemo, useSyncExternalStore } from "react";
import type { ShellState } from "../../shell/bootstrap/store";
import { useShellSelector } from "../../shell/useShellSelector";
import { resolveConfirm } from "./resolve";
import type { ConfirmAction, ConfirmEnv, Resolution, ServerFloor } from "./resolve";
import { getConfirmPolicyStore } from "./store";
import type { ConfirmPolicyStore } from "./store";

export interface ConfirmPolicyOptions {
  readonly serverFloor?: ServerFloor;
  /** For tests. */
  readonly store?: ConfirmPolicyStore;
}

const selectEnvironment = (state: ShellState): ConfirmEnv => state.environment;

/**
 * How `action` is confirmed in the shell's environment for `userId` (UX only, C-2.12). The environment is
 * read from the bootstrap store here (L1), so no caller can pass a weaker one; "unknown" (before /me) and
 * anything but "demo" resolve under the Live rules. `userId` must be the server-issued /me id; a blank
 * one keeps the policy in memory only. The owning screens (SCR-029, 072, 076, 129) call this.
 */
export function useConfirmPolicy(
  action: ConfirmAction,
  userId: string,
  options: ConfirmPolicyOptions = {},
): Resolution {
  const environment = useShellSelector(selectEnvironment);
  // One store per user id across renders: a blank id gets a fresh in-memory store, kept for this mount.
  const shared = useMemo(() => getConfirmPolicyStore(userId), [userId]);
  const store = options.store ?? shared;
  const policy = useSyncExternalStore(store.subscribe, store.get, store.get);
  const confirmFlatten = options.serverFloor?.confirmFlatten;
  return useMemo(
    () =>
      resolveConfirm(
        action,
        environment,
        policy,
        confirmFlatten === undefined ? {} : { confirmFlatten },
      ),
    [action, environment, policy, confirmFlatten],
  );
}
