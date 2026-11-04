import { expect, test } from "@playwright/test";
import { axeFindings, goldenBars, openChart, patient } from "./bars-harness";
import { BLOCKED } from "./blockers";
import { COPY } from "./chart-probe";

// E12-Q03 (#419), US-CHART-004 and US-CHART-002 scenario 3: E12-TC-D09, B04.
const RENKO = goldenBars("btcusdt-2026-09-01", "renko:30");
const RANGE = goldenBars("btcusdt-2026-09-01", "range:20");

test.describe("range, delta and renko rebuilds (US-CHART-004)", () => {
  test.fixme(true, `blocked: ${BLOCKED.barModes}`);

  test("a renko size change shows its progress; Escape cancels and the previous series stays", async ({
    page,
  }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT renko 30", {
      symbol: "BTCUSDT",
      bars: RENKO,
    });
    await page.keyboard.press("Control+K");
    await page.keyboard.type("40R");
    await page.keyboard.press("Enter");
    const progress = probe.panel.getByRole("progressbar");
    await patient(progress).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(progress).toHaveCount(0);
    await expect(probe.panel.getByText(COPY.buildCancelled)).toBeVisible();
    await probe.openTableByKey();
    expect(await probe.barsLoaded()).toBe(RENKO.length);
    expect(backend.refused).toEqual([]);
    expect(await axeFindings(page)).toEqual([]);
  });

  test("range 20 loads its bars with no off-host request", async ({ page }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT range 20", {
      symbol: "BTCUSDT",
      bars: RANGE,
    });
    await probe.openTableByKey();
    expect(await probe.barsLoaded()).toBe(RANGE.length);
    expect(backend.refused).toEqual([]);
  });
});

test.describe("unsupported combination (US-CHART-002 scenario 3)", () => {
  test.fixme(true, `blocked: ${BLOCKED.seriesTypes}`);

  test("Heikin-Ashi with footprint shows the guard and draws nothing new", async ({ page }) => {
    const { probe } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: goldenBars("btcusdt-2026-09-01", "time:1"),
    });
    await probe.chartType.getByRole("checkbox", { name: COPY.heikinAshi }).check();
    const guard = page.getByRole("alertdialog");
    await patient(guard).toBeVisible();
    await expect(guard.getByRole("button", { name: COPY.keepType })).toBeFocused();
    await expect(guard.getByRole("button", { name: COPY.haTurnFootprintOff })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(guard).toHaveCount(0);
    await expect(
      probe.chartType.getByRole("checkbox", { name: COPY.heikinAshi }),
    ).not.toBeChecked();
  });
});
