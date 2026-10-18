/**
 * `apps/web/src/shell/bootstrap.ts` (ticket scope path): the single parallel
 * fetch of `GET /me`, `GET /me/preferences`, `GET /me/keymap` on app start.
 * Route guards (E10-T01) and chrome (E10-S01) read the resulting cache
 * synchronously via `useShellState()` / `getShellState()` — nothing else
 * fetches these endpoints.
 *
 * Contract: ticket AC "One bootstrap, not many" — exactly one request each,
 * issued in parallel; "Environment is never guessed" — the environment
 * field stays `"unknown"` until `/me` resolves; "Bootstrap failure is
 * explicit" — a `/me` failure sets `bootstrap.kind = "failed"`, never a
 * silently empty shell; preferences/keymap failures are non-fatal (a broken
 * keymap must not block login).
 */
import { setMeClaims } from "../../lib/auth/meCache.js";
import type { MeClaims, Role } from "../../routes/rbac.js";
import { HttpError, HttpTimeoutError, fetchJson } from "./httpClient.js";
import {
  applyAppearance,
  applyChartColorMode,
  readStoredChartColorMode,
} from "./preferencesApply.js";
import { type Keymap, type Me, type Settings, setShellState } from "./store.js";

/** `/me` has this ceiling before the "slow boot" state is shown (SCR-150). */
export const SLOW_BOOT_THRESHOLD_MS = 5_000;
/** Hard timeout for each bootstrap call. */
export const BOOTSTRAP_TIMEOUT_MS = 10_000;

export interface BootstrapDeps {
  readonly fetchImpl?: typeof fetch | undefined;
  readonly setTimeoutImpl?: typeof setTimeout | undefined;
  readonly clearTimeoutImpl?: typeof clearTimeout | undefined;
}

function meToClaims(me: Me): MeClaims {
  return {
    authenticated: true,
    role: me.role as Role,
    permissions: me.permissions,
    elevatedAt: me.session?.elevated_until ?? null,
  };
}

/** Runs the three-call parallel bootstrap. Never throws — failures are
 * recorded on the shell store, matching the ticket's "explicit failure"
 * and "non-fatal preference/keymap failure" requirements. */
export async function runBootstrap(deps: BootstrapDeps = {}): Promise<void> {
  const { fetchImpl, setTimeoutImpl = setTimeout, clearTimeoutImpl = clearTimeout } = deps;

  const slowTimer = setTimeoutImpl(() => {
    setShellState({ bootstrap: { kind: "slow" } });
  }, SLOW_BOOT_THRESHOLD_MS);

  const mePromise = fetchJson<Me>("/api/v1/me", {
    timeoutMs: BOOTSTRAP_TIMEOUT_MS,
    fetchImpl,
  });
  const preferencesPromise = fetchJson<Settings>("/api/v1/me/preferences", {
    timeoutMs: BOOTSTRAP_TIMEOUT_MS,
    fetchImpl,
  });
  const keymapPromise = fetchJson<Keymap>("/api/v1/me/keymap", {
    timeoutMs: BOOTSTRAP_TIMEOUT_MS,
    fetchImpl,
  });

  const [meResult, preferencesResult, keymapResult] = await Promise.allSettled([
    mePromise,
    preferencesPromise,
    keymapPromise,
  ]);

  clearTimeoutImpl(slowTimer);

  if (meResult.status === "rejected") {
    setShellState({ bootstrap: classifyMeFailure(meResult.reason) });
    return;
  }

  const me = meResult.value;
  setMeClaims(meToClaims(me));
  setShellState({
    me,
    // Environment comes from `/me` (`session.environment`) or the WS
    // `system` topic only — never a client default (ticket AC).
    environment: me.session?.environment ?? "unknown",
  });

  if (preferencesResult.status === "fulfilled") {
    applyAppearance(preferencesResult.value);
    setShellState({ preferences: preferencesResult.value, preferencesWarning: null });
  } else {
    // Nothing to apply: the runtime keeps the persisted choice or its own defaults (no clobber).
    setShellState({
      preferencesWarning: "Preferences failed to load; using defaults.",
    });
  }
  applyChartColorMode(readStoredChartColorMode());

  if (keymapResult.status === "fulfilled") {
    setShellState({ keymap: keymapResult.value, keymapWarning: null });
  } else {
    setShellState({ keymapWarning: "Keymap failed to load; hotkeys are unavailable." });
  }

  setShellState({ bootstrap: { kind: "ready" } });
}

function classifyMeFailure(reason: unknown): {
  kind: "failed";
  reason: "timeout" | "http_error" | "unknown";
  status?: number;
} {
  if (reason instanceof HttpTimeoutError) {
    return { kind: "failed", reason: "timeout" };
  }
  if (reason instanceof HttpError) {
    return { kind: "failed", reason: "http_error", status: reason.status };
  }
  return { kind: "failed", reason: "unknown" };
}
