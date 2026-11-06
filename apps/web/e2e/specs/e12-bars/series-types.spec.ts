import { expect, test } from "@playwright/test";
import { axeFindings, goldenBars, openChart, patient } from "./bars-harness";
import { BLOCKED, blockedBy } from "./blockers";
import { COPY } from "./chart-probe";

// E12-Q03 (#419), US-CHART-002: E12-TC-B01, B02, B05. The volume pane case, B03, is held back:
// E12-S08 (PR #5681) builds the pane in the engine with no DOM surface, and no design gives its
// toggle a home (D05-G6).
const BARS = goldenBars("btcusdt-2026-09-01", "time:5");

test.describe("series types (US-CHART-002)", blockedBy(BLOCKED.seriesTypes), () => {
  test("every CMP-222 type redraws from the same bars: no market read, same bar count", async ({
    page,
  }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 5m", {
      symbol: "BTCUSDT",
      bars: BARS,
    });
    await patient(probe.seriesType(COPY.seriesTypes[0])).toBeChecked();
    const reads = backend.marketReads.length;
    for (const type of COPY.seriesTypes.slice(1)) {
      await probe.seriesType(type).click();
      await expect(probe.seriesType(type)).toBeChecked();
    }
    await probe.openTableByKey();
    expect(await probe.barsLoaded()).toBe(BARS.length);
    expect(backend.marketReads).toHaveLength(reads);
    expect(backend.refused()).toEqual([]);
  });

  test("candles to Heikin-Ashi issues no market read and keeps the bar count", async ({ page }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 5m", {
      symbol: "BTCUSDT",
      bars: BARS,
    });
    const reads = backend.marketReads.length;
    await probe.heikinAshi.click();
    await expect(probe.heikinAshi).toBeChecked();
    await probe.openTableByKey();
    expect(await probe.barsLoaded()).toBe(BARS.length);
    expect(backend.marketReads).toHaveLength(reads);
  });

  test("CMP-222 is operable by keyboard alone (B05) and passes axe", async ({ page }) => {
    const { probe } = await openChart(page, "BTCUSDT 5m", { symbol: "BTCUSDT", bars: BARS });
    await probe.seriesType(COPY.seriesTypes[0]).focus();
    for (const type of COPY.seriesTypes.slice(1)) {
      await page.keyboard.press("ArrowRight");
      await expect(probe.seriesType(type)).toBeFocused();
      await expect(probe.seriesType(type)).toBeChecked();
    }
    expect(await axeFindings(page)).toEqual([]);
  });
});
