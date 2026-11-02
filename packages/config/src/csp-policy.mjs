// The one CSP policy builder (SR-112, C-12.10, E43-T01). The web `<meta>` (Vite build plugin), the
// Electron header (apps/desktop/src/main/csp.ts, a mirror: the packaged shell cannot import a
// workspace package) and the FastAPI header (candleviewer/api/csp.py, a mirror) must all produce
// the strings in csp-policy.golden.json; a parity test in each package pins that.
//
// No `'unsafe-inline'` / `'unsafe-eval'` anywhere (C-12.10): React `style={}` goes through the CSSOM,
// which `style-src 'self'` allows. A `<meta>` cannot carry `frame-ancestors`, `report-uri` or
// `report-to` (browsers ignore them there), so those exist on the "header" surface only.

import { URL } from "node:url";

export const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8000";
export const CSP_REPORT_PATH = "/api/v1/csp-report";
export const CSP_REPORT_GROUP = "csp-endpoint";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);
// DNS name of two or more labels, optional :port. No wildcard, scheme, path, userinfo or IP literal.
const LABEL = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
const TAILNET_HOST_RE = new RegExp(`^${LABEL}(?:\\.${LABEL})+(?::[0-9]{1,5})?$`);

/** Loopback-only backend origin; anything else falls back to the default (never widens connect-src). */
export function resolveBackendOrigin(raw) {
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    return DEFAULT_BACKEND_ORIGIN;
  }
  if (!LOOPBACK_HOSTS.has(parsed.hostname)) return DEFAULT_BACKEND_ORIGIN;
  return parsed.origin;
}

/** A validated tailnet host (lowercase DNS name, optional port), or `null` when absent or invalid. */
export function parseTailnetHost(raw) {
  if (typeof raw !== "string") return null;
  const host = raw.trim().toLowerCase();
  if (host.length === 0 || host.length > 253 || !TAILNET_HOST_RE.test(host)) return null;
  const [name, port] = host.split(":");
  if (/^[0-9.]+$/.test(name)) return null; // an IPv4 literal is not a DNS name
  if (port !== undefined && (Number(port) < 1 || Number(port) > 65535)) return null;
  return host;
}

/**
 * @param {{ backendOrigin?: string, tailnetHost?: string | null, surface?: "header" | "meta" }} [options]
 * `surface: "meta"` omits the directives a `<meta>` cannot carry.
 */
export function buildCspPolicy(options = {}) {
  const origin = resolveBackendOrigin(options.backendOrigin ?? DEFAULT_BACKEND_ORIGIN);
  const tailnet = parseTailnetHost(options.tailnetHost);
  const connect = ["'self'", origin, origin.replace(/^http/, "ws")];
  if (tailnet !== null) connect.push(`https://${tailnet}`, `wss://${tailnet}`);
  const header = (options.surface ?? "header") === "header";
  const directives = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    `connect-src ${connect.join(" ")}`,
    "img-src 'self' data: blob:",
    "worker-src 'self' blob:",
    "object-src 'none'",
  ];
  if (header) directives.push("frame-ancestors 'none'");
  directives.push("base-uri 'none'", "form-action 'none'");
  if (header) {
    directives.push(
      `report-uri ${reportOrigin(origin, tailnet)}${CSP_REPORT_PATH}`,
      `report-to ${CSP_REPORT_GROUP}`,
    );
  }
  return directives.join("; ");
}

/** Where reports go: the tailnet https origin when one is configured, else the backend origin. */
function reportOrigin(origin, tailnet) {
  return tailnet === null ? origin : `https://${tailnet}`;
}

/** Value of the `Reporting-Endpoints` header that `report-to` names. */
export function buildReportingEndpoints(
  backendOrigin = DEFAULT_BACKEND_ORIGIN,
  tailnetHost = null,
) {
  const origin = resolveBackendOrigin(backendOrigin);
  return `${CSP_REPORT_GROUP}="${reportOrigin(origin, parseTailnetHost(tailnetHost))}${CSP_REPORT_PATH}"`;
}
