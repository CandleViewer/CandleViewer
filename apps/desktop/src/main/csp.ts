/**
 * Content-Security-Policy string builder for the Electron renderer (SR-112, C-12.10, E43-T01).
 *
 * This is a MIRROR of the one policy builder `packages/config/src/csp-policy.mjs` (the web `<meta>`
 * and the FastAPI header come from the same policy): the packaged shell ships only `dist/` and
 * cannot import a workspace package at runtime. `test/csp.test.ts` asserts every output equals
 * `csp-policy.golden.json`, so the three copies cannot drift.
 *
 * No `'unsafe-inline'` anywhere: React `style={}` goes through the CSSOM, which `style-src 'self'`
 * allows. `connect-src` is the app itself plus the loopback backend origin (`50-security.md`:
 * "Backend binds 127.0.0.1 / WSL-internal only") and, only when `CV_CSP_TAILNET_HOST` is a valid
 * DNS name, its https/wss origin. It never opens connections to an arbitrary host. `frame-ancestors`
 * and the report directives are header-only (a `<meta>` ignores them), which is this surface.
 */
export const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8000";
export const CSP_REPORT_PATH = "/api/v1/csp-report";
export const CSP_REPORT_GROUP = "csp-endpoint";
const ALLOWED_LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);
const LABEL = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
const TAILNET_HOST_RE = new RegExp(`^${LABEL}(?:\\.${LABEL})+(?::[0-9]{1,5})?$`);

/**
 * Parses `rawOrigin` and returns its normalised origin, restricted to a loopback host. Falls back
 * to `DEFAULT_BACKEND_ORIGIN` if the value is unparsable or not loopback, so an unvalidated
 * `CV_BACKEND_ORIGIN` env var can never inject extra CSP directives/tokens or widen `connect-src`.
 */
export function resolveBackendOrigin(rawOrigin: string): string {
  let parsed: URL;
  try {
    parsed = new URL(rawOrigin);
  } catch {
    return DEFAULT_BACKEND_ORIGIN;
  }
  if (!ALLOWED_LOOPBACK_HOSTS.has(parsed.hostname)) {
    return DEFAULT_BACKEND_ORIGIN;
  }
  return parsed.origin;
}

/** A validated tailnet host (lowercase DNS name, optional port), or `null` when absent or invalid. */
export function parseTailnetHost(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const host = raw.trim().toLowerCase();
  if (host.length === 0 || host.length > 253 || !TAILNET_HOST_RE.test(host)) return null;
  const [name = "", port] = host.split(":");
  if (/^[0-9.]+$/.test(name)) return null; // an IPv4 literal is not a DNS name
  if (port !== undefined && (Number(port) < 1 || Number(port) > 65535)) return null;
  return host;
}

export function buildCsp(
  backendOrigin: string = process.env["CV_BACKEND_ORIGIN"] ?? DEFAULT_BACKEND_ORIGIN,
  tailnetHost: string | undefined = process.env["CV_CSP_TAILNET_HOST"],
): string {
  const safeOrigin = resolveBackendOrigin(backendOrigin);
  const tailnet = parseTailnetHost(tailnetHost);
  const connect = ["'self'", safeOrigin, safeOrigin.replace(/^http/, "ws")];
  if (tailnet !== null) {
    connect.push(`https://${tailnet}`, `wss://${tailnet}`);
  }
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    `connect-src ${connect.join(" ")}`,
    "img-src 'self' data: blob:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    `report-uri ${safeOrigin}${CSP_REPORT_PATH}`,
    `report-to ${CSP_REPORT_GROUP}`,
  ].join("; ");
}

/** Value of the `Reporting-Endpoints` header that `report-to` names. */
export function buildReportingEndpoints(
  backendOrigin: string = process.env["CV_BACKEND_ORIGIN"] ?? DEFAULT_BACKEND_ORIGIN,
): string {
  return `${CSP_REPORT_GROUP}="${resolveBackendOrigin(backendOrigin)}${CSP_REPORT_PATH}"`;
}
