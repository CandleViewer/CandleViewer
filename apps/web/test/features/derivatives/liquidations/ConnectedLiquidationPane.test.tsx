// E24-S05 (#780) PR 4: the connected pane end to end on a fake client — one polite AN-4 summary for a burst (never
// one per print), silent while `announce_prices` is off; `liquidation.print_clicked` and the crosshair on a row;
// teardown on unmount. Preferences load through the real provider from a stubbed `/api/v1/settings`.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../../../../src/features/a11y-preferences";
import {
  announce,
  clearAnnouncements,
  ShellAnnouncer,
} from "../../../../src/features/app-shell/announcer";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import { ConnectedLiquidationPane } from "../../../../src/features/derivatives/liquidations/ui/ConnectedLiquidationPane";
import { fakeClient, fakeDisplay } from "../../tape/fakeFeed";
import { delta, EXAMPLE } from "./liqFrames";

afterEach(() => {
  act(() => setActiveClient(null));
  vi.unstubAllGlobals();
  vi.useRealTimers();
  clearAnnouncements();
});

/** The settings answer: `accessibility` as the server sends it. */
const settings = (accessibility: Record<string, unknown>): void => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ accessibility }) }),
  );
};
const loaded = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await act(async () => undefined);
};
const withPrefs = (ui: JSX.Element): JSX.Element => <PreferencesProvider>{ui}</PreferencesProvider>;

/** One burst of 20 prints in one push window: 40 prints/s, above the PROPOSED 10 prints/s threshold. */
function burst(
  handle: { queue: unknown[] },
  d: { frame: () => void },
  tick: () => void,
  item = EXAMPLE,
  frames = 8,
): void {
  handle.queue.push(
    delta(Array.from({ length: 20 }, (_, k) => ({ ...item, ts_ms: item.ts_ms + k * 20 }))),
  );
  for (let f = 0; f < frames; f += 1) {
    tick();
    act(() => d.frame());
  }
}

