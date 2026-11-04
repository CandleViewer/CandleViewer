import { expect, test } from "@playwright/test";
import { axeFindings, goldenBars, openChart, patient } from "./bars-harness";
import { BLOCKED, blockedBy } from "./blockers";
import { COPY } from "./chart-probe";

// E12-Q03 (#419), US-CHART-003: E12-TC-E02, E06, F02. Tick and volume bars over the conformance
// tape; the window opens before `recording_started_at`, so the partial-history marker shows.
const TICK = goldenBars("btcusdt-2026-09-01", "tick:1000");
const VOLUME = goldenBars("btcusdt-2026-09-01", "vol:50");

test.describe("tick and volume bar modes (US-CHART-003)", blockedBy(BLOCKED.barModes), () => {
  test("tick 1000 from SCR-041 by keyboard: the bar count and the partial-history marker", async ({
    page,
  }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: TICK,
    });
    await page.keyboard.press("Control+K");
    await patient(probe.quickSwitcher).toBeVisible();
    await page.keyboard.type("1000T");
    await page.keyboard.press("Enter");
    await expect(probe.quickSwitcher).toHaveCount(0);
    await patient(probe.panel.getByText(COPY.recordingStart)).toBeVisible();
    expect(backend.marketReads.at(-1)).toMatch(
      /bar_type=tick&param=1000|param=1000.*bar_type=tick/u,
    );
    await probe.openTableByKey();
    expect(await probe.barsLoaded()).toBe(TICK.length);
    expect(await axeFindings(page)).toEqual([]);
  });

  test("volume 50 states its parameter on CMP-220 and loads the volume bars", async ({ page }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: VOLUME,
    });
    await page.keyboard.press("Control+K");
    await page.keyboard.type("50V");
    await page.keyboard.press("Enter");
    await patient(
      page.getByRole("button", { name: new RegExp(`^${COPY.barMode}: Volume`, "u") }),
    ).toBeVisible();
    expect(backend.marketReads.at(-1)).toContain("bar_type=volume");
    await probe.openTableByKey();
    expect(await probe.barsLoaded()).toBe(VOLUME.length);
  });

  test("a window before recording: 422 no_data_recorded labels the region, never a flat line", async ({
    page,
  }) => {
    const { probe } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: [],
      fail: { status: 422, code: "no_data_recorded" },
    });
    await patient(probe.panel.getByText(COPY.recordingStart)).toBeVisible();
    await expect(probe.panel.getByRole("alert")).toHaveCount(0);
  });
});
