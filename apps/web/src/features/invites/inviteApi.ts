/** Thin REST client for E09-S05 invites (`docs/plan/22-api-openapi.yaml`). */

import { apiFetch } from "../../lib/http/csrfFetch";
const BASE = "/api/v1";

export interface ApiResult<T> {
  readonly ok: boolean;
  readonly status: number;
  readonly code: string | null;
  readonly data: T | null;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<ApiResult<T>> {
  const init: RequestInit = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) init.body = JSON.stringify(body);
  let response: Response;
  try {
    response = await apiFetch(`${BASE}${path}`, init);
  } catch {
    return { ok: false, status: 0, code: null, data: null };
  }
  let json: unknown = null;
  try {
    json = await response.json();
  } catch {
    json = null;
  }
  const obj = (json ?? {}) as { code?: string };
  return {
    ok: response.ok,
    status: response.status,
    code: typeof obj.code === "string" ? obj.code : null,
    data: response.ok ? (json as T) : null,
  };
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
