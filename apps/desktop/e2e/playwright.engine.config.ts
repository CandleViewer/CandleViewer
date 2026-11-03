import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";
import { closeShell, launchShell } from "./support/shell";

// E11-Q02 (#444, BQ-04): the Electron leg of the engine suite: apps/web's specs (a test directory, no
// import either way) on the harness build apps/web's playwright.engine.config.ts serves, with the
// shell launched by `launchShell` (chromiumSandbox, egress guard) through the dev-server hook.
// `openShell` is declared by apps/web's support/engine/test.ts. No packaged leg (it ignores the hook).
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ENGINE_URL = process.env["CV_ENGINE_HARNESS_URL"] ?? "http://127.0.0.1:4175";
process.env["CV_WEB_URL"] = ENGINE_URL; // launchShell's dev-server target

const openShell = async () => {
  const shell = await launchShell({ devServer: true });
  return { page: shell.win, close: () => closeShell(shell) };
};

export default defineConfig<{ openShell: typeof openShell }>({
  testDir: path.resolve(HERE, "../../web/e2e/specs/e11-chart"),
  testMatch: "**/*.spec.ts",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  projects: [{ name: "electron", grepInvert: /@flaky/u, use: { openShell } }],
  reporter: [["list"]],
  use: { baseURL: ENGINE_URL, trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: {
    command:
      "npx vite build -c e2e/engine-harness/vite.config.ts && " +
      "npx vite preview -c e2e/engine-harness/vite.config.ts --port 4175 --strictPort --host 127.0.0.1",
    url: ENGINE_URL,
    cwd: path.resolve(HERE, "../../web"),
    reuseExistingServer: !process.env["CI"],
    timeout: 300_000,
  },
});
