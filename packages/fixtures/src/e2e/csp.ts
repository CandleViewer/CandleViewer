// E10-Q02: a served Content-Security-Policy compared with SR-112 (04-security-program.md §6.11)
// directive by directive, and with SR-119's ban on exchange hosts. Each finding names the SR id and
// the directive, so a failing test says which control broke (Gherkin "Abuse regressions").

/** SR-112's fixed directives, source by source. `connect-src` is checked separately below. */
export const SR112_FIXED: Readonly<Record<string, readonly string[]>> = {
  "default-src": ["'self'"],
  "script-src": ["'self'"],
  "style-src": ["'self'", "'unsafe-inline'"],
  "img-src": ["'self'", "data:", "blob:"],
  "worker-src": ["'self'", "blob:"],
  "object-src": ["'none'"],
  "frame-ancestors": ["'none'"],
  "base-uri": ["'none'"],
  "form-action": ["'none'"],
};

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

export interface CspCheckOptions {
  /** `<meta>` policies cannot carry `frame-ancestors` (CSP3 §6.4.2); the header must. */
  readonly delivery: "header" | "meta";
  /** Non-loopback `connect-src` origins this deployment allows (a tailnet host); none by default. */
  readonly extraConnect?: readonly string[];
}

/** Every way `header` deviates from SR-112 / SR-119, as `SR-<id> <directive>: <what>`; empty when it holds. */
export function sr112Findings(header: string, opts: CspCheckOptions): string[] {
  const policy = parseCsp(header);
  const findings: string[] = [];
  for (const [directive, expected] of Object.entries(SR112_FIXED)) {
    if (directive === "frame-ancestors" && opts.delivery === "meta") continue;
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
      if (source !== "'self'" && !LOOPBACK.test(source) && !opts.extraConnect?.includes(source))
        findings.push(`SR-112 connect-src: "${source}" is neither 'self' nor an allowed origin`);
  }
  for (const [directive, sources] of policy) {
    if (sources.some((s) => s.includes("unsafe-eval")))
      findings.push(`SR-112 ${directive}: 'unsafe-eval'`);
    if (sources.some((s) => EXCHANGE_HOST.test(s)))
      findings.push(`SR-119 ${directive}: an exchange host`);
    if (!(directive in SR112_FIXED) && directive !== "connect-src")
      findings.push(`SR-112 ${directive}: a directive SR-112 does not list`);
  }
  return findings;
}
