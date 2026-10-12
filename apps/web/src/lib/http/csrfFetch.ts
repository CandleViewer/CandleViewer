/**
 * SR-041 double-submit CSRF for every REST call (`22-api-openapi.yaml` info "CSRF", #2090).
 *
 * On `POST`/`PUT`/`PATCH`/`DELETE` the client reads the `__Host-cv_csrf` cookie and sends it in
 * `X-CSRF-Token`. If the server answers `403 csrf_token_invalid` (e.g. another tab rotated the
 * token), the cookie is re-read and the request retried exactly once; a second refusal is returned
 * to the caller unchanged. Safe methods pass through untouched.
 */

export const CSRF_COOKIE = "__Host-cv_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
export const CSRF_ERROR_CODE = "csrf_token_invalid";

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

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

function withToken(init: RequestInit): RequestInit {
  const headers = new Headers(init.headers);
  const token = readCsrfCookie();
  if (token === null) headers.delete(CSRF_HEADER);
  else headers.set(CSRF_HEADER, token);
  return { ...init, headers };
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

/** `fetch` with the SR-041 header and the multi-tab retry-once rule. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  if (!UNSAFE.has(method)) return fetch(input, init);
  const first = await fetch(input, withToken(init));
  if (!(await isCsrfRefusal(first))) return first;
  return fetch(input, withToken(init));
}
