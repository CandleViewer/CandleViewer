/**
 * Thin REST client for E09-S01 sign-in (`docs/plan/22-api-openapi.yaml` /auth/login, /auth/password,
 * /auth/mfa/verify, /auth/mfa/recovery).
 */

import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../lib/http/csrfFetch";

const BASE = "/api/v1";

type Schemas = generated.rest.components["schemas"];
/** `remember_device_days` is never sent: there is no trust-device control in v1 (E09-D12 §5.2). */
type MfaVerifyBody = Omit<Schemas["MfaVerifyRequest"], "remember_device_days">;
type MfaRecoveryBody =
  generated.rest.operations["authMfaRecovery"]["requestBody"]["content"]["application/json"];

export type LoginOutcome =
  | {
      readonly kind: "mfa_required";
      readonly mfaToken: string;
      readonly methods: readonly string[];
      /** The challenge's life in seconds (`MfaChallengeResponse.expires_in`), read once at receipt. */
      readonly expiresInS: number;
    }
  | { readonly kind: "authenticated" }
  | { readonly kind: "invalid" }
  | { readonly kind: "rate_limited"; readonly retryAfterS: number }
  | { readonly kind: "unreachable" };

/** The countdown when a `429` carries no usable `Retry-After`. */
const DEFAULT_RETRY_S = 15 * 60;
/** The challenge life when an `mfa_required` answer carries no usable `expires_in` (`22`: 5 min). */
const DEFAULT_CHALLENGE_S = 5 * 60;

const retryAfter = (res: Response): number => {
  const header = Number(res.headers?.get("Retry-After"));
  return Number.isFinite(header) && header > 0 ? header : DEFAULT_RETRY_S;
};

/**
 * `POST /auth/login`. Every failed sign-in is the contract's one `401` (SR-014, #4961), so a refusal
 * keys on the status alone, never on a `code`, `title` or `detail`: a `429` counts down from its
 * `Retry-After`, a `5xx` is unreachable, and any other refusal is the one failure string.
 */
export async function login(identifier: string, password: string): Promise<LoginOutcome> {
  let res: Response;
  try {
    res = await apiFetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier, password }),
    });
  } catch {
    return { kind: "unreachable" };
  }
  if (res.status === 429) return { kind: "rate_limited", retryAfterS: retryAfter(res) };
  if (res.status === 503 || res.status >= 500) return { kind: "unreachable" };
  if (!res.ok) return { kind: "invalid" };
  let body: { status?: string; mfa_token?: string; methods?: string[]; expires_in?: unknown } = {};
  try {
    body = (await res.json()) as typeof body;
  } catch {
    return { kind: "unreachable" };
  }
  if (body.status === "mfa_required" && typeof body.mfa_token === "string") {
    const life = body.expires_in;
    return {
      kind: "mfa_required",
      mfaToken: body.mfa_token,
      methods: body.methods ?? [],
      expiresInS:
        typeof life === "number" && Number.isFinite(life) && life > 0 ? life : DEFAULT_CHALLENGE_S,
    };
  }
  return body.status === "authenticated" ? { kind: "authenticated" } : { kind: "invalid" };
}

/**
 * The answer to one second-factor submission. `invalid` is the `401` alone, the only answer the
 * client's display-only attempt mirror counts; `refused` is any other `4xx`, rendered the same way
 * and not counted. The server holds the real count and the lock (C-2.21).
 */
export type MfaOutcome =
  | { readonly kind: "authenticated"; readonly enrolmentOnly: boolean }
  | { readonly kind: "invalid" }
  | { readonly kind: "refused" }
  | { readonly kind: "rate_limited"; readonly retryAfterS: number }
  | { readonly kind: "unreachable" };

/** A complete TOTP code as SCR-002 sends it: six digits (CMP-204), inside `MfaVerifyRequest.code`. */
export const TOTP_CODE = /^[0-9]{6}$/u;
/** A recovery code the contract accepts (`authMfaRecovery`: 8 to 64 characters; the code charset). */
export const RECOVERY_CODE = /^[0-9A-Za-z-]{8,64}$/u;

async function completeChallenge(
  path: string,
  body: MfaVerifyBody | MfaRecoveryBody,
  enrolmentOnlyAlways: boolean,
): Promise<MfaOutcome> {
  let res: Response;
  try {
    res = await apiFetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { kind: "unreachable" };
  }
  if (res.status === 429) return { kind: "rate_limited", retryAfterS: retryAfter(res) };
  if (res.status >= 500) return { kind: "unreachable" };
  if (res.status === 401) return { kind: "invalid" };
  if (!res.ok) return { kind: "refused" };
  // The session cookies are set by now. Only `user` is read; the token bundle is never kept: the
  // page load that follows re-derives the access token from the refresh cookie (ADR-0020).
  let user: Partial<Schemas["User"]> | undefined;
  try {
    const parsed = (await res.json()) as { user?: unknown } | null;
    const candidate = parsed?.user;
    user = typeof candidate === "object" && candidate !== null ? candidate : undefined;
  } catch {
    user = undefined;
  }
  const enrolmentOnly = user?.mfa_required === true && user.mfa_enabled === false;
  return { kind: "authenticated", enrolmentOnly: enrolmentOnlyAlways || enrolmentOnly };
}

/**
 * `POST /auth/mfa/verify` with a TOTP code. Like `login`, the outcome keys on the status alone,
 * never on a `code`, `title` or `detail` (E09-D12 §4.1, F-2): a replayed code reads as an invalid
 * one. The caller sends only a code matching `TOTP_CODE`, so no `422` leaves the browser.
 */
export function verifyTotp(mfaToken: string, code: string): Promise<MfaOutcome> {
  return completeChallenge(
    "/auth/mfa/verify",
    { mfa_token: mfaToken, method: "totp", code },
    false,
  );
}

/**
 * `POST /auth/mfa/recovery`. Its `200` is always an enrolment-only session (`22` authMfaRecovery),
 * so the caller goes to enrolment whatever the body says. Status-only, as `verifyTotp`.
 */
export function verifyRecovery(mfaToken: string, recoveryCode: string): Promise<MfaOutcome> {
  return completeChallenge(
    "/auth/mfa/recovery",
    { mfa_token: mfaToken, recovery_code: recoveryCode },
    true,
  );
}

export type ChangePasswordOutcome = "ok" | "reused" | "breached" | "invalid" | "unreachable";

export async function changePassword(
  current: string,
  next: string,
): Promise<ChangePasswordOutcome> {
  let res: Response;
  try {
    res = await apiFetch(`${BASE}/auth/password`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
  } catch {
    return "unreachable";
  }
  if (res.ok) return "ok";
  if (res.status >= 500) return "unreachable";
  let code = "";
  try {
    const b = (await res.json()) as { code?: string; detail?: string };
    code = `${b.code ?? ""} ${b.detail ?? ""}`.toLowerCase();
  } catch {
    code = "";
  }
  if (code.includes("reuse") || code.includes("previous")) return "reused";
  if (code.includes("breach")) return "breached";
  return "invalid";
}

export function formatRemaining(totalSeconds: number): string {
  const s = Math.max(0, Math.ceil(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
