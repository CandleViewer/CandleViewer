import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// E10-Q03 (#302) driver B config (see e10-q03-manual.qa.ts for the run command). It serves the existing apps/web
// build (`vite preview`, loopback only, a fixed port that is not driver A's 4186 or the design system's 4176 / 4177,
// --strictPort so a taken port fails instead of silently testing another server); build first. Results go to
// A11Y_OUT, never into the repository. The `control` project (the negative controls) runs first and the check
// projects depend on it. Per-test timeouts are set in the driver from measured run times, not from this file.
const PORT = process.env["A11Y_PORT"] ?? "4197";
export default defineConfig({
  testDir: ".",
  testMatch: /e10-q03-manual\.qa\.ts$/,
  outputDir: join(process.env["A11Y_OUT"] ?? join(tmpdir(), "e10-q03-manual"), "pw-test-results"),
  fullyParallel: true,
  workers: Number(process.env["A11Y_WORKERS"] ?? "3"),
  retries: 0,
  reporter: "line",
  projects: [
    { name: "control", grep: /negative control/ },
    { name: "checks", grepInvert: /negative control/, dependencies: ["control"] },
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
