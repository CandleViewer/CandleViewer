import { expect, test } from "@playwright/test";
import { axeFindings, openChart, patient } from "./bars-harness";
import { BLOCKED } from "./blockers";
import { NO_BARS } from "../../../src/chart/a11y/copy";
import { COPY } from "./chart-probe";

// E12-Q03 (#419), US-CHART-010 and US-MKT-008: E12-TC-A06, F02 and the SCR-048 failure scenario.

test.describe("history states (US-CHART-010, US-MKT-008)", () => {
  test.fixme(true, `blocked: ${BLOCKED.states}`);

  test("503 on the market read shows SCR-048 with its cause and a keyboard retry", async ({
    page,
  }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: [],
      fail: { status: 503, code: "service_unavailable" },
    });
    await patient(probe.panel.getByText(COPY.feedFailed)).toBeVisible();
    await expect(probe.panel.getByText(NO_BARS)).toHaveCount(0);
    const retry = probe.panel.getByRole("button", { name: COPY.retry });
    await retry.focus();
    const reads = backend.marketReads.length;
    await page.keyboard.press("Enter");
    await patient.poll(() => backend.marketReads.length).toBeGreaterThan(reads);
    expect(await axeFindings(page)).toEqual([]);
  });

  test("422 no_data_recorded shows SCR-047 naming the first available timestamp", async ({
    page,
  }) => {
    const { probe } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: [],
      fail: { status: 422, code: "no_data_recorded" },
    });
    await patient(probe.panel.getByText(COPY.historyStarts)).toBeVisible();
    await expect(probe.panel.getByText(COPY.feedFailed)).toHaveCount(0);
    expect(await axeFindings(page)).toEqual([]);
  });
});
