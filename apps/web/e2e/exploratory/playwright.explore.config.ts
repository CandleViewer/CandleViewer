import { defineConfig } from "@playwright/test";

// E49-Q02 (#1336): the exploratory lane. Its sessions end in `.explore.ts`, which the PR lane's
// `playwright.config.ts` (`*.spec.ts`), the a11y collectors (`*.collect.ts`) and the real-backend
// lane (`*.real.ts`) never match, so no CI job runs them; a person or an agent runs them on purpose
// (docs/qa/e49-exploratory-harness.md). Build first: `vite preview` serves whatever `dist/` holds.
const port = process.env["CV_EXPLORE_PORT"] ?? "4174";
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.explore.ts",
  timeout: 300_000,
  // A session is one run in order: no retry hides an observation, no parallel worker interleaves logs.
  retries: 0,
  workers: 1,
  forbidOnly: true,
  outputDir: "../../test-results/explore",
  reporter: [["list"]],
  use: {
    baseURL: origin,
    // The session's recording (ticket: charters are screen-recorded). Stub values only: no real
    // session, key or password is ever on these pages, and the output dir is git-ignored.
    trace: "on",
    video: "on",
    screenshot: "on",
  },
  webServer: {
    command: `npx vite preview --port ${port} --host 127.0.0.1 --strictPort`,
    url: origin,
    // Never another process's server: it may serve another build.
    reuseExistingServer: false,
    cwd: "../..",
    timeout: 120_000,
  },
});
