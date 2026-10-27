/**
 * #1640: the session-lifetime calls of the idle lock (`22-api-openapi.yaml` "Idle lock"):
 * `GET /auth/session` (read-only, never activity), `POST /auth/session/extend` (CMP-098 Extend, the
 * only activity signal besides unlock) and `POST /auth/unlock` (SCR-005, password only).
 */
import type { generated } from "@candleviewer/protocol";
import { accessToken, type SignOutReason } from "../../lib/auth/accessToken";
import { apiFetch } from "../../lib/http/csrfFetch";

type Ops = generated.rest.operations;
/** The deadlines plus the server clock they are timed against (never a client clock). */
export type SessionClock =
  Ops["authExtendSession"]["responses"][200]["content"]["application/json"];
type UnlockBody = Ops["authUnlock"]["requestBody"]["content"]["application/json"];

export type UnlockOutcome =
  | { readonly kind: "unlocked"; readonly clock: SessionClock }
  /** `401 unlock_invalid` */
  | { readonly kind: "invalid" }
  /** `401 session_revoked` (fifth wrong password, absolute expiry) or `unauthenticated`: sign in again. */
  | { readonly kind: "revoked"; readonly reason?: "expired" | "unlock_attempts_exceeded" }
  /** `409 conflict`: the session is not locked; re-read it. */
  | { readonly kind: "not_locked" }
  | { readonly kind: "throttled" }
  | { readonly kind: "unreachable" };

export interface SessionApi {
  read(): Promise<SessionClock | null>;
  extend(): Promise<SessionClock | null>;
  unlock(password: string): Promise<UnlockOutcome>;
  /** SCR-005 "Sign out instead": `POST /auth/logout` (bearer, else the cookie); `true` once the session is gone. */
  signOut(): Promise<boolean>;
  /** Forgets the token in every tab and routes to SCR-001, with `reason` for its reason line. */
  endSession(reason?: SignOutReason): void;
  /** Calls `listener` when a refresh or a call finds the session idle-locked; returns the unsubscribe. */
  onLocked(listener: () => void): () => void;
}

const BASE = "/api/v1/auth";

/** The sign-out failure line (SCR-005 `sign-out-instead`, PROPOSED `lock.unreachable`; the TopBar's Sign out). */
export const SIGN_OUT_FAILED = "Couldn't reach the server. Try again.";

const finiteTime = (value: unknown): boolean =>
  typeof value === "string" && Number.isFinite(Date.parse(value));

/** Only a clock the host can time from: a bad date would schedule a 0 ms re-read loop. */
function isClock(body: unknown): body is SessionClock {
  if (typeof body !== "object" || body === null) return false;
  const { session, server_time: time } = body as Partial<SessionClock>;
  return (
    finiteTime(time) &&
    finiteTime(session?.idle_deadline) &&
    typeof session?.locked === "boolean" &&
    Number.isFinite(session.idle_timeout_s)
  );
}

async function clockOf(call: Promise<Response>): Promise<SessionClock | null> {
  try {
    const res = await call;
    const body: unknown = res.ok ? await res.json() : null;
    return isClock(body) ? body : null;
  } catch {
    return null;
  }
}

/** An unlock with no answer by then is reported unreachable, so SCR-005 never stays verifying. */
export const UNLOCK_TIMEOUT_MS = 15_000;

async function unlock(password: string): Promise<UnlockOutcome> {
  const body: UnlockBody = { password };
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), UNLOCK_TIMEOUT_MS);
  try {
    const res = await apiFetch(`${BASE}/unlock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: abort.signal,
    });
    if (res.status === 409) return { kind: "not_locked" };
    if (res.status === 429) return { kind: "throttled" };
    if (res.status === 401) {
      // fail safe: any 401 but a wrong password, a body that is not JSON included, ends the session
      const problem: unknown = await res.json().catch(() => null);
      // a body cut off by the timeout is no answer, not a refusal: never sign out over a slow server
      if (problem === null && abort.signal.aborted) return { kind: "unreachable" };
      const { code, revoked_reason: why } = (problem ?? {}) as Record<string, unknown>;
      if (code === "unlock_invalid") return { kind: "invalid" };
      const known =
        code === "session_revoked" && (why === "expired" || why === "unlock_attempts_exceeded");
      return known ? { kind: "revoked", reason: why } : { kind: "revoked" };
    }
    const clock = res.ok ? await clockOf(Promise.resolve(res)) : null;
    if (clock === null) return { kind: "unreachable" };
    // 22: after a long lock the token may have lapsed, so the client unlocks, then refreshes
    void accessToken.refresh();
    return { kind: "unlocked", clock };
  } catch {
    return { kind: "unreachable" }; // no answer, or the timeout aborted it
  } finally {
    clearTimeout(timeout);
  }
}

/** A `401` means the session is already gone; any other refusal or no answer revoked nothing. */
async function signOut(): Promise<boolean> {
  try {
    const res = await apiFetch(`${BASE}/logout`, { method: "POST" });
    return res.ok || res.status === 401;
  } catch {
    return false;
  }
}

export const sessionApi: SessionApi = {
  read: () => clockOf(apiFetch(`${BASE}/session`)),
  extend: () => clockOf(apiFetch(`${BASE}/session/extend`, { method: "POST" })),
  unlock,
  signOut,
  endSession: (reason) => accessToken.endSession(reason),
  onLocked: (listener) => accessToken.onLocked(listener),
};
