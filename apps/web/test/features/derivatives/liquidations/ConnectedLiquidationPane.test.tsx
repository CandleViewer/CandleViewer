// E24-S05 (#780) PR 4: the connected pane end to end on a fake client — one polite AN-4 summary for a burst (never
// one per print), silent while `announce_prices` is off; `liquidation.print_clicked` and the crosshair on a row;
// teardown on unmount. Preferences load through the real provider from a stubbed `/api/v1/settings`.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../../../../src/features/a11y-preferences";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import { ConnectedLiquidationPane } from "../../../../src/features/derivatives/liquidations/ui/ConnectedLiquidationPane";
import { fakeClient, fakeDisplay } from "../../tape/fakeFeed";
import { delta, EXAMPLE } from "./liqFrames";

afterEach(() => {
  act(() => setActiveClient(null));
  vi.unstubAllGlobals();
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
function burst(handle: { queue: unknown[] }, d: { frame: () => void }, tick: () => void): void {
  handle.queue.push(
    delta(Array.from({ length: 20 }, (_, k) => ({ ...EXAMPLE, ts_ms: EXAMPLE.ts_ms + k * 20 }))),
  );
  for (let f = 0; f < 8; f += 1) {
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
  });
});
