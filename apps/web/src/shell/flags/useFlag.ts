/**
 * `useFlag(name)` / `readFlag(name)`: one feature flag's resolved value from the WS `system`
 * mirror (`23` §15.9, `flags.ts`). `undefined` while the flag has not been read (or the role may
 * not see it); callers treat `undefined` as OFF. The hook selects one key, so a component
 * re-renders only when that flag's value changes, not on every shell-store update.
 */
import { getShellState, type ShellState } from "../bootstrap/store.js";
import { useShellSelector } from "../useShellSelector.js";

/** The flag's value for non-React code; `undefined` while unread. */
export function readFlag(name: string): boolean | undefined {
  return getShellState().flags.get(name);
}

/** The flag's value; `undefined` while unread, which callers treat as OFF. */
export function useFlag(name: string): boolean | undefined {
  return useShellSelector((state: ShellState) => state.flags.get(name));
}
