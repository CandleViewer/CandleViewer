import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  _electron as electron,
  expect,
  type ElectronApplication,
  type Page,
} from "@playwright/test";
import { ELECTRON_EGRESS_GUARD, ELECTRON_EGRESS_HITS } from "@candleviewer/fixtures/e2e";

// E10-Q02 Electron support: launch the shell (unpacked `dist/`, through the loopback dev-server hook,
// or the packaged `electron-builder --dir` output), guard its egress, and read SR-110 and the
// sandbox from the running process. No main-process hook: everything is read via `app.evaluate`.

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const MAIN_ENTRY = path.join(__dirname, "../../dist/main/index.js");
/** Where the Electron config's webServer serves the built web app (`vite preview`). */
export const WEB_URL = process.env["CV_WEB_URL"] ?? "http://127.0.0.1:4173";

export interface LaunchOptions {
  /** Load the built web app through the loopback dev-server hook (unpacked builds only). */
  readonly devServer?: boolean;
  /** The packaged executable (`electron-builder --dir`); default: Electron on `dist/main`. */
  readonly executablePath?: string;
}

export interface Shell {
  readonly app: ElectronApplication;
  readonly win: Page;
}

export async function launchShell(opts: LaunchOptions = {}): Promise<Shell> {
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env))
    if (v !== undefined && k !== "CV_DEV_SERVER_URL") env[k] = v;
  if (opts.devServer === true) env["CV_DEV_SERVER_URL"] = WEB_URL;
  // `chromiumSandbox: true`: on Linux Playwright otherwise prepends `--no-sandbox`, which turns
  // off the very OS sandbox `sandboxFindings` asserts (SR-110, BQ-09). CI provides the SUID helper.
  const app = await electron.launch(
    opts.executablePath === undefined
      ? { args: [MAIN_ENTRY], env, chromiumSandbox: true }
      : { executablePath: opts.executablePath, env, chromiumSandbox: true },
  );
  // `defaultSession` is only safe once the app is ready. The guard sees every request from here
  // on; main-process requests made during startup, before this line, are not covered.
  await app.evaluate(({ app: a }) => a.whenReady());
  await app.evaluate(ELECTRON_EGRESS_GUARD);
  const win = await app.firstWindow();
  await win.waitForLoadState("domcontentloaded");
  return { app, win };
}

/** Fails with each non-loopback request the shell made (C-13.5, SR-119), then closes it. */
export async function closeShell({ app }: Shell): Promise<void> {
  const hits = await app.evaluate(ELECTRON_EGRESS_HITS);
  await app.close();
  expect(hits, "the shell sent a request past the loopback interface").toEqual([]);
}

/** SR-110's values, as `getLastWebPreferences` reports them. */
export const SR110 = {
  contextIsolation: true,
  nodeIntegration: false,
  nodeIntegrationInWorker: false,
  nodeIntegrationInSubFrames: false,
  sandbox: true,
  webSecurity: true,
  allowRunningInsecureContent: false,
  experimentalFeatures: false,
  remoteModulePrefSet: false,
} as const;

/** SR-110 as read from every live web contents (every window, not only the first). */
export async function webPreferencesOfAll(app: ElectronApplication) {
  return app.evaluate(({ webContents }) =>
    webContents.getAllWebContents().map((wc) => {
      // getLastWebPreferences is documented but missing from the @types surface (hardening.spec.ts)
      const wp = (
        wc as unknown as { getLastWebPreferences: () => Record<string, unknown> }
      ).getLastWebPreferences();
      return {
        url: wc.getURL().replace(/[?#].*$/su, ""),
        contextIsolation: wp["contextIsolation"],
        nodeIntegration: wp["nodeIntegration"],
        nodeIntegrationInWorker: wp["nodeIntegrationInWorker"],
        nodeIntegrationInSubFrames: wp["nodeIntegrationInSubFrames"],
        sandbox: wp["sandbox"],
        webSecurity: wp["webSecurity"],
        allowRunningInsecureContent: wp["allowRunningInsecureContent"],
        experimentalFeatures: wp["experimentalFeatures"],
        remoteModulePrefSet: wp["enableRemoteModule"] !== undefined,
      };
    }),
  );
}

/**
 * The OS sandbox, not the preference (BQ-09; ADR-0011 "Decision — 2026-10-29"): every renderer
 * process runs under seccomp-bpf with no_new_privs, read from `/proc/<pid>/status` (Linux, as CI
 * runs); and the shell was not started with `--no-sandbox`.
 */
export async function sandboxFindings(app: ElectronApplication): Promise<string[]> {
  const { pids, noSandbox } = await app.evaluate(({ app: a }) => ({
    pids: a
      .getAppMetrics()
      .filter((m) => m.type === "Tab")
      .map((m) => m.pid),
    noSandbox: a.commandLine.hasSwitch("no-sandbox") || process.argv.includes("--no-sandbox"),
  }));
  const findings: string[] = noSandbox ? ["SR-110 sandbox: the shell runs with --no-sandbox"] : [];
  if (pids.length === 0) findings.push("SR-110 sandbox: no renderer process found");
  for (const pid of pids) {
    const status = readFileSync(`/proc/${pid}/status`, "utf8");
    if (!/^Seccomp:\s+2$/mu.test(status))
      findings.push(`SR-110 sandbox: renderer ${pid} has no seccomp filter`);
    if (!/^NoNewPrivs:\s+1$/mu.test(status))
      findings.push(`SR-110 sandbox: renderer ${pid} lacks no_new_privs`);
  }
  return findings;
}

/** The CSP header the shell serves for `url`, read through its session (the renderer cannot fetch app://). */
export async function servedCsp(app: ElectronApplication, url: string): Promise<string> {
  const header = await app.evaluate(async ({ session }, u) => {
    const response = await session.defaultSession.fetch(u);
    return response.headers.get("content-security-policy");
  }, url);
  expect(header, "no Content-Security-Policy header").not.toBeNull();
  return header ?? "";
}

/** The `<meta http-equiv>` fallback policy of the loaded document. */
export async function metaCsp(win: Page): Promise<string> {
  return win.evaluate(() => {
    const doc = (
      globalThis as unknown as {
        document: { querySelector(s: string): { getAttribute(n: string): string | null } | null };
      }
    ).document;
    return (
      doc.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute("content") ?? ""
    );
  });
}
