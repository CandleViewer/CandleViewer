import { defineConfig } from "@playwright/test";

// E42-Q02 (#1215) part 1: the admin real-stack lane (BQ-3). Its specs end in `.stack.ts`, which
// the stub lane (`playwright.config.ts`, `*.spec.ts`) and the auth lane (`playwright.real.config.ts`,
// `*.real.ts`) never match, and it matches neither of theirs, so no lane runs another's specs.
// The stack is e2e-admin-real.yml's throwaway one, built as e2e-auth-real.yml builds its own: the
// API on loopback with the real storage backend, the synthetic feed and the server test clock, the
// role-seeded fixture users (`support/real/stack.ts`), and the built SPA served by `vite preview`
// with `vite.real.config.ts`, which proxies `/api/v1` to the API and refuses any other origin. It
// has its own API process, so its own refresh budget. One test at a time: the refresh pace
// (`support/real/failureArtefacts.ts`) is exact and the server clock has one writer.
const port = process.env["CV_E2E_REAL_PREVIEW_PORT"] ?? "4173";
// The port reaches a shell command line: digits only, and a real port, or the config throws.
if (!/^\d{1,5}$/u.test(port) || Number(port) < 1 || Number(port) > 65535) {
  throw new Error("CV_E2E_REAL_PREVIEW_PORT is a port number, 1 to 65535");
}
const origin = `http://127.0.0.1:${port}`;
const FLAKY = /@flaky/u;
// C-9.3: a `@flaky` spec is quarantined, never retried into green: this lane drops it and the
// nightly's quarantine run (CV_E2E_QUARANTINE=1) runs it alone, as `playwright.config.ts` does.
const QUARANTINE = process.env["CV_E2E_QUARANTINE"] === "1";

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.stack.ts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // A nightly lane's flake is data (BQ-5's ten-run record): no retry hides one.
  retries: 0,
  forbidOnly: true,
  workers: 1,
  fullyParallel: false,
  outputDir: "../test-results/admin-stack",
  reporter: process.env["CI"] ? [["list"], ["github"]] : [["list"]],
  use: {
    baseURL: origin,
    // The pages hold fixture passwords, real session cookies and bearers: a trace, a video or a
    // screenshot would keep them in a file the upload's secret check cannot read. A failure keeps
    // the correlation ids and the audit slice instead (`support/real/failureArtefacts.ts`).
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  projects: QUARANTINE
    ? [{ name: "flaky-nightly", grep: FLAKY }]
    : [{ name: "admin", grepInvert: FLAKY }],
  webServer: {
    command: `npx vite preview -c e2e/vite.real.config.ts --port ${port} --host 127.0.0.1`,
    url: origin,
    // Never another process's server: on a shared host it may serve another build or another API.
    reuseExistingServer: false,
    cwd: "..",
    timeout: 120_000,
  },
});
