/** Thin REST client for E09-S05 invites (`docs/plan/22-api-openapi.yaml`). */

import {
  holdRequest,
  readChallenge,
  sendHeld,
  type HeldRequest,
  type StepUpChallenge,
} from "../stepUp/challenge";

const BASE = "/api/v1";

/** A `403 step_up_required` refusal: the challenge, and the refused request held unchanged. */
export interface StepUpHold {
  readonly challenge: StepUpChallenge;
  readonly held: HeldRequest;
}

export interface ApiResult<T> {
  readonly ok: boolean;
  readonly status: number;
  readonly code: string | null;
  readonly data: T | null;
  /** Set when the call was refused with a step-up challenge (#2725). */
  readonly stepUp: StepUpHold | null;
}

/** Reads a response of `held` (its first send or its re-send after a step-up). */
export async function readResult<T>(response: Response, held: HeldRequest): Promise<ApiResult<T>> {
  let json: unknown = null;
  try {
    json = await response.json();
  } catch {
    json = null;
  }
  const obj = (json ?? {}) as { code?: string };
  // The `Date` header gives the server clock the challenge's expiry is on (plain test doubles have no headers).
  const date = response.headers?.get("Date") ?? null;
  const challenge = response.status === 403 ? readChallenge(json, date) : null;
  return {
    ok: response.ok,
    status: response.status,
    code: typeof obj.code === "string" ? obj.code : null,
    data: response.ok ? (json as T) : null,
    stepUp: challenge === null ? null : { challenge, held },
  };
}

const SAFE_METHODS: ReadonlySet<string> = new Set(["GET", "HEAD", "OPTIONS"]);

async function call<T>(method: string, path: string, body?: unknown): Promise<ApiResult<T>> {
  const payload = body === undefined ? null : JSON.stringify(body);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // One key per call, held with the request, so a re-send after a step-up is the same submission (C-2.10).
  if (!SAFE_METHODS.has(method)) headers["Idempotency-Key"] = crypto.randomUUID();
  const held = holdRequest(method, `${BASE}${path}`, headers, payload);
  let response: Response;
  try {
    response = await sendHeld(held);
  } catch {
    return { ok: false, status: 0, code: null, data: null, stepUp: null };
  }
  return readResult<T>(response, held);
}

export interface CreatedInvite {
  readonly id: string;
  readonly username: string;
  readonly invite_url: string;
  readonly invite_expires_at: string;
}
export interface PendingInvite {
  readonly user_id: string;
  readonly username: string;
  readonly role: string;
  readonly expires_at: string;
  readonly expired: boolean;
}
export interface InviteView {
  readonly display_name: string;
  readonly role: string;
  readonly expires_at: string;
}
export interface EnrollStart {
  readonly method_id: string;
  readonly otpauth_uri: string;
  readonly secret_base32: string;
}
export interface Confirmed {
  readonly status: string;
  readonly role: string;
  readonly recovery_codes: readonly string[];
}

export const inviteApi = {
  create: (body: { username: string; email: string; roles: string[] }) =>
    call<CreatedInvite>("POST", "/users", body),
  list: () => call<{ items: PendingInvite[] }>("GET", "/users/invites"),
  reissue: (userId: string) => call<CreatedInvite>("POST", `/users/${userId}/invite`),
  revoke: (userId: string) => call<unknown>("DELETE", `/users/${userId}/invite`),
  inspect: (token: string) => call<InviteView>("GET", `/invites/${encodeURIComponent(token)}`),
  redeem: (token: string, password: string) =>
    call<EnrollStart>("POST", `/invites/${encodeURIComponent(token)}`, { password }),
  confirm: (token: string, methodId: string, code: string) =>
    call<Confirmed>("POST", `/invites/${encodeURIComponent(token)}/confirm`, {
      method_id: methodId,
      code,
    }),
};
