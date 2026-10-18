import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import playwrightConfig from "../e2e/playwright.config";

const E2E_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../e2e");

// Bug #1527 (E03-T06-B1, parent #107 AC3): apps/desktop's Electron
// Playwright config had no failure-artifact capture configured either;
// this config has no retries, so "retain-on-failure" (not
// "on-first-retry") is required for trace to be produced on a single
// failing run.
describe("apps/desktop e2e playwright-electron config", () => {
  it("enables trace capture on failure", () => {
    expect(playwrightConfig.use?.trace).toBe("retain-on-failure");
  });

  it("enables screenshot capture on failure", () => {
    expect(playwrightConfig.use?.screenshot).toBe("only-on-failure");
  });

  it("enables video capture on failure", () => {
    expect(playwrightConfig.use?.video).toBe("retain-on-failure");
  });

  // #3366: Playwright resolves webServer.cwd against the config file's own directory (e2e/), so
  // "../web" named a missing apps/desktop/web and `vite preview` failed to spawn
  // ("spawn /bin/sh ENOENT") the first time CI ran this suite.
  it("serves the apps/web package, with cwd resolved the way Playwright resolves it", () => {
    const server = playwrightConfig.webServer;
    if (server === undefined || Array.isArray(server)) {
      throw new Error("expected exactly one webServer entry");
    }
    const manifest = path.join(path.resolve(E2E_DIR, server.cwd ?? "."), "package.json");
    expect(existsSync(manifest), `${manifest} must exist`).toBe(true);
    const pkg = JSON.parse(readFileSync(manifest, "utf8")) as { name?: unknown };
    expect(pkg.name).toBe("@candleviewer/web");
  });
});
