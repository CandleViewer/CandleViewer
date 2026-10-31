import { defineConfig } from "@playwright/test";

// E09-Q02 (#293) PR 2 (#2490): the real-backend auth lane. Its specs end in `.real.ts`, which the
// stub lane's `playwright.config.ts` (`*.spec.ts`, the `e2e-web` job) never matches, so neither lane
// runs the other's specs and no conditional skip is needed. The stack is a seeded throwaway one:
// the API on testnet with the real storage backend, the synthetic feed and the server test clock,
// and Postgres, all on loopback (`.github/workflows/e2e-auth-real.yml`; `support/real/stack.ts`
// reads what the lane hands over). The SPA is the built `dist/`, served by `vite preview` with
// `vite.real.config.ts`, which proxies `/api/v1` to the API, so the browser sees one origin.
const port = process.env["CV_E2E_REAL_PREVIEW_PORT"] ?? "4173";
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.real.ts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // A nightly lane's flake is data (the ten-run record): no retry hides one.
  retries: 0,
  forbidOnly: true,
  workers: 2,
  outputDir: "../test-results/real",
  reporter: process.env["CI"] ? [["list"], ["github"]] : [["list"]],
  use: {
    baseURL: origin,
    // The pages hold the fixture password, real session cookies and access tokens. A trace, a video
    // or a screenshot would keep them in a file the upload's secret check cannot read (a zip, an
    // image), so none is made: a failure keeps the correlation ids and the audit slice instead
    // (`support/real/failureArtefacts.ts`).
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  projects: [
    // Sign-in specs: one fixture user per test, so they run side by side. Two at most: sign-in
    // verification runs four at a time on the API (`CV_AUTH_LOGIN_VERIFY_CONCURRENCY`).
    { name: "real", grepInvert: /@clock/u, fullyParallel: true, workers: 2 },
    // Specs that move the server clock (`support/serverClock.ts`, tagged `@clock`): the clock is the
    // API process's and only moves forward, so they run alone, one at a time, after `real`.
    {
      name: "real-clock",
      grep: /@clock/u,
      fullyParallel: false,
      workers: 1,
      dependencies: ["real"],
    },
  ],
  webServer: {
    command: `npx vite preview -c e2e/vite.real.config.ts --port ${port} --host 127.0.0.1`,
    url: origin,
    // Never another process's server: on a shared host it may serve another build or another API.
    reuseExistingServer: false,
    cwd: "..",
    timeout: 120_000,
  },
});
