// E24-S03 (#778) slice 2: header and pane on one entry and one timer, skew, rollover, AN-1 once, teardown.
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSecondTick, type FundingCharge } from "@candleviewer/ui";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { syncedNow } from "../../../src/lib/state/syncedTick";
import { ConnectedFundingCountdown } from "../../../src/features/funding/ui/ConnectedFundingCountdown";
import { ConnectedFundingPane } from "../../../src/features/funding/ui/ConnectedFundingPane";
import type {
  FundingHistoryRequest,
  FundingHistoryResult,
} from "../../../src/features/funding/history";
import { fakeClient, fakeDisplay } from "../tape/fakeFeed";
import { recordedSettled } from "./support/fundingFixtures";
import { recordedFundingItems, snap } from "./support/tickerFrames";

const ITEM = recordedFundingItems()[0];
const NEXT = 1792396800000; // the recorded `nextFundingTime`
const LEAD_MS = 1_500; // the local clock runs 1.5 s ahead of the exchange: measured, under the alarm
const SETTLED = recordedSettled("BTCUSDT_8h").map((i) => ({
  tMs: Date.parse(i.t),
  rate: i.funding_rate,
}));

const ok = (settled: typeof SETTLED): FundingHistoryResult => ({
  kind: "ok",
  settled,
  intervalMinutes: 480,
  coverage: null,
  truncated: false,
});

/** `null`: no skew measured yet (the default parameter would swallow `undefined`). */
function install(skewMs: number | null = -LEAD_MS) {
  const fake = fakeClient();
  const display = fakeDisplay(100);
  const diag: { clockSkewMs: number | undefined } = { clockSkewMs: skewMs ?? undefined };
  const client = { ...fake.client, diagnostics: () => diag };
  act(() => setActiveClient(client as unknown as WsClientHandle));
  /** A new measurement, as the next `diag` would bring it. */
  const setSkew = (ms: number): void => void (diag.clockSkewMs = ms);
  return { fake, display, setSkew };
}

/** One recorded ticker item naming `next` as the next settlement. */
const tickerAt = (next: number) =>
  snap([{ ...(ITEM as NonNullable<typeof ITEM>), next_funding_time_ms: next }]);

const digitsOf = (el: HTMLElement): string =>
  el.querySelector(".cv-funding__digits")?.textContent ?? "";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NEXT + LEAD_MS - 10_000); // ten exchange seconds before the settlement
});
afterEach(() => {
  act(() => setActiveClient(null));
  vi.useRealTimers();
});

