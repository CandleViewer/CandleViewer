import { mkdirSync, writeFileSync } from "node:fs";
import { expect, test, type Browser, type TestInfo } from "@playwright/test";
import { stubSession } from "../support/api";
import { REPORT_DIR } from "./screens";

// E47-Q05 reduced-motion profile: reduced motion must remove WORK, not only hide it. The real shell
// (session stubbed at the network layer, no app code mocked) runs the same scripted interaction under
// no-preference and under reduce, and each run is profiled: animations running right after each
// action (`document.getAnimations()`, CSS transitions included), requestAnimationFrame callbacks,
// and the browser's own ScriptDuration and Layout + RecalcStyle time over the scenario (CDP
// Performance.getMetrics; "paint_ms" is that style + layout proxy, GPU time is not exposed here).
// tools/a11y/motion_audit.py `reduce` decides; a collector fails only when it cannot collect.
const CYCLES = 10;
const SURFACES = "nav rail collapse/expand, Notifications panel, shell toast";

interface Profile {
  running_animations: number;
  script_ms: number;
  paint_ms: number;
  raf_callbacks: number;
}

async function profileRun(
  browser: Browser,
  info: TestInfo,
  reducedMotion: "reduce" | "no-preference",
): Promise<Profile> {
  const context = await browser.newContext({
    reducedMotion,
    baseURL: info.project.use.baseURL ?? "http://127.0.0.1:4173",
  });
  try {
    const page = await context.newPage();
    await page.addInitScript(() => {
      const w = window as unknown as { __raf: number };
      w.__raf = 0;
      const raw = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (cb) =>
        raw((t) => {
          w.__raf++;
          cb(t);
        });
    });
    await stubSession(page, { role: "owner" });
    await page.goto("/terminal");
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute(
      "data-motion",
      reducedMotion === "reduce" ? "reduce" : /^(?!reduce$)/,
    );
    const cdp = await context.newCDPSession(page);
    await cdp.send("Performance.enable");
    const metrics = async (): Promise<Record<string, number>> =>
      Object.fromEntries(
        (await cdp.send("Performance.getMetrics")).metrics.map((m) => [m.name, m.value]),
      );
    const running = (): Promise<number> =>
      page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length);
    const rafBefore = await page.evaluate(() => (window as unknown as { __raf: number }).__raf);
    const before = await metrics();
    let maxRunning = 0;
    for (let i = 0; i < CYCLES; i++) {
      for (const name of ["Collapse navigation rail", "Expand navigation rail", "Notifications"]) {
        await page.getByRole("button", { name }).click();
        maxRunning = Math.max(maxRunning, await running());
      }
      await page.keyboard.press("Control+Shift+X"); // an inert chord: the shell explains it in a toast
      maxRunning = Math.max(maxRunning, await running());
    }
    const after = await metrics();
    const raf = await page.evaluate(() => (window as unknown as { __raf: number }).__raf);
    const ms = (k: string): number => ((after[k] ?? 0) - (before[k] ?? 0)) * 1000;
    return {
      running_animations: maxRunning,
      script_ms: ms("ScriptDuration"),
      paint_ms: ms("LayoutDuration") + ms("RecalcStyleDuration"),
      raf_callbacks: raf - rafBefore,
    };
  } finally {
    await context.close();
  }
}

test(`collect reduced-motion profile (${SURFACES}, ${CYCLES} cycles)`, async ({
  browser,
  browserName,
}, info) => {
  // Chromium only: Performance.getMetrics is a CDP call, and profiles from another engine are not
  // comparable. Anything else is an infrastructure error, never a silent skip.
  if (browserName !== "chromium") throw new Error("A11Y-INFRA the motion profile needs Chromium");
  const safe = await profileRun(browser, info, "no-preference");
  const reduced = await profileRun(browser, info, "reduce");
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(`${REPORT_DIR}/motion-profile.json`, JSON.stringify({ safe, reduced }));
});
