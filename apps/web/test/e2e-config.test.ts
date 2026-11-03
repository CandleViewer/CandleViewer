import { afterEach, describe, expect, it, vi } from "vitest";
import playwrightConfig from "../e2e/playwright.config";

// Bug #1527 (E03-T06-B1, parent #107 AC3): Playwright must capture
// trace/screenshot/video on failure so the "e2e failure produces a
// debuggable artifact" scenario is actually satisfied — Playwright's
// defaults are all "off", so the upload-artifact step in
// _job-e2e.yml had nothing to upload.
describe("apps/web e2e playwright config", () => {
  it("keeps the trace of every failed run, the first attempt included (E10-Q02 BQ-20)", () => {
    expect(playwrightConfig.use?.trace).toBe("retain-on-failure");
  });

  it("enables screenshot capture on failure", () => {
    expect(playwrightConfig.use?.screenshot).toBe("only-on-failure");
  });

  it("enables video capture on failure", () => {
    expect(playwrightConfig.use?.video).toBe("retain-on-failure");
  });

  describe("GA regression pack project (#1335 ruling a)", () => {
    afterEach(() => {
      vi.unstubAllEnvs();
      vi.resetModules();
    });

    it("runs the pack with zero retries and leaves the global CI retry alone", async () => {
      vi.stubEnv("CI", "1");
      vi.stubEnv("CV_E2E_GA", "1");
      vi.resetModules();
      const { default: config } = await import("../e2e/playwright.config");
      expect(config.retries).toBe(1);
      expect(config.projects?.map((p) => [p.name, p.retries])).toEqual([["ga-regression", 0]]);
    });
  });
});
