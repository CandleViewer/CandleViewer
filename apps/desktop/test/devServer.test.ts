import { describe, expect, it } from "vitest";
import { resolveDevServerUrl } from "../src/main/devServer";

// #3411 (C-12.9, SR-113): the page CV_DEV_SERVER_URL names gets the preload bridge, so the shell
// honours it only in an unpackaged build and only for a loopback http origin with a port.
describe("resolveDevServerUrl", () => {
  it("is unset when the variable is not set, packaged or not", () => {
    expect(resolveDevServerUrl(undefined, false)).toEqual({ kind: "unset" });
    expect(resolveDevServerUrl(undefined, true)).toEqual({ kind: "unset" });
  });

  it.each([
    ["http://127.0.0.1:4173", "http://127.0.0.1:4173/"],
    ["http://localhost:5173/", "http://localhost:5173/"],
    ["http://LOCALHOST:5173/route?tab=1", "http://localhost:5173/route?tab=1"],
    ["http://127.0.0.1:65535", "http://127.0.0.1:65535/"],
    // Other spellings of the two hosts are accepted only as the canonical href the window loads.
    ["http://127.1:4173", "http://127.0.0.1:4173/"],
    ["http://0x7f.0.0.1:4173", "http://127.0.0.1:4173/"],
    ["http://2130706433:4173", "http://127.0.0.1:4173/"],
    ["http:\\\\127.0.0.1:4173", "http://127.0.0.1:4173/"],
    ["http://@%6Cocalhost:04173", "http://localhost:4173/"],
  ])("accepts the loopback http origin %s in an unpackaged build", (raw, url) => {
    expect(resolveDevServerUrl(raw, false)).toEqual({ kind: "accepted", url });
  });

  it.each([
    "http://example.test:4173", // another host
    "http://127.0.0.1.example:4173", // look-alike hosts
    "http://localhost.example.test:4173",
    // The scheme is a separate literal so no user:password-shaped URL is written whole in
    // source, which a secret scanner would flag (docs/ci-runbook.md, #3482).
    "http" + "://127.0.0.1:4173@example.test:8080/", // the loopback part is userinfo
    "http://127.0.0.2:4173", // only the two named hosts
    "http://[::1]:4173",
    "https://127.0.0.1:4173", // other schemes
    "ws://127.0.0.1:4173",
    "file:///home/user/index.html",
    "data:text/html,page",
    "app://candleviewer/",
  ])("ignores %s in an unpackaged build: not a loopback http origin", (raw) => {
    expect(resolveDevServerUrl(raw, false)).toEqual({
      kind: "ignored",
      reason: "not-loopback-http",
    });
  });

  it.each([
    "",
    "not a url",
    " http://127.0.0.1:4173", // the parser would trim these spaces and controls silently
    "http://127.0.0.1:4173 ",
    "http://127.0.0.1:41\t73",
    "http://127.0.0.1:4173/\n",
    "127.0.0.1:4173", // no scheme
    "http://127.0.0.1", // no port
    "http://localhost/",
    "http://127.0.0.1:80", // the scheme's default port is no explicit port
    "http://127.0.0.1:0",
    "http://127.0.0.1:65536", // out of range
    "http://127.0.0.1:-1",
    "http://user@127.0.0.1:4173", // credentials
    "http://user:pw@localhost:4173",
  ])("ignores %j in an unpackaged build as malformed", (raw) => {
    expect(resolveDevServerUrl(raw, false)).toEqual({ kind: "ignored", reason: "malformed" });
  });

  it.each(["http://127.0.0.1:4173", "http://localhost:5173", "https://example.test", "", "x y"])(
    "ignores any value in a packaged build, %j included",
    (raw) => {
      expect(resolveDevServerUrl(raw, true)).toEqual({
        kind: "ignored",
        reason: "unpackaged-only",
      });
    },
  );
});
