// A fake of the client the shell holds, for component tests: `useWsState` reads its `getState` and
// `subscribe`, CMP-077's `Retry now` calls its `retryNow`. `go` replaces the state as a transition does.
import { act } from "@testing-library/react";
import { vi } from "vitest";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import { INITIAL_WS_STATE, reduce } from "../../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../../src/lib/ws/state/types";

export const runEvents = (...events: EngineEvent[]): WsState =>
  events.reduce(reduce, INITIAL_WS_STATE);

export function fakeActiveClient(initial: WsState = INITIAL_WS_STATE) {
  let state = initial;
  const listeners = new Set<() => void>();
  const retryNow = vi.fn(() => true);
  const client = {
    getState: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    retryNow,
  } as unknown as WsClientHandle; // the shell chrome reads only these three
  const go = (next: WsState): void =>
    act(() => {
      state = next;
      listeners.forEach((listener) => listener());
    });
  act(() => setActiveClient(client));
  const detach = (): void => act(() => setActiveClient(null));
  return { client, go, retryNow, detach, current: () => state };
}
