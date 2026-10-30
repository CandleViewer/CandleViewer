import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BASELINE_DIR,
  CONTEXT,
  FROZEN_TIME,
  ORIGIN,
  REDUCED_MOTION,
  SETTLE,
  STORYBOOK_INDEX,
  TOLERANCE,
} from "../../vr/settings.js";

/** A variable, not a literal: the config is loaded the way Playwright loads it, under a given argv. */
const CONFIG: string = "../../vr/playwright.config.ts";

async function loadConfig(argv: string[] = ["node", "playwright", "test"]) {
  const saved = process.argv;
  process.argv = argv;
  try {
    vi.resetModules();
    return (await import(/* @vite-ignore */ CONFIG)).default;
  } finally {
    process.argv = saved;
  }
}

afterEach(() => vi.unstubAllEnvs());

describe("the visual-regression config", () => {
  it("compares at ADR-0019's documented tolerance with animation disabled, never writing a baseline", async () => {
    const config = await loadConfig();
    // The ratio and an absolute cap: Playwright fails a capture past the smaller of the two, so a
    // page-sized one (2 Mpx and more) allows 25 pixels, not 2% of it (the measured noise floor is 0).
    expect(TOLERANCE).toEqual({ maxDiffPixelRatio: 0.02, maxDiffPixels: 25, threshold: 0.2 });
    expect(config.expect.toHaveScreenshot).toEqual({
      maxDiffPixelRatio: 0.02,
      maxDiffPixels: 25,
      threshold: 0.2,
      animations: "disabled",
      caret: "hide",
      scale: "css",
    });
    expect(config).toMatchObject({
      updateSnapshots: "none",
      retries: 0,
      fullyParallel: true,
      forbidOnly: true,
      // One browser per two CPUs: a play races the page less on a runner it does not saturate.
      workers: "50%",
    });
    expect(config.snapshotPathTemplate).toBe("{testDir}/baselines/{arg}{ext}");
    // The vr job uploads this directory as the vr-diffs artifact (test_vr_job.py pins the path).
    expect(config.outputDir).toBe("../test-results/vr");
    // The update gate on the resolved mode, whatever spelling of the flag set it (gate.ts).
    expect(config.globalSetup).toBe("./global-setup.ts");
    expect(BASELINE_DIR).toMatch(/packages\/ui\/vr\/baselines$/);
  });

  it("captures at 1920x1080, one device pixel per CSS pixel, frozen in time and offline", () => {
    expect(CONTEXT).toEqual({
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 1,
      locale: "en-US",
      timezoneId: "UTC",
      reducedMotion: "no-preference",
      proxy: { server: "http://127.0.0.1:9", bypass: "127.0.0.1" },
    });
    expect(Number.isNaN(Date.parse(FROZEN_TIME))).toBe(false);
  });

  it("plays with no reduced-motion preference, as the storybook job does, and captures with reduce", () => {
    expect(REDUCED_MOTION).toEqual({ play: "no-preference", capture: "reduce" });
    expect(CONTEXT.reducedMotion).toBe(REDUCED_MOTION.play);
  });

  it("waits for timers due within 1 s, then two still frames, and gives up by name after 3 s", () => {
    expect(SETTLE).toEqual({ horizonMs: 1000, quietFrames: 2, capMs: 3000 });
  });

  it("serves the built Storybook on loopback and reads the stories from its index.json", async () => {
    const { webServer, use } = await loadConfig();
    expect(ORIGIN).toBe("http://127.0.0.1:6007");
    expect(webServer).toMatchObject({
      command: "python3 -m http.server 6007 --bind 127.0.0.1 --directory storybook-static",
      url: "http://127.0.0.1:6007/index.json",
      reuseExistingServer: false,
    });
    expect(use).toEqual({ browserName: "chromium", headless: true });
    expect(STORYBOOK_INDEX).toMatch(/packages\/ui\/storybook-static\/index\.json$/);
  });

  it("runs as the vr and vr:update scripts, and refuses an update in CI without the dispatch flag", async () => {
    const { scripts } = JSON.parse(
      readFileSync(new URL("../../package.json", import.meta.url), "utf-8"),
    );
    expect(scripts.vr).toBe("playwright test -c vr/playwright.config.ts");
    expect(scripts["vr:update"]).toBe(`${scripts.vr} --update-snapshots=changed`);
    const update = [
      "node",
      "playwright",
      "test",
      "-c",
      "vr/playwright.config.ts",
      "--update-snapshots=changed",
    ];
    vi.stubEnv("CI", "true");
    await expect(loadConfig(update)).rejects.toThrow(/vr:update refuses to run in CI/);
    vi.stubEnv("VR_UPDATE", "1");
    await expect(loadConfig(update)).resolves.toMatchObject({ testMatch: "vr.spec.ts" });
  });
});
