/** Thin REST client for E09-S01 sign-in (`docs/plan/22-api-openapi.yaml` /auth/login, /auth/password). */

import { apiFetch } from "../../lib/http/csrfFetch";

const BASE = "/api/v1";

export type LoginOutcome =
  | {
      readonly kind: "mfa_required";
      readonly mfaToken: string;
      readonly methods: readonly string[];
    }
  | { readonly kind: "authenticated" }
  | { readonly kind: "invalid" }
  | { readonly kind: "rate_limited"; readonly retryAfterS: number }
  | { readonly kind: "unreachable" };

/** The countdown when a `429` carries no usable `Retry-After`. */
const DEFAULT_RETRY_S = 15 * 60;

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
  if (res.status === 429) {
    const header = Number(res.headers?.get("Retry-After"));
    return {
      kind: "rate_limited",
      retryAfterS: Number.isFinite(header) && header > 0 ? header : DEFAULT_RETRY_S,
    };
  }
  if (res.status === 503 || res.status >= 500) return { kind: "unreachable" };
  if (!res.ok) return { kind: "invalid" };
  let body: { status?: string; mfa_token?: string; methods?: string[] } = {};
  try {
    body = (await res.json()) as typeof body;
  } catch {
    return { kind: "unreachable" };
  }
  if (body.status === "mfa_required" && typeof body.mfa_token === "string") {
    return { kind: "mfa_required", mfaToken: body.mfa_token, methods: body.methods ?? [] };
  }
  return body.status === "authenticated" ? { kind: "authenticated" } : { kind: "invalid" };
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
