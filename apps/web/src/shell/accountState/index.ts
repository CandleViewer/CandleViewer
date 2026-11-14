/**
 * The shell's one account-state store (E29-S07 #1028; BQ-5 of the ruling of record 6575172489,
 * BQ-2 ruled (6610918411)). `shell/bootstrap/store.ts` feeds it every `account_notice` as it
 * arrives — not only the last one the shell keeps per kind — so a surface that mounts late (the
 * Positions tab, the `recovered` region, a new-exposure control) still knows each account a notice
 * named on this connection, and a replay at reconnect (`23` §15.9) is deduped by the store.
 */
import { createAccountSignals, useAccountSignals, type SignalsSnapshot } from "./accountSignals";

export * from "./accountSignals";

/** The shell-level store: one per page, like the shell store it is fed from. */
export const shellAccountSignals = createAccountSignals();

/** Reads the shell store through a selector (`useSyncExternalStore`). */
export function useShellAccountSignals<T>(select: (s: SignalsSnapshot) => T): T {
  return useAccountSignals(shellAccountSignals, select);
}
