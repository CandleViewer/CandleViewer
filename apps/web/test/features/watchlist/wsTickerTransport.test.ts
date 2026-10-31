/**
 * E08-S08 (#4702): the ticker client's transport over the WS client's public API (E17-T04): one `consume` of the
 * batched `ticker` with its `symbols` (23 §6.1), frames read on the hub's own beat, `release` to let go.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import { createWsClient } from "../../../src/lib/ws/client/createWsClient";
import {
  hubFor,
  useTickerHub,
  wsTickerTransport,
} from "../../../src/features/watchlist/ticker/wsTickerTransport";
import { fakePage } from "../../lib/ws/support/fakePage";
import { FakePort } from "../../lib/ws/support/fakePort";
import { snapOf, streamItem } from "./support";

const stops: (() => void)[] = [];
afterEach(() => {
  act(() => setActiveClient(null));
  for (const stop of stops.splice(0)) stop();
});

function started() {
  const port = new FakePort();
  const client = createWsClient({
    wsUrl: "wss://cv.test/api/v1/ws",
    tokens: { getToken: async () => ({ kind: "unavailable" }), invalidate: () => undefined },
    shell: "browser",
    locale: "en-GB",
    clientVersion: "1.0.0",
    port,
    page: fakePage().page,
    raf: () => 0,
    caf: () => undefined,
  });
  stops.push(() => client.stop());
  return { client, port };
}

describe("wsTickerTransport", () => {
  it("asks for one batched `ticker` with the symbols as its option", () => {
    const { client, port } = started();
    wsTickerTransport(client).open(["BTCUSDT", "ETHUSDT"]);
    expect(port.of("consume")).toEqual([
      expect.objectContaining({
        ch: "ticker",
        opts: { symbols: ["BTCUSDT", "ETHUSDT"] },
        priority: "other",
      }),
    ]);
  });

  it("hands over the frames the worker sends, in order, once each", () => {
    const { client, port } = started();
    const channel = wsTickerTransport(client).open(["BTCUSDT"]);
    const id = port.of("consume")[0]?.["id"];
    const snap = snapOf([streamItem(0)]);
    port.say({ t: "data", id, frames: [snap], status: "live", effective: {}, source: "live" });
    expect(channel.read()).toEqual([snap]);
    expect(channel.read()).toEqual([]);
  });

  it("release lets the subscription go", () => {
    const { client, port } = started();
    const channel = wsTickerTransport(client).open(["BTCUSDT"]);
    channel.release();
    expect(port.of("release")).toHaveLength(1);
  });
});

describe("one hub per WS client", () => {
  it("is null while the shell holds no client, and the client's own hub once it does", () => {
    const { client } = started();
    const { result } = renderHook(() => useTickerHub());
    expect(result.current).toBeNull();
    act(() => setActiveClient(client));
    expect(result.current).toBe(hubFor(client));
  });

  it("a client the shell lets go takes its hub's subscription with it", () => {
    const first = started();
    const second = started();
    act(() => setActiveClient(first.client));
    hubFor(first.client).claim("pane", ["BTCUSDT"]);
    expect(first.port.of("consume")).toHaveLength(1);
    act(() => setActiveClient(second.client));
    expect(first.port.of("release")).toHaveLength(1);
    expect(hubFor(second.client)).not.toBe(hubFor(first.client));
  });
});
