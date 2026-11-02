/**
 * Thin REST client for E09-S01 sign-in (`docs/plan/22-api-openapi.yaml` /auth/login, /auth/password,
 * /auth/mfa/verify, /auth/mfa/recovery).
 */

import type { ErrorCode, generated } from "@candleviewer/protocol";
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

type ChangePasswordBody = Schemas["ChangePasswordRequest"];
type Problem = Schemas["Problem"];

/** Why the server refused the new password (`04-security-program.md` §6.3.1), one W-string each. */
export type PasswordRefusal =
  "breached" | "reused" | "too_short" | "too_long" | "identity" | "other";

/**
 * The answer to `PUT /auth/password` (`authChangePassword`), keyed on the problem `code` and
 * `errors[].rule`, never on `detail` (E09-D05 §6.1, BQ-21).
 */
export type ChangePasswordOutcome =
  /** `200`: the replacement session's token bundle is already held (`accessToken`, MINTING). */
  | { readonly kind: "changed" }
  /** `403 current_password_invalid`, or `409`: the password it was checked against changed meanwhile. */
  | { readonly kind: "current_invalid" }
  | { readonly kind: "refused"; readonly reason: PasswordRefusal }
  | { readonly kind: "rate_limited"; readonly retryAfterS: number }
  /** `403 session_read_only` (D09:273). */
  | { readonly kind: "read_only" }
  /** `403 mfa_enrollment_required`: the second factor comes first (E09-D05 §3.3). */
  | { readonly kind: "enrolment_required" }
  /** `401`: the session is gone (D08:127). */
  | { readonly kind: "signed_out" }
  /** `401 session_idle_locked`: the session lives on, locked; SCR-005 unlocks it, nothing is cleared. */
  | { readonly kind: "locked" }
  /**
   * `503 store_unavailable`: the rotation may have failed after the new password was committed (`22`
   * route `503`: "sign in again with it"), so the change is never re-sent; the client signs in again.
   */
  | { readonly kind: "sign_in_again" }
  /** Any other `403` (view-as is not reachable before the shell, E09-D05 §8). */
  | { readonly kind: "not_allowed" }
  | { readonly kind: "unreachable" };

const POLICY_RULES: Readonly<Record<string, PasswordRefusal>> = {
  min_length: "too_short",
  contains_identity: "identity",
};

function refusalOf(problem: Partial<Problem>): PasswordRefusal {
  const code = problem.code as ErrorCode | undefined;
  if (code === "password_breached") return "breached";
  if (code === "password_reused") return "reused";
  const rules = (problem.errors ?? [])
    .filter((e) => e.field === undefined || e.field === "new_password")
    .map((e) => e.rule ?? "");
  if (code === "password_policy") {
    const rule = rules.find((r) => Object.hasOwn(POLICY_RULES, r));
    return rule === undefined ? "other" : (POLICY_RULES[rule] ?? "other");
  }
  if (code === "validation_failed" && rules.includes("max_length")) return "too_long";
  return "other";
}

/** `PUT /auth/password`. The rotated session's bundle is adopted by `apiFetch` (#2110, SR-013). */
export async function changePassword(
  current: string,
  next: string,
): Promise<ChangePasswordOutcome> {
  const body: ChangePasswordBody = { current_password: current, new_password: next };
  let res: Response;
  try {
    res = await apiFetch(`${BASE}/auth/password`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { kind: "unreachable" };
  }
  if (res.ok) return { kind: "changed" };
  if (res.status === 429) return { kind: "rate_limited", retryAfterS: retryAfter(res) };
  if (res.status === 409) return { kind: "current_invalid" };
  let problem: Partial<Problem> = {};
  try {
    const parsed: unknown = await res.json();
    if (typeof parsed === "object" && parsed !== null) problem = parsed as Partial<Problem>;
  } catch {
    problem = {};
  }
  const code = problem.code as ErrorCode | undefined;
  if (res.status === 401) {
    return code === "session_idle_locked" ? { kind: "locked" } : { kind: "signed_out" };
  }
  if (res.status === 403) {
    if (code === "current_password_invalid") return { kind: "current_invalid" };
    if (code === "session_read_only") return { kind: "read_only" };
    if (code === "mfa_enrollment_required") return { kind: "enrolment_required" };
    // a CSRF refusal apiFetch could not recover from is the 503 row (E09-D05 §6.1)
    return code === "csrf_token_invalid" ? { kind: "unreachable" } : { kind: "not_allowed" };
  }
  if (res.status === 422) {
    // a current password the schema refuses (over 512 characters) cannot be the right one
    const errors = problem.errors ?? [];
    const currentOnly = errors.length > 0 && errors.every((e) => e.field === "current_password");
    if (code === "validation_failed" && currentOnly) return { kind: "current_invalid" };
    return { kind: "refused", reason: refusalOf(problem) };
  }
  // `audit_unavailable` changed nothing: W-18 and Retry; `store_unavailable` may follow a commit
  if (res.status === 503 && code === "store_unavailable") return { kind: "sign_in_again" };
  return { kind: "unreachable" };
}

export function formatRemaining(totalSeconds: number): string {
  const s = Math.max(0, Math.ceil(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
