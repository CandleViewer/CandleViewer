import golden from "@candleviewer/config/csp-policy.golden.json" with { type: "json" };
import { describe, expect, it } from "vitest";
import {
  classify,
  concretePath,
  isLocal,
  parseCsp,
  sr112Findings,
  sr112Fixed,
} from "../../src/e2e/index";

// The one SR-112 policy (E43-T01), as every surface ships it for the default backend.
const SHIPPED = golden.header;

describe("sr112Findings", () => {
  it("takes its expected directives from the golden policy, not from a list of its own", () => {
    const header = new Map(parseCsp(golden.header));
    header.delete("connect-src");
    header.delete("report-uri");
    expect(sr112Fixed("header")).toEqual(header);
    const meta = new Map(parseCsp(golden.meta));
    meta.delete("connect-src");
    expect(sr112Fixed("meta")).toEqual(meta);
    expect(sr112Fixed("header").get("style-src")).toEqual(["'self'"]);
  });

  it("passes every golden policy on its surface", () => {
    expect(sr112Findings(golden.header, { delivery: "header" })).toEqual([]);
    expect(sr112Findings(golden.meta, { delivery: "meta" })).toEqual([]);
    expect(sr112Findings(golden.bind_8080, { delivery: "header" })).toEqual([]);
    expect(sr112Findings(golden.https_loopback_origin, { delivery: "header" })).toEqual([]);
    const tailnet = ["https://box.tail1234.ts.net", "wss://box.tail1234.ts.net"];
    expect(sr112Findings(golden.tailnet, { delivery: "header", extraConnect: tailnet })).toEqual(
      [],
    );
  });

  it("fails the pre-E43 policy (style unsafe-inline, no reporting) and a meta used as a header", () => {
    const old = SHIPPED.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'").replace(
      /; report-uri [^;]+; report-to \S+$/u,
      "",
    );
    expect(sr112Findings(old, { delivery: "header" })).toEqual([
      `SR-112 style-src: "'self' 'unsafe-inline'", expected "'self'"`,
      "SR-112 report-to: missing",
      "SR-112 report-uri: missing",
    ]);
    expect(sr112Findings(golden.meta, { delivery: "header" })).toEqual([
      "SR-112 frame-ancestors: missing",
      "SR-112 report-to: missing",
      "SR-112 report-uri: missing",
    ]);
    expect(sr112Findings(golden.header, { delivery: "meta" })).toEqual([
      "SR-112 frame-ancestors: a directive SR-112 does not list",
      "SR-112 report-uri: a directive SR-112 does not list",
      "SR-112 report-to: a directive SR-112 does not list",
    ]);
  });

  it("rejects a report-uri off the loopback, off the receiver path or with two sources", () => {
    const at = (uri: string): string => SHIPPED.replace(/report-uri [^;]+/u, `report-uri ${uri}`);
    for (const uri of [
      "https://evil.invalid/api/v1/csp-report",
      "http://127.0.0.1:8000/other",
      "http://127.0.0.1:8000/api/v1/csp-report http://127.0.0.1:9/api/v1/csp-report",
    ])
      expect(sr112Findings(at(uri), { delivery: "header" })).toEqual([
        `SR-112 report-uri: "${uri}" is not one allowed origin + /api/v1/csp-report`,
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
