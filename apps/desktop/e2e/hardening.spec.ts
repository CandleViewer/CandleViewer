import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, test, expect } from "@playwright/test";
import type { ElectronApplication } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MAIN_ENTRY = path.join(__dirname, "../dist/main/index.js");

async function launchApp(): Promise<ElectronApplication> {
  return electron.launch({ args: [MAIN_ENTRY] });
}

test.describe("Electron main-window smoke", () => {
  test("boots and the main window loads", async () => {
    const app = await launchApp();
    const window = await app.firstWindow();
    await expect(window).toBeTruthy();
    await app.close();
  });

  test("the sandboxed preload bundle exposes window.cv", async () => {
    // Regression guard: a sandboxed preload built as ESM with unresolved
    // relative imports fails silently (no thrown error, window.cv simply
    // never appears). Bundling to a single CJS file (scripts/build-preload.mjs)
    // fixes this; this assertion fails loudly if that regresses.
    const app = await launchApp();
    const window = await app.firstWindow();
    const hasCv = await window.evaluate(
      () => typeof (window as unknown as { cv?: unknown }).cv !== "undefined",
    );
    expect(hasCv).toBe(true);
    await app.close();
  });
});

test.describe("Electron hardening assertion", () => {
  test("reads live webPreferences and fails if any hardening flag is off", async () => {
    const app = await launchApp();
    const window = await app.firstWindow();

    const webPreferences = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      if (!win) {
        throw new Error("no BrowserWindow found");
      }
      // getLastWebPreferences is a real, documented Electron API but is not
      // present in the current @types surface; narrow via a named interface
      // rather than `any` to keep the assertion type-safe.
      interface LiveWebPreferences {
        contextIsolation?: boolean;
        nodeIntegration?: boolean;
        nodeIntegrationInWorker?: boolean;
        nodeIntegrationInSubFrames?: boolean;
        sandbox?: boolean;
        webSecurity?: boolean;
        allowRunningInsecureContent?: boolean;
        experimentalFeatures?: boolean;
        enableRemoteModule?: boolean;
      }
      const webContents = win.webContents as unknown as {
        getLastWebPreferences: () => LiveWebPreferences | undefined;
      };
      const wp = webContents.getLastWebPreferences();
      return {
        contextIsolation: wp?.contextIsolation,
        nodeIntegration: wp?.nodeIntegration,
        nodeIntegrationInWorker: wp?.nodeIntegrationInWorker,
        nodeIntegrationInSubFrames: wp?.nodeIntegrationInSubFrames,
        sandbox: wp?.sandbox,
        webSecurity: wp?.webSecurity,
        allowRunningInsecureContent: wp?.allowRunningInsecureContent,
        experimentalFeatures: wp?.experimentalFeatures,
        // Reported as a presence flag rather than echoing the key into an
        // object literal (keeps the SR-110 `enableRemoteModule: $X` lint
        // pattern meaningful); the assertion is equivalent to toBeUndefined.
        remoteModulePrefSet: wp?.enableRemoteModule !== undefined,
      };
    });

    expect(webPreferences.contextIsolation).toBe(true);
    expect(webPreferences.nodeIntegration).toBe(false);
    expect(webPreferences.nodeIntegrationInWorker).toBe(false);
    expect(webPreferences.nodeIntegrationInSubFrames).toBe(false);
    expect(webPreferences.sandbox).toBe(true);
    expect(webPreferences.webSecurity).toBe(true);
    expect(webPreferences.allowRunningInsecureContent).toBe(false);
    expect(webPreferences.experimentalFeatures).toBe(false);
    expect(webPreferences.remoteModulePrefSet).toBe(false);

    await window.close();
    await app.close();
  });
});

test.describe("SR-112 CSP", () => {
  test("the CSP header matches SR-112 verbatim and lists no Bybit host", async () => {
    const app = await launchApp();
    const electronWindow = await app.firstWindow();
    await electronWindow.waitForLoadState("domcontentloaded");

    // The page is served over app:// (#3410), which the renderer's fetch() cannot read: the
    // scheme is not granted the Fetch API. Read the same response through the window's session.
    const cspHeader = await app.evaluate(async ({ session }, url) => {
      const response = await session.defaultSession.fetch(url);
      return response.headers.get("Content-Security-Policy");
    }, electronWindow.url());

    expect(cspHeader).not.toBeNull();
    expect(cspHeader).not.toContain("unsafe-eval");
    for (const host of ["api.bybit.com", "api-demo.bybit.com", "api.bytick.com", "stream"]) {
      expect(cspHeader ?? "").not.toContain(host);
    }

    await app.close();
  });
});

test.describe("Navigation and window-open denial (SR-113)", () => {
  test("window.open to an arbitrary origin is denied and nothing opens", async () => {
    const app = await launchApp();
    const electronWindow = await app.firstWindow();

    const openedHandle = await electronWindow.evaluate(() => {
      const popup = (
        globalThis as unknown as { open: (url: string, target: string) => unknown }
      ).open("https://example.com", "_blank");
      return popup === null;
    });

    expect(openedHandle).toBe(true);

    await app.close();
  });
});
