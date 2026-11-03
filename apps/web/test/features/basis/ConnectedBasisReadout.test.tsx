// E24-S08 (#783) slice 1: the readout on the active client; the source is in-memory and defaults to the
// contract's `last` on every mount (owner ruling on #778: no local-storage fallback).
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DEFAULT_BASIS_SOURCE } from "../../../src/features/basis/settings";
import { ConnectedBasisReadout } from "../../../src/features/basis/ui/ConnectedBasisReadout";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { fakeClient } from "../tape/fakeFeed";
import { recordedTickerItems, tickerSnap } from "./support/basisFixtures";

afterEach(() => {
  act(() => setActiveClient(null));
  localStorage.clear();
});

describe("ConnectedBasisReadout", () => {
  it("starts at last, follows the ticker, switches source in memory and writes no storage", () => {
    expect(DEFAULT_BASIS_SOURCE).toBe("last");
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    const pending: (() => void)[] = [];
    const clock = {
      raf: (cb: (t: number) => void) => (pending.push(() => cb(0)), pending.length),
      caf: () => undefined,
      now: () => 0,
      wallNow: () => 0,
    };
    const { unmount } = render(<ConnectedBasisReadout symbol="BTCUSDT" paneId="p" clock={clock} />);
    const handle = fake.handles[0];
    const item = recordedTickerItems()[0];
    if (handle === undefined || item === undefined) throw new Error("fixture");
    handle.queue.push(tickerSnap([item]));
    handle.status = "live";
    act(() => pending.splice(0).forEach((cb) => cb()));
    const group = screen.getByRole("group", { name: "Basis, BTCUSDT" });
    expect(group.textContent).toContain("−31.17 (−0.038 %)");
    expect(screen.getByRole("radio", { name: "last" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("radio", { name: "mark" }));
    expect(group.textContent).toContain("basis, mark − index");
    expect(localStorage.length).toBe(0);
    unmount();
    expect(handle.release).toHaveBeenCalledTimes(1);
  });
});
