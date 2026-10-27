/**
 * #1640: the session-lifetime calls of the idle lock (`22-api-openapi.yaml` "Idle lock"):
 * `GET /auth/session` (read-only, never activity), `POST /auth/session/extend` (CMP-098 Extend, the
 * only activity signal besides unlock) and `POST /auth/unlock` (SCR-005, password only).
 */
import type { generated } from "@candleviewer/protocol";
import { accessToken } from "../../lib/auth/accessToken";
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
  | { readonly kind: "revoked" }
  /** `409 conflict`: the session is not locked; re-read it. */
  | { readonly kind: "not_locked" }
  | { readonly kind: "throttled" }
  | { readonly kind: "unreachable" };

export interface SessionApi {
  read(): Promise<SessionClock | null>;
  extend(): Promise<SessionClock | null>;
  unlock(password: string): Promise<UnlockOutcome>;
  /** Forgets the token in every tab and routes to SCR-001. */
  endSession(): void;
}

const BASE = "/api/v1/auth";

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
      const code = (problem as { code?: unknown } | null)?.code;
      return code === "unlock_invalid" ? { kind: "invalid" } : { kind: "revoked" };
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

export const sessionApi: SessionApi = {
  read: () => clockOf(apiFetch(`${BASE}/session`)),
  extend: () => clockOf(apiFetch(`${BASE}/session/extend`, { method: "POST" })),
  unlock,
  endSession: () => accessToken.endSession(),
};
