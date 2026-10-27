import type { ShellState } from "../../shell/bootstrap/store.js";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { selectDegradedIssues } from "../system-states/degradedIssues";
import { deriveShellMode, sameShellMode, type ShellModeResult } from "./shellMode";

/**
 * The store → `deriveShellMode` (E10-S01 S8, #304). Pure and module-level: every consumer reads
 * the same store facts, including the store's `everLive` latch, so a component that mounts
 * mid-outage reads `disconnected` like one mounted before it. `frozen`, `lockout` and `viewAs` are
 * `false`: the store has no source for them (#304 gap 13; see `shellMode.ts`).
 */
export const selectShellMode = (s: ShellState): ShellModeResult =>
  deriveShellMode({
    connection: s.connection.kind,
    everLive: s.everLive,
    degraded: selectDegradedIssues(s.degraded).length > 0,
    frozen: false,
    lockout: false,
    role: s.me?.role ?? null,
    viewAs: false,
  });

/**
 * The shell mode through `useShellSelector` with `sameShellMode`: a component re-renders only when
 * the mode or the read-only overlay changes, never on the 1 Hz latency tick, a reconnect attempt or
 * a repeated degraded frame.
 */
export function useShellMode(): ShellModeResult {
  return useShellSelector(selectShellMode, sameShellMode);
}
