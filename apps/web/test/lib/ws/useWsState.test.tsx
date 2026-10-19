// E17-T04 S5g (C9, C11, C12; WS-E06; D5): `useWsState`, the surface the connection chrome reads. A data message never touches
// the state a component binds to, so 500 of them re-render nothing; a transition re-renders once; the hook follows the client
// the shell holds, and lets go of it on unmount.
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TopicFrame } from "../../../src/lib/ws/api";
import { setActiveClient, subscribeActiveClient } from "../../../src/lib/ws/client/activeClient";
import { createWsClient } from "../../../src/lib/ws/client/createWsClient";
import { useWsState } from "../../../src/lib/ws/client/useWsState";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import { fakePage } from "./support/fakePage";
import { FakePort } from "./support/fakePort";

afterEach(() => act(() => setActiveClient(null)));

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
  return { client, port };
}
const delta = (seq: number): TopicFrame => ({
  kind: "d",
  seq,
  ts: 1_000,
  sp: undefined,
  decodeMs: 0.1,
  size: 20,
  meta: undefined,
  body: { e: "j", p: {} },
});
const up = reduce(INITIAL_WS_STATE, { type: "welcome", connectionId: "ws_1" });

describe("the registry of the client the app holds", () => {
  it("lets go of a listener that has stopped listening, and tells the others of a client that comes or goes", () => {
    const heard = vi.fn();
    const stopped = vi.fn();
    const stop = subscribeActiveClient(stopped);
    subscribeActiveClient(heard);
    stop();
    const { client } = started();
    setActiveClient(client);
    setActiveClient(client); // the same client again is no change
    setActiveClient(null);
    expect(heard).toHaveBeenCalledTimes(2);
    expect(stopped).not.toHaveBeenCalled();
  });
});

describe("useWsState", () => {
  it("reads the initial state while there is no client", () => {
    const { result } = renderHook(() => useWsState());
    expect(result.current).toBe(INITIAL_WS_STATE);
  });

  it("re-renders nothing for 500 data frames, and once for a transition", () => {
    const { client, port } = started();
    client.consume({ ch: "book.BTCUSDT.50", paneId: "p1", priority: "focused" });
    act(() => setActiveClient(client));
    let renders = 0;
    const { result } = renderHook(() => {
      renders += 1;
      return useWsState();
    });
    const before = renders;
    act(() => {
      for (let seq = 1; seq <= 500; seq += 1) {
        port.say({
          t: "data",
          id: "c1",
          frames: [delta(seq)],
          status: "live",
          effective: {},
          source: "live",
        });
      }
    });
    expect(renders).toBe(before);
    act(() => port.say({ t: "state", state: up }));
    expect(renders).toBe(before + 1);
    expect(result.current).toBe(up);
  });

  it("follows the client the shell holds: the next one's state, and none of the previous one's", () => {
    const first = started();
    const second = started();
    act(() => setActiveClient(first.client));
    let renders = 0;
    const { result } = renderHook(() => {
      renders += 1;
      return useWsState();
    });
    act(() => first.port.say({ t: "state", state: up }));
    expect(result.current).toBe(up);
    act(() => setActiveClient(second.client));
    expect(result.current).toBe(INITIAL_WS_STATE); // the second client has heard nothing yet
    const settled = renders;
    act(() => first.port.say({ t: "state", state: up })); // it is not the shell's any more
    expect(renders).toBe(settled);
    act(() => setActiveClient(null));
    expect(result.current).toBe(INITIAL_WS_STATE);
  });

  it("lets go of the client when the component goes", () => {
    const { client, port } = started();
    const unsubscribe = vi.fn();
    const subscribed = vi.fn();
    const subscribe = client.subscribe.bind(client);
    client.subscribe = (listener) => {
      subscribed();
      const stop = subscribe(listener);
      return () => {
        unsubscribe();
        stop();
      };
    };
    act(() => setActiveClient(client));
    const { unmount, rerender } = renderHook(() => useWsState());
    rerender();
    rerender();
    expect(subscribed).toHaveBeenCalledTimes(1); // one subscription for as long as it is the same client
    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
    expect(() => port.say({ t: "state", state: up })).not.toThrow();
  });
});
