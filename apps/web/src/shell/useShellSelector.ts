/**
 * `useShellSelector(selector, isEqual?)` (E10-S01 S3, #304): a slice of the shell store. The
 * component re-renders only when its selection changes (by `isEqual`, `Object.is` by default), so a
 * chip that reads `connection` stays still through the 1 Hz `latency` tick that `useShellState()`
 * would re-render it on.
 */
import { useRef, useSyncExternalStore } from "react";
import { getShellState, subscribeShellState, type ShellState } from "./bootstrap/store.js";

interface Memo<T> {
  readonly state: ShellState;
  readonly selector: (state: ShellState) => T;
  readonly value: T;
}

export function useShellSelector<T>(
  selector: (state: ShellState) => T,
  isEqual: (a: T, b: T) => boolean = Object.is,
): T {
  const memo = useRef<Memo<T> | null>(null);
  const getSnapshot = (): T => {
    const state = getShellState();
    const last = memo.current;
    if (last !== null && last.state === state && last.selector === selector) return last.value;
    const next = selector(state);
    // An equal selection keeps the previous reference, so `useSyncExternalStore` skips the render.
    const value = last !== null && isEqual(last.value, next) ? last.value : next;
    memo.current = { state, selector, value };
    return value;
  };
  return useSyncExternalStore(subscribeShellState, getSnapshot, getSnapshot);
}
