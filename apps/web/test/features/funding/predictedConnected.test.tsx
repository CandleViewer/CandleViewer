// E24-S04 (#779): the connected pane. The header never shows the ticker's rate as settled (predicted and
// estimated, even before REST answers); the server's annualised value is shown only for the rate the ticker
// shows; the toggle reports its event; n/a is counted once per entry and nothing is carried across reads.
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSecondTick } from "@candleviewer/ui";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { syncedNow } from "../../../src/lib/state/syncedTick";
import { ConnectedFundingPane } from "../../../src/features/funding/ui/ConnectedFundingPane";
import type { FundingHistoryResult } from "../../../src/features/funding/history";
import type { FundingAnalytics } from "../../../src/features/funding/analytics";
import { fakeClient, fakeDisplay } from "../tape/fakeFeed";
import { recordedFundingItems, snap } from "./support/tickerFrames";

const ITEM = recordedFundingItems()[0] as NonNullable<ReturnType<typeof recordedFundingItems>[0]>;
const NEXT = 1792396800000;

const history = (
  predicted: { rate: string; annualisedPct: string | null } | null,
): FundingHistoryResult => ({
  kind: "ok",
  settled: [{ tMs: NEXT - 8 * 3_600_000, rate: "0.0001", annualisedPct: "10.95" }],
  predicted: predicted === null ? null : { tMs: NEXT, ...predicted },
  intervalMinutes: 480,
  coverage: null,
  truncated: false,
});

const analytics = (): FundingAnalytics & { calls: unknown[][] } => {
  const calls: unknown[][] = [];
  return {
    calls,
    historyFailed: () => undefined,
    annualiseToggled: (...a) => void calls.push(["toggled", ...a]),
    predictedNa: (...a) => void calls.push(["na", ...a]),
  };
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NEXT - 3_600_000);
});
afterEach(() => {
  act(() => setActiveClient(null));
  vi.useRealTimers();
});

async function mountPane(result: FundingHistoryResult, tickerRate: string | null) {
  const fake = fakeClient();
  const display = fakeDisplay(100);
  const client = { ...fake.client, diagnostics: () => ({ clockSkewMs: 0 }) };
  act(() => setActiveClient(client as unknown as WsClientHandle));
  const report = analytics();
  render(
    <ConnectedFundingPane
      symbol="BTCUSDT"
      fromMs={0}
      toMs={NEXT}
      tick={createSecondTick({ now: syncedNow })}
      loadCharges={async () => []}
      countdownClock={display.clock}
      loadHistory={async () => result}
      analytics={report}
    />,
  );
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("no handle");
  handle.status = "live";
  const next = { ...ITEM, next_funding_time_ms: NEXT } as typeof ITEM;
  const rate =
    tickerRate === null
      ? { ...next, funding_rate: undefined }
      : { ...next, funding_rate: tickerRate };
  handle.queue.push(snap([rate as typeof ITEM]));
  await act(async () => display.frame());
  await act(async () => vi.advanceTimersByTime(1));
  return { report, pane: screen.getByRole("region", { name: "Funding, BTCUSDT" }) };
}

describe("connected predicted funding", () => {
  it("shows the ticker's rate as predicted and estimated, with the served annualised value", async () => {
    const { pane } = await mountPane(
      history({ rate: ITEM.funding_rate ?? "", annualisedPct: "10.95" }),
      ITEM.funding_rate ?? null,
    );
    expect(within(pane).getByRole("button", { name: "Estimated, Funding rate" })).toBeTruthy();
    expect(within(pane).getAllByText(/^predicted/).length).toBeGreaterThan(0);
    expect(within(pane).getByText(/\+10\.95 % p\.a\./)).toBeTruthy();
  });

  it("reports the toggle and leads with the annualised figure", async () => {
    const { pane, report } = await mountPane(
      history({ rate: ITEM.funding_rate ?? "", annualisedPct: "10.95" }),
      ITEM.funding_rate ?? null,
    );
    await act(async () =>
      within(pane).getByRole("switch", { name: "Annualised (% p.a.)" }).click(),
    );
    expect(report.calls).toContainEqual(["toggled", "BTCUSDT", true]);
    expect(pane.querySelector(".cv-funding__rate")?.textContent).toBe("+10.95 % p.a.");
  });

  it("is n/a, counted once, when REST published no predicted rate", async () => {
    const { pane, report } = await mountPane(history(null), ITEM.funding_rate ?? null);
    expect(within(pane).getByText("Funding n/a")).toBeTruthy();
    expect(within(pane).queryByRole("button", { name: /Estimated/ })).toBeNull();
    expect(report.calls.filter((c) => c[0] === "na")).toEqual([["na", "BTCUSDT"]]);
  });

  it("is n/a with no ticker rate and carries no earlier value", async () => {
    const { pane } = await mountPane(history({ rate: "0.0001", annualisedPct: "10.95" }), null);
    expect(within(pane).getByText("Funding n/a")).toBeTruthy();
    expect(within(pane).queryByText(/0\.0100/)).toBeNull();
  });
});