describe("connected funding countdown", () => {
  it("shows one value in the header and the pane, on one ticker topic and one timer", async () => {
    const { fake, display } = install();
    const tick = createSecondTick({ now: syncedNow });
    const loadCharges = vi.fn(async (): Promise<readonly FundingCharge[]> => []);
    const loadHistory = vi
      .fn<(req: FundingHistoryRequest) => Promise<FundingHistoryResult>>(async () => ok(SETTLED))
      .mockResolvedValueOnce(ok(SETTLED.slice(0, 3)));
    const common = { symbol: "BTCUSDT", tick, loadCharges };
    const { unmount } = render(
      <>
        <header data-testid="header">
          <ConnectedFundingCountdown {...common} clock={display.clock} />
        </header>
        <ConnectedFundingPane
          {...common}
          announce={false}
          showTables
          fromMs={0}
          toMs={NEXT}
          countdownClock={display.clock}
          loadHistory={loadHistory}
          now={syncedNow}
        />
      </>,
    );
    expect(fake.client.consume).toHaveBeenCalledOnce();
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("no handle");
    handle.status = "live";
    handle.queue.push(tickerAt(NEXT));
    await act(async () => display.frame());
    const header = screen.getByTestId("header");
    const pane = screen.getByRole("region", { name: "Funding, BTCUSDT" });
    expect(digitsOf(header)).toBe("settles in 00:00:10 · 08:00 UTC");
    expect(digitsOf(pane)).toBe(digitsOf(header));
    expect(vi.getTimerCount()).toBe(1); // the one shared tick

    // the count reaches zero at the exchange's settlement, not the local clock's
    await act(async () => vi.advanceTimersByTime(9_000));
    expect(digitsOf(header)).toBe("settles in 00:00:01 · 08:00 UTC");
    await act(async () => vi.advanceTimersByTime(1_000));
    expect(digitsOf(header)).toBe("settles in 00:00:00 · 08:00 UTC"); // the floor, D06 §7
    await act(async () => vi.advanceTimersByTime(1));
    expect(
      within(header).getAllByText("Settlement time passed — waiting for an update"),
    ).toHaveLength(2);
    // the zero lands within a second of the exchange's settlement: here 1 ms after it
    expect(syncedNow() - NEXT).toBeGreaterThanOrEqual(0);
    expect(syncedNow() - NEXT).toBeLessThan(1_000);

    // the pane polled `to = now` and appended the settled rate
    expect(loadHistory).toHaveBeenCalledTimes(2);
    expect(loadHistory.mock.calls[1]?.[0].toMs).toBeGreaterThan(NEXT);
    expect(within(pane).getAllByText("settled")).toHaveLength(4);

    // the ticker advances the next time: both restart from it, never from the interval
    handle.queue.push(tickerAt(NEXT + 8 * 3_600_000));
    await act(async () => display.frame());
    expect(digitsOf(header)).toBe("next in 07:59:59 · 16:00 UTC");
    expect(digitsOf(pane)).toBe(digitsOf(header));

    unmount();
    expect(handle.release).toHaveBeenCalledOnce();
    expect(display.pending()).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  /** The header's countdown and / or the pane on one client with `skewMs`, after one ticker frame. */
  async function screenWith(o: {
    skew?: number | null;
    charges?: FundingCharge[];
    pane?: boolean;
  }) {
    const { fake, display, setSkew } = install(o.skew === undefined ? -LEAD_MS : o.skew);
    const loadCharges = vi.fn(async (): Promise<readonly FundingCharge[]> => o.charges ?? []);
    const common = { symbol: "BTCUSDT", tick: createSecondTick({ now: syncedNow }), loadCharges };
    const never = () => new Promise<FundingHistoryResult>(() => undefined);
    render(
      <>
        {o.pane === true ? null : <ConnectedFundingCountdown {...common} clock={display.clock} />}
        {o.pane === undefined ? null : (
          <ConnectedFundingPane
            {...common}
            {...{ announce: o.pane, countdownClock: display.clock, fromMs: 0, toMs: NEXT }}
            loadHistory={never}
          />
        )}
      </>,
    );
    fake.handles[0]?.queue.push(tickerAt(NEXT));
    await act(async () => display.frame());
    const state = () => document.querySelector("[data-cmp='CMP-126']")?.getAttribute("data-state");
    return { setSkew, loadCharges, state };
  }

  it("shows the server's charge line under 5 minutes", async () => {
    vi.setSystemTime(NEXT + LEAD_MS - 250_000);
    const pay = {
      accountLabel: "Demo 1",
      env: "DEMO",
      direction: "pay",
      amountUsdt: "12.40",
    } as const;
    const { loadCharges } = await screenWith({ charges: [pay] });
    await act(async () => vi.advanceTimersByTime(1_000));
    expect(screen.getByText("— you pay ≈ 12.40 USDT on Demo 1 · DEMO")).toBeTruthy();
    expect(loadCharges).toHaveBeenCalledOnce();
  });

  it("under a 3 s lead it shows the alarm's absolute time and still ends within a second (m3)", async () => {
    vi.setSystemTime(NEXT + 3_000 - 10_000);
    const { state } = await screenWith({ skew: -3_000 });
    expect(state()).toBe("clock-alarm");
    const note = { selector: ".cv-funding__note" };
    expect(screen.getByText("Clock skew 3000 ms — the countdown may be off", note)).toBeTruthy();
    await act(async () => vi.advanceTimersByTime(10_001));
    expect(state()).toBe("elapsed");
    expect(syncedNow() - NEXT).toBeGreaterThanOrEqual(0);
    expect(syncedNow() - NEXT).toBeLessThan(1_000);
  });

  it("shows the absolute time alone while unmeasured, and follows a new measurement within a tick", async () => {
    const { state, setSkew } = await screenWith({ skew: null });
    expect(state()).toBe("clock-alarm");
    expect(screen.getByText(/^at 08:00:00 UTC/)).toBeTruthy();
    expect(screen.queryByText(/Clock skew/)).toBeNull();
    setSkew(-LEAD_MS); // no other re-render: the tick re-reads the skew
    await act(async () => vi.advanceTimersByTime(1_000));
    expect(state()).toBe("settling");
  });

  it.each([
    ["the pane alone", true],
    ["the header's countdown and a silent pane", false],
  ])("speaks AN-1 once with %s", async (_name, pane) => {
    vi.setSystemTime(NEXT + LEAD_MS - 302_000);
    await screenWith({ pane });
    await act(async () => vi.advanceTimersByTime(3_000));
    const line = "BTCUSDT funding settles in 5 minutes.";
    expect(screen.getAllByRole("status").filter((n) => n.textContent === line)).toHaveLength(1);
    expect(document.querySelectorAll("[data-cmp='CMP-126']")).toHaveLength(pane ? 1 : 2);
  });
});
