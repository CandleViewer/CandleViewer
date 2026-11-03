/**
 * `apps/web/src/shell/bootstrap.ts` (ticket scope path): the single parallel
 * fetch of `GET /me`, `GET /me/preferences`, `GET /me/keymap` and (E42-S03)
 * `GET /auth/session/view-as` on app start.
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
 *
 * The view-as read (`22` `getViewAs`: a window reads it "before it mounts any control") is the
 * shell's read-only state, so it is never optional: a read that fails fails the boot as `/me`'s
 * does (fail closed), and the shell never mounts writable as if no context were held. A context
 * the server ended refuses `/me` itself (`view_as_expired`, reads included): that boot is `held`,
 * whose page is SCR-124's banner with Exit (`main.tsx`), never /login.
 */
import {
  MeSignedOutError,
  setMeClaims,
  setMeClaimsReader,
  type MeClaimsReader,
} from "../../lib/auth/meCache.js";
import { accessToken } from "../../lib/auth/accessToken.js";
import { bootViewAs } from "../../lib/auth/viewAsContext.js";
import type { MeClaims, Role } from "../../routes/rbac.js";
import { HttpError, HttpTimeoutError, fetchJson } from "./httpClient.js";
import {
  applyAppearance,
  applyChartColorMode,
  readStoredChartColorMode,
} from "./preferencesApply.js";
import { SHELL_PERF_MARKS, markShellStage } from "../perfMarks.js";
import {
  type BootstrapPhase,
  type Keymap,
  type Me,
  type Settings,
  setShellState,
} from "./store.js";

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
  };
}

/** Runs the four-call parallel bootstrap. Never throws — failures are
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
  // E42-S03: never rejects; its answer is in the store before `/me`'s is (the keymap keys on both)
  const viewAsPromise = bootViewAs({ fetchImpl });

  const [[meResult, preferencesResult, keymapResult], viewAs] = await Promise.all([
    Promise.allSettled([mePromise, preferencesPromise, keymapPromise]),
    viewAsPromise,
  ]);

  clearTimeoutImpl(slowTimer);

  // The server ended the context and holds it: `/me` is refused, and only Exit leads on (V-8).
  if (viewAs.ok && viewAs.state.kind === "held" && viewAs.state.state === "expired") {
    setShellState({ bootstrap: { kind: "held" } });
    return;
  }

  if (meResult.status === "rejected") {
    setShellState({ bootstrap: classifyFailure(meResult.reason) });
    return;
  }

  // Fail closed: no `204` and no context read is never "no context".
  if (!viewAs.ok) {
    setShellState({ bootstrap: classifyFailure(viewAs.error) });
    return;
  }

  const me = meResult.value;
  setMeClaims(meToClaims(me));
  // #5405: a later navigation re-reads `/me` past the claims' staleness bound, so a role or grant
  // the server changed applies without a reload; the shell's `me` and environment follow the
  // same answer, so the environment badge never disagrees with `me`.
  setMeClaimsReader(createMeClaimsReader(fetchImpl));
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
  markShellStage(SHELL_PERF_MARKS.bootstrapReady);
}

/**
 * The route loaders' `/me` re-read (#5405). It is `quiet`: a lost session's `401` does not make the
 * token holder route to sign-in from the page being left (the loader runs before the navigation
 * commits); the reader answers `MeSignedOutError` and the guard routes with the destination as
 * `next`. Only a session the holder found gone is a sign-out: a `401` it could not cure because its
 * refresh failed (a network error, a timeout, a 5xx, a malformed bundle) or found the session
 * idle-locked (the lock overlay answers that), or an idle lock's own `401`, rejects as any other
 * failure does, and the cached claims stay.
 */
export function createMeClaimsReader(fetchImpl?: typeof fetch): MeClaimsReader {
  return async () => {
    let next: Me;
    try {
      next = await fetchJson<Me>("/api/v1/me", {
        timeoutMs: BOOTSTRAP_TIMEOUT_MS,
        fetchImpl,
        quiet: true,
      });
    } catch (error) {
      if (
        error instanceof HttpError &&
        error.status === 401 &&
        error.code !== "session_idle_locked" &&
        accessToken.isSignedOut()
      ) {
        throw new MeSignedOutError();
      }
      throw error;
    }
    setShellState({ me: next, environment: next.session?.environment ?? "unknown" });
    return meToClaims(next);
  };
}

/** A `/me` or view-as read failure as the boot's phase: SCR-005, R-902 (unreached), the guards. */
function classifyFailure(reason: unknown): BootstrapPhase {
  if (reason instanceof HttpError && reason.code === "session_idle_locked") {
    return { kind: "locked" };
  }
  if (reason instanceof HttpTimeoutError) {
    return { kind: "failed", reason: "timeout" };
  }
  if (reason instanceof HttpError) {
    return { kind: "failed", reason: "http_error", status: reason.status };
  }
  return { kind: "failed", reason: "unknown" };
}
