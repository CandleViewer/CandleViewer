// E10-X02: collects the runtime facts the electron-hardening gate asserts (SR-110, SR-112,
// SR-174).
//
// Launches the PACKAGED build (apps/desktop/dist) headlessly via Playwright-Electron and reads,
// for EVERY window that exists (a pop-out created with weaker options is the realistic
// regression), `webContents.getLastWebPreferences()` and the URL it shows once loaded, plus the
// CSP header string the main process builds (`dist/main/csp.js#buildCsp`, the exact function
// installCspHeader() and the app:// handler use). It then fetches through the real app://
// handler from the main process and records each response's status and CSP header.
//
import console from "node:console";
// Usage: node scripts/collect-hardening-facts.mjs <out.json>
import { writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { _electron as electron } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(here, "../dist");
const out = process.argv[2];
if (!out) {
  console.error("usage: collect-hardening-facts.mjs <out.json>");
  process.exit(2);
}

// The handler responses to fetch: the page, a missing asset and an /api path (the SPA fallback
// leaves both 404) and a non-GET method (405). Same list as APP_PROBES in
// tools/ci/electron_hardening_checks.py, which judges each status and CSP header.
const PROBES = [
  ["GET", "app://candleviewer/"],
  ["GET", "app://candleviewer/assets/cv-hardening-probe.js"],
  ["GET", "app://candleviewer/api/cv-hardening-probe"],
  ["POST", "app://candleviewer/"],
];

const { buildCsp } = await import(pathToFileURL(path.join(dist, "main/csp.js")).href);

const app = await electron.launch({
  args: [path.join(dist, "main/index.js")],
});
try {
  await app.firstWindow();
  // getURL() is empty until a window's first load commits, so wait until each one stops
  // loading (bounded: a load that hangs is read as it stands and the gate judges that URL).
  const windows = await app.evaluate(async ({ BrowserWindow }) => {
    const all = BrowserWindow.getAllWindows();
    await Promise.all(
      all.map((w) =>
        w.webContents.isLoading()
          ? new Promise((resolve) => {
              w.webContents.once("did-stop-loading", resolve);
              globalThis.setTimeout(resolve, 30_000);
            })
          : null,
      ),
    );
    return all.map((w, i) => ({
      name: `window-${i}`,
      title: w.getTitle(),
      url: w.webContents.getURL(),
      webPreferences: w.webContents.getLastWebPreferences(),
    }));
  });
  const appProbes = await app.evaluate(async ({ session }, probes) => {
    const results = [];
    for (const [method, url] of probes) {
      try {
        const res = await session.defaultSession.fetch(url, { method });
        await res.arrayBuffer();
        const csp = res.headers.get("content-security-policy");
        results.push({ method, url, status: res.status, csp });
      } catch (error) {
        results.push({ method, url, status: null, csp: null, error: String(error) });
      }
    }
    return results;
  }, PROBES);
  writeFileSync(
    out,
    JSON.stringify(
      {
        cspHeader: buildCsp(),
        // Flip to true once the env badge (E10 env-badge ticket) puts DEMO/LIVE in the title.
        requireEnvTitle: false,
        windows,
        appProbes,
      },
      null,
      2,
    ),
    "utf-8",
  );
  const seen = appProbes.map((p) => `${p.method} ${p.url} ${p.status ?? p.error}`).join(", ");
  console.log(
    `collected ${windows.length} window(s) at ${windows.map((w) => w.url).join(", ")} and ` +
      `${appProbes.length} app:// response(s): ${seen} -> ${out}`,
  );
} finally {
  await app.close();
}
