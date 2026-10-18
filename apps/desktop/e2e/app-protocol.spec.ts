import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { _electron as electron, test, expect } from "@playwright/test";

// #3410: without CV_DEV_SERVER_URL the shell serves the built web app over its app:// handler.
// The other smoke specs only check that a window exists; this one launches the shell the
// default way and asserts the web app actually renders, under the shell's CSP (SR-112).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MAIN_ENTRY = path.join(__dirname, "../dist/main/index.js");
const CSP_MODULE = path.join(__dirname, "../dist/main/csp.js");
// A loopback backend origin other than the default, so the shell's CSP header differs from the
// <meta> fallback in apps/web/index.html and a violation shows which policy reported it.
const BACKEND_ORIGIN = "http://127.0.0.1:8123";

/** The runner's environment minus CV_DEV_SERVER_URL (the default load path), plus the backend. */
function defaultLoadEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && key !== "CV_DEV_SERVER_URL") {
      env[key] = value;
    }
  }
  return { ...env, CV_BACKEND_ORIGIN: BACKEND_ORIGIN };
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
        buildCsp: (backendOrigin: string) => string;
      };
      const header = buildCsp(BACKEND_ORIGIN);
      const served = await app.evaluate(async ({ session }, url) => {
        const response = await session.defaultSession.fetch(url);
        return { status: response.status, csp: response.headers.get("content-security-policy") };
      }, win.url());
      expect(served).toEqual({ status: 200, csp: header });

      // The page enforces that header, not only index.html's <meta> fallback: the two policies
      // differ in connect-src, and each enforced policy reports its own violation when it blocks
      // an injected inline script (script-src 'self').
      const ran = await win.evaluate(() => {
        const page = globalThis as unknown as { document: PageDocument; cvViolations: Violation[] };
        const doc = page.document;
        page.cvViolations = [];
        doc.addEventListener("securitypolicyviolation", (event) => {
          const { blockedURI, effectiveDirective, originalPolicy, disposition } = event;
          page.cvViolations.push({ blockedURI, effectiveDirective, originalPolicy, disposition });
        });
        const script = doc.createElement("script");
        script.textContent = "document.documentElement.dataset.cvInline = 'ran';";
        doc.head.append(script);
        return doc.documentElement.dataset["cvInline"] === "ran";
      });
      expect(ran).toBe(false);
      const reported = (): Promise<Violation[]> =>
        win.evaluate(() => (globalThis as unknown as { cvViolations: Violation[] }).cvViolations);
      await expect.poll(reported).toContainEqual({
        blockedURI: "inline",
        effectiveDirective: "script-src-elem",
        originalPolicy: header,
        disposition: "enforce",
      });
    } finally {
      await app.close();
    }
  });
});
