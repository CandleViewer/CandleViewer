/**
 * Single read/write API for shell chrome state — `useShellState()`'s
 * backing store. Module-scoped (no external state lib per `AGENTS.md` §5.1
 * "no new deps without justification"; the pattern mirrors the existing
 * `lib/auth/meCache.ts`), with a plain pub/sub so React can subscribe via
 * `useSyncExternalStore`.
 *
 * Holds:
 *  - bootstrap phase (`/me`, `/me/preferences`, `/me/keymap`) and any
 *    non-fatal warnings from the optional calls;
 *  - the environment (DEMO/LIVE/testnet), which is **never defaulted** —
 *    `"unknown"` until `/me` (or a `system` WS frame) says otherwise;
 *  - the latest `SystemUpdate` per `kind`, since the WS topic carries
 *    several independent facets (health, kill-switch, feature flags, ...);
 *  - the WS connection state and reconnect countdown;
 *  - the WS latency indicator (budget #3), at most once a second.
 */
import type { generated } from "@candleviewer/protocol";
import { toLatencyIndicator, type LatencyIndicator } from "../../lib/telemetry/latencyIndicator.js";

export type Me = generated.rest.components["schemas"]["Me"];
export type Settings = generated.rest.components["schemas"]["Settings"];
export type Keymap = {
  hotkey_profile_id?: string;
  bindings?: generated.rest.components["schemas"]["HotkeyBinding"][];
};
export type SystemUpdate = generated.ws.System;
export type Environment = generated.rest.components["schemas"]["Environment"];

export type BootstrapPhase =
  | { readonly kind: "loading" }
  | { readonly kind: "slow" }
  | { readonly kind: "ready" }
  | {
      readonly kind: "failed";
      readonly reason: "timeout" | "http_error" | "unknown";
      readonly status?: number;
    };

export type ConnectionState =
  | { readonly kind: "connecting" }
  | { readonly kind: "live" }
  | { readonly kind: "reconnecting"; readonly attempt: number; readonly nextAttemptAtMs: number }
  | {
      readonly kind: "offline";
      readonly cause: "offline" | "tailnet_unreachable" | "backend_unreachable";
    };

export interface ShellState {
  readonly bootstrap: BootstrapPhase;
  readonly me: Me | null;
  readonly preferences: Settings | null;
  readonly preferencesWarning: string | null;
  readonly keymap: Keymap | null;
  readonly keymapWarning: string | null;
  /** Never defaulted (ticket AC "Environment is never guessed"). */
  readonly environment: Environment | "unknown";
  readonly connection: ConnectionState;
  readonly systemByKind: Readonly<Partial<Record<SystemUpdate["kind"], SystemUpdate>>>;
  /** The age of the newest live frame the client rendered (budget #3); `unavailable` until one is. */
  readonly latency: LatencyIndicator;
}

const INITIAL_BOOTSTRAP: BootstrapPhase = { kind: "loading" };
const INITIAL_CONNECTION: ConnectionState = { kind: "connecting" };

export const INITIAL_SHELL_STATE: ShellState = Object.freeze({
  bootstrap: INITIAL_BOOTSTRAP,
  me: null,
  preferences: null,
  preferencesWarning: null,
  keymap: null,
  keymapWarning: null,
  environment: "unknown",
  connection: INITIAL_CONNECTION,
  systemByKind: Object.freeze({}),
  latency: toLatencyIndicator(null),
});

let state: ShellState = INITIAL_SHELL_STATE;
const listeners = new Set<() => void>();

export function getShellState(): ShellState {
  return state;
}

export function subscribeShellState(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setShellState(patch: Partial<ShellState>): void {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
}

/** Merges one `SystemUpdate` frame into `systemByKind`, keyed by its `kind`. */
export function applySystemUpdate(update: SystemUpdate): void {
  setShellState({ systemByKind: { ...state.systemByKind, [update.kind]: update } });
}

/** Test-only reset to the initial, unauthenticated shell state. */
export function resetShellState(): void {
  state = INITIAL_SHELL_STATE;
  for (const listener of listeners) listener();
}
