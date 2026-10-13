/**
 * SR-041 double-submit CSRF for every REST call (`22-api-openapi.yaml` info "CSRF", #2090).
 *
 * On every state-changing method (anything but GET/HEAD/OPTIONS) to this origin, the client
 * reads the `__Host-cv_csrf` cookie and sends it in `X-CSRF-Token`. The header is never attached to
 * a cross-origin URL. It is also sent on the exempt pre-session routes (login, MFA, invites), where
 * the server ignores it.
 *
 * On `403 csrf_token_invalid` (e.g. another tab rotated the token) the client recovers once:
 * - if the cookie is absent, it calls `GET /auth/session` first with the request's own
 *   `Authorization` header (that route authenticates the bearer only, then re-issues the cookie);
 * - if the re-read cookie equals the token just sent, nothing rotated, so the first 403 is returned
 *   without repeating a non-idempotent request;
 * - otherwise it retries exactly once. A second refusal is returned to the caller unchanged.
 *
 * Bodies must be replayable (string / ArrayBuffer / Blob / URLSearchParams): a `ReadableStream` body
 * is refused up front because it cannot be retried.
 */

import { ERROR_META } from "@candleviewer/protocol";

export const CSRF_COOKIE = "__Host-cv_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
export const CSRF_ERROR_CODE: keyof typeof ERROR_META = "csrf_token_invalid";
const SESSION_PATH = "/api/v1/auth/session";

/** The contract's safe set ("Exempt"); everything else, TRACE included, is guarded. */
const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

/** Current `__Host-cv_csrf` value, or `null` when absent. */
export function readCsrfCookie(cookieSource: string = document.cookie): string | null {
  for (const part of cookieSource.split(";")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    if (part.slice(0, eq).trim() === CSRF_COOKIE) {
      const value = part.slice(eq + 1).trim();
      return value === "" ? null : value;
    }
  }
  return null;
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

/** True only for URLs on this page's own origin (relative URLs included). */
export function isSameOrigin(input: RequestInfo | URL): boolean {
  try {
    return new URL(urlOf(input), window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

function withToken(init: RequestInit, token: string | null): RequestInit {
  const headers = new Headers(init.headers);
  if (token === null) headers.delete(CSRF_HEADER);
  else headers.set(CSRF_HEADER, token);
  return { ...init, headers };
}

function authorizationOf(input: RequestInfo | URL, init: RequestInit): string | null {
  const own = new Headers(init.headers).get("Authorization");
  if (own !== null) return own;
  return input instanceof Request ? input.headers.get("Authorization") : null;
}

async function isCsrfRefusal(res: Response): Promise<boolean> {
  if (res.status !== 403) return false;
  try {
    const body = (await res.clone().json()) as { code?: unknown };
    return body.code === CSRF_ERROR_CODE;
  } catch {
    return false;
  }
}

/** `fetch` with the SR-041 header and the multi-tab recover-and-retry-once rule. */
export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  if (SAFE.has(method) || !isSameOrigin(input)) return fetch(input, init);
  if (typeof ReadableStream !== "undefined" && init.body instanceof ReadableStream) {
    throw new TypeError("apiFetch: streaming bodies cannot be retried; pass a replayable body");
  }
  const sent = readCsrfCookie();
  const first = await fetch(input, withToken(init, sent));
  if (!(await isCsrfRefusal(first))) return first;
  let fresh = readCsrfCookie();
  if (fresh === null) {
    const auth = authorizationOf(input, init);
    if (auth === null) return first; // no session to re-issue for
    try {
      await fetch(SESSION_PATH, { credentials: "same-origin", headers: { Authorization: auth } });
    } catch {
      return first;
    }
    fresh = readCsrfCookie();
  }
  if (fresh === null || fresh === sent) return first; // nothing new to retry with
  return fetch(input, withToken(init, fresh));
}
