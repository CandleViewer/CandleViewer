import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// E10-Q03 (#302) shell axe matrix config (see e10-q03-shell.qa.ts for the run commands). It serves the
// existing apps/web build (`vite preview`, loopback only); build first. Results go to A11Y_OUT, never
// into the repository. The control project runs first; the state tests depend on it.
const PORT = process.env["A11Y_PORT"] ?? "4186";
const TARGET = process.env["A11Y_TARGET"] === "electron" ? "electron" : "web";
export default defineConfig({
  testDir: ".",
  testMatch: /e10-q03-shell\.qa\.ts$/,
  outputDir: join(
    process.env["A11Y_OUT"] ?? join(tmpdir(), "e10-q03-shell"),
    TARGET,
    "pw-test-results",
  ),
  timeout: 1_800_000,
  fullyParallel: true,
  // One Electron window per worker is enough; the web matrix is the long one.
  workers: Number(process.env["A11Y_WORKERS"] ?? (TARGET === "electron" ? "1" : "3")),
  retries: 0,
  reporter: "line",
  projects: [
    { name: "control", grep: /negative control/ },
    { name: "matrix", grepInvert: /negative control/, dependencies: ["control"] },
  ],
  use: { baseURL: `http://127.0.0.1:${PORT}`, screenshot: "off", video: "off", trace: "off" },
  webServer: {
    command: `npx vite preview --port ${PORT} --host 127.0.0.1 --strictPort`,
    cwd: "../../../../apps/web",
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
