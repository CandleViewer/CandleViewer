// E10-Q02: a served Content-Security-Policy compared with SR-112 (04-security-program.md §6.11)
// directive by directive, and with SR-119's ban on exchange hosts. Each finding names the SR id and
// the directive, so a failing test says which control broke (Gherkin "Abuse regressions").
//
// The expected directives are not a list kept here: they come from the one policy builder
// (`@candleviewer/config/csp-policy`, pinned to `csp-policy.golden.json`, E43-T01), so SR-112, the
// golden, the shipped policies and these smokes cannot drift apart.

import { buildCspPolicy, CSP_REPORT_PATH } from "@candleviewer/config/csp-policy";

/**
 * Directives whose sources depend on the deployment's backend origin; checked by pattern below,
 * never by value. Every other directive must equal the builder's sources exactly.
 */
const ORIGIN_BOUND = new Set(["connect-src", "report-uri"]);

/**
 * The exchange's brand names as a pattern, never as a list of hosts (SR-119: no exchange host in
 * any directive). A pattern also catches regional and stream subdomains.
 */
const EXCHANGE_HOST = /by(?:bit|tick)/iu;

/** Loopback origins (the backend binds 127.0.0.1, C-12.9); SR-112's tailnet host is a deployment value. */
const LOOPBACK = /^(?:https?|wss?):\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?$/u;

export type Policy = ReadonlyMap<string, readonly string[]>;

export function parseCsp(header: string): Policy {
  const out = new Map<string, readonly string[]>();
  for (const part of header.split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/u);
    if (name !== undefined && name !== "" && !out.has(name.toLowerCase()))
      out.set(name.toLowerCase(), sources);
  }
  return out;
}

/** SR-112's origin-independent directives for one delivery surface, source by source, from the builder. */
export function sr112Fixed(delivery: "header" | "meta"): Policy {
  const fixed = new Map(parseCsp(buildCspPolicy({ surface: delivery })));
  for (const directive of ORIGIN_BOUND) fixed.delete(directive);
  return fixed;
}

/** Every directive SR-112 lists for one delivery surface (the origin-bound ones included). */
function sr112Directives(delivery: "header" | "meta"): ReadonlySet<string> {
  return new Set(parseCsp(buildCspPolicy({ surface: delivery })).keys());
}

export interface CspCheckOptions {
  /** A `<meta>` cannot carry `frame-ancestors`, `report-uri` or `report-to` (CSP3); the header must. */
  readonly delivery: "header" | "meta";
  /** Non-loopback `connect-src` origins this deployment allows (a tailnet host); none by default. */
  readonly extraConnect?: readonly string[];
}

/** Every way `header` deviates from SR-112 / SR-119, as `SR-<id> <directive>: <what>`; empty when it holds. */
export function sr112Findings(header: string, opts: CspCheckOptions): string[] {
  const policy = parseCsp(header);
  const listed = sr112Directives(opts.delivery);
  const allowed = (source: string): boolean =>
    LOOPBACK.test(source) || (opts.extraConnect?.includes(source) ?? false);
  const findings: string[] = [];
  for (const [directive, expected] of sr112Fixed(opts.delivery)) {
    const got = policy.get(directive);
    if (got === undefined) findings.push(`SR-112 ${directive}: missing`);
    else if ([...got].sort().join(" ") !== [...expected].sort().join(" "))
      findings.push(`SR-112 ${directive}: "${got.join(" ")}", expected "${expected.join(" ")}"`);
  }
  const connect = policy.get("connect-src");
  if (connect === undefined) findings.push("SR-112 connect-src: missing");
  else {
    if (!connect.includes("'self'")) findings.push("SR-112 connect-src: no 'self'");
    for (const source of connect)
      if (source !== "'self'" && !allowed(source))
        findings.push(`SR-112 connect-src: "${source}" is neither 'self' nor an allowed origin`);
  }
  if (listed.has("report-uri")) {
    const report = policy.get("report-uri");
    if (report === undefined) findings.push("SR-112 report-uri: missing");
    else if (report.length !== 1 || !reportsToAllowedOrigin(report[0] ?? "", allowed))
      findings.push(
        `SR-112 report-uri: "${report.join(" ")}" is not one allowed origin + ${CSP_REPORT_PATH}`,
      );
  }
  for (const [directive, sources] of policy) {
    if (sources.some((s) => s.includes("unsafe-eval")))
      findings.push(`SR-112 ${directive}: 'unsafe-eval'`);
    if (sources.some((s) => EXCHANGE_HOST.test(s)))
      findings.push(`SR-119 ${directive}: an exchange host`);
    if (!listed.has(directive))
      findings.push(`SR-112 ${directive}: a directive SR-112 does not list`);
  }
  return findings;
}

/** `report-uri` is one loopback (or allowed tailnet) origin followed by exactly the receiver path. */
function reportsToAllowedOrigin(uri: string, allowed: (origin: string) => boolean): boolean {
  if (!uri.endsWith(CSP_REPORT_PATH)) return false;
  return allowed(uri.slice(0, uri.length - CSP_REPORT_PATH.length));
}
