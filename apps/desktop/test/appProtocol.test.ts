import { afterAll, beforeAll, describe, expect, it, vi, type Mock } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  APP_ENTRY_URL,
  APP_SCHEME_PRIVILEGES,
  contentTypeFor,
  createDistReader,
  isAppUrl,
  resolveAppRequest,
  resolveDistPath,
  type DistReader,
} from "../src/main/appProtocol";

// #3410 / SR-174: the app:// handler is a read-only static-file server confined to the web
// app's dist root. These tests drive its pure parts with an in-memory reader; the last block
// runs the real file reader against a temporary directory.
const ROOT = path.resolve(process.platform === "win32" ? "C:\\app\\web\\dist" : "/app/web/dist");
const CSP = "default-src 'self'";

function memoryReader(files: Record<string, string>): Mock<DistReader> {
  const table = new Map(
    Object.entries(files).map(([rel, text]) => [
      path.join(ROOT, rel),
      new TextEncoder().encode(text),
    ]),
  );
  return vi.fn<DistReader>((absolutePath) => Promise.resolve(table.get(absolutePath) ?? null));
}

const DIST = {
  "index.html": "<!doctype html><div id=root></div>",
  "assets/index-abc.js": "export {};",
  "assets/index-abc.css": "body{}",
};

describe("APP_SCHEME_PRIVILEGES", () => {
  it("is exactly standard + secure (never a CSP bypass, fetch, CORS or service workers)", () => {
    expect(APP_SCHEME_PRIVILEGES).toEqual({ standard: true, secure: true });
  });

  it("the entry URL is the root of the one fixed app origin", () => {
    expect(APP_ENTRY_URL).toBe("app://candleviewer/");
  });
});

describe("isAppUrl", () => {
  it("accepts the app scheme with its fixed host", () => {
    expect(isAppUrl("app://candleviewer/")).toBe(true);
    expect(isAppUrl("app://candleviewer/assets/x.js?v=1#h")).toBe(true);
  });

  it("rejects another scheme, host, port, credentials or an unparseable URL", () => {
    for (const url of [
      "https://candleviewer/",
      "file:///app/web/dist/index.html",
      "app://candleviewer.evil.test/",
      "app://evil.test/",
      "app://candleviewer:8080/",
      "app://user:pass@candleviewer/",
      "not a url",
    ]) {
      expect(isAppUrl(url), url).toBe(false);
    }
  });
});

describe("resolveDistPath (path mapping)", () => {
  it.each([
    ["app://candleviewer/", "index.html"],
    ["app://candleviewer", "index.html"],
    ["app://candleviewer/assets/index-abc.js?v=2", "assets/index-abc.js"],
    // The URL parser resolves dot segments, raw or encoded, before the handler sees the path.
    ["app://candleviewer/../../etc/passwd", "etc/passwd"],
    ["app://candleviewer/%2e%2e/%2e%2e/etc/passwd", "etc/passwd"],
    // Decoded once: a double-encoded traversal stays a literal name inside the root.
    ["app://candleviewer/%252e%252e%252fsecret", "%2e%2e%2fsecret"],
  ])("maps %s inside the root", (url, relative) => {
    expect(resolveDistPath(url, ROOT)).toBe(path.join(ROOT, ...relative.split("/")));
  });

  it.each([
    "app://evil.test/index.html", // another host
    "https://candleviewer/index.html", // another scheme
    "app://candleviewer/..%2f..%2fetc%2fpasswd", // encoded traversal out of the root
    "app://candleviewer/assets/..%2F..%2F..%2Fsecret.txt",
    "app://candleviewer/%2e%2e%2f%2e%2e%2fsecret.txt",
    "app://candleviewer/..\\..\\secret.txt", // backslashes, raw or encoded, on every platform
    "app://candleviewer/..%5c..%5csecret.txt",
    "app://candleviewer/index.html%00.png", // encoded NUL
    "app://candleviewer/%E0%A4%A", // malformed percent-encoding
  ])("refuses %s", (url) => {
    expect(resolveDistPath(url, ROOT)).toBeNull();
  });
});

