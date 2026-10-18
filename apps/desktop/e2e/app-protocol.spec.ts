import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { _electron as electron, test, expect } from "@playwright/test";

// #3410: without CV_DEV_SERVER_URL the shell serves the built web app over its app:// handler.
// The other smoke specs only check that a window exists; this one launches the shell the
// default way and asserts the web app actually renders, under the shell's CSP (SR-112).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MAIN_ENTRY = path.join(__dirname, "../dist/main/index.js");
const CSP_MODULE = path.join(__dirname, "../dist/main/csp.js");

/** The test runner's environment minus CV_DEV_SERVER_URL: the default (non-dev) load path. */
function defaultLoadEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && key !== "CV_DEV_SERVER_URL") {
      env[key] = value;
    }
  }
  return env;
}

interface Violation {
  readonly blockedURI: string;
  readonly effectiveDirective: string;
  readonly originalPolicy: string;
  readonly disposition: string;
}

/** The few DOM members the in-page check uses (this package compiles without DOM types). */
interface PageDocument {
  addEventListener(type: "securitypolicyviolation", listener: (event: Violation) => void): void;
  createElement(tag: "script"): { textContent: string | null };
  readonly head: { append(node: unknown): void };
  readonly documentElement: { readonly dataset: Record<string, string | undefined> };
}

test.describe("Default load path (#3410)", () => {
  test("renders the web app over app:// with the shell's CSP in force", async () => {
    const app = await electron.launch({ args: [MAIN_ENTRY], env: defaultLoadEnv() });
    try {
      const win = await app.firstWindow();

      // The root element renders the default route. Without a backend session that is the
      // sign-in screen (R-001).
      await expect(win.locator("#root main")).toBeVisible();
      await expect(win.getByRole("heading", { level: 1, name: /sign in/i })).toBeVisible();
      const loaded = new URL(win.url());
      expect(`${loaded.protocol}//${loaded.host}`).toBe("app://candleviewer");

      // The handler serves the page with the shell's CSP header. The renderer cannot fetch()
      // app:// (the scheme is not granted the Fetch API), so read the same response through
      // the window's session.
      const { buildCsp } = (await import(pathToFileURL(CSP_MODULE).href)) as {
        buildCsp: () => string;
      };
      const served = await app.evaluate(async ({ session }, url) => {
        const response = await session.defaultSession.fetch(url);
        return { status: response.status, csp: response.headers.get("content-security-policy") };
      }, win.url());
      expect(served).toEqual({ status: 200, csp: buildCsp() });

      // The page enforces it: an injected inline script is blocked by script-src 'self'.
      const inline = await win.evaluate(async () => {
        const doc = (globalThis as unknown as { document: PageDocument }).document;
        const reported = new Promise<Violation>((resolve) => {
          doc.addEventListener("securitypolicyviolation", (event) => {
            if (event.blockedURI === "inline") {
              resolve({
                blockedURI: event.blockedURI,
                effectiveDirective: event.effectiveDirective,
                originalPolicy: event.originalPolicy,
                disposition: event.disposition,
              });
            }
          });
        });
        const script = doc.createElement("script");
        script.textContent = "document.documentElement.dataset.cvInline = 'ran';";
        doc.head.append(script);
        if (doc.documentElement.dataset["cvInline"] === "ran") {
          return { ran: true, violation: null };
        }
        return { ran: false, violation: await reported };
      });
      expect(inline.ran).toBe(false);
      expect(inline.violation?.disposition).toBe("enforce");
      expect(inline.violation?.effectiveDirective).toMatch(/^script-src/);
      expect(inline.violation?.originalPolicy).toContain("script-src 'self'");
      expect(inline.violation?.originalPolicy).not.toContain("unsafe-eval");
    } finally {
      await app.close();
    }
  });
});
