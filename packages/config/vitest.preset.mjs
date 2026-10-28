import { URL, fileURLToPath } from "node:url";

// Shared Vitest preset. Consumers spread this into their own vitest.config
// via `defineConfig({ ...vitestPreset, test: { ...vitestPreset.test, ... } })`.
export const vitestPreset = {
  test: {
    environment: "node",
    globals: false,
    // C-9.3 (E02-T10): `it.flaky`, `test.flaky` and `describe.flaky` before every test file, and the
    // tag a quarantined test carries, declared because Vitest refuses an undeclared tag.
    setupFiles: [fileURLToPath(new URL("./src/vitest-flaky.mjs", import.meta.url))],
    tags: [
      {
        name: "flaky",
        description: "C-9.3 quarantine (src/vitest-flaky.mjs): skipped in every run",
      },
    ],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
  },
};

export default vitestPreset;
