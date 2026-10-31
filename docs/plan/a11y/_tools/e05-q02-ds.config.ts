import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// E05-Q02 (#262) design-system axe matrix config (see e05-q02-ds.qa.ts for the run command). It serves the
// built Storybook (packages/ui/storybook-static) on loopback only; build it first.
const PORT = process.env["A11Y_PORT"] ?? "4175";
export default defineConfig({
  testDir: ".",
  testMatch: /e05-q02-ds\.qa\.ts$/,
  outputDir: join(process.env["A11Y_OUT"] ?? join(tmpdir(), "e05-q02-ds"), "pw-test-results"),
  timeout: 3_600_000,
  workers: 1,
  retries: 0,
  reporter: "line",
  use: { baseURL: `http://127.0.0.1:${PORT}`, screenshot: "off", video: "off", trace: "off" },
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1 --directory storybook-static`,
    cwd: "../../../../packages/ui",
    url: `http://127.0.0.1:${PORT}/index.json`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
