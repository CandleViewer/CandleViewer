// The shared CSP builder (E43-T01): the golden strings, the tailnet validation and the invariants
// C-12.10 demands. The desktop and FastAPI mirrors assert against the same golden file.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  buildCspPolicy,
  buildReportingEndpoints,
  parseTailnetHost,
  resolveBackendOrigin,
} from "../src/csp-policy.mjs";

const golden = JSON.parse(
  readFileSync(path.join(import.meta.dirname, "../src/csp-policy.golden.json"), "utf8"),
);

describe("buildCspPolicy", () => {
  it("matches the golden header and meta", () => {
    expect(buildCspPolicy()).toBe(golden.header);
    expect(buildCspPolicy({ surface: "meta" })).toBe(golden.meta);
    expect(buildReportingEndpoints()).toBe(golden.reporting_endpoints);
  });

  it("never contains unsafe-inline, unsafe-eval or a wildcard", () => {
    for (const policy of [golden.header, golden.meta, golden.tailnet, golden.tailnet_port]) {
      expect(policy).not.toMatch(/unsafe-inline|unsafe-eval|\*/);
    }
  });

  it("keeps frame-ancestors and report directives to the header surface", () => {
    expect(golden.header).toMatch(/frame-ancestors 'none'.*report-uri .*report-to /);
    expect(golden.meta).not.toMatch(/frame-ancestors|report-uri|report-to/);
  });

  it("adds the tailnet host over https and wss only", () => {
    expect(buildCspPolicy({ tailnetHost: "Box.tail1234.ts.net" })).toBe(golden.tailnet);
    expect(buildCspPolicy({ tailnetHost: "box.tail1234.ts.net:8443" })).toBe(golden.tailnet_port);
  });

  it.each(golden.invalid_tailnet_hosts)("ignores the invalid tailnet host %j", (host) => {
    expect(parseTailnetHost(host)).toBeNull();
    expect(buildCspPolicy({ tailnetHost: host })).toBe(golden.header);
  });

  it("ignores a non-string tailnet host and an out-of-range port", () => {
    expect(parseTailnetHost(undefined)).toBeNull();
    expect(parseTailnetHost("box.ts.net:0")).toBeNull();
  });

  it("falls back to the default for a non-loopback or unparsable backend origin", () => {
    expect(buildCspPolicy({ backendOrigin: "http://evil.example" })).toBe(
      golden.non_loopback_origin_falls_back,
    );
    expect(resolveBackendOrigin("not a url")).toBe("http://127.0.0.1:8000");
    expect(resolveBackendOrigin("https://127.0.0.1:8000")).toBe("https://127.0.0.1:8000");
    expect(resolveBackendOrigin("http://localhost:9000/x")).toBe("http://localhost:9000");
  });
});
