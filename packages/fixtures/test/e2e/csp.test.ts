import { describe, expect, it } from "vitest";
import { classify, concretePath, isLocal, parseCsp, sr112Findings } from "../../src/e2e/index";

// The shell's policy as apps/desktop/src/main/csp.ts builds it for the default backend.
const SHIPPED =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
  "connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000; img-src 'self' data: blob:; " +
  "worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; " +
  "form-action 'none'";

describe("sr112Findings", () => {
  it("passes the shipped policy as a header and as a meta fallback", () => {
    expect(sr112Findings(SHIPPED, { delivery: "header" })).toEqual([]);
    const meta = SHIPPED.replace("frame-ancestors 'none'; ", "");
    expect(sr112Findings(meta, { delivery: "meta" })).toEqual([]);
    expect(sr112Findings(meta, { delivery: "header" })).toEqual([
      "SR-112 frame-ancestors: missing",
    ]);
  });

  it("names unsafe-eval, a widened directive and an exchange host by SR id and directive", () => {
    const weak = SHIPPED.replace("script-src 'self'", "script-src 'self' 'unsafe-eval'").replace(
      "ws://127.0.0.1:8000",
      "wss://stream.bybit.invalid",
    );
    expect(sr112Findings(weak, { delivery: "header" })).toEqual([
      `SR-112 script-src: "'self' 'unsafe-eval'", expected "'self'"`,
      "SR-112 connect-src: \"wss://stream.bybit.invalid\" is neither 'self' nor an allowed origin",
      "SR-112 script-src: 'unsafe-eval'",
      "SR-119 connect-src: an exchange host",
    ]);
  });

  it("flags a directive SR-112 does not list and a connect-src without 'self'", () => {
    const odd = SHIPPED.replace("connect-src 'self' ", "connect-src ") + "; frame-src *";
    expect(sr112Findings(odd, { delivery: "header" })).toEqual([
      "SR-112 connect-src: no 'self'",
      "SR-112 frame-src: a directive SR-112 does not list",
    ]);
  });

  it("parses the first occurrence of a directive, case-insensitively", () => {
    expect(parseCsp("Script-Src 'self'; script-src *").get("script-src")).toEqual(["'self'"]);
  });
});

describe("helpers", () => {
  it("classifies a landing by its heading, then by its path", () => {
    expect(classify("/risk", "/risk", "You don't have access to this")).toBe("forbidden");
    expect(classify("/admin", "/admin", "Page not found")).toBe("not-found");
    expect(classify("/terminal", "/terminal/last", "x")).toBe("redirect:/terminal/last");
    expect(classify("/journal", "/journal", "R-180 — owned by E17")).toBe("render");
  });

  it("fills every path parameter and recognises loopback by pattern", () => {
    expect(concretePath("/terminal/:layoutId/pane/:paneId")).toBe("/terminal/x1/pane/x1");
    expect(isLocal("http://127.0.0.1:4173/x")).toBe(true);
    expect(isLocal("app://candleviewer/index.html")).toBe(true);
    expect(isLocal("https://example.com/")).toBe(false);
    expect(isLocal("not a url")).toBe(false);
  });
});
