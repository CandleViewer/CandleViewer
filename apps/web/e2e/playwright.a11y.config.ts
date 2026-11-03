import { defineConfig } from "@playwright/test";

// E47-T02: accessibility collectors. They emit JSON/text under reports/a11y/
// for tools/a11y/gates.py to judge; a collector fails only when it cannot
// collect (infrastructure), never on axe/flash/tree content.
const PORT = process.env["A11Y_PORT"] ?? "4173";
export default defineConfig({
  testDir: ".",
  timeout: 300_000,
  workers: 1,
  retries: 0,
  // The collectors (gates 1-6) and the keyboard-only journeys (E47-Q03, a11y-nav/README.md) are two
  // projects of one config, so they share the preview server and the required `a11y` job.
  projects: [
    { name: "collectors", testDir: "./a11y", testMatch: /.*\.collect\.ts/ },
    { name: "a11y-nav", testDir: "./a11y-nav", testMatch: /.*\.journey\.ts/ },
  ],
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  webServer: {
    command: `npx vite preview --port ${PORT} --host 127.0.0.1`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env["CI"],
    cwd: "..",
    timeout: 120_000,
  },
});
