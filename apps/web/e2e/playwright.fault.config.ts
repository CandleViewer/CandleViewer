import { defineConfig } from "@playwright/test";

// E17-Q04 (#569): the flagged-build lane, one smoke per command of the dev-only WS fault channel (E17-T04 S5e,
// `faultChannel.ts`), the channel E17-D04's design QA forces states with. Its specs end in `.flagged.ts`, which the
// stub lane's `playwright.config.ts` (`*.spec.ts`) never matches: the shipped bundle has no channel to drive. It builds
// its own bundle with `CV_ALLOW_FAULT_INJECTION=1` outside `dist/`, so the shipped one is never replaced.
const port = process.env["CV_E2E_FAULT_PREVIEW_PORT"] ?? "4175";
const origin = `http://127.0.0.1:${port}`;
const outDir = "node_modules/.cache/cv-e2e-fault-build";

export default defineConfig({
  testDir: "./e17",
  testMatch: "**/*.flagged.ts",
  timeout: 30_000,
  retries: 0,
  forbidOnly: true,
  workers: 1,
  outputDir: "../test-results/fault",
  use: {
    baseURL: origin,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command:
      `CV_ALLOW_FAULT_INJECTION=1 npx vite build --outDir ${outDir} --emptyOutDir && ` +
      `npx vite preview --outDir ${outDir} --port ${port} --strictPort --host 127.0.0.1`,
    url: origin,
    reuseExistingServer: false,
    cwd: "..",
    timeout: 300_000,
  },
});
