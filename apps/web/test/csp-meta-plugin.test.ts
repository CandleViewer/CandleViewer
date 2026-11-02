// E43-T01: the build-time CSP meta comes from the shared builder, and a hand-written one is refused.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { buildCspPolicy } from "@candleviewer/config/csp-policy";
import { cspMetaPlugin } from "../plugins/cspMetaPlugin";

type Handler = (html: string) => string;
function transform(html: string, tailnetHost?: string): string {
  const plugin = cspMetaPlugin(tailnetHost === undefined ? {} : { tailnetHost });
  const hook = plugin.transformIndexHtml as { handler: Handler };
  return hook.handler(html);
}

describe("cspMetaPlugin", () => {
  it("applies to the build only", () => {
    expect(cspMetaPlugin().apply).toBe("build");
  });

  it("injects exactly the shared meta policy", () => {
    const out = transform("<html><head></head></html>");
    expect(out).toContain(`content="${buildCspPolicy({ surface: "meta" })}"`);
    expect(out).not.toMatch(/unsafe-inline|unsafe-eval|frame-ancestors|report-/);
  });

  it("adds a valid tailnet host and ignores an invalid one", () => {
    expect(transform("<head></head>", "box.tail1234.ts.net")).toContain(
      "https://box.tail1234.ts.net wss://box.tail1234.ts.net",
    );
    expect(transform("<head></head>", "*.ts.net")).not.toContain("ts.net");
  });

  it("refuses a hand-written CSP meta in the source page", () => {
    expect(() =>
      transform('<head><meta http-equiv="Content-Security-Policy" content="x" /></head>'),
    ).toThrow(/must not carry a CSP meta/);
  });

  it("the source index.html carries no CSP meta", () => {
    const html = readFileSync(resolve(import.meta.dirname, "../index.html"), "utf8");
    expect(html).not.toMatch(/<meta[^>]*Content-Security-Policy/i);
  });
});
