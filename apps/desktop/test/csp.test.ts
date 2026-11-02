import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { buildCspPolicy } from "@candleviewer/config/csp-policy";
import { buildCsp, buildReportingEndpoints, parseTailnetHost } from "../src/main/csp";

// The shared builder's golden strings (packages/config/src/csp-policy.golden.json): this mirror
// and the FastAPI one must equal them.
const golden = JSON.parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../packages/config/src/csp-policy.golden.json"),
    "utf8",
  ),
) as Record<string, string | string[]>;

describe("CSP string builder", () => {
  it("matches the SR-112 policy verbatim (golden, C-12.10: no unsafe-inline)", () => {
    expect(buildCsp("http://127.0.0.1:8000", undefined)).toBe(golden["header"]);
    expect(buildReportingEndpoints("http://127.0.0.1:8000")).toBe(golden["reporting_endpoints"]);
  });

  it("equals the shared builder for every golden variant", () => {
    expect(buildCsp("http://127.0.0.1:8000", "Box.tail1234.ts.net")).toBe(golden["tailnet"]);
    expect(buildCsp("http://127.0.0.1:8000", "box.tail1234.ts.net")).toBe(
      buildCspPolicy({ tailnetHost: "box.tail1234.ts.net" }),
    );
    expect(buildCsp("http://127.0.0.1:8000", "box.tail1234.ts.net:8443")).toBe(
      golden["tailnet_port"],
    );
    expect(buildCsp("https://localhost:9000", undefined)).toBe(golden["https_loopback_origin"]);
    expect(buildCsp("http://evil.example", undefined)).toBe(
      golden["non_loopback_origin_falls_back"],
    );
  });

  it("sends reports to the tailnet origin when set, else the backend origin (golden)", () => {
    expect(buildReportingEndpoints("http://127.0.0.1:8000", "box.tail1234.ts.net")).toBe(
      golden["reporting_endpoints_tailnet"],
    );
    expect(buildReportingEndpoints("http://127.0.0.1:8080", undefined)).toBe(
      golden["reporting_endpoints_8080"],
    );
    expect(buildCsp("http://127.0.0.1:8080", undefined)).toBe(golden["bind_8080"]);
  });

  it.each(golden["invalid_tailnet_hosts"] as string[])(
    "ignores the invalid tailnet host %j",
    (host) => {
      expect(parseTailnetHost(host)).toBeNull();
      expect(buildCsp("http://127.0.0.1:8000", host)).toBe(golden["header"]);
    },
  );

  it("ignores a non-string tailnet host and an out-of-range port", () => {
    expect(parseTailnetHost(undefined)).toBeNull();
    expect(parseTailnetHost("box.ts.net:0")).toBeNull();
  });

  it("names the report endpoint on the backend origin (header only)", () => {
    expect(buildCsp()).toContain("report-uri http://127.0.0.1:8000/api/v1/csp-report");
    expect(buildCsp()).toContain("report-to csp-endpoint");
  });

  it("includes hardening directives (object-src, base-uri, frame-ancestors, form-action)", () => {
    const csp = buildCsp();
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("form-action 'none'");
  });

  it("never allows unsafe-eval", () => {
    expect(buildCsp()).not.toContain("unsafe-eval");
  });

  it("never lists a Bybit host in any directive (SR-119)", () => {
    const csp = buildCsp();
    for (const host of [
      "api.bybit.com",
      "api-demo.bybit.com",
      "api.bytick.com",
      "stream.bybit.com",
    ]) {
      expect(csp).not.toContain(host);
    }
  });

  it("falls back to the default origin for a non-loopback CV_BACKEND_ORIGIN (rejects injection)", () => {
    const csp = buildCsp("http://evil.example.com\"; script-src 'unsafe-inline");
    expect(csp).not.toContain("evil.example.com");
    expect(csp).not.toContain("'unsafe-inline'; script-src 'unsafe-inline'");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000");
  });

  it("falls back to the default origin for an unparsable CV_BACKEND_ORIGIN", () => {
    const csp = buildCsp("not a url");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000");
  });

  it("accepts localhost and IPv6 loopback as valid backend origins", () => {
    expect(buildCsp("http://localhost:9000")).toContain(
      "http://localhost:9000 ws://localhost:9000",
    );
    expect(buildCsp("http://[::1]:9000")).toContain("http://[::1]:9000");
  });

  it("never allows unsafe-inline (C-12.10)", () => {
    expect(buildCsp("http://127.0.0.1:8000", "box.tail1234.ts.net")).not.toContain("unsafe-inline");
    expect(buildCsp()).toContain("style-src 'self';");
  });

  it("does not allow an unrestricted connect-src", () => {
    const csp = buildCsp();
    expect(csp).not.toContain("connect-src 'self' ws: wss:");
    expect(csp).toMatch(/connect-src 'self' https?:\/\/\S+ wss?:\/\/\S+/);
  });
});