describe("ConnectedLiquidationPane", () => {
  it("says one polite summary for a burst, reports a clicked print and locates it, then lets go", async () => {
    settings({ announce_prices: "always" });
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    const d = fakeDisplay(50);
    let now = 0;
    const say = vi.fn();
    const analytics = { printClicked: vi.fn(), backfillFailed: vi.fn() };
    const onLocate = vi.fn();
    const { unmount } = render(
      withPrefs(
        <ConnectedLiquidationPane
          symbol="BTCUSDT"
          paneId="liq"
          fromMs={0}
          toMs={1}
          loadHistory={() => new Promise(() => undefined)}
          clock={{ ...d.clock, wallNow: () => 0 }}
          now={() => now}
          say={say}
          analytics={analytics}
          onLocate={onLocate}
        />,
      ),
    );
    await loaded();
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("no handle");
    handle.status = "live";
    // 20 prints in one push window: 40 prints/s, above the PROPOSED 10 prints/s threshold
    handle.queue.push(
      delta(Array.from({ length: 20 }, (_, k) => ({ ...EXAMPLE, ts_ms: EXAMPLE.ts_ms + k * 20 }))),
    );
    for (let f = 0; f < 8; f += 1) {
      now += 50;
      act(() => d.frame());
    }
    expect(say.mock.calls).toEqual([["Liquidations: 40 per second, mostly longs liquidated."]]);
    const grid = screen.getByRole("grid", { name: /Liquidation prints, BTCUSDT/ });
    // with onLocate the rows activate, and the grid's hint says what Enter does
    const hint = document.getElementById(grid.getAttribute("aria-describedby") ?? "");
    expect(hint?.textContent).toBe("Enter moves the chart crosshair to this print.");
    const row = within(grid).getAllByRole("row")[1];
    if (row === undefined) throw new Error("no row");
    fireEvent.click(within(row).getAllByRole("gridcell")[0] ?? row);
    expect(analytics.printClicked).toHaveBeenCalledWith("BTCUSDT", "long", 1);
    expect(onLocate).toHaveBeenCalledWith(EXAMPLE.ts_ms + 19 * 20);
    unmount();
    expect(handle.release).toHaveBeenCalledTimes(1);
  });

  it("stays silent through a burst while announce_prices is off", async () => {
    settings({ announce_prices: "off" });
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    const d = fakeDisplay(50);
    let now = 0;
    const say = vi.fn();
    render(
      withPrefs(
        <ConnectedLiquidationPane
          symbol="BTCUSDT"
          paneId="liq"
          fromMs={0}
          toMs={1}
          loadHistory={() => new Promise(() => undefined)}
          clock={{ ...d.clock, wallNow: () => 0 }}
          now={() => now}
          say={say}
        />,
      ),
    );
    await loaded();
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("no handle");
    handle.status = "live";
    burst(handle, d, () => (now += 50));
    expect(screen.getByText("40 prints per second")).toBeTruthy(); // the counter still shows
    expect(say).not.toHaveBeenCalled();
    // no onLocate: nothing would move, so no row activates and no hint promises it
    const grid = screen.getByRole("grid", { name: /Liquidation prints, BTCUSDT/ });
    expect(grid.hasAttribute("aria-describedby")).toBe(false);
    expect(screen.queryByText("Enter moves the chart crosshair to this print.")).toBeNull();
  });

  it("waits out the shell's polite budget: a message written just before survives, then the summary speaks", async () => {
    settings({ announce_prices: "always" });
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse("2026-10-21T09:14:00Z"));
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    const d = fakeDisplay(50);
    let now = 0;
    render(
      withPrefs(
        <>
          <ShellAnnouncer />
          <ConnectedLiquidationPane
            symbol="BTCUSDT"
            paneId="liq"
            fromMs={0}
            toMs={1}
            loadHistory={() => new Promise(() => undefined)}
            clock={{ ...d.clock, wallNow: () => 0 }}
            now={() => now}
          />
        </>,
      ),
    );
    await loaded();
    const polite = (): string => document.querySelector('[aria-live="polite"]')?.textContent ?? "";
    act(() => void announce("polite", "Order filled.", "pre"));
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("no handle");
    handle.status = "live";
    burst(handle, d, () => (now += 50), EXAMPLE, 30); // inside the 5 s budget, then the rate falls back
    expect(polite()).toBe("Order filled.");
    vi.setSystemTime(Date.parse("2026-10-21T09:14:05.001Z"));
    burst(handle, d, () => (now += 50), { ...EXAMPLE, ts_ms: EXAMPLE.ts_ms + 10_000 });
    expect(polite()).toBe("Liquidations: 40 per second, mostly longs liquidated.");
  });

  it("gives a symbol switch its own leading-edge summary, even within 5 s", async () => {
    settings({ announce_prices: "always" });
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    const d = fakeDisplay(50);
    let now = 0;
    const say = vi.fn();
    const props = {
      paneId: "liq",
      fromMs: 0,
      toMs: 1,
      loadHistory: () => new Promise<never>(() => undefined),
      clock: { ...d.clock, wallNow: () => 0 },
      now: () => now,
      say,
      canSay: () => true,
    };
    const { rerender } = render(
      withPrefs(<ConnectedLiquidationPane symbol="BTCUSDT" {...props} />),
    );
    await loaded();
    const btc = fake.handles[0];
    if (btc === undefined) throw new Error("no handle");
    btc.status = "live";
    burst(btc, d, () => (now += 50));
    rerender(withPrefs(<ConnectedLiquidationPane symbol="ETHUSDT" {...props} />));
    const eth = fake.handles[1];
    if (eth === undefined) throw new Error("no ETH handle");
    eth.status = "live";
    burst(eth, d, () => (now += 50), { ...EXAMPLE, symbol: "ETHUSDT" });
    expect(now).toBeLessThan(5_000);
    expect(say).toHaveBeenCalledTimes(2);
  });

  it("re-checks a steady cascade every second: a refused write retries, summaries stay 5 s apart", async () => {
    settings({ announce_prices: "always" });
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-10-21T09:14:00Z"));
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    const d = fakeDisplay(50);
    const saidAt: number[] = [];
    const say = vi.fn(() => void saidAt.push(Date.now()));
    let open = false;
    const { unmount } = render(
      withPrefs(
        <ConnectedLiquidationPane
          symbol="BTCUSDT"
          paneId="liq"
          fromMs={0}
          toMs={1}
          loadHistory={() => new Promise(() => undefined)}
          clock={{ ...d.clock, wallNow: () => 0 }}
          now={() => Date.now()}
          say={say}
          canSay={() => open}
        />,
      ),
    );
    await loaded();
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("no handle");
    handle.status = "live";
    burst(handle, d, () => undefined, EXAMPLE, 4); // the rate holds at 40 prints/s: no further frames
    expect(say).not.toHaveBeenCalled(); // the region's budget refused, nothing consumed
    open = true;
    act(() => vi.advanceTimersByTime(1_000));
    expect(say).toHaveBeenCalledTimes(1); // the refusal retried within a second, with a flat rate
    act(() => vi.advanceTimersByTime(4_000));
    expect(say).toHaveBeenCalledTimes(1); // never sooner than 5 s
    act(() => vi.advanceTimersByTime(1_000));
    expect(say).toHaveBeenCalledTimes(2); // still active, five seconds on
    act(() => vi.advanceTimersByTime(12_000));
    for (let i = 1; i < saidAt.length; i += 1) {
      expect((saidAt[i] ?? 0) - (saidAt[i - 1] ?? 0)).toBeGreaterThanOrEqual(5_000);
    }
    expect(saidAt.length).toBe(4); // at 1, 6, 11 and 16 s: never stretched to 10 s
    unmount();
    expect(vi.getTimerCount()).toBe(0); // cleared on unmount
  });
});