describe("resolveAppRequest", () => {
  it("serves a dist file with its content type, the CSP header and nosniff", async () => {
    const res = await resolveAppRequest(
      "app://candleviewer/assets/index-abc.js",
      ROOT,
      memoryReader(DIST),
      CSP,
    );
    expect(res.status).toBe(200);
    expect(res.headers).toEqual({
      "content-security-policy": CSP,
      "x-content-type-options": "nosniff",
      "content-type": "text/javascript; charset=utf-8",
    });
    expect(new TextDecoder().decode(res.body as Uint8Array)).toBe("export {};");
  });

  it("serves index.html for the origin root", async () => {
    const res = await resolveAppRequest(APP_ENTRY_URL, ROOT, memoryReader(DIST), CSP);
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toBe("text/html; charset=utf-8");
  });

  // /apiary: only the whole first segment "api" is the backend's prefix, not any path starting so.
  it.each(["app://candleviewer/terminal/last", "app://candleviewer/apiary"])(
    "falls back to index.html for the client route %s (no extension), as the browser router needs",
    async (url) => {
      const read = memoryReader(DIST);
      const res = await resolveAppRequest(url, ROOT, read, CSP);
      expect(res.status).toBe(200);
      expect(res.headers["content-type"]).toBe("text/html; charset=utf-8");
      expect(new TextDecoder().decode(res.body as Uint8Array)).toContain("id=root");
      expect(read).toHaveBeenLastCalledWith(path.join(ROOT, "index.html"));
    },
  );

  it.each([
    "app://candleviewer/assets/missing-secret-name.js", // a missing asset (with an extension)
    "app://candleviewer/api/v1/me", // the backend's prefix is never a client route
    "app://candleviewer/api",
  ])("answers 404 for %s, with the CSP and no echoed path", async (url) => {
    const res = await resolveAppRequest(url, ROOT, memoryReader(DIST), CSP);
    expect(res.status).toBe(404);
    expect(res.headers["content-security-policy"]).toBe(CSP);
    expect(res.body).toBe("Not found");
  });

  it("answers 404 for a client route when index.html itself is missing", async () => {
    const res = await resolveAppRequest("app://candleviewer/login", ROOT, memoryReader({}), CSP);
    expect(res.status).toBe(404);
  });

  it.each(["app://evil.test/index.html", "app://candleviewer/..%2f..%2fetc%2fpasswd"])(
    "answers 404 for %s, with the CSP, and never reads a file for it",
    async (url) => {
      const read = memoryReader(DIST);
      const res = await resolveAppRequest(url, ROOT, read, CSP);
      expect(res.status).toBe(404);
      expect(res.headers["content-security-policy"]).toBe(CSP);
      expect(read).not.toHaveBeenCalled();
    },
  );

  it("serves GET and HEAD only: another method gets 405 with the CSP and reads nothing", async () => {
    const read = memoryReader(DIST);
    expect((await resolveAppRequest(APP_ENTRY_URL, ROOT, read, CSP, "HEAD")).status).toBe(200);
    read.mockClear();
    for (const method of ["POST", "PUT", "DELETE", "OPTIONS"]) {
      const res = await resolveAppRequest(APP_ENTRY_URL, ROOT, read, CSP, method);
      expect(res, method).toMatchObject({ status: 405, body: "Not allowed" });
      expect(res.headers).toMatchObject({ "content-security-policy": CSP, allow: "GET, HEAD" });
    }
    expect(read).not.toHaveBeenCalled();
  });
});

describe("contentTypeFor (MIME map)", () => {
  it.each([
    ["index.html", "text/html; charset=utf-8"],
    ["a.js", "text/javascript; charset=utf-8"],
    ["a.mjs", "text/javascript; charset=utf-8"],
    ["a.css", "text/css; charset=utf-8"],
    ["a.json", "application/json"],
    ["a.js.map", "application/json"],
    ["a.svg", "image/svg+xml"],
    ["a.png", "image/png"],
    ["favicon.ico", "image/x-icon"],
    ["a.woff", "font/woff"],
    ["a.woff2", "font/woff2"],
    ["a.wasm", "application/wasm"],
    ["robots.txt", "text/plain; charset=utf-8"],
    ["A.JS", "text/javascript; charset=utf-8"],
  ])("%s -> %s", (file, type) => {
    expect(contentTypeFor(file)).toBe(type);
  });

  it("serves an unknown extension as opaque bytes", () => {
    expect(contentTypeFor("a.exe")).toBe("application/octet-stream");
    expect(contentTypeFor("LICENSE")).toBe("application/octet-stream");
  });
});

describe("createDistReader (real filesystem)", () => {
  let tmp: string;
  let root: string;

  beforeAll(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cv-app-protocol-"));
    root = path.join(tmp, "dist");
    fs.mkdirSync(path.join(root, "assets"), { recursive: true });
    fs.writeFileSync(path.join(root, "index.html"), "<!doctype html>");
    fs.writeFileSync(path.join(tmp, "outside.txt"), "outside the root");
  });

  afterAll(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  it("reads a regular file inside the root", async () => {
    const bytes = await createDistReader(root)(path.join(root, "index.html"));
    expect(new TextDecoder().decode(bytes ?? new Uint8Array())).toBe("<!doctype html>");
  });

  it("reads a directory or a missing file as missing (nothing is listed)", async () => {
    const read = createDistReader(root);
    expect(await read(path.join(root, "assets"))).toBeNull();
    expect(await read(path.join(root, "missing.js"))).toBeNull();
  });

  it("refuses a path outside the root", async () => {
    expect(await createDistReader(root)(path.join(tmp, "outside.txt"))).toBeNull();
  });

  it("refuses a symlink inside the root that points outside it", async () => {
    const link = path.join(root, "assets", "escape.js");
    fs.symlinkSync(path.join(tmp, "outside.txt"), link);
    expect(await createDistReader(root)(link)).toBeNull();
  });

  it("reads everything as missing when the root does not exist", async () => {
    const read = createDistReader(path.join(tmp, "no-such-dist"));
    expect(await read(path.join(tmp, "no-such-dist", "index.html"))).toBeNull();
  });
});
