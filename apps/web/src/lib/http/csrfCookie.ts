/** The SR-041 double-submit pair: read by `apiFetch` and by the access-token refresh (#2712). */
export const CSRF_COOKIE = "__Host-cv_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

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
