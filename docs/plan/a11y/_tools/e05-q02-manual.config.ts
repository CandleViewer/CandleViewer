import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// E05-Q02 (#262) manual-pass config (see e05-q02-manual.qa.ts for the run command): the same loopback server
// of the built Storybook as e05-q02-ds.config.ts. Build packages/ui's Storybook first.
const PORT = process.env["A11Y_PORT"] ?? "4177";
export default defineConfig({
  testDir: ".",
  testMatch: /e05-q02-manual\.qa\.ts$/,
  outputDir: join(process.env["A11Y_OUT"] ?? join(tmpdir(), "e05-q02-ds"), "pw-manual-results"),
  timeout: 300_000,
  fullyParallel: true,
  workers: Number(process.env["A11Y_WORKERS"] ?? "2"),
  retries: 0,
  reporter: "line",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1280, height: 800 },
    screenshot: "off",
    video: "off",
    trace: "off",
  },
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1 --directory storybook-static`,
    cwd: "../../../../packages/ui",
    url: `http://127.0.0.1:${PORT}/index.json`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
