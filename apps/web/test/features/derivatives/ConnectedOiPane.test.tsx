// E24-S01 (#776) slice 2: the pane on its feed — loading, then history and live, Retry re-reading, and the
// subscription released on unmount.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import type { HistoryResult } from "../../../src/features/derivatives/oi/history";
import type { OiClock } from "../../../src/features/derivatives/oi/oiFeed";
import { ConnectedOiPane } from "../../../src/features/derivatives/oi/ui/ConnectedOiPane";
import { fakeClient } from "../tape/fakeFeed";
import { recordedTickerItems, tickerSnap } from "./support/oiFixtures";

const frames = new Map<number, () => void>();
let id = 0;
let now = 0;
const clock: OiClock = {
  raf: (cb) => (frames.set(++id, () => cb(now)), id),
  caf: (h) => void frames.delete(h),
  now: () => now,
  wallNow: () => Date.parse("2026-10-21T09:14:02Z") + now,
};
const frame = (ms = 1_000): void => {
  now += ms;
  const due = [...frames.values()];
  frames.clear();
  act(() => due.forEach((cb) => cb()));
};

afterEach(() => {
  act(() => setActiveClient(null));
  frames.clear();
});

describe("ConnectedOiPane", () => {
  it("loads, streams live through a failed backfill, retries, and releases on unmount", async () => {
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    const results: HistoryResult[] = [{ kind: "failed", status: 503, code: null }];
    const loadHistory = vi.fn(
      async (): Promise<HistoryResult> =>
        results.shift() ?? { kind: "failed", status: 500, code: null },
    );
    const { unmount } = render(
      <ConnectedOiPane
        symbol="BTCUSDT"
        paneId="oi"
        barMs={300_000}
        fromMs={0}
        toMs={1}
        loadHistory={loadHistory}
        clock={clock}
      />,
    );
    expect(screen.getByText("Loading open interest…")).toBeTruthy();
    await act(async () => {
      await Promise.resolve();
    });
    fake.handles[0]?.queue.push(tickerSnap(recordedTickerItems().slice(0, 1)));
    frame();
    expect(screen.getByRole("status").textContent).toBe("Couldn't load OI history");
    expect(screen.getByText("4.8 billion USDT, both sides")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(loadHistory).toHaveBeenCalledTimes(2);
    unmount();
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(frames.size).toBe(0);
  });
});
