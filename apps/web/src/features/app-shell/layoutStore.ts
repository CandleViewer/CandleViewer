/**
 * The shell's layout store (E10-S01 S6, #304): the nav rail's collapse and the right rail's drawer.
 * E10-D02 :248 names a Zustand slice; the app has no Zustand, so this is the same
 * `useSyncExternalStore` pub/sub as the shell store (#304 plan gap 10). Two booleans, nothing derived.
 *
 * Only `railCollapsed` persists, per user on this device (D02 :248, no server round-trip), under one
 * key. Storage may be missing or throw (private mode, a quota, a test): reads fall back to the
 * expanded rail and writes are dropped, so the shell renders either way.
 */
import { useSyncExternalStore } from "react";

export interface ShellLayoutState {
  readonly railCollapsed: boolean;
  readonly rightRailOpen: boolean;
}

export const RAIL_STORAGE_KEY = "cv.shell.layout.v1";

function readCollapsed(): boolean {
  try {
    const raw = globalThis.localStorage?.getItem(RAIL_STORAGE_KEY) ?? null;
    if (raw === null) return false;
    const parsed: unknown = JSON.parse(raw);
    return (
      typeof parsed === "object" &&
      parsed !== null &&
      (parsed as { railCollapsed?: unknown }).railCollapsed === true
    );
  } catch {
    return false;
  }
}

function writeCollapsed(railCollapsed: boolean): void {
  try {
    globalThis.localStorage?.setItem(RAIL_STORAGE_KEY, JSON.stringify({ railCollapsed }));
  } catch {
    // No storage: the choice lasts for this page only.
  }
}

let state: ShellLayoutState = { railCollapsed: readCollapsed(), rightRailOpen: false };
const listeners = new Set<() => void>();

function set(patch: Partial<ShellLayoutState>): void {
  const next = { ...state, ...patch };
  if (next.railCollapsed === state.railCollapsed && next.rightRailOpen === state.rightRailOpen) {
    return;
  }
  state = next;
  for (const listener of [...listeners]) listener();
}

export function getShellLayout(): ShellLayoutState {
  return state;
}

export function subscribeShellLayout(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setRailCollapsed(railCollapsed: boolean): void {
  writeCollapsed(railCollapsed);
  set({ railCollapsed });
}

export function setRightRailOpen(rightRailOpen: boolean): void {
  set({ rightRailOpen });
}

/** Re-reads storage and closes the drawer: a fresh page's state (tests, sign-out). */
export function resetShellLayout(): void {
  set({ railCollapsed: readCollapsed(), rightRailOpen: false });
}

/** One field of the layout; a component re-renders only when that field changes. */
export function useShellLayout<K extends keyof ShellLayoutState>(key: K): ShellLayoutState[K] {
  const read = (): ShellLayoutState[K] => state[key];
  return useSyncExternalStore(subscribeShellLayout, read, read);
}
