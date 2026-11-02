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
 *  - the WS latency indicator (budget #3), at most once a second;
 *  - the SCR-153 degraded facts (E10-S04 #306), folded from every `system` frame,
 *    with row 9's 10 s hand-over to R5 timed here (E17-D02 §6);
 *  - SCR-159's reachability, the liveness probe's verdict (`liveness.ts`), and the desktop
 *    shell's last GPU-process crash while its page shows (`gpuCrash.ts`);
 *  - SCR-157's facts: the last `welcome`'s build label, which the worker read and vetted, whether
 *    the update banner was postponed, and the incompatible build Continue read-only answered.
 */
import type { generated } from "@candleviewer/protocol";
import {
  INITIAL_DEGRADED_FACTS,
  PRIVATE_HANDOVER_MS,
  handOverPrivateReconnect,
  reduceDegraded,
  setGpuFallback,
  type DegradedFacts,
} from "../../features/system-states/degradedIssues.js";
import { toLatencyIndicator, type LatencyIndicator } from "../../lib/telemetry/latencyIndicator.js";
import { SHELL_PERF_MARKS, markShellStage } from "../perfMarks.js";
import type { GpuCrash } from "../ShellPort.js";
import { REACHABLE, type Reachability } from "./reachability.js";

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
  /** `/me` found the session idle-locked (a reload while locked): SCR-005 first, not /login (#1640). */
  | { readonly kind: "locked" }
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
  /** The CMP-092 rows' facts; `degradedIssues(degraded)` lists the rows. */
  readonly degraded: DegradedFacts;
  /** `connection` has been `live` this session; a later `connecting` is a loss, not the boot. */
  readonly everLive: boolean;
  /** SCR-159: reachable until a liveness probe goes unanswered (never `navigator.onLine` alone). */
  readonly reachability: Reachability;
  /** SCR-159's GPU page (F15, desktop only): the last crash, until the user keeps software rendering. */
  readonly gpuCrash: GpuCrash | null;
  /**
   * The last `welcome`'s `protocol` (23 §4.2): `undefined` until the first `welcome`, `null` when
   * it carried none the client keeps, which SCR-157 reads as incompatible (10b fails closed).
   */
  readonly serverProtocol: string | null | undefined;
  /** Its `server_version`: `undefined` until a `welcome` carries one the client keeps. */
  readonly serverVersion: string | undefined;
  /** SCR-157's Later: the update banner is gone for the session, and the StatusBar reminds. */
  readonly updateDeferred: boolean;
  /** SCR-157's Continue read-only: the build (`incompatibleBuild`) it answered, till it changes. */
  readonly continuedFor: string | undefined;
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
  degraded: INITIAL_DEGRADED_FACTS,
  everLive: false,
  reachability: REACHABLE,
  gpuCrash: null,
  serverProtocol: undefined,
  serverVersion: undefined,
  updateDeferred: false,
  continuedFor: undefined,
});

let state: ShellState = INITIAL_SHELL_STATE;
/** The restart count of the newest GPU crash taken, if any: main's push and pull of one are one. */
let newestGpuCrash: number | undefined;
/** Row 9's 10 s hand-over, armed when its episode starts and cleared when the episode ends. */
let handover: ReturnType<typeof setTimeout> | null = null;

function clearHandover(): void {
  if (handover !== null) clearTimeout(handover);
  handover = null;
}

function syncHandover(degraded: DegradedFacts): void {
  if (degraded.asserted.privateReconnect === undefined || degraded.privateHandedOver) {
    clearHandover();
    return;
  }
  handover ??= setTimeout(() => {
    handover = null;
    setShellState({ degraded: handOverPrivateReconnect(state.degraded) });
  }, PRIVATE_HANDOVER_MS);
}
const listeners = new Set<() => void>();

export function getShellState(): ShellState {
  return state;
}

export function subscribeShellState(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setShellState(patch: Partial<ShellState>): void {
  const was = state;
  state = { ...state, ...patch };
  // Latched on the first live link; only `resetShellState` (logout, a stopped shell) clears it.
  if (patch.connection?.kind === "live" && !state.everLive) {
    state = { ...state, everLive: true };
    markShellStage(SHELL_PERF_MARKS.wsLive); // budget #10: once per page load (perfMarks)
  }
  // SCR-157: another build, or the state's end (E10-D04 T-18), ends the answer, so an incompatible
  // build that comes back is the server's answer again and opens the dialog (T-15)
  if (state.serverProtocol !== was.serverProtocol || state.serverVersion !== was.serverVersion) {
    state = { ...state, continuedFor: undefined };
  }
  for (const listener of listeners) listener();
}

/** Merges one `SystemUpdate` frame into `systemByKind`, keyed by its `kind`, and folds it into `degraded`. */
export function applySystemUpdate(update: SystemUpdate): void {
  const degraded = reduceDegraded(state.degraded, update);
  setShellState({ systemByKind: { ...state.systemByKind, [update.kind]: update }, degraded });
  syncHandover(degraded);
}

/** Drops the degraded facts and row 9's hand-over timer, so a stopped shell leaves neither behind. */
export function clearDegraded(): void {
  clearHandover();
  setShellState({ degraded: INITIAL_DEGRADED_FACTS });
}

/**
 * A GPU-process crash: SCR-159's page shows, and an earlier answer's GPU row yields to it. True
 * when the page shows for a crash new to the store. One it took already (#4951: main pushes it
 * and answers it on subscribe) changes nothing, unless its page is gone: the user kept software
 * rendering, and the row holds again (a stopped shell drops it with its other facts). One `kept`
 * this launch (main's answer on subscribe after a reload, #306) is the row, never the page.
 */
export function applyGpuCrash(crash: GpuCrash, kept = false): boolean {
  if (newestGpuCrash !== undefined && crash.restartCount <= newestGpuCrash) {
    if (state.gpuCrash === null && state.degraded.asserted.gpuFallback === undefined) {
      keepSoftwareRendering();
    }
    return false;
  }
  newestGpuCrash = crash.restartCount;
  if (kept) {
    keepSoftwareRendering(); // reported when its page first showed, before the keep
    return false;
  }
  setShellState({ gpuCrash: crash, degraded: setGpuFallback(state.degraded, false) });
  return true;
}

/** "Keep software rendering": the page goes; SCR-153's GPU row holds for the session (BQ-9.3). */
export function keepSoftwareRendering(): void {
  setShellState({ gpuCrash: null, degraded: setGpuFallback(state.degraded, true) });
}

/** SCR-157's Later (E10-D03 §9.1): the banner goes until the next launch; the StatusBar reminds. */
export function deferUpdate(): void {
  setShellState({ updateDeferred: true });
}

/** SCR-157's Continue read-only (E10-D03 §9.1): that build's dialog goes; its T2 legs stay. */
export function continueReadOnly(build: string): void {
  setShellState({ continuedFor: build });
}

/** Test-only reset to the initial, unauthenticated shell state. */
export function resetShellState(): void {
  clearHandover();
  newestGpuCrash = undefined;
  state = INITIAL_SHELL_STATE;
  for (const listener of listeners) listener();
}
